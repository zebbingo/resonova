#!/usr/bin/env python3
"""Fire a simulation HTTP request and forget — no waiting for response"""
import os
import sys
import json
import subprocess
from pathlib import Path

payload_path = Path("/mnt/d/zebbingo/projects/stt-test-tool/backend/sim_payload.json")
url = "http://localhost:8765/api/device/simulate"

# Use curl in background — it can timeout without affecting us
script = f"""curl -s --max-time 300 -X POST {url} \
  -d @{payload_path} \
  -H 'Content-Type: application/json' \
  -o /tmp/sim_http_result.json \
  -w 'HTTP_STATUS: %{{http_code}}' > /tmp/sim_http_status.txt 2>&1 &
echo "CURL_PID=$!"
"""
# Run via bash
proc = subprocess.run(
    ["bash", "-c", script],
    capture_output=True, text=True, timeout=5,
)
print(proc.stdout.strip())
print(proc.stderr.strip() if proc.stderr else "")
sys.exit(0 if "CURL_PID" in proc.stdout else 1)
