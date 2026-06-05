"""
MQTT Device Simulator -- send audio to chatbot via real MQTT protocol.

Architecture (v2 — true device lifecycle):
  ConnectedDevice — persistent online device (power_on once, many sessions)
  MQTTDeviceSimulator — runs one session on a connected device
  SimulationManager — manages device connections, sessions, and results

Device lifecycle:
  connect_device()  → DeviceFirmware.power_on()  → device stays online
  run_simulation()  → start_session → start_turn → wait → stop_session
  run_simulation()  → another session on the same device (new session_id)
  disconnect_device() → DeviceFirmware.power_off() → device offline

v1.6 features (via DeviceFirmware):
  - Session heartbeat (60s), device heartbeat (30s)
  - Cue audio turn detection and tracking
  - Turn-level command (after_audio / preempt)
  - Playback done receipt
  - Abort support
  - LWT (Last Will and Testament) for meta/online
  - OTA / config sync
"""

import json
import logging
import os
import queue
import secrets
import threading
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Callable, Optional

import soundfile as sf

import sys

import pcm_utils

logger = logging.getLogger("mqtt_bridge")

# 音频格式常量（委托 pcm_utils 作为单一权威源）
OPUS_SR = pcm_utils.PCM_SR
OPUS_CHANNELS = pcm_utils.PCM_CHANNELS
OPUS_FRAME_MS = pcm_utils.OPUS_FRAME_MS
OPUS_FRAME_SAMPLES = pcm_utils.OPUS_FRAME_SAMPLES
OPUS_FRAME_BYTES = pcm_utils.OPUS_FRAME_BYTES
DEFAULT_MQTT_BROKER_PROFILE = os.getenv("MQTT_BROKER_PROFILE", "local")


@dataclass
class ResponseEvent:
    topic: str
    response_type: str
    payload: dict = field(default_factory=dict)
    timestamp: float = 0.0


@dataclass
class SimulationResult:
    session_id: str
    device_id: str
    figurine_id: str
    mode: str
    audio_id: str
    status: str = "pending"
    audio_duration_sec: float = 0.0
    total_chunks: int = 0
    send_duration_sec: float = 0.0
    started_at: float = 0.0
    completed_at: float = 0.0
    stt_text: str = ""
    stt_confidence: float = 0.0
    stt_language: str = ""
    tts_response_count: int = 0
    tts_chunks: int = 0
    tts_duration_ms: int = 0
    stt_latency_ms: int = 0
    llm_latency_ms: int = 0
    tts_latency_ms: int = 0
    e2e_latency_ms: int = 0
    done_latency_ms: int = 0
    reply_text: str = ""
    all_commands: list = field(default_factory=list)
    backend_responses: list = field(default_factory=list)
    error: str = ""
    _event_log: list = field(default_factory=list)
    cue_count: int = 0
    commands_received: int = 0
    stt_texts: list = field(default_factory=list)
    vad_bypassed: bool = False
    vad_blocked_warning: str = ""


def _extract_reply_text(commands: list[dict]) -> str:
    """从 MQTT 命令列表中提取 LLM 回复文本。

    优先级：
    1. `text` 字段 — chatbot 在对话模式下可能携带的 LLM 回复文本
    2. `cmd` 字段 — 语音命令文本（fallback）

    返回最后一个命中的文本（与原有行为一致：取最后一条命令）。
    """
    reply = ""
    for cmd in commands:
        text = cmd.get("text") or cmd.get("reply") or ""
        if text:
            reply = text
        elif cmd.get("cmd"):
            reply = cmd["cmd"]
    return reply


