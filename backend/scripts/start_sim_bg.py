#!/usr/bin/env python3
"""Start a simulation in background and save result to a file"""
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

OUTPUT_DIR = Path("/tmp")
payload = {
    "device_id": "sim-dev-002",
    "figurine_id": "doctor",
    "audio_id": "117",
    "subscribe_response": True,
    "use_existing_device": True,
}
payload_file = OUTPUT_DIR / "sim_req_bg.json"
result_file = OUTPUT_DIR / "sim_result_bg.json"

# Save the payload for reference
payload_file.write_text(json.dumps(payload, indent=2))

try:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        "http://localhost:8765/api/device/simulate",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    resp = urllib.request.urlopen(req, timeout=120)
    result = json.loads(resp.read().decode("utf-8"))
    result_file.write_text(json.dumps(result, indent=2))
    print(f"OK: session_id={result.get('session_id', '?')}")
except Exception as e:
    result_file.write_text(json.dumps({"error": str(e)}))
    print(f"FAIL: {e}")
