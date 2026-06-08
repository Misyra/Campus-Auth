#!/usr/bin/env bash
# Campus-Auth 启动脚本（macOS / Linux）
# 用法: ./start.sh [参数]
#   --install-only  仅安装环境，不启动应用
set -euo pipefail

# ── 常量 ──────────────────────────────────────────────────
PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
UV_DIR="$PROJECT_ROOT/.uv"
UV_VERSION="0.7.3"
MIRRORS=(
    "https://ghfast.top/"
    "https://gh-proxy.com/"
    "https://ghproxy.net/"
    ""  # GitHub 官方源
)

# ── 检测平台和文件名 ──────────────────────────────────────
_detect_uv_filename() {
    local system arch
    system="$(uname -s)"
    arch="$(uname -m)"

    case "$system" in
        Darwin)
            if [[ "$arch" == "arm64" ]]; then
                echo "uv-aarch64-apple-darwin.tar.gz"
            else
                echo "uv-x86_64-apple-darwin.tar.gz"
            fi
            ;;
        Linux)
            if [[ "$arch" == "aarch64" || "$arch" == "arm64" ]]; then
                echo "uv-aarch64-unknown-linux-gnu.tar.gz"
            else
                echo "uv-x86_64-unknown-linux-gnu.tar.gz"
            fi
            ;;
        *)
            echo "[X] 不支持的系统: $system" >&2
            exit 1
            ;;
    esac
}

# ── 下载 uv ──────────────────────────────────────────────
_download_uv() {
    local filename="$1"
    local github_url="https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/${filename}"

    mkdir -p "$UV_DIR"
    local archive="$UV_DIR/uv.tar.gz"
    local success=0

    for mirror in "${MIRRORS[@]}"; do
        local url="${mirror}${github_url}"
        if [[ -z "$mirror" ]]; then
            echo "  尝试: GitHub 官方" >&2
        else
            echo "  尝试: ${mirror}" >&2
        fi
        if curl -fsSL --connect-timeout 10 --max-time 120 -o "$archive" "$url" 2>/dev/null; then
            if tar -tzf "$archive" &>/dev/null; then
                success=1
                break
            else
                echo "  [!] 文件无效，尝试下一个源..." >&2
                rm -f "$archive"
            fi
        fi
    done

    if [[ "$success" -eq 0 ]]; then
        echo "[X] 所有下载源均失败" >&2
        echo "    请手动安装 uv: https://docs.astral.sh/uv/" >&2
        exit 1
    fi

    echo "正在解压..." >&2
    tar -xzf "$archive" -C "$UV_DIR"
    rm -f "$archive"

    # uv 解压后可能在子目录，找到并移到 UV_DIR
    if [[ ! -f "$UV_DIR/uv" ]]; then
        local found
        found=$(find "$UV_DIR" -name "uv" -type f | head -1)
        if [[ -n "$found" ]]; then
            mv "$found" "$UV_DIR/uv"
        fi
    fi

    chmod +x "$UV_DIR/uv"
    echo "[OK] uv 下载完成" >&2
}

# ── 查找 uv ──────────────────────────────────────────────
_find_uv() {
    if command -v uv &>/dev/null; then
        echo "uv"
        return
    fi

    if [[ -x "$UV_DIR/uv" ]]; then
        echo "$UV_DIR/uv"
        return
    fi

    echo "正在下载 uv ${UV_VERSION}..." >&2
    local filename
    filename="$(_detect_uv_filename)"
    _download_uv "$filename"
    echo "$UV_DIR/uv"
}

# ── 主流程 ───────────────────────────────────────────────
UV_CMD="$(_find_uv)"
echo "使用 uv: $UV_CMD"

cd "$PROJECT_ROOT"

echo "[1/3] 安装依赖..."
$UV_CMD sync

echo "[2/3] 安装 Playwright Chromium..."
$UV_CMD run playwright install chromium || {
    echo "[!] Playwright 安装失败，如已安装可忽略"
    echo "    手动运行: uv run playwright install chromium"
}

# 检查 --install-only 参数
for arg in "$@"; do
    if [[ "$arg" == "--install-only" ]]; then
        echo "[OK] 环境准备完成"
        exit 0
    fi
done

echo "[3/3] 启动 Campus-Auth..."
exec "$UV_CMD" run main.py "$@"
