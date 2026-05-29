import json
from collections import Counter

capture_file = "/tmp/mqtt_capture.jsonl"
with open(capture_file) as f:
    lines = f.readlines()

print("Total messages: %d" % len(lines))

topic_counter = Counter()
for line in lines:
    try:
        d = json.loads(line.strip())
        topic_counter[d.get("topic", "unknown")] += 1
    except:
        pass

for t, c in topic_counter.most_common():
    short = t.split("development/")[-1] if "development/" in t else t
    print("  %s: %d" % (short, c))

# Find sessions
sessions = set()
for line in lines:
    try:
        d = json.loads(line.strip())
        topic = d.get("topic", "")
        parts = topic.split("/")
        for i, p in enumerate(parts):
            if p in ("session", "audio") and i+1 < len(parts):
                sessions.add(parts[i+1])
    except:
        pass

print("\nSessions found: %s" % (", ".join(sorted(sessions))))
