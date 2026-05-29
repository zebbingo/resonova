#!/usr/bin/env python3
"""
MQTT Probe — check broker clients, subscriptions, and test message flow
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

rx = []
stop = threading.Event()

def on_msg(c, u, msg):
    rx.append({"t": msg.topic, "p": msg.payload[:300].decode("utf-8","replace"), "ts": time.time()})

def test_broker():
    """Connect, check $SYS info, publish a test message"""
    cid = f"probe-{int(time.time())}"
    c = mqtt.Client(client_id=cid)
    c.on_message = on_msg
    c.connect_timeout = 5
    c.connect(MQTT_HOST, MQTT_PORT, 30)

    # Try $SYS topics (NanoMQ supports these)
    sys_topics = [
        "$SYS/broker/uptime",
        "$SYS/broker/version",
        "$SYS/broker/clients/total",
        "$SYS/broker/clients/connected",
        "$SYS/broker/bytes/received",
        "$SYS/broker/bytes/sent",
    ]
    for t in sys_topics:
        c.subscribe(t, qos=0)

    c.loop_start()
    time.sleep(1)
    c.loop_stop()

    print("=== Broker Info ===")
    for m in rx:
        print(f"  {m['t']}: {m['p']}")

    # Now test message flow — subscribe and publish
    rx.clear()
    test_topic = f"{MQTT_ENV}/probe-test"
    c.subscribe(f"{MQTT_ENV}/#", qos=0)
    c.loop_start()

    print(f"\n=== Publishing to {test_topic} ===")
    c.publish(test_topic, json.dumps({"test": True, "ts": time.time()}))
    time.sleep(0.5)

    print(f"\n=== Checking if we received own message ===")
    own_rx = [m for m in rx if m['t'] == test_topic]
    print(f"  Received own message: {'✓' if own_rx else '✗'}")

    # Check how many unique base topics exist
    topics = set()
    for m in rx:
        parts = m['t'].split('/')
        if len(parts) >= 2:
            topics.add(f"{parts[0]}/{parts[1]}")

    print(f"\n=== Active device topics ({len(topics)}) ===")
    for t in sorted(topics):
        print(f"  {t}")

    print(f"\n=== All captured messages (recent) ===")
    recent = [m for m in rx if time.time() - m['ts'] < 5]
    for m in recent:
        print(f"  {m['t']}: {m['p'][:120]}")

    c.disconnect()

def monitor_for(duration=15):
    """Subscribe to everything and print messages"""
    cid = f"mon-{int(time.time())}"
    c = mqtt.Client(client_id=cid)
    c.on_message = on_msg
    c.connect(MQTT_HOST, MQTT_PORT, 30)
    c.subscribe(f"{MQTT_ENV}/#", qos=0)

    print(f"Monitoring {MQTT_ENV}/# for {duration}s...")
    c.loop_start()
    for i in range(duration):
        time.sleep(1)
        for m in rx:
            age = time.time() - m['ts']
            print(f"  [{age:.1f}s] {m['t']}: {m['p'][:100]}")
        rx.clear()
    c.loop_stop()
    c.disconnect()

if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "broker"
    if action == "broker":
        test_broker()
    elif action == "monitor":
        dur = int(sys.argv[2]) if len(sys.argv) > 2 else 15
        monitor_for(dur)
    elif action == "scan":
        test_broker()
