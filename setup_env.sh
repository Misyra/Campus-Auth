#!/usr/bin/env bash
set -euo pipefail

# Campus-Auth setup script for macOS/Linux
# - Create/use project-local venv
# - Install/update dependencies by requirements hash
# - Ensure Playwright Chromium is installed
# - Avoid duplicate start by checking APP_PORT

PYTHON_VERSION="${PYTHON_VERSION:-3.10}"
PYTHON_FULL_VERSION="${PYTHON_FULL_VERSION:-3.10.16}"
PIP_MIRROR="${PIP_MIRROR:-https://mirrors.cernet.edu.cn/pypi/simple}"
PYTHON_MIRROR="${PYTHON_MIRROR:-https://mirrors.cernet.edu.cn/python}"
FORCE_REINSTALL="${FORCE_REINSTALL:-0}"
VERBOSE="${VERBOSE:-0}"

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_DIR="$PROJECT_ROOT/environment"
VENV_DIR="$ENV_DIR/python"
PYTHON_EXE="$VENV_DIR/bin/python3"
PIP_EXE="$VENV_DIR/bin/pip3"
REQUIREMENTS_FILE="$PROJECT_ROOT/requirements.txt"
HASH_FILE="$ENV_DIR/.requirements_hash"
LOG_DIR="$PROJECT_ROOT/logs"
LOG_FILE="$LOG_DIR/setup_env.log"

DEFAULT_PORT="50721"
DUPLICATE_EXIT_DELAY="${CAMPUS_AUTH_DUPLICATE_EXIT_DELAY:-10}"

mkdir -p "$LOG_DIR" "$ENV_DIR"

usage() {
  cat <<'EOF'
Usage: ./setup_env.sh [options]

Options:
  --python-version <ver>    Python version (default: 3.10)
  --python-mirror <url>     Python download mirror URL
  --pip-mirror <url>        Pip mirror URL
  --force-reinstall         Force reinstall dependencies
  --no-auto                 Skip auto-login and auto-start (recovery mode)
  --verbose                 Print logs to terminal
  -h, --help                Show help

Environment:
  CAMPUS_AUTH_DUPLICATE_EXIT_DELAY   Delay seconds before exit on duplicate start (default: 10)
EOF
}

NO_AUTO=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --python-version)
      PYTHON_VERSION="${2:-$PYTHON_VERSION}"
      shift 2
      ;;
    --python-mirror)
      PYTHON_MIRROR="${2:-$PYTHON_MIRROR}"
      shift 2
      ;;
    --pip-mirror)
      PIP_MIRROR="${2:-$PIP_MIRROR}"
      shift 2
      ;;
    --force-reinstall)
      FORCE_REINSTALL="1"
      shift
      ;;
    --no-auto)
      NO_AUTO="--no-auto"
      shift
      ;;
    --verbose|-v)
      VERBOSE="1"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1"
      usage
      exit 1
      ;;
  esac
done

timestamp() {
  date "+%Y-%m-%d %H:%M:%S"
}

write_log() {
  local level="$1"
  local message="$2"
  local line="[$(timestamp)] [$level] $message"
  if [[ "$VERBOSE" == "1" ]]; then
    echo "$line"
  fi
  echo "$line" >> "$LOG_FILE"
}

log_info() { write_log "INFO" "$1"; }
log_success() { write_log "SUCCESS" "$1"; }
log_warning() { write_log "WARNING" "$1"; }
log_error() { write_log "ERROR" "$1"; }

resolve_port() {
  if [[ -n "${APP_PORT:-}" ]]; then
    echo "$APP_PORT"
    return
  fi

  local env_file="$PROJECT_ROOT/.env"
  if [[ -f "$env_file" ]]; then
    local val
    val="$(grep -E '^APP_PORT=' "$env_file" | tail -n 1 | cut -d '=' -f2- | tr -d '[:space:]' || true)"
    if [[ -n "$val" ]]; then
      echo "$val"
      return
    fi
  fi

  echo "$DEFAULT_PORT"
}

is_service_running() {
  local port="$1"
  "$PYTHON_EXE" - "$port" <<'PY'
import socket
import sys

port = int(sys.argv[1])
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
    sock.settimeout(0.6)
    sys.exit(0 if sock.connect_ex(("127.0.0.1", port)) == 0 else 1)
PY
}

wait_before_duplicate_exit() {
  local delay="$DUPLICATE_EXIT_DELAY"
  if [[ "$delay" =~ ^[0-9]+$ ]] && (( delay > 0 )); then
    log_info "${delay} 秒后自动退出"
    sleep "$delay"
  fi
}

calculate_hash() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$REQUIREMENTS_FILE" | awk '{print $1}'
  else
    shasum -a 256 "$REQUIREMENTS_FILE" | awk '{print $1}'
  fi
}

FALLBACK_PIP_MIRRORS=(
  "https://mirrors.aliyun.com/pypi/simple"
  "https://pypi.org/simple"
)

