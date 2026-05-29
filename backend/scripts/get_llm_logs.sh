#!/bin/bash
# Search for LLM and StudioAIService related logs near the session time
echo "=== LLM responses near 13:22 ==="
grep -n "start_response\|end_response\|user_text\|LLM.*response\|StudioAI.*response\|llm_inference\|tts_synthesis\|publish_audio.*start" /tmp/bot_mqtt_start.log | awk -F: '{ if ($1+0 >= 4980 && $1+0 <= 5200) print }'
