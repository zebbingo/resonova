#!/bin/bash
echo "=== Watch log size ==="
wc -l /tmp/bot_mqtt_watch.log 2>/dev/null
echo ""
echo "=== Watch log first 10 lines ==="
head -10 /tmp/bot_mqtt_watch.log 2>/dev/null
echo ""
echo "=== Watch log last 20 lines ==="
tail -20 /tmp/bot_mqtt_watch.log 2>/dev/null
echo ""
echo "=== Any GSFolAdxd1TG in watch log? ==="
grep -c "GSFolAdxd1TG" /tmp/bot_mqtt_watch.log 2>/dev/null
echo ""
echo "=== Check for any errors in start log ==="
grep -c -i "error\|exception\|traceback" /tmp/bot_mqtt_start.log 2>/dev/null
echo ""
echo "=== Get all VAD/eos events from start log (last 100) ==="
grep -n "vadeos\|stt_text\|TranscriptionFrame\|end_response\|start_response\|push_frame\|queue_frame" /tmp/bot_mqtt_start.log | tail -30
