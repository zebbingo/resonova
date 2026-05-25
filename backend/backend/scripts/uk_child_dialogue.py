#!/usr/bin/env python3
"""
VoicePipe — UK Child Dialogue Simulation (v1.1 协议)

真实设备级行为:
  1. 设备上电 → 常连接 MQTT
  2. start_session → 一个 session 跑完所有 turn
  3. wait_intro → turn 1 → wait response → turn 2 → wait response → ...
  4. stop_session → power_off

每个场景 = 1 个设备 (持久身份) + 1 个 session (多轮 turn)
"""

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from device_firmware import DeviceFirmware

HOST = os.getenv("VOICEPIPE_HOST", "localhost")
PORT = int(os.getenv("VOICEPIPE_PORT", "8765"))
BASE = f"http://{HOST}:{PORT}"

SCENARIOS = {
    "storytime": {
        "description": "Emma (7yo) asks Lumi the Unicorn for a bedtime story",
        "figurine_id": "unicorn", "mode": "dialogue", "nfc_id": "sim-uk-emma",
        "device_id": "uk-emma-unicorn",
        "turns": [
            {"speaker": "Emma (girl, 7)", "text": "Hello! Can you tell me a story about a brave rabbit?", "gender": "girl", "personality": "cute", "tone": "happy"},
            {"speaker": "Emma", "text": "What happened to the rabbit next? Did he find his way home?", "gender": "girl", "personality": "cute", "tone": "happy"},
            {"speaker": "Emma", "text": "That was brilliant! Can you tell me another one about a dragon?", "gender": "girl", "personality": "cute", "tone": "happy"},
        ],
    },
    "music_commands": {
        "description": "Oliver (9yo) controls music with Tara the T-Rex",
        "figurine_id": "t-rex", "mode": "dialogue", "nfc_id": "sim-uk-oliver",
        "device_id": "uk-oliver-trex",
        "turns": [
            {"speaker": "Oliver (boy, 9)", "text": "Play the next song please!", "gender": "boy", "personality": "cool", "tone": "happy"},
            {"speaker": "Oliver", "text": "Stop! I want to talk to you instead.", "gender": "boy", "personality": "cool", "tone": "neutral"},
            {"speaker": "Oliver", "text": "Can you turn the volume up a bit?", "gender": "boy", "personality": "cool", "tone": "neutral"},
        ],
    },
    "daily_chat": {
        "description": "Lily (6yo) chats with Pip the pup about her school day",
        "figurine_id": "puppy", "mode": "dialogue", "nfc_id": "sim-uk-lily",
        "device_id": "uk-lily-puppy",
        "turns": [
            {"speaker": "Lily (girl, 6)", "text": "I had a really fun day at school today! My teacher said I did great on my maths test.", "gender": "girl", "personality": "cute", "tone": "happy"},
            {"speaker": "Lily", "text": "Do you want to know what I had for lunch? I had fish and chips!", "gender": "girl", "personality": "cute", "tone": "happy"},
            {"speaker": "Lily", "text": "Can you sing me a song about the rain? It is raining outside.", "gender": "girl", "personality": "cute", "tone": "sad"},
        ],
    },
}


def _api(method: str, path: str, j: dict | None = None, timeout: float = 30):
    import httpx
    with httpx.Client(base_url=BASE, timeout=timeout) as c:
        r = c.get(path) if method == "get" else c.post(path, json=j)
        return r.status_code, r.json()


def generate_tts(turn: dict) -> dict | None:
    code, data = _api("post", "/api/tts/generate", {
        "text": turn["text"],
        "name": f"sim_{turn['speaker'].split(' ')[0].lower()}_{int(time.time())}",
        "gender": turn["gender"], "personality": turn["personality"],
        "tone": turn["tone"], "speed": 1.0, "pitch": 0, "volume": 1.0,
        "language": "en", "save_to_db": True,
    })
    if code == 200 and data.get("success"):
        return data
    print(f"  ❌ TTS failed: {data.get('error', 'unknown')}")
    return None


def load_pcm(tts_data: dict):
    ap = tts_data.get("audio_path", "")
    if not ap:
        return None, 0
    src = Path(ap)
    if not src.exists():
        return None, 0
    wav = src.parent / f"{src.stem}_sim.wav"
    if not wav.exists():
        import subprocess
        try:
            subprocess.run(["ffmpeg", "-y", "-i", str(src), "-ar", "16000", "-ac", "1", str(wav)], capture_output=True, timeout=30)
        except Exception:
            return None, 0
    if not wav.exists():
        return None, 0
    import scipy.io.wavfile as wf
    import numpy as np
    # 引用 pcm_utils 确保换算因子一致（单一权威源）
    import sys, os
    _SK_DIR = os.path.dirname(os.path.dirname(__file__))
    if _SK_DIR not in sys.path:
        sys.path.insert(0, _SK_DIR)
    from pcm_utils import float32_to_int16, PCM_SR
    sr, d = wf.read(str(wav))
    if d.dtype in (np.float32, np.float64):
        d = float32_to_int16(d)
    if sr != PCM_SR:
        from scipy.signal import resample
        d = resample(d, int(len(d) * PCM_SR / sr)).astype(np.int16)
    return d, len(d) / PCM_SR


