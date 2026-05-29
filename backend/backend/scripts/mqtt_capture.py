#!/usr/bin/env python3
"""MQTT capture tool - listens on development/# and writes all messages to a file"""
import json
import os
import sys
import time
import signal

import paho.mqtt.client as mqtt

MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_ENV = os.getenv("MQTT_ENV", "development")
OUTPUT_FILE = "/tmp/mqtt_capture.jsonl"

captured = []
running = True

def on_connect(client, userdata, flags, rc, properties=None):
    print(f"[MON] Connected rc={rc}", flush=True)
    if rc == 0:
        client.subscribe(f"{MQTT_ENV}/#", qos=0)
        print(f"[MON] Subscribed to {MQTT_ENV}/#", flush=True)

def on_message(client, userdata, msg):
    entry = {
        "ts": time.time(),
        "topic": msg.topic,
        "payload": msg.payload.decode("utf-8", errors="replace")[:500],
        "retain": msg.retain,
    }
    captured.append(entry)
    print(f"[MQTT] {msg.topic}", flush=True)
    # Write to file immediately
    with open(OUTPUT_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")

def on_disconnect(client, userdata, rc, properties=None):
    print(f"[MON] Disconnected rc={rc}", flush=True)

def signal_handler(sig, frame):
    global running
    print(f"[MON] Signal received, stopping...", flush=True)
    running = False

signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)

print(f"[MON] Starting MQTT capture to {OUTPUT_FILE}", flush=True)
print(f"[MON] Broker: {MQTT_HOST}:{MQTT_PORT}", flush=True)

client = mqtt.Client(
    client_id=f"mqtt-capture-{int(time.time())}",
    callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
    protocol=mqtt.MQTTv311,
)
client.on_connect = on_connect
client.on_message = on_message
client.on_disconnect = on_disconnect

client.connect(MQTT_HOST, MQTT_PORT, 30)
client.loop_start()

try:
    while running:
        time.sleep(0.5)
except KeyboardInterrupt:
    pass

client.loop_stop()
client.disconnect()

print(f"[MON] Stopped. Captured {len(captured)} messages", flush=True)
