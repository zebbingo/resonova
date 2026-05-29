#!/usr/bin/env python3
"""
Start a simulation and monitor MQTT traffic simultaneously.
Used via: python3 scripts/sim_and_monitor.py
"""
import json
import os
import subprocess
import sys
import time
import threading
from pathlib import Path

import paho.mqtt.client as mqtt

MQTT_HOST = "localhost"
MQTT_PORT = 1883
MQTT_ENV = "development"
SIM_URL = "http://localhost:8765/api/device/simulate"
PAYLOAD_FILE = "/mnt/d/zebbingo/projects/stt-test-tool/backend/sim_payload.json"

mqtt_messages = []
mqtt_ready = threading.Event()
monitor_done = threading.Event()

def on_message(client, userdata, msg):
    topic = msg.topic
    payload = msg.payload[:300].decode("utf-8", errors="replace")
    mqtt_messages.append((topic, payload))
    print(f"  [MQTT] {topic}: {payload[:120]}", flush=True)

def monitor_mqtt(duration=20):
    """Monitor MQTT in a thread"""
    client = mqtt.Client(client_id=f"sim-mon-{int(time.time())}")
    client.on_message = on_message
    try:
        client.connect(MQTT_HOST, MQTT_PORT, 30)
        client.subscribe(f"{MQTT_ENV}/#", qos=0)
        print(f"  [MON] Subscribed to {MQTT_ENV}/#", flush=True)
        mqtt_ready.set()
        client.loop_start()
        time.sleep(duration)
        client.loop_stop()
    except Exception as e:
        print(f"  [MON] Error: {e}", flush=True)
    finally:
        client.disconnect()
        monitor_done.set()

def run_simulation():
    """Run simulation via curl"""
    result_file = "/tmp/sim_and_mon_result.txt"
    # Wait for MQTT monitor to be ready
    mqtt_ready.wait(timeout=5)

    print(f"  [SIM] Starting simulation...", flush=True)
    result = subprocess.run(
        ["curl", "-s", "--max-time", "90", "-X", "POST", SIM_URL,
         "-d", f"@{PAYLOAD_FILE}",
         "-H", "Content-Type: application/json"],
        capture_output=True, text=True, timeout=40,
    )
    Path(result_file).write_text(result.stdout + "\n" + result.stderr)
    print(f"  [SIM] Response: {result.stdout[:300]}", flush=True)

if __name__ == "__main__":
    print("=== Simulation + MQTT Monitor ===", flush=True)

    # Start MQTT monitor in background thread
    mon = threading.Thread(target=monitor_mqtt, args=(35,), daemon=True)
    mon.start()

    time.sleep(1)  # Give monitor time to connect

    # Run simulation (this will block up to 120s but we monitor MQTT)
    run_simulation()

    # Wait for monitoring to finish
    monitor_done.wait(timeout=30)

    print(f"\n=== Summary: {len(mqtt_messages)} MQTT messages captured ===", flush=True)

    # Categorize messages
    request_msgs = [m for m in mqtt_messages if "/request/" in m[0]]
    response_msgs = [m for m in mqtt_messages if "/response/" in m[0]]
    meta_msgs = [m for m in mqtt_messages if "/meta/" in m[0]]
    other_msgs = [m for m in mqtt_messages if "/request/" not in m[0] and "/response/" not in m[0] and "/meta/" not in m[0]]

    print(f"  Request messages: {len(request_msgs)}")
    for t, p in request_msgs[:10]:
        print(f"    {t}: {p[:80]}")
    print(f"  Response messages: {len(response_msgs)}")
    for t, p in response_msgs[:10]:
        print(f"    {t}: {p[:80]}")
    print(f"  Meta messages: {len(meta_msgs)}")
    print(f"  Other: {len(other_msgs)}")
