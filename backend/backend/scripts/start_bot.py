#!/usr/bin/env python3
"""Simple script to start bot_mqtt.py and capture errors."""
import subprocess, sys, time

result = subprocess.run(
    ["cd", "/home/administrator/projects/chatbot/src", "&&",
     "../.venv/bin/python", "bot_mqtt.py"],
    shell=True,
    capture_output=True,
    text=True,
    timeout=60,
)
if result.returncode != 0:
    print("STDERR:", result.stderr[-2000:])
    print("STDOUT:", result.stdout[-1000:])
    sys.exit(1)
else:
    print("bot_mqtt started OK")
