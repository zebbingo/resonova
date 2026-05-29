#!/bin/bash
# Find all bot_mqtt log files
echo "=== All log files ==="
find /tmp -name "bot_mqtt*" -o -name "bot_mqtt*.log*" 2>/dev/null | sort

echo ""
echo "=== Any files with GSFolAdxd1TG ==="
grep -l "GSFolAdxd1TG" /tmp/* 2>/dev/null

echo ""
echo "=== Chatbot user-facing logs ==="
find /home/administrator/projects/chatbot -name "*.log" -newer /tmp/bot_mqtt_start.log 2>/dev/null | head -10
find /home/administrator/projects/chatbot -name "logs" -type d 2>/dev/null

echo ""
echo "=== bot_mqtt_start.log last 3 lines ==="
tail -3 /tmp/bot_mqtt_start.log
