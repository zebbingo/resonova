import json
from collections import Counter

capture_file = "/tmp/mqtt_capture.jsonl"
with open(capture_file) as f:
    lines = f.readlines()

print("Total: %d msgs" % len(lines))

# Categorize messages by type
cats = Counter()
sessions = set()

for line in lines:
    d = json.loads(line.strip())
    topic = d.get("topic", "")
    parts = topic.split("/")
    # Get the action part (last meaningful segment)
    for i, p in enumerate(parts):
        if p == "audio" and i+2 < len(parts):
            sessions.add(parts[i+1])
            cats["audio/" + parts[i+2] + "/" + parts[-1]] += 1
            break
        elif p == "session" and i+2 < len(parts):
            sessions.add(parts[i+1])
            cats["session/" + parts[-1]] += 1
            break
        elif p == "meta":
            cats["meta/" + parts[-1]] += 1
            break

print("Categories:")
for t, c in cats.most_common():
    print("  %s: %d" % (t, c))

print("Sessions: %s" % ", ".join(sorted(sessions)))
