#!/usr/bin/env python3
"""
VoicePipe 全链路快速验证脚本
============================
验证顺序:
  1. 后端 API 可用 (health check)
  2. bot_mqtt 在线
  3. MQTT Broker 可用
  4. 设备连接 + session 模拟
  5. STT 识别 + 结果返回

用法:
  # 快速检查（仅服务存活）
  python scripts/e2e_verify.py --quick

  # 完整端到端验证（需 2-3 分钟）
  python scripts/e2e_verify.py

环境要求:
  PYTHONPATH=/home/administrator/chatbot-test/.venv/lib/python3.13/site-packages
"""

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

QUICK_MODE = "--quick" in sys.argv

BACKEND = "http://127.0.0.1:8765"
DEVICE_ID = "verify-dev"
FIGURINE_ID = "astronaut"
MODE = "dialogue"
TIMEOUT_SIM = 120

PASS = []
FAIL = []

def ok(label: str, detail: str = ""):
    PASS.append(label)
    pad = 36 - len(label)
    print(f"  [PASS]{' '*pad} {label}  {detail}")

def fail(label: str, detail: str = ""):
    FAIL.append(label)
    pad = 36 - len(label)
    print(f"  [FAIL]{' '*pad} {label}  {detail}")

def http_get(path: str) -> dict | None:
    try:
        req = urllib.request.Request(f"{BACKEND}{path}")
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        return None

def http_post(path: str, body: dict) -> dict | None:
    try:
        data = json.dumps(body).encode()
        req = urllib.request.Request(
            f"{BACKEND}{path}", data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return {"_http_error": e.code, "_body": e.read().decode()[:200]}
    except Exception as e:
        return {"_error": str(e)}

def tcp_ping(host: str, port: int, timeout: int = 2) -> bool:
    try:
        s = socket.socket()
        s.settimeout(timeout)
        s.connect((host, port))
        s.close()
        return True
    except Exception:
        return False

# ══════════════════════════════════════════════════════
print("=" * 60)
print("  VoicePipe Full Chain Verification")
import datetime
print(f"  {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 60)

# ── Phase 1: Services ────────────────────────────────
print("\n[1/5] Service Health")
print("-" * 40)

# Backend API
data = http_get("/api/figurines")
api_ok = data is not None
if api_ok: ok("Backend API")
else: fail("Backend API")

# MQTT Broker
mq = tcp_ping("127.0.0.1", 1883)
ok("MQTT Broker") if mq else fail("MQTT Broker")

# bot_mqtt
try:
    r = subprocess.run(["pgrep", "-f", "bot_mqtt"], capture_output=True, text=True, timeout=5)
    has_bot = any("e2e_verify" not in l for l in r.stdout.strip().split("\n") if l)
    ok("bot_mqtt") if has_bot else fail("bot_mqtt")
except: fail("bot_mqtt")

if not (api_ok and mq and has_bot):
    print("\n  ABORT: core services not healthy")
    sys.exit(1)

if QUICK_MODE:
    p, f = len(PASS), len(FAIL)
    print(f"\n  QUICK CHECK: {p}/{p+f} PASS")
    sys.exit(0 if f == 0 else 1)

# ── Phase 2: Figurines ───────────────────────────────
print("\n[2/5] Figurine Data")
print("-" * 40)

figs = []
if data and isinstance(data, dict):
    raw = data.get("figurines", data.get("data", []))
    figs = raw if isinstance(raw, list) else [raw] if isinstance(raw, dict) else []
elif isinstance(data, list):
    figs = data

fids = [f.get("figurine_id", "") for f in figs if isinstance(f, dict)]
ok(f"Figurines loaded ({len(fids)})")
found = FIGURINE_ID in fids
if found: ok(f"Target '{FIGURINE_ID}' found")
else: fail(f"Target '{FIGURINE_ID}' not found")

# ── Phase 3: Connect ─────────────────────────────────
print("\n[3/5] Device Connect")
print("-" * 40)

# Disconnect first to clear any stale state
http_post("/api/device/disconnect/verify-dev", {})

conn = http_post("/api/device/connect", {
    "device_id": DEVICE_ID,
    "figurine_id": FIGURINE_ID,
    "mode": MODE,
})
cok = conn is not None and conn.get("status") in ("started", "already_connected", "connected")
ok("Device connected") if cok else fail("Device connected", str(conn))

# ── Phase 4: Simulate Session ────────────────────────
print("\n[4/5] Simulate Session")
print("-" * 40)

# Use the direct WAV file from chatbot test data
test_wav = "/home/administrator/projects/chatbot/tests/asr/testdata/mqtt_vad_capture_input.wav"
if os.path.exists(test_wav):
    ok("Test WAV exists")
else:
    fail("Test WAV missing", test_wav)

sim = http_post("/api/device/simulate", {
    "device_id": DEVICE_ID,
    "figurine_id": FIGURINE_ID,
    "mode": MODE,
    "audio_id": test_wav,
    "subscribe_response": True,
})

sid = sim.get("session_id", "") if sim else ""
sim_ok = bool(sid)
if sim_ok: ok("Session started", sid[:20])
else: fail("Session started", str(sim))

if not sim_ok:
    print("\n  ABORT: simulation failed")
    sys.exit(1)

# ── Phase 5: Wait & Results ──────────────────────────
print(f"\n[5/5] Waiting for E2E result (timeout={TIMEOUT_SIM}s)")
print("-" * 40)

stt_text = ""
cmd_count = 0
total_chunks = 0
status = ""
start_ts = time.time()

deadline = start_ts + TIMEOUT_SIM
while time.time() < deadline:
    elapsed = int(time.time() - start_ts)
    raw = http_get(f"/api/device/result/{sid}")
    if raw:
        data = raw.get("result", raw)
        status = data.get("status", "")
        stt_text = data.get("stt_text", "")
        cmd_count = data.get("commands_received", 0)
        total_chunks = data.get("total_chunks", 0)

        if status == "completed":
            ok("Session completed", f"elapsed={elapsed}s chunks={total_chunks} cmds={cmd_count}")
            break
        elif status == "error":
            fail("Session error", data.get("error", ""))
            break
    time.sleep(2)
else:
    fail("Session timeout", f"elapsed={int(time.time()-start_ts)}s status={status}")

# Analysis
print(f"\n{'─' * 40}")
has_stt = bool(stt_text and stt_text.strip())
if has_stt: ok("STT result", f'"{stt_text[:80]}"')
else: fail("STT result (empty)")

has_cmd = cmd_count > 0
if has_cmd: ok(f"Commands ({cmd_count})")
else: fail("Commands (0)", "may be fine if audio has no command intent")

if total_chunks > 0: ok(f"Audio chunks ({total_chunks})")
else: fail("Audio chunks (0)")

# Summary
print(f"\n{'=' * 60}")
p, f = len(PASS), len(FAIL)
if f == 0:
    print(f"  RESULT: {p}/{p+f} PASS - FULL CHAIN WORKING!")
else:
    print(f"  RESULT: {p}/{p+f} PASS, {f} FAIL")
    for l in FAIL: print(f"    FAIL: {l}")

if stt_text:
    print(f'\n  STT: "{stt_text}"')
print("=" * 60)
sys.exit(0 if f == 0 else 1)
