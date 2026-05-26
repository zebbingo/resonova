"""
VoicePipe Test Suite — end-to-end + unit tests for the voice pipeline test platform.

Test audio IDs (generated via TTS API, English, UK child persona):
  11 — test_story_request  "Hello! Can you tell me a story about a brave rabbit?" (3.88s)
  12 — test_next_song      "Play the next song please!"                           (2.0s)
  13 — test_daily_chat     "I had a really fun day at school today!..."           (5.84s)
  14 — test_stop_command   "Stop! I want to talk to you instead."                 (3.19s)

Run:
  cd /home/administrator/projects/stt-test-tool
  uv run pytest backend/tests/ -v
"""

import json
import os
import threading
import time
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

os.environ.setdefault("MQTT_HOST", "localhost")

BACKEND_DIR = Path(__file__).resolve().parent.parent
AUDIO_CACHE = BACKEND_DIR / "audio_cache"

WSL_IP = os.getenv("VOICEPIPE_HOST", "localhost")
VOICEPIPE_PORT = int(os.getenv("VOICEPIPE_PORT", "8765"))
VOICEPIPE_BASE = f"http://{WSL_IP}:{VOICEPIPE_PORT}"

TTS_TEST_IDS = {
    "story_request": 11,
    "next_song": 12,
    "daily_chat": 13,
    "stop_command": 14,
}


def _real_backend_available() -> bool:
    import socket

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(2)
    try:
        sock.connect((WSL_IP, VOICEPIPE_PORT))
        sock.close()
        return True
    except (ConnectionRefusedError, OSError):
        return False


# ── Helpers ──────────────────────────────────────────────


def _make_wav(tmp_path: Path, duration_sec: float = 1.0, sr: int = 16000) -> Path:
    import soundfile as sf
    import pcm_utils

    samples = int(sr * duration_sec)
    # Generate int16 tone directly; this is not a float32->int16 conversion.
    tone = (np.sin(2 * np.pi * 440 * np.arange(samples) / sr) * 0.3 * 32767).astype(
        np.int16
    )
    wav = tmp_path / "test_tone.wav"
    pcm_utils.assert_wav_consistent(tone, sr)
    sf.write(str(wav), tone, sr)
    return wav


def _find_cached_wav(audio_id: int) -> Path | None:
    for f in AUDIO_CACHE.iterdir():
        if f.suffix == ".wav":
            continue
        stem = f.stem
        if f.suffix == ".mp3" and stem.startswith("tts_"):
            pass
    return None


# ══════════════════════════════════════════════════════════
# 1. mqtt_bridge unit tests
# ══════════════════════════════════════════════════════════


class TestResponseEvent:
    def test_fields(self):
        from mqtt_bridge import ResponseEvent

        ev = ResponseEvent(topic="t", response_type="vadeos", payload={"text": "hi"})
        assert ev.topic == "t"
        assert ev.response_type == "vadeos"
        assert ev.payload["text"] == "hi"
        assert ev.timestamp == 0.0

    def test_default_payload(self):
        from mqtt_bridge import ResponseEvent

        ev = ResponseEvent(topic="t", response_type="raw")
        assert ev.payload == {}


class TestSimulationResult:
    def test_defaults(self):
        from mqtt_bridge import SimulationResult

        r = SimulationResult(
            session_id="s1", device_id="d1", figurine_id="f1", mode="dialogue", audio_id="a1"
        )
        assert r.status == "pending"
        assert r.stt_text == ""
        assert r.backend_responses == []
        assert r.error == ""

    def test_asdict_roundtrip(self):
        from dataclasses import asdict
        from mqtt_bridge import SimulationResult

        r = SimulationResult(
            session_id="s1", device_id="d1", figurine_id="f1", mode="story", audio_id="a1"
        )
        d = asdict(r)
        assert d["session_id"] == "s1"
        assert d["mode"] == "story"
        d.pop("_event_log", None)
        restored = SimulationResult(**d)
        assert restored.session_id == "s1"


