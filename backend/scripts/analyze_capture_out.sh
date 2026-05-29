#!/bin/bash
cd /mnt/d/zebbingo/projects/stt-test-tool/backend/scripts
python3 analyze_capture.py > /tmp/analysis_result.txt 2>&1
cat /tmp/analysis_result.txt
