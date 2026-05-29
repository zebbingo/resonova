#!/bin/bash
# Coordinated test #3 - Full pipeline test with MQTT monitoring
SRV_LOG=/tmp/srv8765.log
MQTT_CAPTURE=/tmp/mqtt_capture3.jsonl
SIM_HISTORY=/mnt/d/zebbingo/projects/stt-test-tool/backend/simulation_history.json

echo "[TEST] $(date '+%H:%M:%S') Starting coordinated test #3"

# 1. Check server health
echo "[TEST] Server health check..."
curl -s -o /dev/null -w "HTTP %{http_code}\n" http://localhost:8765/api/health

# 2. Start MQTT capture in background
echo "[TEST] Starting MQTT capture..."
python3 /mnt/d/zebbingo/projects/stt-test-tool/backend/scripts/mqtt_capture.py "$MQTT_CAPTURE" &
MQTT_PID=$!
sleep 2

# 3. Check capture is running
if kill -0 $MQTT_PID 2>/dev/null; then
    echo "[MON] MQTT capture running (PID $MQTT_PID)"
else
    echo "[MON] MQTT capture failed to start!"
fi

# 4. Trigger simulation
echo "[TEST] Triggering simulation with audio_id=117..."
curl -s -X POST http://localhost:8765/api/device/simulate \
  -H 'Content-Type: application/json' \
  -d '{"device_id":"sim-dev-002","audio_id":"117","figurine_id":"doctor","subscribe_response":true}' | python3 -m json.tool

# 5. Wait for simulation to complete
echo "[TEST] Waiting 40s for simulation..."
sleep 40

# 6. Get simulation result
echo "[TEST] Latest simulation entry:"
python3 -c "
import json
with open('$SIM_HISTORY') as f:
    data = json.load(f)
items = sorted(data.items(), key=lambda x: x[1].get('started_at',0), reverse=True)[:1]
for sid, d in items:
    print(f'Session: {sid}')
    print(f'  status={d.get(\"status\")} send_dur={d.get(\"send_duration_sec\")}')
    print(f'  stt=\"{d.get(\"stt_text\",\"\")[:80]}\"')
    print(f'  tts_count={d.get(\"tts_response_count\")} tts_chunks={d.get(\"tts_chunks\")}')
    print(f'  reply=\"{d.get(\"reply_text\",\"\")[:80]}\"')
    print(f'  commands={d.get(\"commands_received\")}')
"

# 7. Show captured MQTT topics (summary)
echo ""
echo "[TEST] MQTT capture summary:"
if [ -f "$MQTT_CAPTURE" ]; then
    echo "  Total messages: $(wc -l < $MQTT_CAPTURE)"
    echo "  Topics:"
    cat "$MQTT_CAPTURE" | python3 -c "
import json,sys
topics={}
for line in sys.stdin:
    try:
        d=json.loads(line)
        t=d.get('topic','')
        short='/'.join(t.split('/')[-3:]) if len(t.split('/'))>=3 else t
        topics[short]=topics.get(short,0)+1
    except: pass
for t,c in sorted(topics.items()):
    print(f'    {t}: {c}')
" 2>/dev/null
    echo ""
    echo "[TEST] Full capture file: $MQTT_CAPTURE ($(du -h $MQTT_CAPTURE | cut -f1))"
else
    echo "  No capture file found"
fi

# 8. Stop MQTT capture
kill $MQTT_PID 2>/dev/null
wait $MQTT_PID 2>/dev/null
echo "[TEST] $(date '+%H:%M:%S') Test complete"