class TestMQTTConstants:
    def test_opus_params(self):
        from mqtt_bridge import OPUS_SR, OPUS_CHANNELS, OPUS_FRAME_MS, OPUS_FRAME_SAMPLES

        assert OPUS_SR == 16000
        assert OPUS_CHANNELS == 1
        assert OPUS_FRAME_MS == 60
        assert OPUS_FRAME_SAMPLES == 960  # 16000 * 0.06

    def test_frame_bytes(self):
        from mqtt_bridge import OPUS_FRAME_BYTES, OPUS_FRAME_SAMPLES

        assert OPUS_FRAME_BYTES == OPUS_FRAME_SAMPLES * 2


class TestResolveMQTTHost:
    def test_env_override(self):
        from mqtt_bridge import _resolve_mqtt_host

        with patch.dict(os.environ, {"MQTT_HOST": "10.0.0.99"}):
            assert _resolve_mqtt_host() == "10.0.0.99"

    def test_fallback(self):
        from mqtt_bridge import _resolve_mqtt_host

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MQTT_HOST", None)
            host = _resolve_mqtt_host()
            assert isinstance(host, str)
            assert len(host) > 0


class TestParseResponseTopic:
    def test_vadeos(self):
        from mqtt_bridge import MQTTDeviceSimulator

        tp, meta = MQTTDeviceSimulator._parse_response_topic(
            "development/dev1/response/vadeos/sess1/turn1"
        )
        assert tp == "vadeos"
        assert meta["session_id"] == "sess1"

    def test_audio_start(self):
        from mqtt_bridge import MQTTDeviceSimulator

        tp, meta = MQTTDeviceSimulator._parse_response_topic(
            "development/dev1/response/audio/sess1/turn1/start"
        )
        assert tp == "audio_start"

    def test_audio_chunk(self):
        from mqtt_bridge import MQTTDeviceSimulator

        tp, meta = MQTTDeviceSimulator._parse_response_topic(
            "development/dev1/response/audio/sess1/turn1/chunk/42"
        )
        assert tp == "audio_chunk"
        assert meta["seq"] == "42"

    def test_audio_eos(self):
        from mqtt_bridge import MQTTDeviceSimulator

        tp, _ = MQTTDeviceSimulator._parse_response_topic(
            "development/dev1/response/audio/sess1/turn1/eos"
        )
        assert tp == "audio_eos"

    def test_command(self):
        from mqtt_bridge import MQTTDeviceSimulator

        tp, meta = MQTTDeviceSimulator._parse_response_topic(
            "development/dev1/response/command/sess1"
        )
        assert tp == "command"
        assert meta["session_id"] == "sess1"

    def test_raw_no_response(self):
        from mqtt_bridge import MQTTDeviceSimulator

        tp, _ = MQTTDeviceSimulator._parse_response_topic("development/dev1/request/session/s1/start")
        assert tp == "raw"

    def test_audio_abort(self):
        from mqtt_bridge import MQTTDeviceSimulator

        tp, _ = MQTTDeviceSimulator._parse_response_topic(
            "development/dev1/response/audio/sess1/turn1/abort"
        )
        assert tp == "audio_abort"

    def test_audio_introeos(self):
        from mqtt_bridge import MQTTDeviceSimulator

        tp, _ = MQTTDeviceSimulator._parse_response_topic(
            "development/dev1/response/audio/sess1/turn1/introeos"
        )
        assert tp == "audio_introeos"


