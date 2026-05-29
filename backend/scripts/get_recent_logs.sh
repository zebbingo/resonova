#!/bin/bash
# Get recent bot_mqtt logs - search for intro guard and session patterns
grep -n -i "intro_guard\|intro_playing\|stop_intro_guard\|start_intro_guard\|blocked.*Transcription\|Transcription.*blocked\|drain.*pending\|pending.*VAD" /tmp/bot_mqtt_start.log | tail -30
