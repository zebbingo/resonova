#!/bin/bash
python3 -c "
import json
with open('/mnt/d/zebbingo/projects/stt-test-tool/backend/simulation_history.json') as f:
    data = json.load(f)
items = sorted(data.items(), key=lambda x: x[1].get('started_at',0), reverse=True)[:3]
for sid, d in items:
    print(json.dumps({k:d.get(k) for k in ['session_id','status','send_duration_sec','stt_text','tts_response_count','tts_chunks','reply_text','commands_received','audio_id','error']}, indent=2))
    print('---')
"