class TestMQTTDeviceSimulatorInit:
    def test_topic_format_session(self):
        from mqtt_bridge import MQTTDeviceSimulator

        sim = MQTTDeviceSimulator(
            device_id="dev-test",
            figurine_id="bunny",
            mode="dialogue",
            env="test",
            broker_host="localhost",
        )
        topic = sim._topic("session", "start")
        assert topic.startswith("test/dev-test/request/session/")
        assert topic.endswith("/start")

    def test_topic_format_audio(self):
        from mqtt_bridge import MQTTDeviceSimulator

        sim = MQTTDeviceSimulator(
            device_id="dev-test",
            figurine_id="bunny",
            mode="story",
            env="test",
            broker_host="localhost",
        )
        topic = sim._topic("audio", "start")
        assert "request/audio/" in topic
        assert "/start" in topic

    def test_session_id_unique(self):
        from mqtt_bridge import MQTTDeviceSimulator

        ids = set()
        for _ in range(20):
            sim = MQTTDeviceSimulator(
                device_id="dev-test",
                figurine_id="bunny",
                mode="dialogue",
                env="test",
                broker_host="localhost",
            )
            ids.add(sim.session_id)
        assert len(ids) == 20


class TestLoadWav:
    def test_load_stereo_to_mono(self, tmp_path):
        scipy = pytest.importorskip("scipy")
        import soundfile as sf
        from mqtt_bridge import MQTTDeviceSimulator

        sr = 44100
        dur = 0.5
        samples = int(sr * dur)
        stereo = np.column_stack(
            [np.sin(2 * np.pi * 440 * np.arange(samples) / sr)] * 2
        )
        wav_path = tmp_path / "stereo.wav"
        sf.write(str(wav_path), stereo, sr)

        sim = MQTTDeviceSimulator(
            device_id="d", figurine_id="f", mode="dialogue", broker_host="localhost"
        )
        pcm, duration = sim._load_wav(wav_path)
        assert pcm.ndim == 1
        assert pcm.dtype == np.float64
        assert duration > 0

    def test_load_resample(self, tmp_path):
        scipy = pytest.importorskip("scipy")
        import soundfile as sf
        from mqtt_bridge import OPUS_SR, MQTTDeviceSimulator

        sr = 48000
        dur = 0.3
        samples = int(sr * dur)
        mono = np.sin(2 * np.pi * 440 * np.arange(samples) / sr)
        wav_path = tmp_path / "48k.wav"
        sf.write(str(wav_path), mono, sr)

        sim = MQTTDeviceSimulator(
            device_id="d", figurine_id="f", mode="dialogue", broker_host="localhost"
        )
        pcm, duration = sim._load_wav(wav_path)
        expected_samples = int(OPUS_SR * dur)
        assert abs(len(pcm) - expected_samples) < 100

    def test_load_16k_passthrough(self, tmp_path):
        import soundfile as sf
        from mqtt_bridge import OPUS_SR, MQTTDeviceSimulator

        sr = OPUS_SR
        dur = 0.2
        samples = int(sr * dur)
        mono = np.sin(2 * np.pi * 440 * np.arange(samples) / sr)
        wav_path = tmp_path / "16k.wav"
        sf.write(str(wav_path), mono, sr)

        sim = MQTTDeviceSimulator(
            device_id="d", figurine_id="f", mode="dialogue", broker_host="localhost"
        )
        pcm, duration = sim._load_wav(wav_path)
        assert len(pcm) == samples


class TestSimulationEventBus:
    def test_create_and_publish(self):
        from mqtt_bridge import SimulationEventBus

        bus = SimulationEventBus()
        q = bus.create_queue("sess1")
        bus.publish("sess1", {"type": "test", "data": 42})

        event = q.get_nowait()
        assert event["type"] == "test"
        assert event["data"] == 42

    def test_remove_queue(self):
        from mqtt_bridge import SimulationEventBus

        bus = SimulationEventBus()
        bus.create_queue("sess1")
        bus.remove_queue("sess1")
        bus.publish("sess1", {"type": "test"})
        assert "sess1" not in bus._queues

    def test_unknown_session_noop(self):
        from mqtt_bridge import SimulationEventBus

        bus = SimulationEventBus()
        bus.publish("nonexistent", {"type": "test"})

    def test_reuse_queue(self):
        from mqtt_bridge import SimulationEventBus

        bus = SimulationEventBus()
        q1 = bus.create_queue("sess1")
        q2 = bus.create_queue("sess1")
        assert q1 is q2


