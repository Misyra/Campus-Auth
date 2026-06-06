#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# Campus-Auth 环境初始化脚本 (macOS/Linux)
# - 交互式选择启动方式：uv（推荐）或系统 Python
# - uv 模式：uv sync → uv run playwright install → 启动
# - 系统 Python 模式：检查版本 → 虚拟环境 → 安装依赖 → 启动
# - 通过 APP_PORT 检测重复启动
# ============================================================

# ==================== 配置 ====================

PIP_MIRROR_EXPLICIT=0                # 用户是否显式指定了镜像（env/--pip-mirror）
[[ -n "${PIP_MIRROR+set}" ]] && PIP_MIRROR_EXPLICIT=1
PIP_MIRROR="${PIP_MIRROR:-https://mirrors.cernet.edu.cn/pypi/simple}"
FORCE_REINSTALL="${FORCE_REINSTALL:-0}"
VERBOSE="${VERBOSE:-0}"
PLAYWRIGHT_READY=0
USE_SYSTEM_PROXY="${USE_SYSTEM_PROXY:-0}"
LAUNCH_METHOD="${LAUNCH_METHOD:-}"   # uv 或 system，空则自动检测

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_DIR="$PROJECT_ROOT/environment"
VENV_DIR="$ENV_DIR/python"
VENV_PYTHON="$VENV_DIR/bin/python3"
VENV_PIP="$VENV_DIR/bin/pip3"
REQUIREMENTS_FILE="$PROJECT_ROOT/requirements.txt"
HASH_FILE="$ENV_DIR/.requirements_hash"
LOG_DIR="$PROJECT_ROOT/logs"
LOG_FILE="$LOG_DIR/setup_env.log"

DEFAULT_PORT="50721"
DUPLICATE_EXIT_DELAY="${CAMPUS_AUTH_DUPLICATE_EXIT_DELAY:-10}"

mkdir -p "$LOG_DIR" "$ENV_DIR"

# ==================== 工具函数 ====================

timestamp() { date "+%Y-%m-%d %H:%M:%S"; }

write_log() {
  local level="$1" message="$2"
  local line="[$(timestamp)] [$level] $message"
  [[ "$VERBOSE" == "1" ]] && echo "$line"
  echo "$line" >> "$LOG_FILE"
}

log_info()    { write_log "INFO" "$1"; }
log_success() { write_log "SUCCESS" "$1"; }
log_warning() { write_log "WARNING" "$1"; }
log_error()   { write_log "ERROR" "$1"; }

# ---------- 端口与重复启动检测 ----------

resolve_port() {
  if [[ -n "${APP_PORT:-}" ]]; then echo "$APP_PORT"; return; fi
  local env_file="$PROJECT_ROOT/.env"
  if [[ -f "$env_file" ]]; then
    local val
    val="$(grep -E '^APP_PORT=' "$env_file" | tail -n 1 | cut -d '=' -f2- | tr -d '[:space:]' || true)"
    [[ -n "$val" ]] && echo "$val" && return
  fi
  echo "$DEFAULT_PORT"
}

# 检测 127.0.0.1 上的 TCP 端口是否在监听
# 优先用 python3，其次 python，最后用 bash /dev/tcp 兜底
check_port_open() {
  local port="$1"
  local py
  py="$(command -v python3 || command -v python || true)"
  if [[ -n "$py" ]]; then
    "$py" -c "
import socket, sys
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(0.6)
sys.exit(0 if s.connect_ex(('127.0.0.1', $port)) == 0 else 1)
" 2>/dev/null && return 0
  fi
  # bash 兜底（/dev/tcp 需 shell 编译时开启，部分环境不可用）
  timeout 1 bash -c "echo >/dev/tcp/127.0.0.1/$port" 2>/dev/null && return 0
  return 1
}

wait_before_duplicate_exit() {
  local delay="$DUPLICATE_EXIT_DELAY"
  if [[ "$delay" =~ ^[0-9]+$ ]] && (( delay > 0 )); then
    log_info "${delay}s 后自动退出..."
    sleep "$delay"
  fi
}

# ---------- usage 帮助 ----------