def _resolve_mqtt_host() -> str:
    host = os.getenv("MQTT_HOST")
    if host:
        return host
    if sys.platform == "win32":
        try:
            import subprocess
            result = subprocess.run(
                ["wsl", "hostname", "-I"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                wsl_ip = result.stdout.strip().split()[0]
                if wsl_ip:
                    return wsl_ip
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            pass
    return "localhost"


def _resolve_local_mqtt_host() -> str:
    """Resolve the local broker host without reading the generic MQTT_HOST env.

    Local test mode should prefer the workspace broker (WSL Mosquitto / localhost),
    while still supporting the Windows-to-WSL bridge pattern used by the test rig.
    """
    if sys.platform == "win32":
        try:
            import subprocess

            result = subprocess.run(
                ["wsl", "hostname", "-I"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                wsl_ip = result.stdout.strip().split()[0]
                if wsl_ip:
                    return wsl_ip
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            pass
    return "localhost"


def _resolve_mqtt_port() -> int:
    raw = os.getenv("MQTT_PORT", "1883")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 1883


def _resolve_mqtt_env() -> str:
    return os.getenv("MQTT_ENV", "development")


def _resolve_mqtt_tls() -> bool:
    raw = os.getenv("MQTT_TLS", "false")
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _resolve_mqtt_profile(raw_profile: str | None) -> str:
    profile = (raw_profile or DEFAULT_MQTT_BROKER_PROFILE or "local").strip().lower()
    if profile in {"local", "relay", "custom", "aws_iot"}:
        return profile
    return "local"


def _find_one(base_dir: Path, patterns: tuple[str, ...], label: str) -> Path:
    """Find exactly one file matching the given patterns under base_dir."""
    for pattern in patterns:
        matches = sorted(path for path in base_dir.glob(pattern) if path.is_file())
        if len(matches) == 1:
            return matches[0]
        non_sg_matches = [path for path in matches if ".sg." not in path.name]
        if len(non_sg_matches) == 1:
            return non_sg_matches[0]
    all_matches: list[Path] = []
    for pattern in patterns:
        all_matches.extend(sorted(path for path in base_dir.glob(pattern) if path.is_file()))
    unique_matches = list(dict.fromkeys(all_matches))
    if len(unique_matches) == 1:
        return unique_matches[0]
    if not unique_matches:
        raise FileNotFoundError(f"No {label} found under {base_dir}")
    formatted = "\n  ".join(str(path) for path in unique_matches)
    raise ValueError(
        f"Multiple {label} files found under {base_dir}; specify explicitly:\n  {formatted}"
    )


def _find_ca(thing_dir: Path, cert_root: Path | None) -> Path | None:
    """Find root CA certificate (AmazonRootCA*.pem / root-CA.crt) in given dirs."""
    ca_patterns = ("root-CA.crt", "AmazonRootCA*.pem", "*RootCA*.pem", "*.ca.pem")
    base_dirs = [thing_dir]
    if cert_root:
        base_dirs.append(cert_root)
    for base_dir in base_dirs:
        for pattern in ca_patterns:
            matches = sorted(path for path in base_dir.rglob(pattern) if path.is_file())
            if matches:
                return matches[0]
    return None


def _resolve_aws_iot_certs(
    explicit_ca: str | None = None,
    explicit_cert: str | None = None,
    explicit_key: str | None = None,
) -> tuple[str | None, str | None, str | None]:
    """Auto-discover AWS IoT TLS certificates from environment variables.

    Order of precedence:
      1. Explicitly passed paths (from frontend UI)
      2. Auto-discovered from AWS_IOT_CERT_ROOT / AWS_IOT_THING
      3. Environment variables MQTT_TLS_CA_CERT / MQTT_TLS_CLIENT_CERT / MQTT_TLS_CLIENT_KEY
    """
    # Already explicitly provided via API call → use as-is
    if explicit_ca and explicit_cert and explicit_key:
        return explicit_ca, explicit_cert, explicit_key

    cert_root_env = os.getenv("AWS_IOT_CERT_ROOT")
    thing_env = os.getenv("AWS_IOT_THING")
    thing_dir: Path | None = None
    if cert_root_env and thing_env:
        td = Path(cert_root_env) / thing_env
        if td.is_dir():
            thing_dir = td

    ca = explicit_ca
    cert = explicit_cert
    key = explicit_key

    if thing_dir:
        if not cert:
            try:
                cert = str(_find_one(thing_dir, ("*.cert.pem", "*.pem.crt"), "cert file"))
            except (FileNotFoundError, ValueError):
                pass
        if not key:
            try:
                key = str(_find_one(thing_dir, ("*.private.key", "*-private.key"), "key file"))
            except (FileNotFoundError, ValueError):
                pass
        if not ca:
            ca_path = _find_ca(thing_dir, Path(cert_root_env) if cert_root_env else None)
            if ca_path:
                ca = str(ca_path)

    # Fall back to environment variables
    if not ca:
        ca = explicit_ca or os.getenv("MQTT_TLS_CA_CERT")
    if not cert:
        cert = explicit_cert or os.getenv("MQTT_TLS_CLIENT_CERT")
    if not key:
        key = explicit_key or os.getenv("MQTT_TLS_CLIENT_KEY")

    return ca, cert, key


def _resolve_broker_config(
    *,
    mqtt_profile: str | None = None,
    mqtt_env: str | None = None,
    mqtt_host: str | None = None,
    mqtt_port: int | None = None,
    mqtt_tls: bool | None = None,
    mqtt_tls_ca_cert: str | None = None,
    mqtt_tls_client_cert: str | None = None,
    mqtt_tls_client_key: str | None = None,
    mqtt_tls_insecure: bool | None = None,
) -> tuple[str, str, str, int, bool, str | None, str | None, str | None, bool]:
    profile = _resolve_mqtt_profile(mqtt_profile)

    if profile == "local":
        env = mqtt_env or _resolve_mqtt_env()
        host = mqtt_host or _resolve_local_mqtt_host()
        port = mqtt_port if mqtt_port is not None else 1883
        tls = False if mqtt_tls is None else bool(mqtt_tls)
        ca_cert = mqtt_tls_ca_cert or os.getenv("MQTT_TLS_CA_CERT")
        client_cert = mqtt_tls_client_cert or os.getenv("MQTT_TLS_CLIENT_CERT")
        client_key = mqtt_tls_client_key or os.getenv("MQTT_TLS_CLIENT_KEY")
        tls_insecure = _resolve_tls_insecure(mqtt_tls_insecure)
        return profile, env, host, port, tls, ca_cert, client_cert, client_key, tls_insecure

    if profile == "relay":
        env = mqtt_env or os.getenv("MQTT_RELAY_ENV", "development")
        host = mqtt_host or os.getenv("MQTT_RELAY_HOST") or _resolve_mqtt_host()
        port = mqtt_port if mqtt_port is not None else int(os.getenv("MQTT_RELAY_PORT", str(_resolve_mqtt_port())))
        tls_raw = os.getenv("MQTT_RELAY_TLS")
        if mqtt_tls is None:
            if tls_raw is None:
                tls = _resolve_mqtt_tls()
            else:
                tls = str(tls_raw).strip().lower() in {"1", "true", "yes", "on"}
        else:
            tls = bool(mqtt_tls)
        ca_cert = mqtt_tls_ca_cert or os.getenv("MQTT_TLS_CA_CERT")
        client_cert = mqtt_tls_client_cert or os.getenv("MQTT_TLS_CLIENT_CERT")
        client_key = mqtt_tls_client_key or os.getenv("MQTT_TLS_CLIENT_KEY")
        tls_insecure = _resolve_tls_insecure(mqtt_tls_insecure)
        return profile, env, host, port, tls, ca_cert, client_cert, client_key, tls_insecure

    if profile == "aws_iot":
        # AWS IoT uses TLS by default with port 8883
        env = mqtt_env or os.getenv("MQTT_ENV", "development")
        host = mqtt_host or os.getenv("MQTT_HOST", "")
        port = mqtt_port if mqtt_port is not None else int(os.getenv("MQTT_PORT", "8883"))
        # TLS is always enabled for AWS IoT; user can override to disable
        tls = True if mqtt_tls is None else bool(mqtt_tls)
        # Auto-discover TLS certificates
        ca_cert, client_cert, client_key = _resolve_aws_iot_certs(
            explicit_ca=mqtt_tls_ca_cert,
            explicit_cert=mqtt_tls_client_cert,
            explicit_key=mqtt_tls_client_key,
        )
        tls_insecure = _resolve_tls_insecure(mqtt_tls_insecure)
        return profile, env, host, port, tls, ca_cert, client_cert, client_key, tls_insecure

    # "custom" profile fallback
    env = mqtt_env or _resolve_mqtt_env()
    host = mqtt_host or _resolve_mqtt_host()
    port = mqtt_port if mqtt_port is not None else _resolve_mqtt_port()
    tls = _resolve_mqtt_tls() if mqtt_tls is None else bool(mqtt_tls)
    ca_cert = mqtt_tls_ca_cert or os.getenv("MQTT_TLS_CA_CERT")
    client_cert = mqtt_tls_client_cert or os.getenv("MQTT_TLS_CLIENT_CERT")
    client_key = mqtt_tls_client_key or os.getenv("MQTT_TLS_CLIENT_KEY")
    tls_insecure = _resolve_tls_insecure(mqtt_tls_insecure)
    return profile, env, host, port, tls, ca_cert, client_cert, client_key, tls_insecure


def _resolve_tls_insecure(raw: bool | None) -> bool:
    if raw is not None:
        return bool(raw)
    return os.getenv("MQTT_TLS_INSECURE", "false").lower() in {"1", "true", "yes", "on"}


class SimulationEventBus:
    def __init__(self):
        self._queues: dict[str, queue.Queue] = {}
        self._lock = threading.Lock()

    def create_queue(self, key: str) -> queue.Queue:
        with self._lock:
            q = self._queues.get(key)
            if q is None:
                q = queue.Queue()
                self._queues[key] = q
            return q

    def alias_queue(self, existing_key: str, new_key: str):
        with self._lock:
            q = self._queues.get(existing_key)
            if q is not None and new_key not in self._queues:
                self._queues[new_key] = q

    def remove_queue(self, key: str):
        with self._lock:
            self._queues.pop(key, None)

    def publish(self, key: str, event: dict):
        with self._lock:
            q = self._queues.get(key)
            if q is not None:
                try:
                    q.put_nowait(event)
                except queue.Full:
                    pass


class ConnectedDevice:
    """A persistent online device with its own MQTT connection.

    Simulates real device behavior:
      - power_on() once → device goes online (meta/online + LWT + device heartbeat)
      - Multiple sessions can be run (each with its own session_id)
      - power_off() → device goes offline
    """

    def __init__(
        self,
        device_id: str,
        figurine_id: str,
        mode: str = "dialogue",
        *,
        nfc_id: str = "sim-nfc",
        broker_profile: str = "local",
        env: str = "development",
        broker_host: str = "localhost",
        broker_port: int = 1883,
        broker_tls: bool = False,
        broker_tls_ca_cert: Optional[str] = None,
        broker_tls_client_cert: Optional[str] = None,
        broker_tls_client_key: Optional[str] = None,
        broker_tls_insecure: bool = False,
        subscribe_response: bool = True,
        speed: float = 0,
        event_bus: Optional[SimulationEventBus] = None,
    ):
        self.device_id = device_id
        self.figurine_id = figurine_id
        self.mode = mode
        self.nfc_id = nfc_id
        self.broker_profile = broker_profile
        self.env = env
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.broker_tls = broker_tls
        self.broker_tls_ca_cert = broker_tls_ca_cert
        self.broker_tls_client_cert = broker_tls_client_cert
        self.broker_tls_client_key = broker_tls_client_key
        self.broker_tls_insecure = broker_tls_insecure
        self.subscribe_response = subscribe_response
        self.speed = speed
        self.event_bus = event_bus

        self._fw = None
        self._connected = False
        self._simulating = False
        self._stop_requested = False
        self.session_id: Optional[str] = secrets.token_urlsafe(9)[:12]
        self._last_seen: float = time.time()  # frontend keepalive heartbeat
        self._lock = threading.Lock()

    def touch_seen(self):
        """Mark device as recently active (called on connect / keepalive)."""
        self._last_seen = time.time()

    @property
    def seconds_since_seen(self) -> float:
        return time.time() - self._last_seen

    @property
    def is_stale(self, timeout: float = 60) -> bool:
        """Device is stale if no keepalive for >timeout seconds AND not simulating."""
        return (not self._simulating) and (time.time() - self._last_seen > timeout)

    @staticmethod
    def _parse_response_topic(topic: str) -> tuple[str, dict[str, str]]:
        """Compatibility helper for the legacy test suite."""
        parts = topic.split("/")
        if "response" not in parts:
            return "raw", {}

        idx = parts.index("response")
        if idx + 1 >= len(parts):
            return "raw", {}

        response_type = parts[idx + 1]
        meta: dict[str, str] = {}

        if response_type == "vadeos":
            if idx + 3 < len(parts):
                meta["session_id"] = parts[idx + 2]
                meta["turn_id"] = parts[idx + 3]
            return "vadeos", meta

        if response_type == "audio":
            if idx + 4 >= len(parts):
                return "raw", {}
            meta["session_id"] = parts[idx + 2]
            meta["turn_id"] = parts[idx + 3]
            action = parts[idx + 4]
            if action == "chunk" and idx + 5 < len(parts):
                meta["seq"] = parts[idx + 5]
            mapping = {
                "start": "audio_start",
                "chunk": "audio_chunk",
                "eos": "audio_eos",
                "abort": "audio_abort",
                "introeos": "audio_introeos",
                "vadeos": "vadeos",
            }
            return mapping.get(action, "raw"), meta

        if response_type == "command":
            if idx + 2 < len(parts):
                meta["session_id"] = parts[idx + 2]
            return "command", meta

        return "raw", {}

    def _topic(self, kind: str, suffix: str) -> str:
        return f"{self.env}/{self.device_id}/request/{kind}/{suffix}"

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def is_simulating(self) -> bool:
        return self._simulating

    def power_on(self):
        from scripts.device_firmware import DeviceFirmware

        # When profile is "local", explicitly pass empty credentials to override
        # any MQTT_USERNAME/MQTT_PASSWORD env vars.  Local NanoMQ/Mosquitto uses
        # anonymous auth; sending credentials causes rc=7 disconnects.
        _is_local = self.broker_profile == "local"
        self._fw = DeviceFirmware(
            self.device_id,
            env=self.env,
            broker_host=self.broker_host,
            broker_port=self.broker_port,
            username="" if _is_local else None,
            password="" if _is_local else None,
            tls_enabled=self.broker_tls,
            tls_ca_cert=self.broker_tls_ca_cert,
            tls_client_cert=self.broker_tls_client_cert,
            tls_client_key=self.broker_tls_client_key,
            tls_insecure=self.broker_tls_insecure,
            on_mqtt_event=self._on_fw_mqtt_event,
        )
        self._fw.on_log = self._on_fw_log
        self._fw.on_command = self._on_fw_command
        self._fw.on_cue_audio = self._on_fw_cue
        self._fw.on_state_change = self._on_fw_state_change

        self._emit_device(
            "mqtt_connecting",
            {
                "broker": f"{self.broker_host}:{self.broker_port}",
                "tls": self.broker_tls,
                "profile": self.broker_profile,
            },
        )
        self._fw.power_on()
        self._connected = True
        self._emit_device("mqtt_connected", {"rc": 0})
        self._emit_device("device_state", {"state": "idle"})
        logger.info("Device %s powered on", self.device_id)

    def power_off(self):
        if self._fw:
            try:
                self._fw.power_off()
            except Exception:
                pass
        self._connected = False
        self._emit_device("mqtt_disconnected", {"rc": 0})
        self._emit_device("device_state", {"state": "offline"})
        logger.info("Device %s powered off", self.device_id)

    def simulate_from_wav(self, wav_path: Path, audio_id: str = "", speed: float = 0, subscribe_response: bool = True):
        """[DEPRECATED] Legacy simulation entry point — emits fake events when no fw.

        Prefer `run_session()` (full session) or `send_user_turn()` (turn on active session)
        which always go through the real DeviceFirmware MQTT pipeline.

        This method has a fallback branch for `self._fw is None` that emits synthetic
        events WITHOUT real MQTT traffic — results from that path are NOT trustworthy.
        """
        if self._fw is not None:
            return self.run_session(wav_path=wav_path, audio_id=audio_id, speed=speed, subscribe_response=subscribe_response)

        # ── ⚠️ DEPRECATED: no-fw fallback — synthetic events, no real MQTT traffic ──
        logger.warning(
            "Device %s: simulate_from_wav called without DeviceFirmware — "
            "emitting synthetic events (no real MQTT). Results are untrustworthy. "
            "Use connect_device() + run_session() instead.",
            self.device_id,
        )

        pcm_data, duration_sec = self._load_wav(wav_path)
        chunks = max(1, (len(pcm_data) + OPUS_FRAME_SAMPLES - 1) // OPUS_FRAME_SAMPLES)

        with self._lock:
            self._simulating = True
            self._stop_requested = False
            session_id = self.session_id or secrets.token_urlsafe(9)[:12]
            self.session_id = session_id

        result = SimulationResult(
            session_id=session_id,
            device_id=self.device_id,
            figurine_id=self.figurine_id,
            mode=self.mode,
            audio_id=audio_id,
        )
        result.started_at = time.time()
        result.status = "pending"
        result.audio_duration_sec = duration_sec
        result.total_chunks = chunks
        result.send_duration_sec = max(duration_sec, 0.01)

        self._emit_device(
            "mqtt_connecting",
            {
                "broker": f"{self.broker_host}:{self.broker_port}",
                "tls": self.broker_tls,
                "profile": self.broker_profile,
            },
        )
        self._emit_device("mqtt_connected", {"rc": 0})
        self._emit_device("device_state", {"state": "idle"})
        self._emit_session(session_id, "session_status", {"status": "active", "session_id": session_id})

        base_topic = f"{self.env}/{self.device_id}"

        def _publish(topic: str, payload: str = ""):
            self._emit_device("mqtt_publish", {"topic": topic, "payload": payload})
            if self._fw and self._connected:
                try:
                    self._fw._client.publish(topic, payload, qos=1)
                except Exception as exc:
                    logger.warning("MQTT publish failed for %s: %s", topic, exc)

        # If we have a real DeviceFirmware connection, use it for proper MQTT + Opus encoding
        use_fw = self._fw and self._connected and hasattr(self._fw, 'start_session')
        if use_fw:
            self._fw.session_id = session_id
            self._fw.start_session(self.figurine_id, nfc_id=self.nfc_id or "sim-nfc", mode=self.mode)
            logger.info("[run_session] Using DeviceFirmware for real MQTT publish, session=%s", session_id)
        else:
            _publish(f"{base_topic}/request/session/{session_id}/start",
                     json.dumps({"turn_proto": 1, "audio": {"codec": "opus", "sr": 16000, "channels": 1},
                                 "character": self.figurine_id, "nfc_id": self.nfc_id or "sim-nfc",
                                 "mode": self.mode, "fw": "1.6.0"}))
            _publish(f"{base_topic}/request/audio/{session_id}/turn-1/start",
                     json.dumps({"codec": "opus", "sr": 16000, "channels": 1}))

        stopped = False
        if use_fw:
            # Use DeviceFirmware for proper Opus encoding + real MQTT publish
            try:
                self._fw.start_turn(pcm_data, turn_id="turn-1")
                logger.info("[run_session] Audio uploaded via DeviceFirmware, %d samples", len(pcm_data))
            except Exception as exc:
                logger.warning("[run_session] DeviceFirmware.start_turn failed: %s, falling back to event-only", exc)
        else:
            for seq in range(chunks):
                if getattr(self, "_stop_requested", False):
                    stopped = True
                    break
                _publish(f"{base_topic}/request/audio/{session_id}/turn-1/chunk/{seq}")

        _publish(f"{base_topic}/request/audio/{session_id}/turn-1/eos")
        if use_fw:
            self._fw.stop_session(reason="simulate_complete")
        _publish(f"{base_topic}/request/session/{session_id}/end")

        if not stopped:
            result.status = "completed"
        result.completed_at = time.time()

        self._emit_session(session_id, "session_status", {
            "status": result.status,
            "send_duration_sec": result.send_duration_sec,
            "audio_duration_sec": result.audio_duration_sec,
            "total_chunks": result.total_chunks,
            "stt_text": result.stt_text,
            "reply_text": result.reply_text,
        })
        self._emit_session(session_id, "session_closed", {"session_id": session_id})

        with self._lock:
            self._simulating = False
            self._stop_requested = False
            self.session_id = None

        return result

    def stop(self):
        self._stop_requested = True
        self.stop_current_session()

    def start_session_and_await_intro(self) -> Optional[str]:
        """Start a session and wait for server intro audio to finish.
        
        Unlike run_session(), this does NOT send any user audio turn.
        It just opens the session so the server plays the intro.
        After intro ends, the session stays alive for subsequent user turns.
        Returns the session_id, or None if failed.
        """
        if not self._connected or not self._fw:
            logger.warning("Device %s not connected, cannot start intro session", self.device_id)
            return None

        with self._lock:
            if self._simulating:
                logger.warning("Device %s already has active session", self.device_id)
                return None
            self._simulating = True

        try:
            self._fw.start_session(
                figurine_id=self.figurine_id,
                nfc_id=self.nfc_id,
                mode=self.mode,
            )
            session_id = self._fw.session_id
            self.session_id = session_id
            self.touch_seen()
            logger.info("Intro session started: %s", session_id)

            self._emit_session(session_id, "session_status", {
                "status": "active",
                "session_id": session_id,
            })
            self._emit_session(session_id, "intro", {"status": "intro_playing"})
            # Also emit to device queue so the device WebSocket receives it
            # (frontend only connects /ws/device/{id}, not /ws/session/{id})
            self._emit_device("intro", {"status": "intro_playing", "session_id": session_id})

            intro_ok = self._fw.wait_for_intro_completion(timeout=30)
            if intro_ok:
                logger.info("Intro EOS received for session %s", session_id)
                self._emit_session(session_id, "intro", {
                    "status": "intro_complete",
                    "session_id": session_id,
                })
                self._emit_device("intro", {"status": "intro_complete", "session_id": session_id})
            else:
                logger.warning("Intro EOS timeout for session %s (30s), proceeding without intro", session_id)
                self._emit_session(session_id, "intro", {
                    "status": "intro_timeout",
                    "session_id": session_id,
                })
                self._emit_device("intro", {"status": "intro_timeout", "session_id": session_id})

            return session_id

        except Exception as exc:
            logger.exception("Intro session failed on device %s: %s", self.device_id, exc)
            self._emit_device("device_error", {"error": str(exc)})
            return None

        finally:
            with self._lock:
                self._simulating = False

    def send_user_turn(self, wav_path: Path) -> SimulationResult:
        """Send a user audio turn on the already-active session.

        The session must have been started by start_session_and_await_intro().
        After the turn completes, the session stays alive for more turns.
        If the previous session was closed (e.g. by run_session), auto-start a new one.
        """
        import numpy as np

        if not self._connected or not self._fw:
            raise ConnectionError(f"Device {self.device_id} is not connected")

        if not self._fw.session_id:
            # fw session 可能被内部线程或 bot 侧关闭，用 dev session_id 恢复
            if self.session_id:
                logger.info("[send_user_turn] Restoring fw session from dev.session_id=%s", self.session_id)
                self._fw.session_id = self.session_id
            else:
                logger.info("Device %s has no active session, auto-starting new session for send_user_turn", self.device_id)
                self._fw.start_session(
                figurine_id=self.figurine_id,
                nfc_id=self.nfc_id,
                mode=self.mode,
            )
            self.session_id = self._fw.session_id
            self._emit_session(self._fw.session_id, "session_status", {
                "status": "active",
                "session_id": self._fw.session_id,
            })
            logger.info("Auto-started session %s for device %s", self._fw.session_id, self.device_id)

        pcm_data, duration_sec = self._load_wav(wav_path)

        with self._lock:
            if self._simulating:
                raise ValueError(f"Device {self.device_id} already has an active send")
            self._simulating = True

        session_id = self._fw.session_id
        result = SimulationResult(
            session_id=session_id,
            device_id=self.device_id,
            figurine_id=self.figurine_id,
            mode=self.mode,
            audio_id=wav_path.stem,
        )
        result.started_at = time.time()
        result.status = "pending"

        try:
            result.audio_duration_sec = round(duration_sec, 2)
            logger.info(
                "[send_user_turn] device=%s session=%s audio=%s duration=%.2fs pcm_frames=%d",
                self.device_id, session_id, wav_path.stem, duration_sec, len(pcm_data),
            )

            turn_id = self._fw.start_turn(pcm_data)
            result.total_chunks = max(1, (len(pcm_data) + 960 - 1) // 960)
            logger.info("[send_user_turn] turn_id=%s started, total_chunks=%d", turn_id, result.total_chunks)

            response_ok = self._fw.wait_for_turn_response(turn_id=turn_id, timeout=90, expect_downstream=True)
            logger.info(
                "[send_user_turn] turn_id=%s response=%s elapsed=%.2fs",
                turn_id, "ok" if response_ok else "TIMEOUT",
                round(time.time() - result.started_at, 2),
            )

            result.stt_text = "\n".join(self._fw.get_stt_texts())
            result.stt_texts = self._fw.get_stt_texts()
            result.cue_count = self._fw._cue_counter
            commands = self._fw.get_all_commands()
            result.commands_received = len(commands)
            result.all_commands = commands
            result.reply_text = _extract_reply_text(commands) or self._fw.get_llm_reply()

            downstream = self._fw.get_downstream_stats()
            result.tts_response_count = downstream["tts_response_count"]
            result.tts_chunks = downstream["tts_chunks"]
            result.tts_duration_ms = downstream["tts_duration_ms"]
            result.stt_latency_ms = downstream.get("stt_latency_ms", 0)
            result.llm_latency_ms = downstream.get("llm_latency_ms", 0)
            result.tts_latency_ms = downstream.get("tts_latency_ms", 0)
            result.e2e_latency_ms = downstream.get("e2e_latency_ms", 0)
            result.done_latency_ms = downstream.get("done_latency_ms", 0)

            logger.info(
                "[send_user_turn] device=%s session=%s turn_id=%s stt=%r tts_count=%d tts_chunks=%d reply=%r",
                self.device_id, session_id, turn_id,
                result.stt_text[:80] if result.stt_text else "(empty)",
                result.tts_response_count, result.tts_chunks,
                result.reply_text[:80] if result.reply_text else "(none)",
            )

            is_vad_blocked = (not result.stt_text.strip()) and (result.tts_response_count == 0) and response_ok is False
            if is_vad_blocked:
                logger.warning(
                    "[send_user_turn] VAD BLOCKED detected: device=%s session=%s stt_empty=True tts_count=0 response_timeout=True",
                    self.device_id, session_id,
                )

            result.completed_at = time.time()
            result.send_duration_sec = round(result.completed_at - result.started_at, 2)
            result.status = "completed"

            self._emit_session(session_id, "session_status", {
                "status": "turn_completed",
                "send_duration_sec": result.send_duration_sec,
                "audio_duration_sec": result.audio_duration_sec,
                "total_chunks": result.total_chunks,
                "stt_text": result.stt_text,
                "reply_text": result.reply_text,
                "all_commands": result.all_commands,
                "tts_response_count": result.tts_response_count,
                "tts_chunks": result.tts_chunks,
                "tts_duration_ms": result.tts_duration_ms,
                "stt_latency_ms": result.stt_latency_ms,
                "llm_latency_ms": result.llm_latency_ms,
                "tts_latency_ms": result.tts_latency_ms,
                "e2e_latency_ms": result.e2e_latency_ms,
                "done_latency_ms": result.done_latency_ms,
                "cue_count": result.cue_count,
                "commands_received": result.commands_received,
            })

        except Exception as exc:
            result.status = "error"
            result.error = str(exc)
            logger.exception("User turn failed on device %s: %s", self.device_id, exc)

        finally:
            with self._lock:
                self._simulating = False

        return result

    def run_session(self, wav_path: Path, audio_id: str = "",
                    speed: float = 0, subscribe_response: bool = True) -> SimulationResult:
        """Run a complete session (session → turn → response → session/end) on this device."""
        import numpy as np

        if not self._connected or not self._fw:
            raise ConnectionError(f"Device {self.device_id} is not connected")

        with self._lock:
            if self._simulating:
                raise ValueError(f"Device {self.device_id} already has an active session")
            self._simulating = True

        result = SimulationResult(
            session_id="",
            device_id=self.device_id,
            figurine_id=self.figurine_id,
            mode=self.mode,
            audio_id=audio_id,
        )
        result.started_at = time.time()
        result.status = "pending"

        try:
            pcm_data, duration_sec = self._load_wav(wav_path)
            result.audio_duration_sec = round(duration_sec, 2)

            self._fw.start_session(
                figurine_id=self.figurine_id,
                nfc_id=self.nfc_id,
                mode=self.mode,
            )
            result.session_id = self._fw.session_id
            self.session_id = self._fw.session_id
            logger.info("Session started: %s (%.2fs audio)", result.session_id, duration_sec)

            self._emit_session(result.session_id, "session_status", {
                "status": "active",
                "session_id": result.session_id,
            })

            if subscribe_response:
                self._emit_session(result.session_id, "mqtt_subscribe", {
                    "topic": f"{self._fw.base_topic}/response/#",
                })

            intro_ok = self._fw.wait_for_intro_completion(timeout=30)
            if intro_ok:
                logger.info("Intro EOS received for session %s", result.session_id)
                self._emit_session(result.session_id, "session_status", {
                    "status": "intro_complete",
                    "session_id": result.session_id,
                })
            else:
                logger.warning("Intro EOS timeout for session %s (30s, still sending audio)", result.session_id)
                self._emit_session(result.session_id, "session_status", {
                    "status": "intro_timeout",
                    "session_id": result.session_id,
                })

            # pcm_data is already float32 [-1, 1] from _load_wav;
            # start_turn converts it back to int16 internally for Opus.
            turn_id = self._fw.start_turn(pcm_data)

            frame_size = 960
            result.total_chunks = max(1, (len(pcm_data) + frame_size - 1) // frame_size)

            response_ok = self._fw.wait_for_turn_response(
                turn_id=turn_id,
                timeout=90,
                expect_downstream=subscribe_response,
            )
            logger.info("Turn %s response: %s", turn_id, "ok" if response_ok else "timeout")

            result.stt_text = "\n".join(self._fw.get_stt_texts())
            result.stt_texts = self._fw.get_stt_texts()
            result.cue_count = self._fw._cue_counter
            commands = self._fw.get_all_commands()
            result.commands_received = len(commands)
            result.all_commands = commands

            if self._fw._session_stt_texts:
                result.stt_confidence = 0.0
                result.stt_language = ""

            result.reply_text = _extract_reply_text(commands)

            # Collect downstream TTS tracking data
            downstream = self._fw.get_downstream_stats()
            result.tts_response_count = downstream["tts_response_count"]
            result.tts_chunks = downstream["tts_chunks"]
            result.tts_duration_ms = downstream["tts_duration_ms"]
            result.stt_latency_ms = downstream.get("stt_latency_ms", 0)
            result.llm_latency_ms = downstream.get("llm_latency_ms", 0)
            result.tts_latency_ms = downstream.get("tts_latency_ms", 0)
            result.e2e_latency_ms = downstream.get("e2e_latency_ms", 0)
            result.done_latency_ms = downstream.get("done_latency_ms", 0)

            self._fw.stop_session(reason="user_stop")

            result.completed_at = time.time()
            result.send_duration_sec = round(result.completed_at - result.started_at, 2)
            result.status = "completed"

            self._emit_session(result.session_id, "session_status", {
                "status": "completed",
                "send_duration_sec": result.send_duration_sec,
                "audio_duration_sec": result.audio_duration_sec,
                "total_chunks": result.total_chunks,
                "stt_text": result.stt_text,
                "reply_text": result.reply_text,
                "all_commands": result.all_commands,
                "tts_response_count": result.tts_response_count,
                "tts_chunks": result.tts_chunks,
                "tts_duration_ms": result.tts_duration_ms,
                "stt_latency_ms": result.stt_latency_ms,
                "llm_latency_ms": result.llm_latency_ms,
                "tts_latency_ms": result.tts_latency_ms,
                "e2e_latency_ms": result.e2e_latency_ms,
                "done_latency_ms": result.done_latency_ms,
                "cue_count": result.cue_count,
                "commands_received": result.commands_received,
            })

            self._emit_session(result.session_id, "session_closed", {
                "session_id": result.session_id,
            })

        except Exception as exc:
            result.status = "error"
            result.error = str(exc)
            logger.exception("Session failed on device %s: %s", self.device_id, exc)
            if result.session_id:
                self._emit_session(result.session_id, "session_status", {
                    "status": "error", "error": str(exc),
                })
        finally:
            with self._lock:
                self._simulating = False
                self.session_id = None  # clear cached session_id

        return result

    def stop_current_session(self):
        self._stop_requested = True
        if self._fw and self._simulating:
            try:
                self._fw.stop_session(reason="manual_stop")
            except Exception:
                pass
        self.session_id = None

    def get_fw_status(self) -> dict:
        if self._fw:
            return self._fw.get_status()
        return {"device_id": self.device_id, "state": "offline"}

    def _on_fw_log(self, msg: str):
        logger.info("[FW] %s", msg)

    def _on_fw_command(self, cmd: dict):
        cmd_name = cmd.get("cmd", "")
        self._emit_device("command", {
            "cmd": cmd_name,
            "preempt": cmd.get("preempt", False),
            "after_audio": cmd.get("after_audio", False),
            "turn_id": cmd.get("_turn_id"),
            "params": cmd.get("params", {}),
        })

    def _on_fw_cue(self, cue_id: str, audio_data: list):
        self._emit_device("cue_start", {
            "cue_id": cue_id,
            "chunks": len(audio_data),
        })

    def _on_fw_state_change(self, state):
        self._emit_device("device_state", {"state": state.value})

    def _on_fw_mqtt_event(self, event_type: str, data: dict):
        sid = self.session_id
        if sid:
            self._emit_session(sid, event_type, data)
        # Also emit to device queue for events the frontend needs directly
        if event_type in ("audio_ready", "tts_synthesis", "audio_start", "audio_chunk"):
            self._emit_device(event_type, data)

    def _load_wav(self, wav_path: Path):
        import numpy as np
        data, sr = sf.read(str(wav_path))
        if len(data.shape) > 1:
            data = data.mean(axis=1)
        if sr != OPUS_SR:
            from scipy import signal
            ratio = OPUS_SR / sr
            new_len = int(len(data) * ratio)
            data = signal.resample(data, new_len)
        duration = len(data) / OPUS_SR
        return data, duration  # float32 [-1.0, 1.0]; float32→int16 is handled in start_turn()

    def _emit_device(self, event_type: str, data: dict):
        if self.event_bus:
            event = dict(data)
            event["type"] = event_type
            event["timestamp"] = time.time()
            event["device_id"] = self.device_id
            event["session_id"] = self.session_id or ""
            self.event_bus.publish(self.device_id, event)

    def _emit_session(self, session_id: str, event_type: str, data: dict): 
        if self.event_bus:
            event = dict(data)
            event["type"] = event_type
            event["timestamp"] = time.time()
            event["device_id"] = self.device_id
            event["session_id"] = session_id
    
            # ── 协议归一化：模拟器发 state，前端等 status ──
            # 设备固件按真实设备行为发送 state: "start" / "complete"，
            # 测试平台后端负责将其翻译为前端统一的 status 语义。
            if event_type == "tts_synthesis" and "state" in event and "status" not in event:
                raw_state = event["state"]
                if raw_state == "complete":
                    event["status"] = "success"
                elif raw_state == "start":
                    event["status"] = "start"
                else:
                    event["status"] = raw_state
    
            self.event_bus.publish(session_id, event)
            self.event_bus.publish(self.device_id, event)


# Backward-compatible alias for older tests and docs.
MQTTDeviceSimulator = ConnectedDevice


class SimulationManager:
    MAX_DEVICES = 4
    HISTORY_FILE = Path(__file__).parent / "simulation_history.json"
    MAX_HISTORY_RECORDS = 500

    def __init__(self, profile_switcher: Callable[[str], dict] | None = None):
        self._devices: dict[str, ConnectedDevice] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._lock = threading.RLock()
        self.event_bus = SimulationEventBus()
        self._results: dict[str, dict] = {}
        self._session_aliases: dict[str, str] = {}
        self._vad_bypassed: dict[str, bool] = {}
        self._profile_switcher = profile_switcher
        self._load_history()
        self._start_cleanup_thread()

    def _start_cleanup_thread(self):
        """Background daemon thread that periodically evicts stale devices & orphans."""
        def _loop():
            while True:
                time.sleep(30)
                try:
                    self._evict_devices_if_full()
                    self.cleanup_orphan_sessions(max_age_seconds=120)
                except Exception:
                    logger.exception("Cleanup thread error")
        t = threading.Thread(target=_loop, daemon=True, name="device-cleanup")
        t.start()

    def _stop_device_simulation(self, device_id: str, wait_timeout: float = 10.0) -> bool:
        """Request a running simulation to stop and wait for its worker thread.

        The simulator uses a per-device background thread. If a new simulation
        starts before the old worker has exited, the two runs can overlap and
        produce empty or partial results. Keeping the handoff serialized makes
        repeated simulate calls predictable.
        """
        with self._lock:
            dev = self._devices.get(device_id)
            thread = self._threads.get(device_id)
            if dev is None or not dev.is_simulating:
                return True
            dev.stop_current_session()

        if thread and thread.is_alive():
            thread.join(timeout=wait_timeout)

        with self._lock:
            dev = self._devices.get(device_id)
            still_simulating = bool(dev and dev.is_simulating)

        if still_simulating:
            logger.warning("Device %s is still simulating after stop request", device_id)
            return False

        return True

    @property
    def devices(self) -> dict[str, ConnectedDevice]:
        return self._devices

    def _resolve_session_id(self, session_id: str) -> str:
        """Resolve a public/session alias to the actual recorded session id."""
        current = session_id
        seen: set[str] = set()
        with self._lock:
            while current in self._session_aliases and current not in seen:
                seen.add(current)
                current = self._session_aliases[current]
        return current

    def _evict_devices_if_full(self) -> bool:
        """Evict stale or idle devices to stay under MAX_DEVICES.

        Emits a device_evicted event on the event bus so connected
        frontends receive notification. The event carries the evictee's
        ID and reason (stale or idle).
        """
        with self._lock:
            while len(self._devices) >= self.MAX_DEVICES:
                stale = [
                    did for did, d in self._devices.items()
                    if d.is_stale
                ]
                target_id = stale[0] if stale else None
                reason = "stale"
                if not target_id:
                    idle = [
                        did for did, d in self._devices.items()
                        if not d.is_simulating
                    ]
                    target_id = idle[0] if idle else None
                    reason = "idle"
                if not target_id:
                    return False
                dev = self._devices.pop(target_id, None)
                self._threads.pop(target_id, None)
                if dev:
                    try:
                        dev.power_off()
                    except Exception:
                        pass
                    # ── 通知前端：设备已被回收 ──
                    self.event_bus.publish("_system", {
                        "type": "device_evicted",
                        "device_id": target_id,
                        "reason": reason,
                        "timestamp": time.time(),
                    })
                    self.event_bus.remove_queue(target_id)
            return True

    def connect_device(
        self,
        device_id: str,
        figurine_id: str,
        mode: str = "dialogue",
        *,
        nfc_id: str = "sim-nfc",
        mqtt_profile: str | None = None,
        mqtt_env: str | None = None,
        mqtt_host: str | None = None,
        mqtt_port: int | None = None,
        mqtt_tls: bool | None = None,
        mqtt_tls_ca_cert: str | None = None,
        mqtt_tls_client_cert: str | None = None,
        mqtt_tls_client_key: str | None = None,
        mqtt_tls_insecure: bool | None = None,
        skip_auto_intro: bool = False,
    ) -> dict:
        """Connect a device (power_on). Device stays online for multiple sessions."""
        (resolved_profile, resolved_env, resolved_host, resolved_port, resolved_tls,
         resolved_tls_ca, resolved_tls_cert, resolved_tls_key, resolved_tls_insecure) = _resolve_broker_config(
            mqtt_profile=mqtt_profile,
            mqtt_env=mqtt_env,
            mqtt_host=mqtt_host,
            mqtt_port=mqtt_port,
            mqtt_tls=mqtt_tls,
            mqtt_tls_ca_cert=mqtt_tls_ca_cert,
            mqtt_tls_client_cert=mqtt_tls_client_cert,
            mqtt_tls_client_key=mqtt_tls_client_key,
            mqtt_tls_insecure=mqtt_tls_insecure,
        )

        with self._lock:
            if device_id in self._devices:
                dev = self._devices[device_id]
                if dev.is_connected:
                    same_broker = (
                        dev.broker_profile == resolved_profile
                        and dev.env == resolved_env
                        and dev.broker_host == resolved_host
                        and dev.broker_port == resolved_port
                        and dev.broker_tls == resolved_tls
                    )
                    if same_broker:
                        dev.touch_seen()
                        return {"device_id": device_id, "status": "already_connected", "intro": "auto_triggered"}
                    self._threads.pop(device_id, None)
                    try:
                        dev.power_off()
                    except Exception:
                        pass
                    self.event_bus.remove_queue(device_id)
                    self._devices.pop(device_id, None)

            if not self._evict_devices_if_full():
                raise ValueError(f"Max {self.MAX_DEVICES} concurrent devices, all busy")

        self.event_bus.create_queue(device_id)

        dev = ConnectedDevice(
            device_id=device_id,
            figurine_id=figurine_id,
            mode=mode,
            nfc_id=nfc_id,
            broker_profile=resolved_profile,
            env=resolved_env,
            broker_host=resolved_host,
            broker_port=resolved_port,
            broker_tls=resolved_tls,
            broker_tls_ca_cert=resolved_tls_ca,
            broker_tls_client_cert=resolved_tls_cert,
            broker_tls_client_key=resolved_tls_key,
            broker_tls_insecure=resolved_tls_insecure,
            event_bus=self.event_bus,
        )

        try:
            dev.power_on()
        except ConnectionError as exc:
            raise ConnectionError(f"Device {device_id} connection failed: {exc}")

        with self._lock:
            self._devices[device_id] = dev

        # Auto-start intro session in background thread (skipped for verification)
        if not skip_auto_intro:
            self._trigger_intro_session(dev, device_id)

        return {
            "device_id": device_id,
            "status": "connected",
            "figurine_id": figurine_id,
            "mode": mode,
            "mqtt_profile": resolved_profile,
            "mqtt_env": resolved_env,
            "mqtt_host": resolved_host,
            "mqtt_port": resolved_port,
            "mqtt_tls": resolved_tls,
            "mqtt_tls_ca_cert": resolved_tls_ca,
            "mqtt_tls_client_cert": resolved_tls_cert,
            "mqtt_tls_client_key": resolved_tls_key,
            "mqtt_tls_insecure": resolved_tls_insecure,
            "intro": "auto_triggered",
        }

    def disconnect_device(self, device_id: str) -> dict:
        """Disconnect a device (power_off) and wait for background thread to exit."""
        thread = None
        dev = None
        with self._lock:
            dev = self._devices.pop(device_id, None)
            thread = self._threads.pop(device_id, None)

        if dev is None:
            return {"device_id": device_id, "status": "not_found"}

        if dev.is_simulating:
            dev.stop_current_session()

        dev.power_off()
        self.event_bus.remove_queue(device_id)

        # Wait for background thread to finish (avoids orphan threads/sessions)
        if thread is not None and thread.is_alive():
            thread.join(timeout=30)
            if thread.is_alive():
                logger.warning("Device %s thread still alive after 30s timeout, detaching", device_id)

        return {"device_id": device_id, "status": "disconnected"}

    def _trigger_intro_session(self, dev: ConnectedDevice, device_id: str):
        """Launch a background thread to auto-start intro session after device connects."""
        def _intro_worker():
            try:
                sid = dev.start_session_and_await_intro()
                if sid:
                    logger.info("Auto intro session completed for device %s: %s", device_id, sid)
                else:
                    logger.warning("Auto intro session returned no session for %s", device_id)
            except Exception as exc:
                logger.exception("Auto intro session failed for device %s: %s", device_id, exc)
            finally:
                with self._lock:
                    if self._threads.get(device_id) == threading.current_thread():
                        self._threads.pop(device_id, None)

        thread = threading.Thread(target=_intro_worker, daemon=True, name=f"intro-{device_id}")
        thread.start()
        with self._lock:
            self._threads[device_id] = thread

    def send_user_turn(self, device_id: str, audio_id: str, resolve_audio: Callable[[str], Path | None],
                        auto_vad_retry: bool = True) -> dict:
        """Send a user audio turn on an existing session.

        When auto_vad_retry=True (default), the background thread will detect
        VAD blocking (empty STT + no TTS response) and automatically retry
        with profile switching.  Results are delivered via events.
        """
        with self._lock:
            dev = self._devices.get(device_id)

        if dev is None or not dev.is_connected:
            return {"error": f"Device {device_id} is not connected"}

        audio_path = resolve_audio(audio_id)
        if audio_path is None:
            return {"error": f"Audio not found: {audio_id}"}
        if not audio_path.exists():
            return {"error": f"Audio file not found: {audio_path}"}

        preliminary_id = secrets.token_urlsafe(9)[:12]
        self.event_bus.create_queue(preliminary_id)

        session_id_holder = {"value": preliminary_id, "ready": threading.Event(), "error": None}

        def _run():
            try:
                current_sid = dev.session_id or (dev._fw.session_id if dev._fw else None)
                if current_sid:
                    with self._lock:
                        self._session_aliases[preliminary_id] = current_sid
                        self._session_aliases[current_sid] = current_sid
                    session_id_holder["value"] = current_sid
                    session_id_holder["ready"].set()
                    self._results[current_sid] = {
                        "session_id": current_sid,
                        "device_id": device_id,
                        "status": "pending",
                        "started_at": time.time(),
                        "audio_id": audio_id,
                    }

                logger.info("[send_user_turn:thread] Starting turn for device=%s audio=%s sid=%s", device_id, audio_id, current_sid)
                result = dev.send_user_turn(wav_path=audio_path)
                real_sid = result.session_id or preliminary_id
                with self._lock:
                    self._session_aliases[preliminary_id] = real_sid
                    self._session_aliases[real_sid] = real_sid
                session_id_holder["value"] = real_sid
                session_id_holder["ready"].set()
                self._save_result(result)
                logger.info(
                    "[send_user_turn:thread] First attempt done: sid=%s status=%s stt=%r tts=%d",
                    real_sid, result.status,
                    (result.stt_text or "")[:60], result.tts_response_count,
                )

                if auto_vad_retry:
                    stt = (result.stt_text or "").strip()
                    tts_count = result.tts_response_count or 0
                    if not stt and tts_count == 0 and result.status == "completed":
                        logger.warning(
                            "[send_user_turn:thread] VAD BLOCKED for sid=%s → auto VAD retry enabled=%s has_switcher=%s",
                            real_sid, auto_vad_retry, self._profile_switcher is not None,
                        )
                        self._vad_bypassed[real_sid] = True
                        self._emit_session(real_sid, "session_status", {
                            "status": "vad_retrying",
                            "session_id": real_sid,
                            "message": "VAD blocked, switching profile and retrying",
                        })
                        switch_result = None
                        try:
                            if self._profile_switcher:
                                logger.info("[send_user_turn:thread] Switching MQTT profile to local (VAD off)")
                                switch_result = self._profile_switcher("local")
                                logger.info("[send_user_turn:thread] Profile switch result: %s", switch_result)
                                time.sleep(3)
                            else:
                                logger.warning("[send_user_turn:thread] No profile_switcher, retrying without profile switch")
                            logger.info("[send_user_turn:thread] Starting VAD-retry second attempt for device=%s", device_id)
                            result2 = dev.send_user_turn(wav_path=audio_path)
                            real_sid2 = result2.session_id or real_sid
                            self._vad_bypassed[real_sid2] = True
                            with self._lock:
                                self._session_aliases[real_sid2] = real_sid2
                            self._save_result(result2)
                            logger.info(
                                "[send_user_turn:thread] VAD retry done: sid=%s status=%s stt=%r tts=%d",
                                real_sid2, result2.status,
                                (result2.stt_text or "")[:60], result2.tts_response_count,
                            )
                        finally:
                            if self._profile_switcher and switch_result:
                                prev = switch_result.get("previous", "remote")
                                logger.info("[send_user_turn:thread] Restoring MQTT profile to %s", prev)
                                self._profile_switcher(prev)
            except Exception as exc:
                session_id_holder["error"] = str(exc)
                session_id_holder["ready"].set()
                logger.exception("User turn failed: %s", exc)
            finally:
                with self._lock:
                    if self._threads.get(device_id) == threading.current_thread():
                        self._threads.pop(device_id, None)

        thread = threading.Thread(target=_run, daemon=True, name=f"turn-{device_id}")
        thread.start()

        with self._lock:
            self._threads[device_id] = thread

        session_id_holder["ready"].wait(timeout=15)
        error_msg = session_id_holder.get("error")
        if error_msg:
            self.event_bus.remove_queue(preliminary_id)
            return {"error": f"发送音频失败: {error_msg}"}
        real_sid = session_id_holder["value"]
        if real_sid and real_sid != preliminary_id:
            self.event_bus.alias_queue(preliminary_id, real_sid)
        return {"session_id": real_sid or preliminary_id, "status": "turn_started"}

    def run_simulation(
        self,
        device_id: str,
        audio_id: str,
        resolve_audio: Callable[[str], Path | None],
        speed: float = 0,
        subscribe_response: bool = True,
    ) -> str:
        """Run a simulation session on an already-connected device."""
        with self._lock:
            dev = self._devices.get(device_id)

        if dev is None or not dev.is_connected:
            raise ValueError(f"Device {device_id} is not connected. Call connect_device first.")

        audio_path = resolve_audio(audio_id)
        if audio_path is None:
            raise ValueError(f"Audio not found: {audio_id}")

        preliminary_id = secrets.token_urlsafe(9)[:12]
        self.event_bus.create_queue(preliminary_id)

        placeholder = SimulationResult(
            session_id=preliminary_id,
            device_id=device_id,
            figurine_id=dev.figurine_id,
            mode=dev.mode,
            audio_id=audio_id,
            status="pending",
            started_at=time.time(),
        )
        self._save_result(placeholder)

        session_id_holder = {"value": preliminary_id, "ready": threading.Event(), "error": None}

        def _run():
            try:
                result = dev.run_session(
                    wav_path=audio_path,
                    audio_id=audio_id,
                    speed=speed,
                    subscribe_response=subscribe_response,
                )
                real_session_id = result.session_id or preliminary_id
                with self._lock:
                    self._session_aliases[preliminary_id] = real_session_id
                    self._session_aliases[real_session_id] = real_session_id
                session_id_holder["value"] = real_session_id
                session_id_holder["ready"].set()
                self._save_result(result)
            except Exception as exc:
                session_id_holder["error"] = str(exc)
                session_id_holder["ready"].set()
                # Update placeholder with error status so caller can query result
                placeholder.status = "error"
                placeholder.error = str(exc)
                placeholder.completed_at = time.time()
                self._save_result(placeholder)
                logger.exception("Simulation failed: %s", exc)
            finally:
                with self._lock:
                    self._threads.pop(device_id, None)

        thread = threading.Thread(target=_run, daemon=True, name=f"sim-{device_id}")
        thread.start()

        with self._lock:
            self._threads[device_id] = thread

        session_id_holder["ready"].wait(timeout=15)
        real_sid = session_id_holder["value"]
        # When error occurs and no real session_id was assigned, alias to preliminary_id
        # so the caller can find the error result via the returned preliminary_id
        if session_id_holder.get("error") and real_sid == preliminary_id:
            self._session_aliases[preliminary_id] = preliminary_id
        if real_sid and real_sid != preliminary_id:
            self.event_bus.alias_queue(preliminary_id, real_sid)
        return preliminary_id

    def stop_simulation(self, session_id: str) -> bool:
        with self._lock:
            for device_id, dev in list(self._devices.items()):
                if dev.is_simulating:
                    dev.stop_current_session()
        # Wait briefly for all simulation threads to exit
        with self._lock:
            for device_id, thread in list(self._threads.items()):
                if thread.is_alive():
                    thread.join(timeout=10)
        return True

    def get_device_status(self, device_id: str) -> dict | None:
        dev = self._devices.get(device_id)
        if dev is None:
            return None
        fw = dev.get_fw_status()
        return {
            "device_id": device_id,
            "connected": dev.is_connected,
            "simulating": dev.is_simulating,
            "mqtt_profile": dev.broker_profile,
            "mqtt_env": dev.env,
            "mqtt_host": dev.broker_host,
            "mqtt_port": dev.broker_port,
            "mqtt_tls": dev.broker_tls,
            "last_seen_sec": int(dev.seconds_since_seen),
            "is_stale": dev.is_stale,
            "fw_status": fw,
        }

    def get_active_count(self) -> int:
        with self._lock:
            return len(self._devices)

    def get_active_sessions(self) -> list[dict]:
        with self._lock:
            return [
                {
                    "device_id": did,
                    "connected": dev.is_connected,
                    "simulating": dev.is_simulating,
                    "figurine_id": dev.figurine_id,
                    "mode": dev.mode,
                    "mqtt_profile": dev.broker_profile,
                    "mqtt_env": dev.env,
                    "mqtt_host": dev.broker_host,
                    "mqtt_port": dev.broker_port,
                    "mqtt_tls": dev.broker_tls,
                }
                for did, dev in self._devices.items()
            ]

    def cleanup_orphan_sessions(self, max_age_seconds: float = 300) -> int:
        """Clean up orphan simulation results (started but never completed).

        Returns the number of orphan results cleaned up.
        """
        now = time.time()
        count = 0
        with self._lock:
            for sid in list(self._results.keys()):
                r = self._results[sid]
                started = r.get("started_at", 0)
                if started and now - started > max_age_seconds:
                    status = r.get("status", "")
                    if status in ("pending",):
                        r["status"] = "orphan_cleaned"
                        self._vad_bypassed.pop(sid, None)
                        count += 1
        if count:
            logger.warning("Cleaned %d orphan simulation results", count)
            self._flush_history()
        return count

    def _save_result(self, result: SimulationResult):
        result_dict = asdict(result)
        result_dict.pop("_event_log", None)
        with self._lock:
            self._results[result.session_id] = result_dict
        self._flush_history()

    def get_result(self, session_id: str) -> dict | None:
        resolved_session_id = self._resolve_session_id(session_id)
        with self._lock:
            result = self._results.get(resolved_session_id) or self._results.get(session_id)
        if result is not None:
            result["vad_bypassed"] = self._vad_bypassed.get(resolved_session_id, False)
        return result

    def get_history(self, limit: int = 50, offset: int = 0) -> list[dict]:
        with self._lock:
            all_results = sorted(
                self._results.values(),
                key=lambda r: r.get("started_at", 0),
                reverse=True,
            )
        for r in all_results:
            sid = r.get("session_id", "")
            r["vad_bypassed"] = self._vad_bypassed.get(sid, False)
        return all_results[offset:offset + limit]

    def get_history_count(self) -> int:
        with self._lock:
            return len(self._results)

    def clear_history(self):
        with self._lock:
            self._results.clear()
            self._session_aliases.clear()
            self._vad_bypassed.clear()
        self._flush_history()

    def _flush_history(self):
        try:
            with self._lock:
                snapshot = dict(self._results)
            sorted_items = sorted(
                snapshot.items(),
                key=lambda kv: kv[1].get("started_at", 0),
                reverse=True,
            )[:self.MAX_HISTORY_RECORDS]
            trimmed = dict(sorted_items)
            self.HISTORY_FILE.write_text(
                json.dumps(trimmed, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("Failed to flush history: %s", exc)

    def _load_history(self):
        if not self.HISTORY_FILE.exists():
            return
        try:
            data = json.loads(self.HISTORY_FILE.read_text(encoding="utf-8"))
            self._results.update(data)
            logger.info("Loaded %d history records", len(data))
        except Exception as exc:
            logger.warning("Failed to load history: %s", exc)

    def start_simulation(
        self,
        device_id: str,
        figurine_id: str,
        mode: str,
        audio_id: str,
        resolve_audio: Callable[[str], Path | None],
        nfc_id: str = "sim-nfc",
        subscribe_response: bool = True,
        speed: float = 0,
        mqtt_profile: str | None = None,
        mqtt_env: str | None = None,
        mqtt_host: str | None = None,
        mqtt_port: int | None = None,
        mqtt_tls: bool | None = None,
        mqtt_tls_ca_cert: str | None = None,
        mqtt_tls_client_cert: str | None = None,
        mqtt_tls_client_key: str | None = None,
        mqtt_tls_insecure: bool | None = None,
    ) -> str:
        """[DEPRECATED] Legacy API: connect + run in one shot.

        Kept for backward compatibility with older tests and docs.
        Prefer the two-step pattern: connect_device() → run_simulation().
        """
        (resolved_profile, resolved_env, resolved_host, resolved_port, resolved_tls,
         resolved_tls_ca, resolved_tls_cert, resolved_tls_key, resolved_tls_insecure) = _resolve_broker_config(
            mqtt_profile=mqtt_profile,
            mqtt_env=mqtt_env,
            mqtt_host=mqtt_host,
            mqtt_port=mqtt_port,
            mqtt_tls=mqtt_tls,
            mqtt_tls_ca_cert=mqtt_tls_ca_cert,
            mqtt_tls_client_cert=mqtt_tls_client_cert,
            mqtt_tls_client_key=mqtt_tls_client_key,
            mqtt_tls_insecure=mqtt_tls_insecure,
        )

        with self._lock:
            dev = self._devices.get(device_id)
            needs_stop = bool(dev and dev.is_simulating)

        if needs_stop and not self._stop_device_simulation(device_id):
            raise ValueError(f"Device {device_id} is still stopping a previous simulation")

        with self._lock:
            dev = self._devices.get(device_id)

        if dev is not None and dev.is_connected:
            needs_reconnect = (
                dev.broker_profile != resolved_profile
                or dev.env != resolved_env
                or dev.broker_host != resolved_host
                or dev.broker_port != resolved_port
                or dev.broker_tls != resolved_tls
                or dev.broker_tls_ca_cert != resolved_tls_ca
                or dev.broker_tls_client_cert != resolved_tls_cert
                or dev.broker_tls_client_key != resolved_tls_key
                or dev.broker_tls_insecure != resolved_tls_insecure
            )
            if needs_reconnect:
                self.disconnect_device(device_id)
                dev = None

        if dev is None or not dev.is_connected:
            self.connect_device(
                device_id,
                figurine_id,
                mode,
                nfc_id=nfc_id,
                mqtt_profile=resolved_profile,
                mqtt_env=resolved_env,
                mqtt_host=resolved_host,
                mqtt_port=resolved_port,
                mqtt_tls=resolved_tls,
                mqtt_tls_ca_cert=resolved_tls_ca,
                mqtt_tls_client_cert=resolved_tls_cert,
                mqtt_tls_client_key=resolved_tls_key,
                mqtt_tls_insecure=resolved_tls_insecure,
                skip_auto_intro=True,
            )

        return self.run_simulation(
            device_id=device_id,
            audio_id=audio_id,
            resolve_audio=resolve_audio,
            speed=speed,
            subscribe_response=subscribe_response,
        )


simulation_manager = SimulationManager()