class TestSimulationManager:
    def test_singleton_exists(self):
        from mqtt_bridge import simulation_manager

        assert simulation_manager is not None
        assert simulation_manager.MAX_DEVICES == 4

    def test_result_save_and_get(self):
        from mqtt_bridge import SimulationManager, SimulationResult

        mgr = SimulationManager()
        r = SimulationResult(
            session_id="test-save-1",
            device_id="d1",
            figurine_id="f1",
            mode="dialogue",
            audio_id="a1",
            status="completed",
        )
        mgr._save_result(r)
        got = mgr.get_result("test-save-1")
        assert got is not None
        assert got["session_id"] == "test-save-1"
        assert got["status"] == "completed"

    def test_result_not_found(self):
        from mqtt_bridge import SimulationManager

        mgr = SimulationManager()
        assert mgr.get_result("nonexistent") is None

    def test_result_lookup_resolves_session_alias(self):
        from mqtt_bridge import SimulationManager, SimulationResult

        mgr = SimulationManager()
        r = SimulationResult(
            session_id="real-session-1",
            device_id="d1",
            figurine_id="f1",
            mode="dialogue",
            audio_id="a1",
            status="completed",
        )
        with mgr._lock:
            mgr._session_aliases["public-session-1"] = "real-session-1"
        mgr._save_result(r)

        got = mgr.get_result("public-session-1")
        assert got is not None
        assert got["session_id"] == "real-session-1"
        assert got["status"] == "completed"

    def test_history_ordering(self):
        from mqtt_bridge import SimulationManager, SimulationResult

        mgr = SimulationManager()
        for i in range(5):
            r = SimulationResult(
                session_id=f"hist-{i}",
                device_id="d",
                figurine_id="f",
                mode="dialogue",
                audio_id="a",
                started_at=float(i),
            )
            mgr._save_result(r)

        history = mgr.get_history(limit=3)
        assert len(history) == 3
        assert history[0]["started_at"] >= history[1]["started_at"]

    def test_max_concurrent(self):
        from mqtt_bridge import SimulationManager

        mgr = SimulationManager()
        assert mgr.MAX_DEVICES == 4

    def test_active_count_initial(self):
        from mqtt_bridge import SimulationManager

        mgr = SimulationManager()
        assert mgr.get_active_count() == 0

    def test_active_sessions_empty(self):
        from mqtt_bridge import SimulationManager

        mgr = SimulationManager()
        assert mgr.get_active_sessions() == []


# ══════════════════════════════════════════════════════════
# 2. server API integration tests (FastAPI TestClient)
# ══════════════════════════════════════════════════════════