def run_scenario(name: str, sc: dict) -> list[dict]:
    print(f"\n{'=' * 60}")
    print(f"🎭 {name}: {sc['description']}")
    print(f"   Device: {sc['device_id']} ({sc['figurine_id']})")
    print(f"{'=' * 60}")

    fw = DeviceFirmware(sc["device_id"])
    fw.power_on()
    print(f"  🔌 Device online")

    # Generate all turn audio first
    turns_audio = []
    for i, turn in enumerate(sc["turns"], 1):
        tts = generate_tts(turn)
        if not tts:
            turns_audio.append(None)
            continue
        pcm, dur = load_pcm(tts)
        turns_audio.append((pcm, dur, turn))
        print(f"  🎙️  Turn {i}: \"{turn['text'][:50]}...\" → {dur:.1f}s")

    # Start ONE session for ALL turns
    fw.start_session(figurine_id=sc["figurine_id"], nfc_id=sc["nfc_id"], mode=sc["mode"])
    print(f"  📡 Session: {fw.session_id}")

    got = fw.wait_for_intro_eos(timeout=25)
    print(f"  ⏳ Intro signal: {'done' if got else 'timeout'}")

    got = fw.wait_for_intro_audio_end(timeout=90)
    print(f"  ⏳ Intro audio: {'done' if got else 'timeout'}")

    results = []
    for i, audio in enumerate(turns_audio, 1):
        if audio is None:
            results.append({"turn": i, "status": "tts_failed"})
            continue
        pcm_data, duration, turn = audio

        print(f"\n  🗣️  [{i}] {turn['speaker']}")
        fw.start_turn(pcm_data)
        print(f"      Turn {fw.current_turn_id} sent")

        got_resp = fw.wait_for_turn_response(timeout=90)
        status = "completed" if (fw.response_chunks > 0 or fw.stt_text) else "no_response"
        print(f"      Response: {'done' if got_resp else 'timeout'} ({status})")
        if fw.response_chunks:
            print(f"         🔊 TTS: {fw.response_chunks} chunks")
        if fw.stt_text:
            print(f"         📝 STT: \"{fw.stt_text[:80]}\"")

        results.append({
            "turn": i, "status": status, "turn_id": fw.current_turn_id,
            "speaker": turn["speaker"], "input_text": turn["text"],
            "stt_text": fw.stt_text, "reply_text": fw.reply_text,
            "tts_chunks": fw.response_chunks, "session_id": fw.session_id,
        })

        if got_resp and i < len(turns_audio):
            time.sleep(2)

    fw.stop_session()
    fw.power_off()
    print(f"\n  🔌 Device offline")
    return results


def main():
    print(f"🔊 VoicePipe Dialogue Simulation")
    print(f"   Backend: {BASE} | MQTT: localhost:1883 | Env: prod\n")

    import socket, subprocess
    print("🔍 Pre-flight...")
    ok = True
    for label, (h, p) in {"VoicePipe": (HOST, PORT), "MQTT": ("localhost", 1883)}.items():
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2)
        try:
            s.connect((h, p)); s.close()
            print(f"  ✅ {label}")
        except:
            print(f"  ❌ {label}"); ok = False
    try:
        r = subprocess.run(["pgrep", "-f", "bot_mqtt"], capture_output=True, text=True, timeout=3)
        if r.stdout.strip():
            print(f"  ✅ bot_mqtt.py")
        else:
            print(f"  ❌ bot_mqtt.py — NOT RUNNING"); ok = False
    except:
        pass
    if not ok:
        sys.exit(1)

    targets = sys.argv[1:] if len(sys.argv) > 1 else list(SCENARIOS.keys())
    all_results = {}
    for name in targets:
        if name in SCENARIOS:
            all_results[name] = run_scenario(name, SCENARIOS[name])
        else:
            print(f"⚠️  Unknown: {name}")

    print(f"\n\n{'=' * 60}")
    print("📊 REPORT")
    print(f"{'=' * 60}")
    total, ok = 0, 0
    for name, results in all_results.items():
        print(f"\n🎭 {name}")
        for r in results:
            total += 1
            icon = "✅" if r["status"] == "completed" else "⚠️"
            print(f"  Turn {r['turn']}: {icon} {r['status']}")
            if r["status"] == "completed":
                ok += 1
                if r.get("tts_chunks"):
                    print(f"         TTS: {r['tts_chunks']} chunks")
                if r.get("stt_text"):
                    print(f"         STT: \"{r['stt_text'][:60]}\"")
    print(f"\n{'─' * 40}\n  Total: {total}  Success: {ok}/{total}\n{'─' * 40}")

    rp = Path(__file__).resolve().parent / "simulation_report.json"
    rp.write_text(json.dumps(all_results, indent=2, default=str))
    print(f"\n📁 {rp}")


if __name__ == "__main__":
    main()
