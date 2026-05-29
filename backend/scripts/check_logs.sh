#!/bin/bash
echo "=== Server log (last 50 lines) ==="
tail -50 /tmp/srv8765.log 2>/dev/null || echo "No server log found"
echo ""
echo "=== Simulation state ==="
cd /mnt/d/zebbingo/projects/stt-test-tool/backend
python3 -c "
import json
with open('simulation_history.json') as f:
    data = json.load(f)
items = sorted(data.items(), key=lambda x: x[1].get('started_at',0), reverse=True)[:3]
for sid, d in items:
    print(f\"  {sid}: status={d.get('status')} dur={d.get('send_duration_sec')} tts_chunks={d.get('tts_chunks')} tts_resp={d.get('tts_response_count')} stt={d.get('stt_text','')[:50]}\")
"
