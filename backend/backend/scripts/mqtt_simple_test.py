#!/usr/bin/env python3
"""Ultra-simple MQTT test using VERSION1 callbacks (same as DeviceFirmware)"""
import json
import os
import sys
import time

import paho.mqtt.client as mqtt

MQTT_HOST = "localhost"
MQTT_PORT = 1883
MQTT_ENV = "development"

received = {"ok": False}

# Use VERSION1 callbacks (like DeviceFirmware)
def on_connect(client, userdata, flags, rc):
    print(f"[on_connect] rc={rc}", flush=True)
    if rc == 0:
        print("[on_connect] SUCCESS", flush=True)
        client.subscribe(f"{MQTT_ENV}/test/simple", qos=1)
        print(f"[on_connect] Subscribed to {MQTT_ENV}/test/simple", flush=True)

def on_message(client, userdata, msg):
    print(f"[on_message] {msg.topic}: {msg.payload.decode()[:100]}", flush=True)
    received["ok"] = True

def on_disconnect(client, userdata, rc):
    print(f"[on_disconnect] rc={rc}", flush=True)

print("=== Simple MQTT Test ===", flush=True)
print(f"Broker: {MQTT_HOST}:{MQTT_PORT}", flush=True)

# Create client - NO callback_api_version (defaults to VERSION1)
client = mqtt.Client(client_id="simple-test-v1", protocol=mqtt.MQTTv311)
client.on_connect = on_connect
client.on_message = on_message
client.on_disconnect = on_disconnect

print("Connecting...", flush=True)
try:
    rc = client.connect(MQTT_HOST, MQTT_PORT, 30)
    print(f"connect() returned: {rc}", flush=True)
except Exception as e:
    print(f"connect() EXCEPTION: {e}", flush=True)
    sys.exit(1)

client.loop_start()
print("loop_start() done. Waiting for on_connect...", flush=True)

time.sleep(2)

if not received["ok"]:
    # Check if on_connect fired
    print("on_connect did NOT fire within 2s!", flush=True)
    # Try publishing anyway
    print(f"Publishing test message...", flush=True)
    info = client.publish(f"{MQTT_ENV}/test/simple", '{"hello":"world"}', qos=1)
    print(f"publish() mid: {info.mid}", flush=True)

time.sleep(2)

if received["ok"]:
    print("SUCCESS: Message received!", flush=True)
else:
    print("FAILED: No message received within 4s", flush=True)

client.loop_stop()
client.disconnect()
print("Done", flush=True)
