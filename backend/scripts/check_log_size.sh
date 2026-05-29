#!/bin/bash
# Check the log file size and count
echo "=== Log file info ==="
wc -l /tmp/bot_mqtt_start.log
ls -lh /tmp/bot_mqtt_start.log

echo ""
echo "=== Last 5 lines ==="
tail -5 /tmp/bot_mqtt_start.log

echo ""
echo "=== First 5 lines ==="
head -5 /tmp/bot_mqtt_start.log

echo ""
echo "=== Any rotated logs? ==="
ls -la /tmp/bot_mqtt*.log* 2>/dev/null
