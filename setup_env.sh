#!/usr/bin/env bash
# Campus-Auth 环境安装脚本（macOS / Linux）
# 复用 launcher.py 的 uv 下载逻辑，不重复实现
set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"

# 如果系统没有 uv 且没有 Python 3，提示手动安装
if ! command -v uv &>/dev/null; then
    if command -v python3 &>/dev/null; then
        python3 "$PROJECT_ROOT/launcher.py"
        exit $?
    else
        echo "错误：未找到 uv 和 python3。请先安装其中之一："
        echo "  uv:     https://docs.astral.sh/uv/getting-started/installation/"
        echo "  python: https://www.python.org/downloads/"
        exit 1
    fi
fi

# 系统已有 uv，直接用
cd "$PROJECT_ROOT"
uv sync
uv run playwright install chromium
echo "环境准备完成。启动：uv run main.py"
