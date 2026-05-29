#!/bin/bash
# Analyze the MQTT capture file in detail
python3 << 'PYEOF'
import json
from collections import Counter

capture_file = "/tmp/mqtt_capture.jsonl"
try:
    with open(capture_file) as f:
        lines = f.readlines()
except FileNotFoundError:
    print("Capture file not found")
    exit(1)

print(f"Total messages: {len(lines)}")

# Parse all messages
msgs = []
for line in lines:
    try:
        d = json.loads(line.strip())
        msgs.append(d)
    except:
        pass

# Count by full topic
topic_counter = Counter()
for d in msgs:
    topic_counter[d.get("topic", "unknown")] += 1

# Show summary grouped by session
for t, c in topic_counter.most_common():
    short = "/".join(t.split("/")[2:])  # remove env/device_id prefix
    print(f"  .../{short}: {c}")

print()
# Find session IDs mentioned
sessions = set()
for d in msgs:
    topic = d.get("topic", "")
    parts = topic.split("/")
    for i, p in enumerate(parts):
        if p == "session" and i+1 < len(parts):
            sessions.add(parts[i+1])
        if p == "audio" and i+1 < len(parts):
            sessions.add(parts[i+1])

print(f"Sessions found: {sessions}")

# For each session, show the message timeline
for sid in sorted(sessions):
    print(f"\n=== Session {sid} ===")
    session_msgs = [(d["ts"] if "ts" in d else 0, d.get("topic","")) for d in msgs if sid in d.get("topic","")]
    session_msgs.sort()
    for ts, topic in session_msgs:
        short = "/".join(topic.split("/")[3:])
        print(f"  {short}")

PYEOF