get_mirror_candidates() {
  local mirrors=("$PIP_MIRROR")
  for m in "${FALLBACK_PIP_MIRRORS[@]}"; do
    local dup=0
    for existing in "${mirrors[@]}"; do
      [[ "$m" == "$existing" ]] && dup=1 && break
    done
    (( dup == 0 )) && mirrors+=("$m")
  done
  printf '%s\n' "${mirrors[@]}"
}

run_pip_with_mirror() {
  local stage="$1"
  shift
  while IFS= read -r mirror; do
    log_info "[$stage] 尝试镜像源: $mirror"
    if "$PYTHON_EXE" -m pip "$@" --progress-bar=on -i "$mirror" 2>/dev/null; then
      log_success "[$stage] 镜像成功: $mirror"
      return 0
    fi
    log_warning "[$stage] 镜像失败: $mirror"
  done < <(get_mirror_candidates)
  log_error "[$stage] 所有镜像均失败"
  return 1
}

get_platform_info() {
  local os arch
  os="$(uname -s)"
  arch="$(uname -m)"

  case "$os" in
    Linux)
      case "$arch" in
        x86_64)  echo "x86_64-unknown-linux-gnu" ;;
        aarch64) echo "aarch64-unknown-linux-gnu" ;;
        *)       log_error "不支持的 Linux 架构: $arch"; exit 1 ;;
      esac
      ;;
    Darwin)
      case "$arch" in
        x86_64)  echo "x86_64-apple-darwin" ;;
        arm64)   echo "aarch64-apple-darwin" ;;
        *)       log_error "不支持的 macOS 架构: $arch"; exit 1 ;;
      esac
      ;;
    *)
      log_error "不支持的操作系统: $os"
      exit 1
      ;;
  esac
}

download_embed_python() {
  local platform="$1"
  local version="$PYTHON_FULL_VERSION"
  local filename="cpython-${version}-${platform}-install_only.tar.gz"

  local temp_dir="$PROJECT_ROOT/temp"
  mkdir -p "$temp_dir"
  local tar_path="$temp_dir/$filename"

  # 构建候选下载地址
  local candidates=(
    "${PYTHON_MIRROR}/${version}/${filename}"
    "https://mirrors.cernet.edu.cn/python/${version}/${filename}"
    "https://mirrors.aliyun.com/python/${version}/${filename}"
    "https://github.com/indygreg/python-build-standalone/releases/download/${version}/${filename}"
  )

  log_info "下载 Python ${version} (${platform})..."
  for url in "${candidates[@]}"; do
    log_info "尝试下载: $url"
    if curl -fSL --connect-timeout 15 --max-time 300 -o "$tar_path" "$url" 2>/dev/null; then
      log_success "Python 下载完成"
      echo "$tar_path"
      return 0
    fi
    log_warning "下载失败，尝试下一个源..."
  done

  log_error "Python 下载失败：所有下载源均不可用"
  return 1
}

install_embed_python() {
  local platform
  platform="$(get_platform_info)"

  local tar_path
  tar_path="$(download_embed_python "$platform")" || return 1

  log_info "解压 Python 到: $VENV_DIR"
  mkdir -p "$VENV_DIR"
  tar -xzf "$tar_path" -C "$VENV_DIR" --strip-components=1

  log_info "清理临时文件..."
  rm -f "$tar_path"

  # 确保 pip 可用
  if [[ ! -x "$PIP_EXE" ]]; then
    log_info "安装 pip..."
    "$PYTHON_EXE" -m ensurepip --upgrade 2>/dev/null || true
  fi

  log_success "Python 嵌入式环境安装完成"
}

check_python_version() {
  if [[ ! -x "$PYTHON_EXE" ]]; then
    return 1
  fi
  local py_ver
  py_ver="$($PYTHON_EXE --version 2>&1 || true)"
  if [[ "$py_ver" == *"$PYTHON_VERSION"* ]]; then
    return 0
  fi
  return 1
}

ensure_python() {
  if check_python_version && [[ "$FORCE_REINSTALL" != "1" ]]; then
    local py_ver
    py_ver="$($PYTHON_EXE --version 2>&1 || true)"
    log_success "Python 已就绪 (版本: $py_ver)"
    return
  fi

  log_info "安装 Python ${PYTHON_VERSION} 嵌入式环境..."
  install_embed_python

  if ! check_python_version; then
    log_error "Python 安装失败，请检查网络连接或手动安装 Python ${PYTHON_VERSION}+"
    exit 1
  fi

  local py_ver
  py_ver="$($PYTHON_EXE --version 2>&1 || true)"
  log_success "Python 已就绪 (版本: $py_ver)"
}

ensure_pip() {
  if [[ ! -x "$PYTHON_EXE" ]]; then
    log_error "Python 不可用: $PYTHON_EXE"
    exit 1
  fi

  "$PYTHON_EXE" -m ensurepip --upgrade >/dev/null 2>&1 || true
  run_pip_with_mirror "基础工具" install --upgrade pip setuptools wheel || true
  local pip_ver
  pip_ver="$($PYTHON_EXE -m pip --version 2>&1 || true)"
  log_success "Pip 已就绪 (版本: $pip_ver)"
}