usage() {
  cat <<'EOF'
用法: ./setup_env.sh [选项]

选项:
  --method <uv|system>      启动方式（默认交互式选择）
  --pip-mirror <url>        pip 镜像源地址（仅系统 Python 模式有效）
  --force-reinstall         强制重新安装依赖
  --no-auto                 跳过自动登录和自动启动（恢复模式）
  --verbose                 输出日志到终端
  --use-system-proxy        使用系统 HTTP_PROXY/HTTPS_PROXY 代理
  -h, --help                显示帮助

环境变量:
  CAMPUS_AUTH_DUPLICATE_EXIT_DELAY   检测到重复启动时延迟退出秒数（默认: 10）

示例:
  ./setup_env.sh                              交互式模式
  ./setup_env.sh --method uv --no-auto        非交互式，使用 uv
  LAUNCH_METHOD=system ./setup_env.sh         通过环境变量指定
EOF
}

# ==================== 命令行参数解析 ====================

NO_AUTO=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --method)
      if [[ $# -ge 2 ]]; then
        case "$2" in
          uv|system) LAUNCH_METHOD="$2" ;;
          *) echo "无效 --method 参数: $2（请使用 uv 或 system）"; exit 1 ;;
        esac
      fi
      shift 2 || shift
      ;;
    --pip-mirror)
      [[ $# -ge 2 ]] && PIP_MIRROR="$2" && PIP_MIRROR_EXPLICIT=1
      shift 2 || shift
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
    --use-system-proxy)
      USE_SYSTEM_PROXY="1"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "未知参数: $1"
      usage
      exit 1
      ;;
  esac
done



# ==================== 交互式选择 ====================

is_interactive() {
  [[ -t 0 ]] && return 0
  return 1
}

detect_uv() {
  command -v uv >/dev/null 2>&1
}

detect_python3() {
  command -v python3 &>/dev/null && echo "python3" && return 0
  command -v python &>/dev/null && echo "python" && return 0
  return 1
}

get_python_version() {
  local py_cmd="$1"
  "$py_cmd" --version 2>&1 | awk '{print $2}'
}

select_launch_method() {
  local has_uv
  detect_uv && has_uv=true || has_uv=false

  local py_cmd py_ver py_status
  py_cmd="$(detect_python3)" && py_ver="$(get_python_version "$py_cmd")" || py_ver=""

  if [[ -n "$py_ver" ]]; then
    py_status="检测到 Python $py_ver"
  else
    py_status="未检测到（请先安装 Python 3.12+）"
  fi

  # 所有菜单文字用 >&2 输出到终端，避免被 $() 捕获
  echo "" >&2
  echo "================================================================" >&2
  echo " Campus-Auth 启动方式选择" >&2
  echo "================================================================" >&2
  echo "" >&2
  if $has_uv; then
    echo "  [1] 使用 uv (推荐)        uv: $(uv --version 2>&1)" >&2
  else
    echo "  [1] 使用 uv (推荐)        uv: 未安装（可自动安装）" >&2
  fi
  echo "" >&2
  echo "  [2] 使用系统 Python        $py_status" >&2
  echo "" >&2
  echo "================================================================" >&2
  echo "" >&2

  echo "  [0] 退出" >&2
  echo "" >&2

  local default=1
  local choice
  read -p "请选择 [0/1/2] (默认: ${default}): " choice
  choice="${choice:-$default}"

  case "$choice" in
    0|q|Q) echo "quit" ;;
    1) echo "uv" ;;
    2) echo "system" ;;
    *) echo "uv" ;;
  esac
}

# ==================== uv 模式 ====================

try_fallback_system_python() {
  local reason="$1"
  log_warning "$reason"
  if is_interactive; then
    echo ""
    local answer
    read -p "是否尝试使用系统 Python 方式? (Y/n/B 返回): " answer
    answer="${answer:-Y}"
    case "$answer" in
      [Bb]) return 2 ;;  # 返回主菜单
      [Nn]) return 1 ;;  # 取消
      *)                 # 确认回退
        log_info "已切换到系统 Python 方式"
        LAUNCH_METHOD="system"
        return 0
        ;;
    esac
  else
    log_warning "非交互模式，自动回退到系统 Python 方式"
    LAUNCH_METHOD="system"
    return 0
  fi
}

