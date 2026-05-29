#!/bin/bash
# Simple topic count from capture
python3 -c "
import json
from collections import Counter
c=Counter()
with open('/tmp/mqtt_capture.jsonl') as f:
    for line in f:
        try:
            t=json.loads(line).get('topic','')
            short='/'.join(t.split('/')[-3:])
            c[short]+=1
        except:
            pass
for t,cnt in c.most_common(30):
    print(t,cnt,sep='=')
" 2>&1 | head -30
