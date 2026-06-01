@echo off
cd /d "D:\zebbingo\projects\resonova\backend"
set PYTHONIOENCODING=utf-8
start /B /MIN "VoicePipe Server" uv run python start_server.py > server_output.log 2>&1