ensure_uv_installed() {
  if detect_uv; then
    log_success "uv 已就绪: $(uv --version 2>&1)"
    return 0
  fi

  log_warning "系统中未检测到 uv"
  echo ""
  local answer
  read -p "是否自动安装 uv? (Y/n/B 返回): " answer
  answer="${answer:-Y}"

  case "$answer" in
    [Bb]) return 2 ;;                              # 返回主菜单
    [Nn])
      local fb_rc=0; try_fallback_system_python "已取消 uv 安装" || fb_rc=$?
      [[ $fb_rc -eq 2 ]] && return 2               # 返回主菜单
      [[ $fb_rc -eq 0 ]] && return 1               # 已切到 system，让上层继续
      exit 1
      ;;
    *) ;;                                           # 安装
  esac

  log_info "正在安装 uv (curl -LsSf https://astral.sh/uv/install.sh)..."
  if curl -LsSf https://astral.sh/uv/install.sh | sh; then
    # 加载 shell 配置文件，使 uv 进入 PATH
    if [[ -f "$HOME/.cargo/env" ]]; then
      source "$HOME/.cargo/env"
    fi
    export PATH="$HOME/.cargo/bin:$HOME/.local/bin:$PATH"

    if detect_uv; then
      log_success "uv 安装成功: $(uv --version 2>&1)"
      return 0
    fi
  fi

  try_fallback_system_python "uv 自动安装失败" && return 1
  log_error "请手动安装 uv:"
  log_error "  curl -LsSf https://astral.sh/uv/install.sh | sh"
  exit 1
}

setup_with_uv() {
  log_info "========== 使用 uv 方式 =========="
  local rc=0; ensure_uv_installed || rc=$?
  [[ $rc -eq 2 ]] && return 2           # 返回主菜单
  [[ "$LAUNCH_METHOD" != "uv" ]] && return 1  # 已回退到 system

  # pyproject.toml 已配置清华源，只在用户显式指定镜像时传入
  if (( PIP_MIRROR_EXPLICIT )); then
    export UV_INDEX_URL="$PIP_MIRROR"
    log_info "uv 镜像源: $UV_INDEX_URL（用户指定）"
  fi

  log_info ">>> 同步依赖 (uv sync)..."

  # 检测系统 Python，避免 uv 使用内嵌 Python（可能缺少 venv 模块）
  local uv_py_flag=()
  local sys_py
  sys_py="$(detect_python3 || true)"
  if [[ -n "$sys_py" ]]; then
    uv_py_flag=(--python "$sys_py")
    log_info "uv 将使用系统 Python: $(command -v "$sys_py")"
  fi

  local sync_ok=true
  # 始终显示 uv 输出（uv 自带清晰的进度信息）
  uv sync "${uv_py_flag[@]}" || sync_ok=false

  if ! $sync_ok; then
    local fb2_rc=0; try_fallback_system_python "uv sync 失败（网络问题或依赖错误）" || fb2_rc=$?
    [[ $fb2_rc -eq 2 ]] && return 2     # 返回主菜单
    [[ $fb2_rc -eq 0 ]] && return 1     # 已回退到 system
    log_error "uv sync 失败，已取消"
    exit 1
  fi

  # 验证虚拟环境已创建
  if [[ ! -d "$PROJECT_ROOT/.venv" ]]; then
    local fb3_rc=0; try_fallback_system_python "uv sync 完成但 .venv 未创建" || fb3_rc=$?
    [[ $fb3_rc -eq 2 ]] && return 2
    [[ $fb3_rc -eq 0 ]] && return 1
    log_error "虚拟环境创建失败，已取消"
    exit 1
  fi

  log_success "依赖同步完成"

  log_info ">>> 安装 Playwright Chromium 浏览器..."
  local pw_host="${PLAYWRIGHT_DOWNLOAD_HOST:-https://npmmirror.com/mirrors/playwright}"
  if PLAYWRIGHT_DOWNLOAD_HOST="$pw_host" uv run playwright install chromium; then
    log_success "Playwright 浏览器安装完成"
    PLAYWRIGHT_READY=1
  else
    log_warning "Playwright 浏览器安装失败，但可继续启动"
  fi
}

# ==================== 系统 Python 模式 ====================

