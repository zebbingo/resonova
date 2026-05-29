#!/usr/bin/env python3
"""Run a single simulation and print the result"""
import json
import os
import sys
import time
from pathlib import Path

import urllib.request
import urllib.error

HOST = os.getenv("HOST", "localhost")
PORT = int(os.getenv("PORT", "8765"))
URL = f"http://{HOST}:{PORT}/api/device/simulate"

payload = json.dumps({
    "device_id": "sim-dev-002",
    "figurine_id": "doctor",
    "audio_id": "117",
    "subscribe_response": True,
    "use_existing_device": True,
}).encode("utf-8")

print(f"POST {URL}")
print(f"Payload: {payload.decode()}")
sys.stdout.flush()

req = urllib.request.Request(URL, data=payload, headers={"Content-Type": "application/json"})
try:
    resp = urllib.request.urlopen(req, timeout=120)
    result = json.loads(resp.read().decode("utf-8"))
    print(f"\nSimulation result:")
    print(json.dumps(result, indent=2, ensure_ascii=False))
except urllib.error.HTTPError as e:
    print(f"\nHTTP Error: {e.code} {e.reason}")
    print(e.read().decode()[:500])
except urllib.error.URLError as e:
    print(f"\nURL Error: {e.reason}")
except Exception as e:
    print(f"\nError: {e}")
