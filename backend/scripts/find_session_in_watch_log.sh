#!/bin/bash
echo "=== watch log has GSFolAdxd1TG? ==="
grep -c "GSFolAdxd1TG" /tmp/bot_mqtt_watch.log 2>/dev/null || echo "no"
echo "lines:"
wc -l /tmp/bot_mqtt_watch.log 2>/dev/null

echo ""
echo "=== start log more session context ==="
# Get the lines around session (5010-5190)
sed -n '5010,5190p' /tmp/bot_mqtt_start.log 2>/dev/null
