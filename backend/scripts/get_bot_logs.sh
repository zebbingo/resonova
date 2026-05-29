#!/bin/bash
# Get the latest bot logs for the simulation
grep -n "GSFolAdxd1TG\|How are you today\|intro_guard\|IntroGuard\|TranscriptionFrame.*blocked\|stop_intro_guard\|start_intro_guard" /tmp/bot_mqtt_start.log | tail -50
