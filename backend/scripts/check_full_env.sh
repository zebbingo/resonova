#!/bin/bash
# Check chatbot logs and environment
echo "=== bot_mqtt log file ==="
ls -la /tmp/bot_mqtt*.log 2>/dev/null || echo "No bot_mqtt log files in /tmp"

echo ""
echo "=== Check logs dir ==="
ls -la /home/administrator/projects/chatbot/logs/ 2>/dev/null || echo "No logs dir"

echo ""
echo "=== bot_mqtt process env ==="
cat /proc/239277/environ 2>/dev/null | tr '\0' '\n' | head -30

echo ""
echo "=== bot_mqtt process env ==="
cat /proc/101242/environ 2>/dev/null | tr '\0' '\n' | head -30