check_system_python() {
  local py_cmd
  py_cmd="$(detect_python3)"
  if [[ -z "$py_cmd" ]]; then
    log_error "系统中未检测到 python3 或 python"
    log_error "请先安装 Python 3.12+ (推荐 https://www.python.org/downloads/)"
    exit 1
  fi

  local py_ver
  py_ver="$(get_python_version "$py_cmd")"
  local major_minor
  major_minor="$(echo "$py_ver" | cut -d. -f1,2)"

  log_info "系统 Python 版本: $py_ver"

  # 检查版本 >= 3.12
  local major minor
  major="$(echo "$major_minor" | cut -d. -f1)"
  minor="$(echo "$major_minor" | cut -d. -f2)"

  if [[ "$major" -gt 3 ]] || [[ "$major" -eq 3 && "$minor" -ge 12 ]]; then
    log_success "Python 版本符合推荐要求"
    return 0
  fi

  # 版本低于 3.12，弹出兼容性警告
  echo ""
  log_warning "=============================================="
  log_warning "  Python $py_ver 低于项目最低要求"
  log_warning "  项目需要 Python 3.12 或更高版本"
  log_warning "  requires-python = \">=3.12\""
  log_warning "=============================================="
  echo ""

  # 非交互模式自动继续，交互模式让用户决定
  if is_interactive; then
    local answer
    read -p "检测到 Python $major_minor，版本过低。是否继续? (Y/n/B 返回): " answer
    answer="${answer:-Y}"
    case "$answer" in
      [Bb]) return 2 ;;                                 # 返回主菜单
      [Nn]) log_info "已取消，请安装 Python 3.12 后重试"; exit 0 ;;
      *) ;;                                              # 继续
    esac
  else
    log_warning "Python $major_minor 不是推荐版本，但将继续 (非交互模式)"
  fi
}

setup_with_system_python() {
  log_info "========== 使用系统 Python 方式 =========="
  local rc=0; check_system_python || rc=$?
  [[ $rc -eq 2 ]] && return 2  # 返回主菜单

  local system_python
  system_python="$(detect_python3)"

  # 创建虚拟环境
  if [[ -d "$VENV_DIR" ]]; then
    log_info "虚拟环境已存在: $VENV_DIR"
    if [[ "$FORCE_REINSTALL" == "1" ]]; then
      log_info "FORCE_REINSTALL 已设置，重新创建虚拟环境..."
      rm -rf "$VENV_DIR"
    fi
  fi

  if [[ ! -d "$VENV_DIR" ]]; then
    log_info ">>> 创建虚拟环境: $VENV_DIR"
    "$system_python" -m venv "$VENV_DIR"
    log_success "虚拟环境创建完成"
  fi

  if [[ ! -x "$VENV_PYTHON" ]]; then
    log_error "虚拟环境 Python 不可用: $VENV_PYTHON"
    exit 1
  fi

  # 升级 pip
  log_info ">>> 升级 pip..."
  "$VENV_PYTHON" -m pip install --upgrade pip setuptools wheel -i "$PIP_MIRROR" --progress-bar off || true

  # 安装项目依赖
  if [[ ! -f "$REQUIREMENTS_FILE" ]]; then
    log_error "requirements.txt 不存在: $REQUIREMENTS_FILE"
    exit 1
  fi

  log_info ">>> 安装项目依赖..."
  "$VENV_PYTHON" -m pip install -r "$REQUIREMENTS_FILE" -i "$PIP_MIRROR" --progress-bar off
  log_success "依赖安装完成"

  # 安装 Playwright 浏览器
  log_info ">>> 安装 Playwright Chromium 浏览器..."
  local pw_host="${PLAYWRIGHT_DOWNLOAD_HOST:-https://npmmirror.com/mirrors/playwright}"
  if PLAYWRIGHT_DOWNLOAD_HOST="$pw_host" "$VENV_PYTHON" -m playwright install chromium; then
    log_success "Playwright 浏览器安装完成"
    PLAYWRIGHT_READY=1
  else
    log_warning "Playwright 浏览器安装失败，但可继续启动"
  fi
}

# ==================== 启动应用 ====================

