#!/bin/bash
# Get ALL intro guard related entries
echo "=== start_intro_guard ==="
grep -n "start_intro_guard" /tmp/bot_mqtt_start.log
echo ""
echo "=== stop_intro_guard ==="
grep -n "stop_intro_guard" /tmp/bot_mqtt_start.log
echo ""
echo "=== blocked (DEBUG) ==="
grep -n "blocked" /tmp/bot_mqtt_start.log | head -10
echo ""
echo "=== Intro guard ENABLED ==="
grep -n "Intro guard ENABLED" /tmp/bot_mqtt_start.log
echo ""
echo "=== Intro guard DISABLED ==="
grep -n "Intro guard DISABLED" /tmp/bot_mqtt_start.log
