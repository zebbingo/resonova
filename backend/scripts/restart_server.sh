#!/bin/bash
PORT=8765
LOG=/tmp/srv8765.log
DIR=/mnt/d/zebbingo/projects/stt-test-tool/backend

rm -f "$LOG"
cd "$DIR"
nohup .venv/bin/python server.py --port $PORT >> "$LOG" 2>&1 &
echo "Server PID=$!"
sleep 2
ss -tlnp 2>/dev/null | grep $PORT && echo "READY" || echo "NOT_READY"
