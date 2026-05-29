#!/usr/bin/env python3
"""Minimal MQTT publish test - subscribe and publish same message"""
import json
import os
import sys
import time
import threading

import paho.mqtt.client as mqtt

MQTT_HOST = "localhost"
MQTT_PORT = 1883
MQTT_ENV = "development"

received = threading.Event()
received_topic = None
received_payload = None

def on_connect(client, userdata, flags, rc, properties=None):
    print(f"  on_connect: rc={rc}")
    if rc == 0:
        print("  Connected successfully!")
        client.subscribe(f"{MQTT_ENV}/test/verify", qos=1)
        print(f"  Subscribed to {MQTT_ENV}/test/verify")

def on_message(client, userdata, msg):
    global received_topic, received_payload
    received_topic = msg.topic
    received_payload = msg.payload.decode("utf-8", errors="replace")
    print(f"  Received: {msg.topic} -> {received_payload[:100]}")
    received.set()

# Create client with explicit callback API version
client = mqtt.Client(
    client_id="pub-test-verify",
    callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
    protocol=mqtt.MQTTv311,
)
client.on_connect = on_connect
client.on_message = on_message

print(f"=== MQTT Publish Test ===")
print(f"Broker: {MQTT_HOST}:{MQTT_PORT}")
print(f"Client: pub-test-verify")
sys.stdout.flush()

# Connect
print(f"Connecting...")
client.connect(MQTT_HOST, MQTT_PORT, 30)
client.loop_start()

time.sleep(1)

# Publish test message
test_payload = json.dumps({"test": True, "ts": time.time()})
print(f"Publishing to {MQTT_ENV}/test/verify: {test_payload}")
sys.stdout.flush()
client.publish(f"{MQTT_ENV}/test/verify", test_payload, qos=1)

# Wait to receive
ok = received.wait(timeout=3)

# Clean up
client.loop_stop()
client.disconnect()

print(f"")
if ok:
    print(f"✓ SUCCESS: Published and received message on same broker")
    print(f"  Topic: {received_topic}")
    print(f"  Payload: {received_payload}")
else:
    print(f"✗ FAILED: Did not receive our own message within 3s")
    sys.exit(1)
