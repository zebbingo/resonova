#!/bin/bash
wc -l /tmp/analysis_result.txt 2>/dev/null && echo "---" && head -5 /tmp/analysis_result.txt && echo "..." && tail -10 /tmp/analysis_result.txt
