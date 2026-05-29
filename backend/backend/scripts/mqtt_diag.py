#!/usr/bin/env python3
"""
MQTT Diagnostic Tool — check broker, subscriptions, and message flow
Usage: python3 scripts/mqtt_diag.py [action]
  actions: check_broker | monitor_messages | run_simulation
"""
import json
import os
import sys
import time
import threading
from pathlib import Path

import paho.mqtt.client as mqtt

MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_ENV = os.getenv("MQTT_ENV", "development")
BACKEND_DIR = Path(__file__).resolve().parent.parent

received_messages = []
stop_monitor = threading.Event()

def on_message(client, userdata, msg):
    received_messages.append({
        "topic": msg.topic,
        "payload": msg.payload[:200].decode("utf-8", errors="replace"),
        "timestamp": time.time(),
    })

def check_broker():
    """Check if broker is alive and list basic info"""
    print(f"=== MQTT Broker Check ===")
    print(f"Host: {MQTT_HOST}:{MQTT_PORT}")
    print(f"Env: {MQTT_ENV}")

    # Try to connect and check
    client = mqtt.Client(client_id="diag-check-" + str(int(time.time())))
    client.connect_timeout = 5
    try:
        client.connect(MQTT_HOST, MQTT_PORT, 60)
        print("✓ Connected to broker")
        client.disconnect()
    except Exception as e:
        print(f"✗ Connection failed: {e}")
        return False
    return True

def monitor_messages(duration=15, topic_filter=f"+/+"):
    """Monitor MQTT traffic for N seconds"""
    client = mqtt.Client(client_id="diag-monitor-" + str(int(time.time())))
    client.on_message = on_message
    client.connect_timeout = 5

    try:
        client.connect(MQTT_HOST, MQTT_PORT, 60)
        client.subscribe(f"{MQTT_ENV}/#", qos=0)
        print(f"✓ Subscribed to {MQTT_ENV}/#")
        client.loop_start()
        time.sleep(duration)
        client.loop_stop()
    except Exception as e:
        print(f"✗ Monitor failed: {e}")
        return []

    client.disconnect()
    return list(received_messages)

def run_simulation_and_monitor():
    """Run a simulation via HTTP API and monitor MQTT traffic"""
    import urllib.request
    import urllib.parse

    device_id = "sim-dev-002"
    figurine_id = "doctor"
    audio_id = "117"

    # Start monitoring in background
    client = mqtt.Client(client_id="diag-sim-" + str(int(time.time())))
    client.on_message = on_message
    client.connect(MQTT_HOST, MQTT_PORT, 60)
    client.subscribe(f"{MQTT_ENV}/#", qos=0)
    client.loop_start()

    # Prepare simulation payload
    payload = json.dumps({
        "device_id": device_id,
        "figurine_id": figurine_id,
        "audio_id": audio_id,
        "subscribe_response": True,
        "use_existing_device": True,
    }).encode("utf-8")

    print(f"=== Triggering simulation for {device_id}/{figurine_id} ===")
    url = "http://localhost:8765/api/device/simulate"
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})

    try:
        resp = urllib.request.urlopen(req, timeout=10)
        result = json.loads(resp.read().decode("utf-8"))
        session_id = result.get("session_id", "?")
        print(f"Session started: {session_id}")
        print(f"Full response: {json.dumps(result, indent=2)}")
    except Exception as e:
        print(f"✗ Simulation request failed: {e}")

    # Wait for messages
    print("Monitoring MQTT for 20 seconds...")
    for i in range(20):
        time.sleep(1)
        if received_messages:
            pass  # continue collecting
        sys.stdout.write(".")
        sys.stdout.flush()
    print()

    client.loop_stop()
    client.disconnect()
    return list(received_messages)

if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "check_broker"

    if action == "check_broker":
        check_broker()
    elif action == "monitor":
        msgs = monitor_messages(int(sys.argv[2]) if len(sys.argv) > 2 else 15)
        print(f"\n=== Captured {len(msgs)} messages ===")
        for m in msgs:
            age = time.time() - m["timestamp"]
            print(f"  [{age:.1f}s ago] {m['topic']}: {m['payload'][:120]}")
    elif action == "simulate":
        msgs = run_simulation_and_monitor()
        print(f"\n=== Captured {len(msgs)} messages ===")
        for m in msgs:
            age = time.time() - m["timestamp"]
            print(f"  [{age:.1f}s ago] {m['topic']}: {m['payload'][:120]}")
    else:
        print(f"Unknown action: {action}")
        print("Usage: python3 scripts/mqtt_diag.py [check_broker|monitor|simulate]")
