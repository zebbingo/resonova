#!/bin/bash
# Simple check - just get the last session from history
python3 << 'PYEOF'
import json
with open('/mnt/d/zebbingo/projects/stt-test-tool/backend/simulation_history.json') as f:
    data = json.load(f)
items = sorted(data.items(), key=lambda x: x[1].get('started_at',0), reverse=True)
for sid, d in items[:1]:
    print("Session:", sid)
    print("  status:", d.get("status"))
    print("  send_dur:", d.get("send_duration_sec"))
    print("  stt:", d.get("stt_text","")[:60])
    print("  tts_count:", d.get("tts_response_count"))
    print("  tts_chunks:", d.get("tts_chunks"))
    print("  reply:", d.get("reply_text","")[:60])
    print("  commands:", d.get("commands_received"))
    print("  audio_id:", d.get("audio_id"))
    print("  error:", d.get("error",""))
PYEOF
