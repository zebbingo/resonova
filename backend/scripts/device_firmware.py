#!/usr/bin/env python3
"""
DeviceFirmware — 嵌入式设备固件模拟器 (v1.6 协议, Han Wu's spec)

模拟真实语音玩具设备的 MQTT 行为，完整覆盖 v1.6 协议：

  上行:
    session/start, session/end, session/hb
    audio/start, audio/chunk/<seq>, audio/eos, audio/abort, audio/done
    meta/online, meta/hb
    state/reported, ota/reported

  下行 (订阅 response/#, state/desired, ota/desired):
    audio/start, audio/chunk/<seq>, audio/eos, audio/abort, audio/vadeos, audio/introeos
    command/<session_id>, command/<session_id>/<turn_id>
    state/desired, ota/desired

  v1.6 关键特性:
    - cue 音频 turn (turn_id = "cue-1", "cue-2", ...)
    - turn 级 command (after_audio / preempt 语义)
    - session 心跳 (60s)
    - 播放回执 (done)
    - abort 支持
    - OTA / 配置同步

协议权威参考: projects/chatbot/docs/03-mqtt/02-mqtt-spec-v1.6.md

用法:
    fw = DeviceFirmware("my-device-001")
    fw.power_on()
    fw.start_session(figurine_id="unicorn")
    fw.wait_for_intro_eos()
    fw.start_turn(pcm_data)
    fw.wait_for_turn_response()
    fw.stop_session()
    fw.power_off()
"""

import json
import os
import secrets
import ssl
import threading
import time
from collections import OrderedDict
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

import numpy as np

# ── 允许从 scripts/ 目录导入 backend/pcm_utils ──────────────
import sys
_THIS_DIR = Path(__file__).resolve().parent
_BACKEND_DIR = _THIS_DIR.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))
import pcm_utils

_MQTT_BROKER = os.getenv("MQTT_HOST", "localhost")
_MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
_MQTT_ENV = os.getenv("MQTT_ENV", "development")
_OPUS_SR = pcm_utils.PCM_SR
_OPUS_CHANNELS = pcm_utils.PCM_CHANNELS
_OPUS_FRAME_SAMPLES = pcm_utils.OPUS_FRAME_SAMPLES
_OPUS_FRAME_MS = pcm_utils.OPUS_FRAME_MS
_IDENTITY_DIR = Path(__file__).resolve().parent / "devices"

_SESSION_HB_INTERVAL = 60
_DEVICE_HB_INTERVAL = 30


def _is_local_or_private_host(host: str) -> bool:
    """Check if a host is local (loopback) or in a private/reserved IP range.

    This handles:
      - localhost / 127.0.0.1 / ::1 (standard loopback)
      - WSL interop IPs (e.g. 172.20.x.x from ``wsl hostname -I``)
      - Docker bridge IPs (e.g. 172.17.x.x)
      - Any private RFC 1918 address (10.x, 172.16-31.x, 192.168.x)

    These brokers typically use anonymous auth; sending MQTT_USERNAME/MQTT_PASSWORD
    credentials is unnecessary and causes rc=7 disconnects.
    """
    host_lower = host.strip().lower()
    if host_lower in {"localhost", "127.0.0.1", "::1"}:
        return True
    # Fast-path: skip DNS resolution for dotted-quad IPs
    import ipaddress
    try:
        addr = ipaddress.ip_address(host_lower)
    except ValueError:
        return False
    return addr.is_private or addr.is_loopback


class DeviceState(Enum):
    OFFLINE = "offline"
    IDLE = "idle"
    SESSION_ACTIVE = "session_active"
    CAPTURING = "capturing"
    WAITING = "waiting"
    PLAYING = "playing"
    SESSION_ENDED = "session_ended"


class TurnState(Enum):
    IDLE = "idle"
    CAPTURING = "capturing"
    UPLOADING = "uploading"
    THINKING = "thinking"
    PLAYING = "playing"
    DRAINING = "draining"
    DONE = "done"
    ABORTED = "aborted"


