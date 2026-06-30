#!/usr/bin/env bash
# Campus-Auth 启动脚本（macOS / Linux）
# 用法: ./start.sh [参数]
#   --install-only  仅安装环境，不启动应用
set -euo pipefail

# ── 常量 ──────────────────────────────────────────────────
PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
UV_DIR="$PROJECT_ROOT/.uv"
UV_VERSION="0.11.21"
MIRRORS=(
    "https://ghfast.top/"
    "https://gh-proxy.com/"
    "https://ghproxy.net/"
    ""  # GitHub 官方源
)
# SHA256 校验和（与 UV_VERSION 严格对应）
# 不用 declare -A，兼容 macOS 自带 bash 3.2
_sha256_for() {
    case "$1" in
        uv-aarch64-apple-darwin.tar.gz)       echo "1f921d491ba5ffeea774eb04d6681ecee379101341cbb1500394993b541bf3f4" ;;
        uv-x86_64-apple-darwin.tar.gz)        echo "f3c8e5708a84b920c18b691214d54d2b0da6b984789caae95d47c95120cb7765" ;;
        uv-aarch64-unknown-linux-gnu.tar.gz)  echo "88e800834007cc5efd4675f166eb2a51e7e3ad19876d85fa8805a6fb5c922397" ;;
        uv-x86_64-unknown-linux-gnu.tar.gz)   echo "8c88519b0ef0af9801fcdee419bbb12116bd9e6b18e162ae093c932d8b264050" ;;
        *) echo "" ;;
    esac
}

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

    local expected
    expected="$(_sha256_for "$filename")"
    if [[ -z "$expected" ]]; then
        echo "[X] 未知文件 $filename，无法校验 SHA256" >&2
        exit 1
    fi

    for mirror in "${MIRRORS[@]}"; do
        local url="${mirror}${github_url}"
        if [[ -z "$mirror" ]]; then
            echo "  尝试: GitHub 官方" >&2
        else
            echo "  尝试: ${mirror}" >&2
        fi
        if ! curl -fsSL --connect-timeout 10 --max-time 120 -o "$archive" "$url" 2>&1; then
            continue
        fi
        if ! tar -tzf "$archive" &>/dev/null; then
            echo "  [!] 文件无效，尝试下一个源..." >&2
            rm -f "$archive"
            continue
        fi

        # SHA256 校验
        echo -n "  校验 SHA256..." >&2
        local actual
        if command -v sha256sum &>/dev/null; then
            actual="$(sha256sum "$archive" | cut -d' ' -f1)"
        else
            actual="$(shasum -a 256 "$archive" | cut -d' ' -f1)"
        fi
        if [[ "$actual" != "$expected" ]]; then
            echo " 失败: 期望 $expected, 实际 $actual" >&2
            rm -f "$archive"
            continue
        fi
        echo " 通过" >&2

        success=1
        break
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
        found=$(find "$UV_DIR" -maxdepth 2 -name "uv" -type f -perm -u+x | head -1)
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

echo "[1/2] 安装依赖..."
"$UV_CMD" sync

# 检查 --install-only 参数
for arg in "$@"; do
    if [[ "$arg" == "--install-only" ]]; then
        echo "[OK] 环境准备完成"
        exit 0
    fi
done

echo "[2/2] 启动 Campus-Auth..."
exec "$UV_CMD" run main.py --browser "$@"