install_dependencies_if_needed() {
  if [[ ! -f "$REQUIREMENTS_FILE" ]]; then
    log_error "requirements.txt 不存在: $REQUIREMENTS_FILE"
    exit 1
  fi

  local current_hash
  current_hash="$(calculate_hash)"
  local last_hash=""
  if [[ -f "$HASH_FILE" ]]; then
    last_hash="$(tr -d '[:space:]' < "$HASH_FILE")"
  fi

  log_info "当前哈希: ${current_hash:0:8}..."
  if [[ -n "$last_hash" ]]; then
    log_info "读取到哈希值: ${last_hash:0:8}..."
  fi

  if [[ "$FORCE_REINSTALL" == "1" || -z "$last_hash" || "$current_hash" != "$last_hash" ]]; then
    log_info ">>> 开始安装依赖..."
    run_pip_with_mirror "项目依赖" install -r "$REQUIREMENTS_FILE"
    printf "%s" "$current_hash" > "$HASH_FILE"
    log_success "依赖安装完成"
  else
    log_success "依赖已是最新，跳过安装"
  fi
}

has_playwright_chromium() {
  "$PYTHON_EXE" - <<'PY'
import os
from pathlib import Path
import sys

try:
    from playwright.sync_api import sync_playwright
except Exception:
    sys.exit(1)

with sync_playwright() as p:
    exe = p.chromium.executable_path
    if not (exe and Path(exe).exists()):
        sys.exit(1)
    # 同时检查 chromium_headless_shell 是否存在
    chromium_dir = Path(exe).resolve().parent.parent
    rev = chromium_dir.name.replace('chromium-', '')
    headless = chromium_dir.parent / f'chromium_headless_shell-{rev}'
    sys.exit(0 if headless.is_dir() else 1)
PY
}

ensure_playwright() {
  if has_playwright_chromium; then
    log_success "Playwright 浏览器已安装"
    return
  fi

  local pw_host="${PLAYWRIGHT_DOWNLOAD_HOST:-https://npmmirror.com/mirrors/playwright}"
  log_info ">>> 安装 Playwright 浏览器..."
  log_info "Playwright 镜像: $pw_host"
  PLAYWRIGHT_DOWNLOAD_HOST="$pw_host" "$PYTHON_EXE" -m playwright install chromium
  log_success "Playwright 安装完成"
}

main() {
  log_info "========================================"
  log_info "Campus-Auth 环境初始化脚本 (macOS/Linux)"
  log_info "========================================"
  log_info "项目根目录: $PROJECT_ROOT"
  log_info "ENV 目录: $ENV_DIR"
  log_info "Python 版本: ${PYTHON_VERSION}"
  log_info "Python 镜像源: $PYTHON_MIRROR"
  log_info "Pip 镜像源: $PIP_MIRROR"

  local port
  port="$(resolve_port)"
  if is_service_running "$port"; then
    log_success "检测到服务已在运行: http://127.0.0.1:$port"
    log_info "请勿重复启动"
    wait_before_duplicate_exit
    exit 0
  fi

  ensure_python
  ensure_pip
  install_dependencies_if_needed
  ensure_playwright

  log_success "环境初始化完成！"
  log_info ""
  log_info "Python 路径: $PYTHON_EXE"
  log_info "Pip 路径: $PIP_EXE"
  log_info ""
  log_info "使用方法:"
  log_info "  运行项目: $PYTHON_EXE app.py"
  log_info "  安装新依赖: $PYTHON_EXE -m pip install <包名> -i $PIP_MIRROR"
  log_info "  查看已安装包: $PYTHON_EXE -m pip list"
  log_info ""
  log_info "日志文件: $LOG_FILE"

  if is_service_running "$port"; then
    log_success "检测到服务已在运行: http://127.0.0.1:$port"
    log_info "已跳过重复启动"
    wait_before_duplicate_exit
    exit 0
  fi

  log_info ">>> 启动应用..."
  env \
    "Campus-Auth_PROJECT_ROOT=$PROJECT_ROOT" \
    "Campus-Auth_ENV_FILE=$PROJECT_ROOT/.env" \
    "AUTO_INSTALL_PLAYWRIGHT=false" \
    "$PYTHON_EXE" "$PROJECT_ROOT/app.py" --no-browser $NO_AUTO &
  APP_PID=$!

  # 等待服务就绪后打开浏览器
  for i in $(seq 1 15); do
    sleep 1
    if is_service_running "$port"; then
      log_success "服务已启动: http://127.0.0.1:$port"
      if command -v open >/dev/null 2>&1; then
        open "http://127.0.0.1:$port"
      elif command -v xdg-open >/dev/null 2>&1; then
        xdg-open "http://127.0.0.1:$port"
      fi
      break
    fi
  done

  wait $APP_PID
}

main "$@"