class _TurnTracker:
    __slots__ = ("turn_id", "state", "chunks_received", "eos_total_seq",
                 "eos_event", "audio_data", "stt_text", "downstream_started",
                 "sent_at", "eos_sent_at", "vadeos_at", "tts_start_at", "tts_eos_at", "done_sent_at")

    def __init__(self, turn_id: str):
        self.turn_id = turn_id
        self.state = TurnState.PLAYING
        self.chunks_received = 0
        self.eos_total_seq: Optional[int] = None
        self.eos_event = threading.Event()
        self.audio_data: list[bytes] = []
        self.stt_text: str = ""
        self.downstream_started = False
        self.sent_at: float = 0.0
        self.eos_sent_at: float = 0.0
        self.vadeos_at: float = 0.0
        self.tts_start_at: float = 0.0
        self.tts_eos_at: float = 0.0
        self.done_sent_at: float = 0.0


class DeviceFirmware:

    def __init__(
        self,
        device_id: str,
        *,
        env: Optional[str] = None,
        broker_host: Optional[str] = None,
        broker_port: Optional[int] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        tls_enabled: bool = False,
        tls_ca_cert: Optional[str] = None,
        tls_client_cert: Optional[str] = None,
        tls_client_key: Optional[str] = None,
        tls_insecure: bool = False,
        on_mqtt_event: Optional[callable] = None,
    ):
        self.device_id = device_id
        self._on_mqtt_event = on_mqtt_event
        self.env = env or _MQTT_ENV
        self._broker_host = broker_host or _MQTT_BROKER
        self._broker_port = broker_port or _MQTT_PORT
        # Only use MQTT_USERNAME/PASSWORD when connecting to a non-local broker.
        # Local NanoMQ uses anonymous auth; sending credentials causes rc=7 disconnects.
        _is_local_broker = _is_local_or_private_host(self._broker_host or "")
        if _is_local_broker:
            self._username = username  # explicit only, skip env
            self._password = password
        else:
            self._username = username or os.getenv("MQTT_USERNAME")
            self._password = password or os.getenv("MQTT_PASSWORD")
        self._tls_enabled = tls_enabled
        self._tls_ca_cert = tls_ca_cert or os.getenv("MQTT_TLS_CA_CERT")
        self._tls_client_cert = tls_client_cert or os.getenv("MQTT_TLS_CLIENT_CERT")
        self._tls_client_key = tls_client_key or os.getenv("MQTT_TLS_CLIENT_KEY")
        self._tls_insecure = tls_insecure

        self.state = DeviceState.OFFLINE
        self.session_id: Optional[str] = None
        self._turn_counter = 0
        self._cue_counter = 0
        self._cmd_counter = 0
        self.figurine_id: Optional[str] = None
        self.nfc_id: Optional[str] = None
        self.mode = "dialogue"

        self.base_topic = f"{self.env}/{device_id}"

        _IDENTITY_DIR.mkdir(parents=True, exist_ok=True)
        self._identity_file = _IDENTITY_DIR / f"{device_id}.json"
        self._load_or_create_identity()

        import paho.mqtt.client as mqtt

        self._client = mqtt.Client(
            client_id=self.identity["mqtt_client_id"],
            protocol=mqtt.MQTTv311,
        )
        if self._username:
            self._client.username_pw_set(self._username, self._password or "")
        if self._tls_enabled:
            missing = []
            if not self._tls_ca_cert:
                missing.append("MQTT_TLS_CA_CERT (CA certificate)")
            if self._tls_client_cert and not os.path.isfile(self._tls_client_cert):
                missing.append(f"MQTT_TLS_CLIENT_CERT: {self._tls_client_cert}")
            if self._tls_client_key and not os.path.isfile(self._tls_client_key):
                missing.append(f"MQTT_TLS_CLIENT_KEY: {self._tls_client_key}")
            if self._tls_ca_cert and not os.path.isfile(self._tls_ca_cert):
                missing.append(f"MQTT_TLS_CA_CERT: {self._tls_ca_cert}")
            if missing:
                raise ValueError(
                    f"Device {self.device_id}: TLS enabled but certificate configuration is incomplete:\n"
                    + "\n".join(f"  - {m}" for m in missing)
                    + "\nSet MQTT_TLS_CA_CERT, MQTT_TLS_CLIENT_CERT, MQTT_TLS_CLIENT_KEY in .env "
                    "or pass tls_ca_cert/tls_client_cert/tls_client_key to DeviceFirmware."
                )

            self._client.tls_set(
                ca_certs=self._tls_ca_cert,
                certfile=self._tls_client_cert,
                keyfile=self._tls_client_key,
                tls_version=ssl.PROTOCOL_TLSv1_2,
            )
            if self._tls_insecure:
                self._client.tls_insecure_set(True)
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._client.on_disconnect = self._on_disconnect

        self._connected = threading.Event()
        self._intro_eos_event = threading.Event()
        self._intro_audio_eos_event = threading.Event()
        self._lock = threading.Lock()
        self._cleaned_up = False

        # Ensure cleanup on process exit (handles kill -9 gracefully for paho threads)
        import atexit
        atexit.register(self._atexit_cleanup)

        self._active_turns: OrderedDict[str, _TurnTracker] = OrderedDict()
        self._commands: list[dict] = []
        self._pending_after_audio: dict[str, list[dict]] = {}
        self._session_stt_texts: list[str] = []
        self._last_error = ""

        self._hb_thread: Optional[threading.Thread] = None
        self._hb_stop = threading.Event()
        self._device_hb_thread: Optional[threading.Thread] = None
        self._device_hb_stop = threading.Event()

        self._ota_reported_ver: Optional[int] = None
        self._config_reported_ver: Optional[int] = None

        self.on_state_change: Optional[Callable[[DeviceState], None]] = None
        self.on_log: Optional[Callable[[str], None]] = None
        self.on_command: Optional[Callable[[dict], None]] = None
        self.on_cue_audio: Optional[Callable[[str, list[bytes]], None]] = None
        self.on_ota: Optional[Callable[[dict], None]] = None
        self.on_config: Optional[Callable[[dict], None]] = None

    @staticmethod
    def _is_cue_turn_id(turn_id: Optional[str]) -> bool:
        return bool(turn_id) and str(turn_id).startswith("cue-")

    def _load_or_create_identity(self):
        if self._identity_file.exists():
            self.identity = json.loads(self._identity_file.read_text())
        else:
            self.identity = {
                "device_id": self.device_id,
                "mqtt_client_id": f"fw_{self.device_id}_{secrets.token_hex(4)}",
                "created_at": time.time(),
                "fw_version": "1.6.0",
            }
            self._identity_file.write_text(json.dumps(self.identity, indent=2))

    def _next_turn_id(self) -> str:
        self._turn_counter += 1
        return str(self._turn_counter)

    def _next_cue_id(self) -> str:
        self._cue_counter += 1
        return f"cue-{self._cue_counter}"

    def _next_cmd_id(self) -> str:
        self._cmd_counter += 1
        return f"cmd-{self._cmd_counter}"

    def _get_or_create_turn(self, turn_id: str) -> _TurnTracker:
        if turn_id not in self._active_turns:
            self._active_turns[turn_id] = _TurnTracker(turn_id)
        return self._active_turns[turn_id]

    def power_on(self):
        self._log(f"[FW] Power on: {self.device_id} broker={self._broker_host}:{self._broker_port} user={self._username} tls={self._tls_enabled}")

        lwt_payload = json.dumps({"online": False, "ts": int(time.time() * 1000),
                                   "fw": self.identity.get("fw_version", "1.6.0")})
        self._client.will_set(
            f"{self.base_topic}/meta/online", lwt_payload, qos=1, retain=True,
        )

        self._set_state(DeviceState.IDLE)
        try:
            self._client.connect(self._broker_host, self._broker_port, keepalive=60)
        except ssl.SSLCertVerificationError as exc:
            raise ConnectionError(
                f"Device {self.device_id}: TLS certificate verification failed connecting to "
                f"{self._broker_host}:{self._broker_port}: {exc}\n"
                "Check that MQTT_TLS_CA_CERT points to the correct Root CA file."
            )
        except ssl.SSLError as exc:
            raise ConnectionError(
                f"Device {self.device_id}: TLS error connecting to "
                f"{self._broker_host}:{self._broker_port}: {exc}\n"
                f"Check certificate files:\n"
                f"  CA:   {self._tls_ca_cert}\n"
                f"  Cert: {self._tls_client_cert}\n"
                f"  Key:  {self._tls_client_key}"
            )
        except OSError as exc:
            raise ConnectionError(
                f"Device {self.device_id}: cannot reach broker {self._broker_host}:{self._broker_port}: {exc}"
            )
        self._client.loop_start()
        if not self._connected.wait(timeout=10):
            self._client.loop_stop()
            raise ConnectionError(
                f"Device {self.device_id}: MQTT connection timeout after 10s "
                f"(broker={self._broker_host}:{self._broker_port}, tls={self._tls_enabled})"
            )

        online_payload = json.dumps({"online": True, "ts": int(time.time() * 1000),
                                      "fw": self.identity.get("fw_version", "1.6.0")})
        self._client.publish(f"{self.base_topic}/meta/online", online_payload, qos=1, retain=True)

        self._device_hb_stop.clear()
        self._device_hb_thread = threading.Thread(
            target=self._device_hb_loop, daemon=True, name=f"devhb-{self.device_id}",
        )
        self._device_hb_thread.start()

    def _atexit_cleanup(self):
        if self._cleaned_up:
            return
        self._cleaned_up = True
        try:
            self._client.loop_stop()
            self._client.disconnect()
        except Exception:
            pass

    def power_off(self):
        self._log(f"[FW] Power off: {self.device_id}")
        self._hb_stop.set()
        self._device_hb_stop.set()
        if self.session_id:
            try:
                self.stop_session(reason="power_off")
            except Exception:
                pass
        try:
            offline = json.dumps({"online": False, "ts": int(time.time() * 1000)})
            self._client.publish(f"{self.base_topic}/meta/online", offline, qos=1, retain=True)
            self._client.loop_stop()
            self._client.disconnect()
        except Exception:
            pass
        self._set_state(DeviceState.OFFLINE)

    def start_session(self, figurine_id: str, nfc_id: str = "sim-nfc", mode: str = "dialogue"):
        if self.session_id is not None:
            self._log(f"[FW] auto-ending previous session {self.session_id} before starting new one")
            self.stop_session(reason="new_session")

        self.session_id = secrets.token_urlsafe(9)[:12]
        self._turn_counter = 0
        self._cue_counter = 0
        self._cmd_counter = 0
        self.figurine_id = figurine_id
        self.nfc_id = nfc_id
        self.mode = mode
        self._reset_session_events()

        payload = {
            "turn_proto": 1,
            "audio": {"codec": "opus", "sr": _OPUS_SR, "channels": _OPUS_CHANNELS},
            "character": figurine_id,
            "nfc_id": nfc_id,
            "mode": mode,
            "fw": self.identity.get("fw_version", "1.6.0"),
        }
        self._publish_request(f"session/{self.session_id}/start", json.dumps(payload))
        self._log(f"[FW] session/start: {self.session_id} ({figurine_id}, mode={mode})")
        self._set_state(DeviceState.SESSION_ACTIVE)

        self._hb_stop.clear()
        self._hb_thread = threading.Thread(
            target=self._session_hb_loop, daemon=True, name=f"sshb-{self.session_id}",
        )
        self._hb_thread.start()

    def stop_session(self, reason: str = "user_stop"):
        self._hb_stop.set()
        if self.session_id:
            self._publish_request(f"session/{self.session_id}/end", json.dumps({"reason": reason}))
        self._log(f"[FW] session/end: {self.session_id} reason={reason}")
        self._set_state(DeviceState.SESSION_ENDED)
        self.session_id = None

    def start_turn(self, pcm_data: np.ndarray, turn_id: Optional[str] = None) -> str:
        import opuslib_next

        tid = turn_id or self._next_turn_id()
        encoder = opuslib_next.Encoder(_OPUS_SR, _OPUS_CHANNELS, opuslib_next.APPLICATION_AUDIO)
        frame_size = _OPUS_FRAME_SAMPLES
        total_frames = max(1, (len(pcm_data) + frame_size - 1) // frame_size)

        self._set_state(DeviceState.CAPTURING)

        with self._lock:
            tracker = self._get_or_create_turn(tid)
            tracker.state = TurnState.UPLOADING
            tracker.eos_event.clear()
            tracker.sent_at = time.time()

        start_payload = json.dumps({
            "codec": "opus", "sr": _OPUS_SR, "channels": _OPUS_CHANNELS,
        })
        self._publish_request(f"audio/{self.session_id}/{tid}/start", start_payload)

        for seq in range(1, total_frames + 1):
            start_idx = (seq - 1) * frame_size
            end_idx = min(start_idx + frame_size, len(pcm_data))
            frame = pcm_data[start_idx:end_idx]
            if len(frame) < frame_size:
                frame = np.pad(frame, (0, frame_size - len(frame)), mode="constant")
            # dtype-aware: float→int16 转换；int16 直接使用（via pcm_utils 单一权威源）
            frame_int16 = pcm_utils.to_int16_safe(frame)
            opus_data = encoder.encode(frame_int16.tobytes(), frame_size)
            self._client.publish(
                self._request_topic(f"audio/{self.session_id}/{tid}/chunk/{seq}"),
                opus_data, qos=0,
            )
            # ── 发射上传进度事件（每 10 chunk 或百分比里程碑） ──
            if self._on_mqtt_event and (seq % 10 == 0 or seq == total_frames):
                pct = round(seq / total_frames * 100)
                self._on_mqtt_event("upload_progress", {
                    "turn_id": tid,
                    "chunk": seq,
                    "total_chunks": total_frames,
                    "percent": pct,
                })

        duration_ms = int(len(pcm_data) / _OPUS_SR * 1000)
        eos_payload = json.dumps({"total_seq": total_frames, "duration_ms": duration_ms})
        self._publish_request(f"audio/{self.session_id}/{tid}/eos", eos_payload)
        with self._lock:
            tracker = self._active_turns.get(tid)
            if tracker:
                tracker.eos_sent_at = time.time()
        self._set_state(DeviceState.WAITING)
        self._log(f"[FW] turn {tid}: {total_frames} chunks, {duration_ms}ms")
        return tid

    def send_abort(self, turn_id: Optional[str] = None, reason: str = "button_up"):
        tid = turn_id or str(self._turn_counter)
        if not self.session_id:
            return
        self._publish_request(
            f"audio/{self.session_id}/{tid}/abort",
            json.dumps({"reason": reason}),
        )
        self._log(f"[FW] abort turn={tid} reason={reason}")

    def send_done(self, turn_id: str, played_seq: int = 0, dropped: int = 0, latency_ms: int = 0):
        if not self.session_id:
            return
        with self._lock:
            tracker = self._active_turns.get(turn_id)
            if tracker:
                tracker.done_sent_at = time.time()
        payload = json.dumps({
            "played_seq": played_seq, "dropped": dropped, "latency_ms": latency_ms,
            "ts": int(time.time() * 1000),
        })
        self._publish_request(f"audio/{self.session_id}/{turn_id}/done", payload)
        self._log(f"[FW] done turn={turn_id} played_seq={played_seq}")

    def wait_for_turn_response(
        self,
        turn_id: Optional[str] = None,
        timeout: float = 90,
        *,
        expect_downstream: bool = False,
    ) -> bool:
        tid = turn_id or str(self._turn_counter)
        with self._lock:
            tracker = self._active_turns.get(tid)
        if not tracker:
            return False

        deadline = time.time() + timeout
        last_count = 0
        stable_time = time.time()

        while time.time() < deadline:
            with self._lock:
                for cmd in self._commands:
                    if cmd.get("_turn_id") == tid:
                        self._flush_after_audio_commands(tid)
                        return True

            if expect_downstream:
                if tracker.downstream_started and tracker.eos_event.is_set():
                    self._flush_after_audio_commands(tid)
                    return True
            else:
                if tracker.eos_event.is_set():
                    self._flush_after_audio_commands(tid)
                    return True

                if tracker.stt_text:
                    self._flush_after_audio_commands(tid)
                    return True

            if tracker.chunks_received > last_count:
                last_count = tracker.chunks_received
                stable_time = time.time()
            if not expect_downstream and tracker.chunks_received > 5 and time.time() - stable_time > 3.0:
                self._flush_after_audio_commands(tid)
                return True

            time.sleep(0.3)
        return False

    def wait_for_intro_eos(self, timeout: float = 30) -> bool:
        result = self._intro_eos_event.wait(timeout=timeout)
        if result:
            self._log("[FW] introeos received")
        return result

    def wait_for_intro_completion(self, timeout: float = 30) -> bool:
        """Wait for either intro completion signal used by the test rig.

        The chatbot side can legitimately finish the intro in two ways:
        - ``audio/eos`` for turn 0, which marks the intro audio buffer drained
        - ``audio/introeos`` for the explicit intro completion marker

        Some sessions only surface one of those signals, so the simulator
        accepts either one as a successful intro completion.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._intro_eos_event.is_set():
                self._log("[FW] introeos received")
                return True
            if self._intro_audio_eos_event.is_set():
                self._log("[FW] intro audio EOS received")
                return True
            time.sleep(0.05)
        return False

    def wait_for_intro_audio_end(self, timeout: float = 60) -> bool:
        return self._intro_audio_eos_event.wait(timeout=timeout)

    def wait_for_command(self, cmd: str, timeout: float = 10) -> Optional[dict]:
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                for c in self._commands:
                    if c.get("cmd") == cmd:
                        return c
            time.sleep(0.2)
        return None

    def get_playback_audio(self, turn_id: str) -> bytes:
        with self._lock:
            tracker = self._active_turns.get(turn_id)
        return b"".join(tracker.audio_data) if tracker else b""

    def get_cue_audio(self, cue_id: str) -> bytes:
        return self.get_playback_audio(cue_id)

    def get_all_commands(self) -> list[dict]:
        with self._lock:
            return list(self._commands)

    def get_stt_texts(self) -> list[str]:
        with self._lock:
            return list(self._session_stt_texts)

    def get_downstream_stats(self) -> dict:
        """Aggregate downstream TTS statistics across all active turns.

        Returns dict with tts_response_count, tts_chunks, tts_duration_ms,
        per-node latency data (stt_latency_ms, llm_latency_ms, tts_latency_ms, e2e_latency_ms),
        and done receipt latency (done_latency_ms).
        """
        total_responses = 0
        total_chunks = 0
        stt_latency_ms: float = 0.0
        llm_latency_ms: float = 0.0
        tts_latency_ms: float = 0.0
        e2e_latency_ms: float = 0.0
        done_latency_ms: float = 0.0
        with self._lock:
            for tid, tracker in self._active_turns.items():
                if tracker.downstream_started:
                    total_responses += 1
                    total_chunks += tracker.chunks_received
                # Compute per-node latencies from the latest active turn
                if tracker.eos_sent_at > 0 and tracker.vadeos_at > 0:
                    stt_latency_ms = max(stt_latency_ms, (tracker.vadeos_at - tracker.eos_sent_at) * 1000)
                if tracker.vadeos_at > 0 and tracker.tts_start_at > 0:
                    llm_latency_ms = max(llm_latency_ms, (tracker.tts_start_at - tracker.vadeos_at) * 1000)
                if tracker.tts_start_at > 0 and tracker.tts_eos_at > 0:
                    tts_latency_ms = max(tts_latency_ms, (tracker.tts_eos_at - tracker.tts_start_at) * 1000)
                if tracker.eos_sent_at > 0 and tracker.tts_eos_at > 0:
                    e2e_latency_ms = max(e2e_latency_ms, (tracker.tts_eos_at - tracker.eos_sent_at) * 1000)
                if tracker.tts_eos_at > 0 and tracker.done_sent_at > 0:
                    done_latency_ms = max(done_latency_ms, (tracker.done_sent_at - tracker.tts_eos_at) * 1000)
        return {
            "tts_response_count": total_responses,
            "tts_chunks": total_chunks,
            "tts_duration_ms": total_chunks * _OPUS_FRAME_MS,
            "stt_latency_ms": round(stt_latency_ms),
            "llm_latency_ms": round(llm_latency_ms),
            "tts_latency_ms": round(tts_latency_ms),
            "e2e_latency_ms": round(e2e_latency_ms),
            "done_latency_ms": round(done_latency_ms),
        }

    def _flush_after_audio_commands(self, turn_id: str):
        cmds = self._pending_after_audio.pop(turn_id, [])
        for cmd in cmds:
            self._log(f"[FW] executing after_audio command: {cmd.get('cmd')} (turn={turn_id} completed)")

    def _session_hb_loop(self):
        while not self._hb_stop.wait(_SESSION_HB_INTERVAL):
            if not self.session_id:
                break
            try:
                payload = json.dumps({"ts": int(time.time() * 1000)})
                self._publish_request(f"session/{self.session_id}/hb", payload, qos=0)
            except Exception:
                break

    def _device_hb_loop(self):
        while not self._device_hb_stop.wait(_DEVICE_HB_INTERVAL):
            try:
                payload = json.dumps({"ts": int(time.time() * 1000)})
                self._client.publish(f"{self.base_topic}/meta/hb", payload, qos=0)
            except Exception:
                break

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        if rc == 0:
            client.subscribe([
                (f"{self.base_topic}/response/#", 1),
                (f"{self.base_topic}/state/desired", 1),
                (f"{self.base_topic}/ota/desired", 1),
            ])
            self._connected.set()
            self._log("[FW] MQTT connected")

    def _on_disconnect(self, client, userdata, rc, properties=None):
        self._connected.clear()
        self._log(f"[FW] MQTT disconnected: rc={rc}")

    def _on_message(self, client, userdata, msg):
        topic = msg.topic
        short = topic.replace(f"{self.base_topic}/", "")

        if short.startswith("response/audio/"):
            self._handle_audio_message(short, msg)
        elif short.startswith("response/command/"):
            self._handle_command_message(short, msg)
        elif short == "state/desired":
            self._handle_state_desired(msg)
        elif short == "ota/desired":
            self._handle_ota_desired(msg)

    def _handle_audio_message(self, short: str, msg):
        parts = short.split("/")
        if len(parts) < 5:
            return
        _prefix, _audio, _sid, turn_id, action = parts[0], parts[1], parts[2], parts[3], parts[4]

        with self._lock:
            tracker = self._get_or_create_turn(turn_id)

        if action == "start":
            is_downstream = _prefix == "response"
            if is_downstream:
                tracker.downstream_started = True
                tracker.tts_start_at = time.time()
                was_uploading = tracker.chunks_received > 0 or len(tracker.audio_data) > 0
                if was_uploading:
                    self._log(f"[FW] downstream audio/start turn={turn_id} (preserving upload tracker)")
                    tracker.state = TurnState.PLAYING
                    tracker.eos_event.clear()
                    if self._on_mqtt_event:
                        self._on_mqtt_event("tts_synthesis", {
                            "state": "start",
                            "turn_id": turn_id,
                        })
                    return
            tracker.chunks_received = 0
            tracker.audio_data = []
            tracker.eos_event.clear()
            tracker.state = TurnState.PLAYING
            self._log(f"[FW] audio/start turn={turn_id} cue={self._is_cue_turn_id(turn_id)}")
            if self._on_mqtt_event:
                self._on_mqtt_event("audio_start", {
                    "turn_id": turn_id,
                    "cue": self._is_cue_turn_id(turn_id),
                    "sample_rate": _OPUS_SR,
                    "channels": _OPUS_CHANNELS,
                })

        elif action.startswith("chunk"):
            tracker.chunks_received += 1
            tracker.audio_data.append(msg.payload)
            # ── 发射音频 chunk 到前端（用于播放） ──
            if self._on_mqtt_event:
                import base64
                self._on_mqtt_event("audio_chunk", {
                    "turn_id": turn_id,
                    "seq": tracker.chunks_received,
                    "audio_b64": base64.b64encode(msg.payload).decode("ascii"),
                    "codec": "opus",
                })
            # ── 发射 TTS 下载进度事件（每 10 chunk） ──
            if self._on_mqtt_event and tracker.chunks_received % 10 == 0:
                self._on_mqtt_event("tts_progress", {
                    "turn_id": turn_id,
                    "chunks_received": tracker.chunks_received,
                })

        elif action == "eos":
            try:
                data = json.loads(msg.payload.decode("utf-8")) if msg.payload else {}
            except Exception:
                data = {}
            tracker.eos_total_seq = data.get("total_seq")
            tracker.state = TurnState.DONE
            tracker.eos_event.set()
            tracker.tts_eos_at = time.time()

            if turn_id == "0":
                self._intro_audio_eos_event.set()
                self._log("[FW] intro audio EOS")
                if self._on_mqtt_event:
                    self._on_mqtt_event("tts_synthesis", {
                        "state": "complete",
                        "turn_id": "0",
                    })
            elif self._is_cue_turn_id(turn_id):
                self._log(f"[FW] cue audio EOS turn={turn_id}")
                if self.on_cue_audio:
                    self.on_cue_audio(turn_id, tracker.audio_data)
            else:
                self._log(f"[FW] TTS EOS turn={turn_id} total_seq={tracker.eos_total_seq}")
                if self._on_mqtt_event:
                    self._on_mqtt_event("tts_synthesis", {
                        "state": "complete",
                        "turn_id": turn_id,
                    })

            self.send_done(turn_id, played_seq=tracker.chunks_received)

        elif action == "abort":
            tracker.state = TurnState.ABORTED
            tracker.eos_event.set()
            self._log(f"[FW] audio/abort turn={turn_id}")

        elif action == "vadeos":
            try:
                data = json.loads(msg.payload.decode("utf-8")) if msg.payload else {}
                tracker.stt_text = data.get("text", "")
                tracker.vadeos_at = time.time()
                with self._lock:
                    self._session_stt_texts.append(tracker.stt_text)
                self._log(f"[FW] vadeos turn={turn_id} text=\"{tracker.stt_text[:60]}\"")
                if self._on_mqtt_event:
                    self._on_mqtt_event("stt_inference", {
                        "text": tracker.stt_text,
                        "turn_id": turn_id,
                    })
            except Exception:
                pass

        elif action == "introeos":
            self._intro_eos_event.set()
            self._log("[FW] introeos")
            if self._on_mqtt_event:
                self._on_mqtt_event("introeos", {
                    "turn_id": turn_id,
                })

    def _handle_command_message(self, short: str, msg):
        try:
            data = json.loads(msg.payload.decode("utf-8")) if msg.payload else {}
        except Exception:
            return

        parts = short.split("/")
        turn_id = parts[3] if len(parts) >= 4 else None
        data["_turn_id"] = turn_id

        with self._lock:
            self._commands.append(data)

        if self._on_mqtt_event:
            self._on_mqtt_event("llm_inference", {
                "command": data,
                "turn_id": turn_id,
            })

        cmd = data.get("cmd", "")
        preempt = data.get("preempt", False)
        after_audio = data.get("after_audio", False)

        if preempt:
            self._log(f"[FW] command PREEMPT: {cmd}")
        elif after_audio and turn_id:
            self._pending_after_audio.setdefault(turn_id, []).append(data)
            self._log(f"[FW] command after_audio: {cmd} (waiting turn={turn_id})")
        else:
            self._log(f"[FW] command: {cmd}")

        if self.on_command:
            self.on_command(data)

    def _handle_state_desired(self, msg):
        try:
            data = json.loads(msg.payload.decode("utf-8")) if msg.payload else {}
        except Exception:
            return
        ver = data.get("ver", 0)
        if self._config_reported_ver is not None and ver <= self._config_reported_ver:
            return
        self._log(f"[FW] state/desired ver={ver}")
        reported = {"ver": ver, "status": "ok", "applied_at": int(time.time() * 1000)}
        self._client.publish(f"{self.base_topic}/state/reported", json.dumps(reported), qos=1)
        self._config_reported_ver = ver
        if self.on_config:
            self.on_config(data)

    def _handle_ota_desired(self, msg):
        try:
            data = json.loads(msg.payload.decode("utf-8")) if msg.payload else {}
        except Exception:
            return
        ver = data.get("ver", 0)
        if self._ota_reported_ver is not None and ver <= self._ota_reported_ver:
            return
        fw_version = data.get("fw_version", "unknown")
        self._log(f"[FW] ota/desired ver={ver} fw={fw_version}")
        reported = {"ver": ver, "status": "downloading", "progress": 0}
        self._client.publish(f"{self.base_topic}/ota/reported", json.dumps(reported), qos=1)

        reported = {"ver": ver, "status": "success", "fw_version": fw_version}
        self._client.publish(f"{self.base_topic}/ota/reported", json.dumps(reported), qos=1)
        self._ota_reported_ver = ver
        self.identity["fw_version"] = fw_version
        self._identity_file.write_text(json.dumps(self.identity, indent=2))
        if self.on_ota:
            self.on_ota(data)

    def _request_topic(self, suffix: str) -> str:
        return f"{self.base_topic}/request/{suffix}"

    def _publish_request(self, suffix: str, payload: str, qos: int = 1):
        result = self._client.publish(self._request_topic(suffix), payload, qos=qos)
        if not self._connected.is_set() or result.rc != 0:
            self._log(f"[FW] publish FAILED topic={self._request_topic(suffix)} rc={result.rc} connected={self._connected.is_set()}")

    def _set_state(self, state: DeviceState):
        self.state = state
        if self.on_state_change:
            self.on_state_change(state)

    def _log(self, msg: str):
        if self.on_log:
            self.on_log(msg)

    def _reset_session_events(self):
        self._intro_eos_event.clear()
        self._intro_audio_eos_event.clear()
        with self._lock:
            self._active_turns.clear()
            self._commands.clear()
            self._pending_after_audio.clear()
            self._session_stt_texts.clear()
        self._last_error = ""

    def get_status(self) -> dict:
        with self._lock:
            active_turn_ids = list(self._active_turns.keys())
            command_count = len(self._commands)
        return {
            "device_id": self.device_id,
            "state": self.state.value,
            "session_id": self.session_id,
            "turn_id": str(self._turn_counter),
            "connected": self._connected.is_set(),
            "active_turns": active_turn_ids,
            "commands_received": command_count,
            "stt_texts": self._session_stt_texts,
            "fw_version": self.identity.get("fw_version", "1.6.0"),
        }