class TestHealthEndpoint:
    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient

        with patch.dict(os.environ, {"MQTT_HOST": "localhost"}):
            from server import app

            with TestClient(app) as c:
                yield c

    def test_health(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_docs(self, client):
        resp = client.get("/docs")
        assert resp.status_code == 200


class TestRuntimeConfigEndpoint:
    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient

        with patch.dict(os.environ, {"MQTT_HOST": "localhost"}):
            from server import app

            with TestClient(app) as c:
                yield c

    def test_runtime_config_snapshot_is_sanitized(self, client):
        resp = client.get("/api/debug/runtime-config")
        assert resp.status_code == 200

        data = resp.json()
        assert data["environment"] in {"test", "production", os.getenv("ENVIRONMENT", "test")}
        assert "mysql" in data
        assert data["mysql"]["host"]
        assert data["mysql"]["database"]
        assert "password" not in data["mysql"]
        assert "env_file" in data
        assert isinstance(data["env_file"]["exists"], bool)
        assert data["env_file"]["path"]
        assert "paths" in data
        assert "chatbot_src" in data["paths"]
        assert "frontend_dist_exists" in data["paths"]


class TestTTSGenerateAPI:
    @pytest.fixture
    def api(self):
        import httpx

        if not _real_backend_available():
            pytest.skip("VoicePipe backend not running")
        return httpx.Client(base_url=VOICEPIPE_BASE, timeout=30)

    def test_generate_english_girl(self, api):
        resp = api.post(
            "/api/tts/generate",
            json={
                "text": "Hello! My name is Emma, I am seven years old.",
                "name": "pytest_girl",
                "gender": "girl",
                "personality": "cute",
                "tone": "happy",
                "speed": 1.0,
                "pitch": 0,
                "volume": 1.0,
                "language": "en",
                "save_to_db": True,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True, f"TTS failed: {data.get('error')}"
        assert data["id"] is not None
        assert data["gender"] == "girl"
        assert data["duration_sec"] > 0 or data["file_size"] > 0

    def test_generate_english_boy(self, api):
        resp = api.post(
            "/api/tts/generate",
            json={
                "text": "Can we play a game please?",
                "name": "pytest_boy",
                "gender": "boy",
                "personality": "cool",
                "tone": "happy",
                "speed": 1.0,
                "pitch": 0,
                "volume": 1.0,
                "language": "en",
                "save_to_db": True,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True, f"TTS failed: {data.get('error')}"

    def test_generate_empty_text_fails(self, api):
        resp = api.post(
            "/api/tts/generate",
            json={
                "text": "",
                "name": "pytest_empty",
                "gender": "girl",
                "personality": "cute",
                "tone": "happy",
                "speed": 1.0,
                "pitch": 0,
                "volume": 1.0,
                "language": "en",
                "save_to_db": True,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False or data.get("error") is not None

    def test_tts_options(self, api):
        resp = api.get("/api/tts/options")
        assert resp.status_code == 200
        data = resp.json()
        assert "genders" in data
        assert "personalities" in data
        assert "emotions" in data
        assert len(data["genders"]) > 0


class TestFigurineAPI:
    @pytest.fixture
    def api(self):
        import httpx

        if not _real_backend_available():
            pytest.skip("VoicePipe backend not running")
        return httpx.Client(base_url=VOICEPIPE_BASE, timeout=10)

    def test_list_figurines(self, api):
        resp = api.get("/api/figurines")
        assert resp.status_code == 200
        data = resp.json()
        assert "figurines" in data
        assert isinstance(data["figurines"], list)

    def test_figurine_tts_audios(self, api):
        resp = api.get("/api/figurines")
        data = resp.json()
        if data["figurines"]:
            fig_id = data["figurines"][0]["figurine_id"]
            resp2 = api.get(f"/api/figurine/{fig_id}/tts-audios")
            assert resp2.status_code == 200
            assert "records" in resp2.json()


class TestMediaAPI:
    @pytest.fixture
    def api(self):
        import httpx

        if not _real_backend_available():
            pytest.skip("VoicePipe backend not running")
        return httpx.Client(base_url=VOICEPIPE_BASE, timeout=10)

    def test_stories(self, api):
        resp = api.get("/api/media/stories")
        assert resp.status_code == 200
        data = resp.json()
        assert "stories" in data

    def test_music(self, api):
        resp = api.get("/api/media/music")
        assert resp.status_code == 200
        data = resp.json()
        assert "music" in data


class TestDeviceSimulateAPI:
    @pytest.fixture
    def api(self):
        import httpx

        if not _real_backend_available():
            pytest.skip("VoicePipe backend not running")
        return httpx.Client(base_url=VOICEPIPE_BASE, timeout=10)

    def test_simulate_no_audio_id(self, api):
        resp = api.post(
            "/api/device/simulate",
            json={
                "device_id": "test-dev",
                "figurine_id": "test-fig",
                "mode": "dialogue",
                "audio_id": "",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "error" in data

    def test_simulate_invalid_audio(self, api):
        resp = api.post(
            "/api/device/simulate",
            json={
                "device_id": "test-dev",
                "figurine_id": "test-fig",
                "mode": "dialogue",
                "audio_id": "nonexistent/file.wav",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "error" in data

    def test_device_status(self, api):
        resp = api.get("/api/device/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "active_count" in data
        assert "max_devices" in data
        assert data["max_devices"] == 4

    def test_device_history(self, api):
        resp = api.get("/api/device/history")
        assert resp.status_code == 200
        data = resp.json()
        assert "records" in data
        assert "total" in data


class TestGeneratedVoiceAPI:
    @pytest.fixture
    def api(self):
        import httpx

        if not _real_backend_available():
            pytest.skip("VoicePipe backend not running")
        return httpx.Client(base_url=VOICEPIPE_BASE, timeout=10)

    def test_list_generated(self, api):
        resp = api.get("/api/tts/generated?limit=20")
        assert resp.status_code == 200
        data = resp.json()
        assert "records" in data
        assert "total" in data

    def test_audio_url_accessible(self, api):
        resp = api.get("/api/tts/generated?limit=5")
        data = resp.json()
        if data["records"]:
            audio_id = data["records"][0]["id"]
            resp2 = api.get(f"/api/tts/audio/{audio_id}", follow_redirects=False)
            assert resp2.status_code in (200, 302, 307)


class TestTranslateAPI:
    @pytest.fixture
    def api(self):
        import httpx

        if not _real_backend_available():
            pytest.skip("VoicePipe backend not running")
        return httpx.Client(base_url=VOICEPIPE_BASE, timeout=10)

    def test_translate_endpoint_exists(self, api):
        resp = api.post(
            "/api/tts/translate",
            json={"text": "Hello, how are you?"},
        )
        assert resp.status_code == 200


# ══════════════════════════════════════════════════════════
# 3. End-to-end MQTT simulation test (needs broker)
# ══════════════════════════════════════════════════════════


class TestMQTTSimulationE2E:
    """These tests require a running MQTT broker at localhost:1883.

    Skipped automatically if broker is unreachable.
    """

    @pytest.fixture(autouse=True)
    def _check_broker(self):
        import socket

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        try:
            sock.connect(("localhost", 1883))
            sock.close()
        except (ConnectionRefusedError, OSError):
            pytest.skip("MQTT broker not available at localhost:1883")

    def test_simulate_with_generated_audio(self, tmp_path):
        from mqtt_bridge import MQTTDeviceSimulator

        wav_path = _make_wav(tmp_path, duration_sec=0.5)

        events = []

        class MockBus:
            def publish(self, sid, ev):
                events.append(ev)

        bus = MockBus()

        sim = MQTTDeviceSimulator(
            device_id="pytest-dev",
            figurine_id="bunny",
            mode="dialogue",
            env="test",
            broker_host="localhost",
            broker_port=1883,
            subscribe_response=True,
            speed=0,
            event_bus=bus,
        )

        result = sim.simulate_from_wav(wav_path, audio_id="pytest-wav")

        assert result.status == "completed"
        assert result.audio_duration_sec > 0
        assert result.total_chunks > 0
        assert result.send_duration_sec > 0
        assert any(e.get("type") == "mqtt_connected" for e in events)
        assert any(e.get("type") == "session_status" for e in events)

    def test_simulate_publishes_all_topics(self, tmp_path):
        from mqtt_bridge import MQTTDeviceSimulator

        wav_path = _make_wav(tmp_path, duration_sec=0.3)

        events = []

        class MockBus:
            def publish(self, sid, ev):
                events.append(ev)

        sim = MQTTDeviceSimulator(
            device_id="pytest-topics",
            figurine_id="bunny",
            mode="dialogue",
            env="test",
            broker_host="localhost",
            broker_port=1883,
            subscribe_response=False,
            speed=0,
            event_bus=MockBus(),
        )

        sim.simulate_from_wav(wav_path, audio_id="pytest-topics")

        publish_events = [e for e in events if e.get("type") == "mqtt_publish"]
        topics = [e.get("topic", "") for e in publish_events]
        topic_actions = []
        for t in topics:
            parts = t.split("/")
            if "session" in parts:
                idx = parts.index("session")
                if idx + 2 < len(parts):
                    topic_actions.append(f"session/{parts[idx + 2]}")
            elif "audio" in parts:
                idx = parts.index("audio")
                if idx + 3 < len(parts):
                    topic_actions.append(f"audio/{parts[idx + 3]}")

        assert any("session/start" in a for a in topic_actions)
        assert any("audio/start" in a for a in topic_actions)
        assert any("session/end" in a for a in topic_actions)

    def test_stop_simulation(self, tmp_path):
        from mqtt_bridge import MQTTDeviceSimulator

        wav_path = _make_wav(tmp_path, duration_sec=5.0)

        sim = MQTTDeviceSimulator(
            device_id="pytest-stop",
            figurine_id="bunny",
            mode="dialogue",
            env="test",
            broker_host="localhost",
            broker_port=1883,
            subscribe_response=False,
            speed=0,
        )

        def _stop_later():
            time.sleep(0.5)
            sim.stop()

        threading.Thread(target=_stop_later, daemon=True).start()
        result = sim.simulate_from_wav(wav_path, audio_id="pytest-stop")

        assert result.status in ("completed", "pending")

    def test_via_api_with_tts_audio(self):
        import httpx

        if not _real_backend_available():
            pytest.skip("VoicePipe backend not running")

        with httpx.Client(base_url=VOICEPIPE_BASE, timeout=30) as api:
            resp = api.post(
                "/api/device/simulate",
                json={
                    "device_id": "pytest-e2e-dev",
                    "figurine_id": "bunny",
                    "mode": "dialogue",
                    "audio_id": f"tts/{TTS_TEST_IDS['next_song']}",
                    "subscribe_response": True,
                    "speed": 0,
                },
            )
            assert resp.status_code == 200
            data = resp.json()

            assert "session_id" in data, f"No session_id in response: {data}"
            assert data["status"] == "started"
            session_id = data["session_id"]

            time.sleep(8)

            result_resp = api.get(f"/api/device/result/{session_id}")
            assert result_resp.status_code == 200
            result_data = result_resp.json()
            assert "result" in result_data
            assert result_data["result"]["status"] in ("completed", "pending", "error")


# ══════════════════════════════════════════════════════════
# 4. Server helper function tests
# ══════════════════════════════════════════════════════════


class TestExtractShortTopic:
    def test_session_start(self):
        from server import _extract_short_topic

        assert _extract_short_topic("env/dev1/request/session/s1/start") == "session/start"

    def test_audio_chunk(self):
        from server import _extract_short_topic

        assert _extract_short_topic("env/dev1/request/audio/s1/t1/chunk/42") == "audio/chunk"

    def test_audio_eos(self):
        from server import _extract_short_topic

        assert _extract_short_topic("env/dev1/request/audio/s1/t1/eos") == "audio/eos"

    def test_session_end(self):
        from server import _extract_short_topic

        assert _extract_short_topic("env/dev1/request/session/s1/end") == "session/end"

    def test_no_request(self):
        from server import _extract_short_topic

        topic = "env/dev1/response/vadeos/s1/t1"
        assert _extract_short_topic(topic) == topic


class TestTranslateWSEvent:
    def test_mqtt_publish_to_message(self):
        from server import _translate_ws_event

        ev = {"type": "mqtt_publish", "topic": "env/dev/request/session/s1/start"}
        out = _translate_ws_event(ev)
        assert out["type"] == "mqtt_message"
        assert out["short_topic"] == "session/start"
        assert out["message_type"] == "session_start"

    def test_vadeos_to_stt_result(self):
        from server import _translate_ws_event

        ev = {"type": "mqtt_response_vadeos", "text": "hello"}
        out = _translate_ws_event(ev)
        assert out["type"] == "stt_result"
        assert out["text"] == "hello"

    def test_session_closed_to_complete(self):
        from server import _translate_ws_event

        ev = {"type": "session_closed"}
        out = _translate_ws_event(ev)
        assert out["type"] == "session_complete"

    def test_passthrough(self):
        from server import _translate_ws_event

        ev = {"type": "mqtt_connected", "rc": 0}
        out = _translate_ws_event(ev)
        assert out["type"] == "mqtt_connected"
