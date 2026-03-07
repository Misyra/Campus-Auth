#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-.venv/bin/python}"
if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "未找到可用 Python: $PYTHON_BIN"
  echo "请先创建虚拟环境并安装依赖（例如: uv sync）"
  exit 1
fi

echo "开始构建 macOS 可执行程序..."
"$PYTHON_BIN" -m nuitka \
  --standalone \
  --assume-yes-for-downloads \
  --remove-output \
  --output-dir=dist \
  --output-filename=jcu-auto-network \
  --include-package=ensurepip \
  --include-package-data=ensurepip \
  --nofollow-import-to=playwright \
  --nofollow-import-to=playwright.async_api \
  --nofollow-import-to=playwright.sync_api \
  --include-data-dir=frontend=frontend \
  --include-data-file=.env.example=.env.example \
  app.py

echo ""
echo "构建完成:"
echo "  dist/app.dist/jcu-auto-network"
echo ""
echo "说明:"
echo "  1) playwright 未打包，程序首次启动会自动下载安装"
echo "  2) .env 文件请放在可执行文件同目录（可先复制 .env.example）"
