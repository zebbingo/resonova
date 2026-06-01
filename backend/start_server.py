"""启动脚本：设置 UTF-8 编码后启动 uvicorn"""
import sys
import os

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")
os.environ["PYTHONIOENCODING"] = "utf-8"

import uvicorn
uvicorn.run("server:app", host="0.0.0.0", port=8765, reload=True)
