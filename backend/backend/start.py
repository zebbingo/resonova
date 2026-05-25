#!/usr/bin/env python3
"""STT 测试平台后端启动脚本"""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_local_app():
    backend_dir = Path(__file__).resolve().parent
    server_path = backend_dir / "server.py"
    spec = importlib.util.spec_from_file_location("stt_test_tool_backend_server", server_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Failed to load backend server module from {server_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.app


if __name__ == "__main__":
    import uvicorn

    app = _load_local_app()

    # STT 测试平台统一使用 8765 端口
    uvicorn.run(app, host="0.0.0.0", port=8765)
