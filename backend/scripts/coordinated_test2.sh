#!/bin/bash
# Coordinated test v2: capture MQTT + trigger simulation with valid audio_id
cd /mnt/d/zebbingo/projects/stt-test-tool/backend || exit 1

SCRIPT_DIR="/mnt/d/zebbingo/projects/stt-test-tool/backend/scripts"
CAPTURE_FILE="/tmp/mqtt_capture2.jsonl"

rm -f "$CAPTURE_FILE"

echo "[TEST] Server health check..."
curl -s -o /dev/null -w "HTTP %{http_code}\n" http://localhost:8765/api/device/list

echo "[TEST] Starting MQTT capture..."
source .venv/bin/activate
python "$SCRIPT_DIR/mqtt_capture.py" &
CAPTURE_PID=$!
sleep 3

echo "[TEST] Triggering simulation with audio_id=117..."
SIM_RESPONSE=$(curl -s -X POST http://localhost:8765/api/device/simulate \
  -H "Content-Type: application/json" \
  -d '{"device_id":"sim-dev-002","figurine_id":"doctor","mode":"dialogue","audio_id":"117","subscribe_response":true}')
echo "[TEST] Simulate response: $SIM_RESPONSE"

echo "[TEST] Waiting 65s for MQTT traffic + simulation..."
sleep 65

echo "[TEST] Killing capture..."
kill $CAPTURE_PID 2>/dev/null
wait $CAPTURE_PID 2>/dev/null

echo "=== RESULTS ==="
if [ -f "$CAPTURE_FILE" ]; then
    COUNT=$(wc -l < "$CAPTURE_FILE")
    echo "Messages captured: $COUNT"
    echo "--- All messages ---"
    python3 -c "
import json, sys
with open('$CAPTURE_FILE') as f:
    for line in f:
        line = line.strip()
        if not line: continue
        d = json.loads(line)
        r = 'R' if d.get('retain') else ' '
        print(f\"  [{r}] {d['topic']} -> {d['payload'][:150]}\")
"
else
    echo "No capture file found!"
fi

# Check simulation result
echo "--- Simulation history (last 2) ---"
python3 -c "
import json
try:
    with open('simulation_history.json') as f:
        data = json.load(f)
    items = sorted(data.items(), key=lambda x: x[1].get('started_at',0), reverse=True)[:2]
    for sid, d in items:
        print(f\"  {sid}: status={d.get('status')} audio={d.get('audio_id')} text={d.get('stt_text','')[:60]} reply={d.get('reply_text','')[:60]} tts_chunks={d.get('tts_chunks')} tts_responses={d.get('tts_response_count')}\")
except: pass
"

echo "[TEST] Done"
