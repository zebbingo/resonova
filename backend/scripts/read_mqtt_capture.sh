#!/bin/bash
# Check what MQTT capture files exist and their content
echo "=== MQTT capture files ==="
ls -la /tmp/mqtt_capture*.jsonl 2>/dev/null

echo ""
echo "=== mqtt_capture3.jsonl ==="
if [ -f /tmp/mqtt_capture3.jsonl ]; then
    echo "Lines: $(wc -l < /tmp/mqtt_capture3.jsonl)"
    echo "Topics:"
    python3 -c "
import json,sys
from collections import Counter
topics=Counter()
with open('/tmp/mqtt_capture3.jsonl') as f:
    for line in f:
        try:
            d=json.loads(line)
            t='/'.join(d.get('topic','').split('/')[-4:])
            topics[t]+=1
        except: pass
for t,c in topics.most_common():
    print(f'  .../{t}: {c}')
"
fi
