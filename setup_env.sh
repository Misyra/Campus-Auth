#!/usr/bin/env bash
# Campus-Auth 环境安装脚本（macOS / Linux）
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
UV_DIR="$PROJECT_ROOT/.uv"
UV_VERSION="0.7.3"

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
            echo "错误：不支持的系统 $system" >&2
            exit 1
            ;;
    esac
}

# ── 下载 uv ──────────────────────────────────────────────

_download_uv() {
    local filename="$1"
    local github_url="https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/${filename}"
    local mirrors=(
        "https://ghfast.top/"
        "https://gh-proxy.com/"
        "https://ghproxy.net/"
    )

    mkdir -p "$UV_DIR"
    local archive="$UV_DIR/uv.tar.gz"

    # 尝试镜像站
    for mirror in "${mirrors[@]}"; do
        local url="${mirror}${github_url}"
        echo "  尝试: ${mirror}" >&2
        if curl -fsSL --connect-timeout 10 --max-time 120 -o "$archive" "$url" 2>/dev/null; then
            goto_extract=0
            break
        fi
    done

    # 回退到 GitHub
    if [[ ! -f "$archive" ]]; then
        echo "  尝试: GitHub 直连" >&2
        if ! curl -fsSL --connect-timeout 10 --max-time 120 -o "$archive" "$github_url"; then
            echo "错误：所有下载源均失败" >&2
            echo "请手动安装 uv: https://docs.astral.sh/uv/" >&2
            exit 1
        fi
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
    echo "uv 下载完成" >&2
}

# ── 查找 uv ──────────────────────────────────────────────

_find_uv() {
    # 1. 系统 PATH
    if command -v uv &>/dev/null; then
        echo "uv"
        return
    fi

    # 2. 本地目录
    if [[ -x "$UV_DIR/uv" ]]; then
        echo "$UV_DIR/uv"
        return
    fi

    # 3. 下载（提示信息输出到 stderr）
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

echo ""
echo "[1/3] 安装依赖..."
$UV_CMD sync

echo ""
echo "[2/3] 安装 Playwright Chromium..."
$UV_CMD run playwright install chromium || {
    echo "警告：Playwright Chromium 安装失败"
    echo "如已安装可忽略，否则手动运行: uv run playwright install chromium"
}

echo ""
echo "[3/3] 环境准备完成"

# --install-only 模式：只安装依赖，不启动应用
if [[ "${1:-}" == "--install-only" ]]; then
    exit 0
fi

echo "启动命令: uv run main.py"
