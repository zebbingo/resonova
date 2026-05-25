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
    reply_text: str = ""
    backend_responses: list = field(default_factory=list)
    error: str = ""
    _event_log: list = field(default_factory=list)
    cue_count: int = 0
    commands_received: int = 0
    stt_texts: list = field(default_factory=list)


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
        env: str = "development",
        broker_host: str = "localhost",
        broker_port: int = 1883,
        event_bus: Optional[SimulationEventBus] = None,
    ):
        self.device_id = device_id
        self.figurine_id = figurine_id
        self.mode = mode
        self.nfc_id = nfc_id
        self.env = env
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.event_bus = event_bus

        self._fw = None
        self._connected = False
        self._simulating = False
        self._lock = threading.Lock()

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def is_simulating(self) -> bool:
        return self._simulating

    def power_on(self):
        from scripts.device_firmware import DeviceFirmware

        self._fw = DeviceFirmware(
            self.device_id,
            env=self.env,
            broker_host=self.broker_host,
            broker_port=self.broker_port,
            on_mqtt_event=self._on_fw_mqtt_event,
        )
        self._fw.on_log = self._on_fw_log
        self._fw.on_command = self._on_fw_command
        self._fw.on_cue_audio = self._on_fw_cue
        self._fw.on_state_change = self._on_fw_state_change

        self._emit_device("mqtt_connecting", {"broker": f"{self.broker_host}:{self.broker_port}"})
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

    def run_session(self, wav_path: Path, audio_id: str = "",
                    speed: float = 0, subscribe_response: bool = False) -> SimulationResult:
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
            logger.info("Session started: %s (%.2fs audio)", result.session_id, duration_sec)

            self._emit_session(result.session_id, "session_status", {
                "status": "active",
                "session_id": result.session_id,
            })

            if subscribe_response:
                self._emit_session(result.session_id, "mqtt_subscribe", {
                    "topic": f"{self._fw.base_topic}/response/#",
                })

            intro_ok = self._fw.wait_for_intro_eos(timeout=15)
            if intro_ok:
                logger.info("Intro EOS received for session %s", result.session_id)

            # pcm_data is already float32 [-1, 1] from _load_wav;
            # start_turn converts it back to int16 internally for Opus.
            turn_id = self._fw.start_turn(pcm_data)

            frame_size = 960
            result.total_chunks = max(1, (len(pcm_data) + frame_size - 1) // frame_size)

            response_ok = self._fw.wait_for_turn_response(turn_id=turn_id, timeout=90)
            logger.info("Turn %s response: %s", turn_id, "ok" if response_ok else "timeout")

            result.stt_text = "\n".join(self._fw.get_stt_texts())
            result.stt_texts = self._fw.get_stt_texts()
            result.cue_count = self._fw._cue_counter
            result.commands_received = len(self._fw.get_all_commands())

            if self._fw._session_stt_texts:
                result.stt_confidence = 0.0
                result.stt_language = ""

            for cmd in self._fw.get_all_commands():
                if cmd.get("cmd"):
                    result.reply_text = cmd["cmd"]

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
                "tts_response_count": result.tts_response_count,
                "tts_chunks": result.tts_chunks,
                "tts_duration_ms": result.tts_duration_ms,
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

        return result

    def stop_current_session(self):
        if self._fw and self._simulating:
            try:
                self._fw.stop_session(reason="manual_stop")
            except Exception:
                pass

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
        sid = self._fw.session_id if self._fw else None
        if sid:
            self._emit_session(sid, event_type, data)

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
            event["session_id"] = (self._fw.session_id
                                   if self._fw and self._fw.session_id else "")
            self.event_bus.publish(self.device_id, event)

    def _emit_session(self, session_id: str, event_type: str, data: dict):
        if self.event_bus:
            event = dict(data)
            event["type"] = event_type
            event["timestamp"] = time.time()
            event["device_id"] = self.device_id
            event["session_id"] = session_id
            self.event_bus.publish(session_id, event)
            self.event_bus.publish(self.device_id, event)


class SimulationManager:
    MAX_DEVICES = 4
    HISTORY_FILE = Path(__file__).parent / "simulation_history.json"
    MAX_HISTORY_RECORDS = 500

    def __init__(self):
        self._devices: dict[str, ConnectedDevice] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._lock = threading.Lock()
        self.event_bus = SimulationEventBus()
        self._results: dict[str, dict] = {}
        self._session_aliases: dict[str, str] = {}
        self._load_history()

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

    def connect_device(
        self,
        device_id: str,
        figurine_id: str,
        mode: str = "dialogue",
        *,
        nfc_id: str = "sim-nfc",
    ) -> dict:
        """Connect a device (power_on). Device stays online for multiple sessions."""
        with self._lock:
            if device_id in self._devices:
                dev = self._devices[device_id]
                if dev.is_connected:
                    return {"device_id": device_id, "status": "already_connected"}
            if len(self._devices) >= self.MAX_DEVICES:
                raise ValueError(f"Max {self.MAX_DEVICES} concurrent devices")

        self.event_bus.create_queue(device_id)

        dev = ConnectedDevice(
            device_id=device_id,
            figurine_id=figurine_id,
            mode=mode,
            nfc_id=nfc_id,
            env=os.getenv("MQTT_ENV", "development"),
            broker_host=_resolve_mqtt_host(),
            broker_port=int(os.getenv("MQTT_PORT", "1883")),
            event_bus=self.event_bus,
        )

        try:
            dev.power_on()
        except ConnectionError as exc:
            raise ConnectionError(f"Device {device_id} connection failed: {exc}")

        with self._lock:
            self._devices[device_id] = dev

        return {
            "device_id": device_id,
            "status": "connected",
            "figurine_id": figurine_id,
            "mode": mode,
        }

    def disconnect_device(self, device_id: str) -> dict:
        """Disconnect a device (power_off)."""
        with self._lock:
            dev = self._devices.pop(device_id, None)
            self._threads.pop(device_id, None)

        if dev is None:
            return {"device_id": device_id, "status": "not_found"}

        if dev.is_simulating:
            dev.stop_current_session()

        dev.power_off()
        self.event_bus.remove_queue(device_id)

        return {"device_id": device_id, "status": "disconnected"}

    def run_simulation(
        self,
        device_id: str,
        audio_id: str,
        resolve_audio: Callable[[str], Path | None],
        speed: float = 0,
        subscribe_response: bool = False,
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

        session_id_holder = {"value": preliminary_id, "ready": threading.Event()}

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
                session_id_holder["ready"].set()
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
        if real_sid and real_sid != preliminary_id:
            self.event_bus.alias_queue(preliminary_id, real_sid)
        return preliminary_id

    def stop_simulation(self, session_id: str) -> bool:
        with self._lock:
            for device_id, dev in list(self._devices.items()):
                if dev.is_simulating:
                    dev.stop_current_session()
                    return True
        return False

    def get_device_status(self, device_id: str) -> dict | None:
        dev = self._devices.get(device_id)
        if dev is None:
            return None
        fw = dev.get_fw_status()
        return {
            "device_id": device_id,
            "connected": dev.is_connected,
            "simulating": dev.is_simulating,
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
                }
                for did, dev in self._devices.items()
            ]

    def _save_result(self, result: SimulationResult):
        result_dict = asdict(result)
        result_dict.pop("_event_log", None)
        with self._lock:
            self._results[result.session_id] = result_dict
        self._flush_history()

    def get_result(self, session_id: str) -> dict | None:
        resolved_session_id = self._resolve_session_id(session_id)
        with self._lock:
            return self._results.get(resolved_session_id) or self._results.get(session_id)

    def get_history(self, limit: int = 50, offset: int = 0) -> list[dict]:
        with self._lock:
            all_results = sorted(
                self._results.values(),
                key=lambda r: r.get("started_at", 0),
                reverse=True,
            )
        return all_results[offset:offset + limit]

    def get_history_count(self) -> int:
        with self._lock:
            return len(self._results)

    def clear_history(self):
        with self._lock:
            self._results.clear()
            self._session_aliases.clear()
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
        subscribe_response: bool = False,
        speed: float = 0,
    ) -> str:
        """Legacy API: connect + run in one shot (for backward compatibility)."""
        with self._lock:
            dev = self._devices.get(device_id)
            if dev and dev.is_connected and dev.is_simulating:
                raise ValueError(f"Device {device_id} already has an active simulation")

        if dev is None or not dev.is_connected:
            self.connect_device(device_id, figurine_id, mode, nfc_id=nfc_id)

        return self.run_simulation(
            device_id=device_id,
            audio_id=audio_id,
            resolve_audio=resolve_audio,
            speed=speed,
            subscribe_response=subscribe_response,
        )


simulation_manager = SimulationManager()
