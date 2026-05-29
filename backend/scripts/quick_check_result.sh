#!/bin/bash
# Check latest simulation result
python3 -c "
import json
with open('/mnt/d/zebbingo/projects/stt-test-tool/backend/simulation_history.json') as f:
    data = json.load(f)
items = sorted(data.items(), key=lambda x: x[1].get('started_at',0), reverse=True)[:2]
for sid, d in items:
    print(f'Session: {sid}')
    print(f'  status={d.get(\"status\")} send_dur={d.get(\"send_duration_sec\")}')
    print(f'  stt=\"{d.get(\"stt_text\",\"\")[:60]}\"')
    print(f'  tts_count={d.get(\"tts_response_count\")} tts_chunks={d.get(\"tts_chunks\")}')
    print(f'  reply=\"{d.get(\"reply_text\",\"\")[:60]}\"')
    print(f'  commands={d.get(\"commands_received\")}')
"
echo "---"
echo "MQTT capture file size:"
ls -lh /tmp/mqtt_capture3.jsonl 2>/dev/null || echo "no capture file"
