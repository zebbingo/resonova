#!/bin/bash
echo "=== Analysis file lines ==="
wc -l /tmp/analysis_result.txt 2>/dev/null
echo "=== First part ==="
head -20 /tmp/analysis_result.txt 2>/dev/null
