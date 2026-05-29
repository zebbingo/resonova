#!/bin/bash
# Launch simulation in background, fully detached
PAYLOAD=/mnt/d/zebbingo/projects/stt-test-tool/backend/sim_payload.json
URL=http://localhost:8765/api/device/simulate
OUT=/tmp/sim_result2.json
ERR=/tmp/sim_err2.txt

curl -s --max-time 300 -X POST "$URL" \
  -d @"$PAYLOAD" \
  -H 'Content-Type: application/json' \
  > "$OUT" 2>"$ERR" &

CURL_PID=$!
echo "Launched curl PID=$CURL_PID"
disown
