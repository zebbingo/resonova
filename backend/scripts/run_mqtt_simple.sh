#!/bin/bash
cd /mnt/d/zebbingo/projects/stt-test-tool/backend || exit 1
source .venv/bin/activate || exit 1
python scripts/mqtt_simple_test.py
