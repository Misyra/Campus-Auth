#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

export UV_INDEX_URL="${UV_INDEX_URL:-https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple}"
export PLAYWRIGHT_DOWNLOAD_HOST="${PLAYWRIGHT_DOWNLOAD_HOST:-https://npmmirror.com/mirrors/playwright}"
export JCU_PROJECT_ROOT="$ROOT_DIR"
export JCU_ENV_FILE="$ROOT_DIR/.env"
export JCU_AUTO_OPEN_BROWSER="${JCU_AUTO_OPEN_BROWSER:-true}"

if command -v uv >/dev/null 2>&1; then
  UV_BIN="uv"
  echo "[1/4] Using uv from PATH..."
else
  echo "[1/4] Installing uv..."
  export UV_UNMANAGED_INSTALL="$ROOT_DIR/.uv"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  UV_BIN="$UV_UNMANAGED_INSTALL/bin/uv"
  if [[ ! -x "$UV_BIN" ]]; then
    echo "Failed to install uv."
    exit 1
  fi
fi

echo "[2/4] Syncing dependencies with mirror..."
"$UV_BIN" sync

echo "[3/4] Installing Playwright Chromium..."
"$UV_BIN" run playwright install chromium

echo "[4/4] Starting web app..."
exec "$UV_BIN" run app.py
