#!/bin/bash
# ensure-venv.sh — 确保 WSL 原生 .venv 可用（跨 WSL 重启持久化）
# 将 .venv 存储在 WSL 原生文件系统而非 /mnt/d/ 挂载，避免重启后丢失

set -e
VENV_SRC="/mnt/d/zebbingo/projects/resonova/backend/.venv"
VENV_TARGET="/home/administrator/.cache/resonova-venv"

if [ -f "$VENV_SRC/bin/python3" ]; then
    echo "[venv] .venv OK at $VENV_SRC"
    exit 0
fi

echo "[venv] .venv missing or broken at $VENV_SRC"

# Step 1: Try symlink recovery
if [ -L "$VENV_SRC" ] && [ -f "$VENV_TARGET/bin/python3" ]; then
    echo "[venv] symlink broken but target exists — re-linking"
    rm -f "$VENV_SRC"
    ln -s "$VENV_TARGET" "$VENV_SRC"
    echo "[venv] symlink restored"
    exit 0
fi

# Step 2: Move existing .venv to WSL-native if it's on /mnt/
if [ -f "$VENV_SRC/bin/python3" ]; then
    echo "[venv] moving .venv to WSL native filesystem..."
    mkdir -p "$(dirname "$VENV_TARGET")"
    cp -a "$VENV_SRC" "$VENV_TARGET"
    rm -rf "$VENV_SRC"
    ln -s "$VENV_TARGET" "$VENV_SRC"
    echo "[venv] moved and symlinked"
    exit 0
fi

# Step 3: Rebuild from scratch at WSL-native path
echo "[venv] rebuilding .venv at $VENV_TARGET..."
export PATH="$HOME/.local/bin:$PATH"
cd /mnt/d/zebbingo/projects/resonova/backend
rm -rf "$VENV_TARGET" "$VENV_SRC"
uv sync --no-progress 2>&1 | tail -5
# Move to WSL-native if uv created it locally
if [ -f "$VENV_SRC/bin/python3" ]; then
    mkdir -p "$(dirname "$VENV_TARGET")"
    cp -a "$VENV_SRC" "$VENV_TARGET"
    rm -rf "$VENV_SRC"
    ln -s "$VENV_TARGET" "$VENV_SRC"
fi
echo "[venv] .venv ready: $($VENV_SRC/bin/python3 --version 2>&1)"
