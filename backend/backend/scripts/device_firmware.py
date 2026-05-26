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
                 "eos_event", "audio_data", "stt_text", "downstream_started")

    def __init__(self, turn_id: str):
        self.turn_id = turn_id
        self.state = TurnState.PLAYING
        self.chunks_received = 0
        self.eos_total_seq: Optional[int] = None
        self.eos_event = threading.Event()
        self.audio_data: list[bytes] = []
        self.stt_text: str = ""
        self.downstream_started = False


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
        on_mqtt_event: Optional[callable] = None,
    ):
        self.device_id = device_id
        self._on_mqtt_event = on_mqtt_event
        self.env = env or _MQTT_ENV
        self._broker_host = broker_host or _MQTT_BROKER
        self._broker_port = broker_port or _MQTT_PORT
        self._username = username or os.getenv("MQTT_USERNAME")
        self._password = password or os.getenv("MQTT_PASSWORD")
        self._tls_enabled = tls_enabled

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
            self._client.tls_set()
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._client.on_disconnect = self._on_disconnect

        self._connected = threading.Event()
        self._intro_eos_event = threading.Event()
        self._intro_audio_eos_event = threading.Event()
        self._lock = threading.Lock()

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
        self._log(f"[FW] Power on: {self.device_id}")

        lwt_payload = json.dumps({"online": False, "ts": int(time.time() * 1000),
                                   "fw": self.identity.get("fw_version", "1.6.0")})
        self._client.will_set(
            f"{self.base_topic}/meta/online", lwt_payload, qos=1, retain=True,
        )

        self._set_state(DeviceState.IDLE)
        self._client.connect(self._broker_host, self._broker_port, keepalive=60)
        self._client.loop_start()
        if not self._connected.wait(timeout=10):
            raise ConnectionError(f"Device {self.device_id}: MQTT connection timeout")

        online_payload = json.dumps({"online": True, "ts": int(time.time() * 1000),
                                      "fw": self.identity.get("fw_version", "1.6.0")})
        self._client.publish(f"{self.base_topic}/meta/online", online_payload, qos=1, retain=True)

        self._device_hb_stop.clear()
        self._device_hb_thread = threading.Thread(
            target=self._device_hb_loop, daemon=True, name=f"devhb-{self.device_id}",
        )
        self._device_hb_thread.start()

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

        duration_ms = int(len(pcm_data) / _OPUS_SR * 1000)
        eos_payload = json.dumps({"total_seq": total_frames, "duration_ms": duration_ms})
        self._publish_request(f"audio/{self.session_id}/{tid}/eos", eos_payload)
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
                self._on_mqtt_event("tts_synthesis", {
                    "state": "start",
                    "turn_id": turn_id,
                })

        elif action.startswith("chunk"):
            tracker.chunks_received += 1
            tracker.audio_data.append(msg.payload)

        elif action == "eos":
            try:
                data = json.loads(msg.payload.decode("utf-8")) if msg.payload else {}
            except Exception:
                data = {}
            tracker.eos_total_seq = data.get("total_seq")
            tracker.state = TurnState.DONE
            tracker.eos_event.set()

            if turn_id == "0":
                self._intro_audio_eos_event.set()
                self._log("[FW] intro audio EOS")
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
        self._client.publish(self._request_topic(suffix), payload, qos=qos)

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
