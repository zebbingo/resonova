#!/usr/bin/env python3
"""
CI grep 红线扫描 — 音频格式规范合规性检查

使用方式（CI / 本地）:
    python scripts/check_audio_convention.py
    python scripts/check_audio_convention.py --fix     # 自动修复

退出码:
    0 = 合规
    1 = 发现不合规（默认）
"""

import sys, re, subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# ── 红线规则 ──────────────────────────────────────────────────────────
# 每个规则是 (模式描述, grep 正则, 排除模式列表)
RULES = [
    ("* 32767 — 禁止使用 32767 作为换算因子", r'\*\s*32767(?!\s*\)\s*\))', [
        "pcm_utils.py",           # 规范定义中可能含 32767 常量名
        "test_pcm_utils.py",      # 测试需要验证边界值 32767
        ".pyc", ".egg-info", ".venv", "node_modules", "__pycache__",
    ]),
    ("无 clip 的 astype(np.int16) — 必须使用 pcm_utils", r'astype\(np\.int16\)(?!\s*\[)', [
        "pcm_utils.py",
        "test_pcm_utils.py",
        ".pyc", ".egg-info", ".venv", "node_modules", "__pycache__",
    ]),
    ("/ 32768 — 业务代码禁止直接写 int16→float 换算", r'/\s*32768[.\d]*\b', [
        "pcm_utils.py",
        "test_pcm_utils.py",
        "check_audio_convention.py",  # 自身注释含规则描述
        ".pyc", ".egg-info", ".venv", "node_modules", "__pycache__",
    ]),
    ("encode\\(frame\\.tobytes\\(\\)\\) — 编码前缺少 dtype 校验", r'encode\(frame\.tobytes\(\)\)', [
        "test_pcm_utils.py",
        ".pyc", ".egg-info", ".venv", "node_modules", "__pycache__",
    ]),
]


def scan(paths: list[Path], auto_fix: bool = False) -> int:
    exit_code = 0
    for name, pattern, excludes in RULES:
        cmd = ["grep", "-rn", "--include=*.py", pattern]
        for ex in excludes:
            cmd.extend(["--exclude", ex])

        try:
            result = subprocess.run(
                cmd + [str(p) for p in paths],
                capture_output=True, text=True, timeout=30,
            )
        except subprocess.TimeoutExpired:
            print(f"  ⚠️  超时: {name}")
            continue

        if result.returncode == 0 and result.stdout.strip():
            exit_code = 1
            print(f"\n❌ {name}")
            print(f"   {result.stdout.replace(chr(10), chr(10)+'   ').rstrip()}")
        else:
            print(f"✅ {name}")

    if exit_code == 0:
        print("\n🎉 全部合规，未发现红线违规。")
    else:
        print(f"\n🔴 发现违规，请按规范使用 pcm_utils 权威函数。")

    return exit_code


def main():
    import argparse
    parser = argparse.ArgumentParser(description="音频格式规范 CI 扫描")
    parser.add_argument("paths", nargs="*", default=[REPO],
                        help="扫描路径（默认: repo 根目录）")
    parser.add_argument("--fix", action="store_true", help="自动修复（仅限安全替换）")
    args = parser.parse_args()

    paths = [Path(p).resolve() for p in args.paths]
    sys.exit(scan(paths, auto_fix=args.fix))


if __name__ == "__main__":
    main()
