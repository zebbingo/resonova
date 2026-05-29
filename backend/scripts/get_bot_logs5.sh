#!/bin/bash
# Extract lines 5010-5160 (the GSFolAdxd1TG session window)
sed -n '5010,5160p' /tmp/bot_mqtt_start.log 2>/dev/null || echo "File too short, showing last 150 lines:" && tail -150 /tmp/bot_mqtt_start.log
