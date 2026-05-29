#!/usr/bin/env python3
"""全链路模拟测试：连接设备 -> 启动模拟 -> 监控 -> 查看结果"""
import json
import os
import sys
import time
import urllib.request
import urllib.error

HOST = os.getenv("HOST", "localhost")
PORT = int(os.getenv("PORT", "8765"))
BASE = "http://%s:%s" % (HOST, PORT)


def api(method, path, data=None):
    url = BASE + path
    body = json.dumps(data).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=body,
                                 headers={"Content-Type": "application/json"},
                                 method=method)
    try:
        resp = urllib.request.urlopen(req, timeout=120)
        return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"error": "HTTP %d" % e.code,
                "detail": e.read().decode()[:300]}
    except Exception as e:
        return {"error": str(e)}


# Step 1: connect device
print("=" * 60)
print("STEP 1: connect device sim-dev-003 (local MQTT)")
print("=" * 60)
result = api("POST", "/api/device/connect", {
    "device_id": "sim-dev-003",
    "figurine_id": "doctor",
    "mode": "dialogue",
    "mqtt_profile": "local",
})
print(json.dumps(result, indent=2, ensure_ascii=False))
if "error" in result:
    print("connect failed, exit")
    sys.exit(1)
print()

# Step 2: list devices
print("=" * 60)
print("STEP 2: list devices")
print("=" * 60)
devices = api("GET", "/api/device/list")
print(json.dumps(devices, indent=2, ensure_ascii=False))
print()

# Step 3: start simulation
AUDIO_PATH = "/home/administrator/projects/chatbot/tests/asr/testdata/mqtt_vad_capture_input.wav"
print("=" * 60)
print("STEP 3: start simulation (audio=%s)" % AUDIO_PATH)
print("=" * 60)
result = api("POST", "/api/device/simulate", {
    "device_id": "sim-dev-003",
    "figurine_id": "doctor",
    "mode": "dialogue",
    "audio_id": AUDIO_PATH,
    "subscribe_response": True,
    "mqtt_profile": "local",
})
print(json.dumps(result, indent=2, ensure_ascii=False))
if "error" in result:
    print("simulation start failed")
    sys.exit(1)
session_id = result.get("session_id", "")
print("\nSession ID: %s" % session_id)
print()

if not session_id:
    sys.exit(1)

# Step 4: poll events
print("=" * 60)
print("STEP 4: monitor simulation (session=%s)" % session_id)
print("=" * 60)
max_wait = 120
poll_interval = 3
start_ts = time.time()
last_count = 0

while time.time() - start_ts < max_wait:
    events = api("GET", "/api/device/events/%s" % session_id)
    if "error" in events:
        print("  events error: %s" % events)
        break

    event_list = events if isinstance(events, list) else \
        events.get("events", events.get("messages", []))
    if len(event_list) > last_count:
        for e in event_list[last_count:]:
            ts = e.get("timestamp", e.get("time", ""))
            et = e.get("type", e.get("event", ""))
            data = e.get("summary", e.get("data", ""))
            if isinstance(data, dict):
                data = json.dumps(data, ensure_ascii=False)[:120]
            print("  [%s] %s: %s" % (ts, et, data))
        last_count = len(event_list)

    result_data = api("GET", "/api/device/result/%s" % session_id)
    if isinstance(result_data, dict) and \
       result_data.get("status") in ("completed", "error", "timeout"):
        print("\nsimulation done: status=%s" % result_data.get("status"))
        break

    time.sleep(poll_interval)

elapsed = time.time() - start_ts
print("\nelapsed: %.1fs" % elapsed)

# Step 5: final result
print("=" * 60)
print("STEP 5: simulation result (session=%s)" % session_id)
print("=" * 60)
result_data = api("GET", "/api/device/result/%s" % session_id)
print(json.dumps(result_data, indent=2, ensure_ascii=False))
print()

# Step 6: history
print("=" * 60)
print("STEP 6: simulation history")
print("=" * 60)
history = api("GET", "/api/device/history?limit=5")
print(json.dumps(history, indent=2, ensure_ascii=False))
