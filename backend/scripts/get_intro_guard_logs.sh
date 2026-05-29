#!/bin/bash
# Search for intro guard related logs near the session time (13:22-13:23)
grep -n "intro_guard\|IntroGuard\|stop_intro_guard\|start_intro_guard\|Intro.*blocked\|TranscriptionFrame" /tmp/bot_mqtt_start.log | awk -F: '$2 >= 5010 && $2 <= 6000' | head -30
