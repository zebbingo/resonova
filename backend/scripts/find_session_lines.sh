#!/bin/bash
# Find the line numbers for the GSFolAdxd1TG session in the log
echo "=== Session GSFolAdxd1TG first and last occurrences ==="
grep -n "GSFolAdxd1TG" /tmp/bot_mqtt_start.log | head -3
echo "---"
grep -n "GSFolAdxd1TG" /tmp/bot_mqtt_start.log | tail -3

echo ""
echo "=== Total lines in log ==="
wc -l /tmp/bot_mqtt_start.log
