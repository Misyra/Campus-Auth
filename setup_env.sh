#!/usr/bin/env bash
set -euo pipefail

# Campus-Auth setup script for macOS/Linux
# - Create/use project-local venv
# - Install/update dependencies by requirements hash
# - Ensure Playwright Chromium is installed
# - Avoid duplicate start by checking APP_PORT

PYTHON_VERSION="${PYTHON_VERSION:-3.10}"
PIP_MIRROR="${PIP_MIRROR:-https://pypi.tuna.tsinghua.edu.cn/simple}"
FORCE_REINSTALL="${FORCE_REINSTALL:-0}"
VERBOSE="${VERBOSE:-0}"

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_DIR="$PROJECT_ROOT/environment"
VENV_DIR="$ENV_DIR/python"
PYTHON_EXE="$VENV_DIR/bin/python"
PIP_EXE="$VENV_DIR/bin/pip"
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
  --python-version <ver>    Python version hint (default: 3.10)
  --pip-mirror <url>        Pip mirror URL
  --force-reinstall         Force reinstall dependencies
  --verbose                 Print logs to terminal
  -h, --help                Show help

Environment:
  CAMPUS_AUTH_DUPLICATE_EXIT_DELAY   Delay seconds before exit on duplicate start (default: 10)
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --python-version)
      PYTHON_VERSION="${2:-$PYTHON_VERSION}"
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

ensure_python() {
  if [[ -x "$PYTHON_EXE" && "$FORCE_REINSTALL" != "1" ]]; then
    local py_ver
    py_ver="$($PYTHON_EXE --version 2>&1 || true)"
    if [[ -n "$py_ver" ]]; then
      log_success "Python 已就绪 (版本: $py_ver)，跳过创建虚拟环境"
      return
    fi
  fi

  local py_cmd
  if command -v python3 >/dev/null 2>&1; then
    py_cmd="python3"
  elif command -v python >/dev/null 2>&1; then
    py_cmd="python"
  else
    log_error "未找到 Python，请先安装 Python ${PYTHON_VERSION}+"
    exit 1
  fi

  log_info "创建虚拟环境: $VENV_DIR"
  "$py_cmd" -m venv "$VENV_DIR"
  log_success "虚拟环境创建完成"
}

ensure_pip() {
  if [[ ! -x "$PYTHON_EXE" ]]; then
    log_error "Python 不可用: $PYTHON_EXE"
    exit 1
  fi

  "$PYTHON_EXE" -m ensurepip --upgrade >/dev/null 2>&1 || true
  "$PYTHON_EXE" -m pip install --upgrade pip setuptools wheel -i "$PIP_MIRROR" >/dev/null
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
    "$PYTHON_EXE" -m pip install -r "$REQUIREMENTS_FILE" -i "$PIP_MIRROR"
    printf "%s" "$current_hash" > "$HASH_FILE"
    log_success "依赖安装完成"
  else
    log_success "依赖已是最新，跳过安装"
  fi
}

has_playwright_chromium() {
  "$PYTHON_EXE" - <<'PY'
from pathlib import Path
import sys

try:
    from playwright.sync_api import sync_playwright
except Exception:
    sys.exit(1)

with sync_playwright() as p:
    exe = p.chromium.executable_path
sys.exit(0 if exe and Path(exe).exists() else 1)
PY
}

ensure_playwright() {
  if has_playwright_chromium; then
    log_success "Playwright 浏览器已安装"
    return
  fi

  log_info ">>> 安装 Playwright 浏览器..."
  "$PYTHON_EXE" -m playwright install chromium
  log_success "Playwright 安装完成"
}

main() {
  log_info "========================================"
  log_info "Campus-Auth 环境初始化脚本 (macOS/Linux)"
  log_info "========================================"
  log_info "项目根目录: $PROJECT_ROOT"
  log_info "ENV 目录: $ENV_DIR"
  log_info "Python 版本要求: ${PYTHON_VERSION}+"
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
  log_info "Python 路径: $PYTHON_EXE"
  log_info "Pip 路径: $PIP_EXE"
  log_info "日志文件: $LOG_FILE"

  if is_service_running "$port"; then
    log_success "检测到服务已在运行: http://127.0.0.1:$port"
    log_info "已跳过重复启动"
    wait_before_duplicate_exit
    exit 0
  fi

  log_info ">>> 启动应用..."
  exec env \
    "Campus-Auth_PROJECT_ROOT=$PROJECT_ROOT" \
    "Campus-Auth_ENV_FILE=$PROJECT_ROOT/.env" \
    "AUTO_INSTALL_PLAYWRIGHT=false" \
    "$PYTHON_EXE" "$PROJECT_ROOT/app.py"
}

main "$@"
