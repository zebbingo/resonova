#!/bin/bash
echo "=== bot_mqtt (PID 239277) env ==="
cat /proc/239277/environ | tr '\0' '\n' | grep -E 'MQTT_ENV|DEVICE_ID|BROKER|TOY_ID'

echo ""
echo "=== bot_mqtt (PID 101242) env ==="
cat /proc/101242/environ | tr '\0' '\n' | grep -E 'MQTT_ENV|DEVICE_ID|BROKER|TOY_ID'
