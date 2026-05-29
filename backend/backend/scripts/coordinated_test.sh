#!/bin/bash
# Coordinated test: capture MQTT + trigger simulation
cd /mnt/d/zebbingo/projects/stt-test-tool/backend || exit 1

SCRIPT_DIR="/mnt/d/zebbingo/projects/stt-test-tool/backend/scripts"
CAPTURE_FILE="/tmp/mqtt_capture.jsonl"

# Clear previous capture
rm -f "$CAPTURE_FILE"

echo "[TEST] Checking server health..."
curl -s -o /dev/null -w "%{http_code}" http://localhost:8765/api/device/list
echo ""

echo "[TEST] Starting MQTT capture..."
source .venv/bin/activate
python "$SCRIPT_DIR/mqtt_capture.py" &
CAPTURE_PID=$!
echo "[TEST] Capture PID: $CAPTURE_PID"

sleep 3

echo "[TEST] Triggering simulation..."
SIM_RESPONSE=$(curl -s -X POST http://localhost:8765/api/device/simulate \
  -H "Content-Type: application/json" \
  -d '{"device_id":"sim-dev-002","figurine_id":"doctor","mode":"dialogue","audio_id":"conv-01","subscribe_response":true}')
SIM_STATUS=$(echo "$SIM_RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status','?'))" 2>/dev/null || echo "parse_error")
SIM_SESSION=$(echo "$SIM_RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('session_id','?'))" 2>/dev/null || echo "parse_error")
echo "[TEST] Simulate response: status=$SIM_STATUS session=$SIM_SESSION"
echo "[TEST] Full response: $SIM_RESPONSE"

echo "[TEST] Waiting 55s for MQTT traffic + simulation..."
sleep 55

echo "[TEST] Killing capture..."
kill $CAPTURE_PID 2>/dev/null
wait $CAPTURE_PID 2>/dev/null

echo "=== RESULTS ==="
if [ -f "$CAPTURE_FILE" ]; then
    COUNT=$(wc -l < "$CAPTURE_FILE")
    echo "Messages captured: $COUNT"
    echo "--- All messages ---"
    cat "$CAPTURE_FILE" | python3 -c "
import sys, json
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        d = json.loads(line)
        r = 'R' if d.get('retain') else ' '
        print(f\"  [{r}] {d['topic']} -> {d['payload'][:120]}\")
    except:
        pass
"
else:
    echo "No capture file found!"
fi

echo "[TEST] Done"
