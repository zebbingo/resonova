#!/bin/bash
# Get ALL pipeline-related logs near the session time
echo "=== GSFolAdxd1TG session logs ==="
grep -n "GSFolAdxd1TG" /tmp/bot_mqtt_start.log | head -40

echo ""
echo "=== VAD / stt / turn events ==="
grep -n "VAD\|stt_text\|transcri\|UserStarted\|UserStopped\|turn_start\|turn.*start\|turn.*eos" /tmp/bot_mqtt_start.log | awk -F: '{ if ($1+0 >= 5100 && $1+0 <= 5300) print }'
