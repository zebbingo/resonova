#!/usr/bin/env python3
"""Sync server.py and mqtt_bridge.py to WSL."""
import shutil, sys

files = [
    (r"d:\zebbingo\projects\stt-test-tool\backend\server.py",
     r"\\wsl$\Ubuntu\home\administrator\projects\stt-test-tool\backend\server.py"),
    (r"d:\zebbingo\projects\stt-test-tool\backend\mqtt_bridge.py",
     r"\\wsl$\Ubuntu\home\administrator\projects\stt-test-tool\backend\mqtt_bridge.py"),
]

for src, dst in files:
    shutil.copy2(src, dst)
    size = shutil.os.path.getsize(dst)
    print(f"Copied {src} -> {dst} ({size} bytes)")

print("Done")
