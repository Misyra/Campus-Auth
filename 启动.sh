#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

PY_DIR="$ROOT_DIR/.jcu_python"
PY_EXE="$PY_DIR/bin/python3"

export PIP_INDEX_URL="${PIP_INDEX_URL:-https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple}"
export PLAYWRIGHT_DOWNLOAD_HOST="${PLAYWRIGHT_DOWNLOAD_HOST:-https://npmmirror.com/mirrors/playwright}"
export JCU_PROJECT_ROOT="$ROOT_DIR"
export JCU_ENV_FILE="$ROOT_DIR/.env"
export JCU_AUTO_OPEN_BROWSER="${JCU_AUTO_OPEN_BROWSER:-true}"

echo "[1/5] Preparing local Python runtime..."
if [[ ! -x "$PY_EXE" ]]; then
  python3 -m venv "$PY_DIR"
fi

echo "[2/5] Installing Python dependencies..."
"$PY_EXE" -m pip install --upgrade pip --disable-pip-version-check --no-warn-script-location
"$PY_EXE" -m pip install --upgrade --disable-pip-version-check --no-warn-script-location -r "$ROOT_DIR/requirements.txt"

echo "[3/5] Installing Playwright Chromium..."
"$PY_EXE" -m playwright install chromium

echo "[4/5] Starting web app..."
exec "$PY_EXE" "$ROOT_DIR/app.py"