launch_app() {
  local port="$1"

  log_info ""
  log_info "================================================"
  log_info "  环境初始化完成!"
  log_info "================================================"

  if [[ "$LAUNCH_METHOD" == "uv" ]]; then
    log_info "  启动命令: uv run app.py"
  else
    log_info "  Python 路径: $VENV_PYTHON"
    log_info "  Pip 路径:   $VENV_PIP"
    log_info "  启动命令:   $VENV_PYTHON app.py"
  fi
  log_info "  日志文件: $LOG_FILE"
  log_info ""

  # 再次检查端口（服务可能在上次检查后已被其他进程启动）
  if check_port_open "$port"; then
    log_success "检测到服务已在运行: http://127.0.0.1:$port"
    log_info "已跳过重复启动"
    wait_before_duplicate_exit
    exit 0
  fi

  log_info ">>> 启动应用..."

  # Playwright 已由脚本安装成功时禁用 app.py 的自动安装，否则保留让 app.py 兜底
  local pw_env="AUTO_INSTALL_PLAYWRIGHT=true"
  if [[ "$PLAYWRIGHT_READY" == "1" ]]; then
    pw_env="AUTO_INSTALL_PLAYWRIGHT=false"
  fi

  if [[ "$LAUNCH_METHOD" == "uv" ]]; then
    env \
      "CAMPUS_AUTH_PROJECT_ROOT=$PROJECT_ROOT" \
      "$pw_env" \
      uv run "$PROJECT_ROOT/app.py" --no-browser $NO_AUTO &
  else
    env \
      "CAMPUS_AUTH_PROJECT_ROOT=$PROJECT_ROOT" \
      "$pw_env" \
      "$VENV_PYTHON" "$PROJECT_ROOT/app.py" --no-browser $NO_AUTO &
  fi
  APP_PID=$!

  # 等待服务就绪后打开浏览器
  for i in $(seq 1 15); do
    sleep 1
    if check_port_open "$port"; then
      log_success "服务已启动: http://127.0.0.1:$port"
      case "$(uname -s)" in
        Darwin)
          open "http://127.0.0.1:$port" ;;
        Linux*)
          command -v xdg-open &>/dev/null && xdg-open "http://127.0.0.1:$port" || true ;;
      esac
      break
    fi
  done

  wait $APP_PID
}

# ==================== 主流程 ====================

main() {
  log_info "================================================"
  log_info "  Campus-Auth 环境初始化脚本 (macOS/Linux)"
  log_info "================================================"
  log_info "项目根目录: $PROJECT_ROOT"

  local port
  port="$(resolve_port)"

  # 检查是否已有实例运行
  if check_port_open "$port"; then
    log_success "检测到服务已在运行: http://127.0.0.1:$port"
    log_info "请勿重复启动"
    wait_before_duplicate_exit
    exit 0
  fi

  # 交互选择 + 执行的循环，子菜单按 B 返回时重新选择
  while true; do
    # 确定启动方法
    if [[ -z "$LAUNCH_METHOD" ]]; then
      if is_interactive; then
        LAUNCH_METHOD="$(select_launch_method)"
        [[ "$LAUNCH_METHOD" == "quit" ]] && log_info "已退出" && exit 0
      else
        # 非交互模式，检测到 uv 就用 uv，否则用系统 Python
        if detect_uv; then
          LAUNCH_METHOD="uv"
        else
          LAUNCH_METHOD="system"
        fi
        log_info "非交互模式，自动选择: $LAUNCH_METHOD"
      fi
    fi

    log_info "启动方式: $LAUNCH_METHOD"

    if [[ "$LAUNCH_METHOD" == "uv" ]]; then
      local rc=0; setup_with_uv || rc=$?
      if [[ $rc -eq 2 ]]; then
        LAUNCH_METHOD=""  # 返回主菜单，清空选择
        continue
      fi
      if [[ "$LAUNCH_METHOD" == "system" ]]; then
        # 已回退到 system，继续走下面的 system 分支
        :
      else
        launch_app "$port"
        break
      fi
    fi

    if [[ "$LAUNCH_METHOD" == "system" ]]; then
      local rc2=0; setup_with_system_python || rc2=$?
      if [[ $rc2 -eq 2 ]]; then
        LAUNCH_METHOD=""  # 返回主菜单
        continue
      fi
      launch_app "$port"
      break
    fi

    # 未知方式，重新选择
    if [[ -n "$LAUNCH_METHOD" ]]; then
      log_error "未知的启动方式: $LAUNCH_METHOD"
    fi
    LAUNCH_METHOD=""
  done
}

main "$@"
