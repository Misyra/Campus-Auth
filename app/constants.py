"""共享常量 — 集中管理项目路径，避免各模块重复计算或循环导入。"""

from __future__ import annotations

import os
import re
from pathlib import Path

_ENV_PROJECT_ROOT = os.getenv("CAMPUS_AUTH_PROJECT_ROOT", "").strip()
PROJECT_ROOT = (
    Path(_ENV_PROJECT_ROOT).expanduser().resolve()
    if _ENV_PROJECT_ROOT
    else Path(__file__).resolve().parents[1]
)

FRONTEND_DIR = PROJECT_ROOT / "frontend"
DEBUG_DIR = PROJECT_ROOT / "debug"
LOGS_DIR = DEBUG_DIR / "logs"
SCREENSHOTS_DIR = DEBUG_DIR / "screenshots"
TEMP_DIR = PROJECT_ROOT / "temp"

# 默认网络检测目标（单一来源，避免 schemas/config_service/monitor_service 重复）
DEFAULT_NETWORK_TARGETS: str = "8.8.8.8:53,114.114.114.114:53,www.baidu.com:443"
DEFAULT_HTTP_TARGETS: str = "https://connect.rom.miui.com/generate_204,https://connectivitycheck.platform.hicloud.com/generate_204"
DEFAULT_URL_CHECK_URLS: str = (
    "http://captive.apple.com/hotspot-detect.html|Success\n"
    "http://www.msftconnecttest.com/connecttest.txt|Microsoft Connect Test\n"
    "http://detectportal.firefox.com/success.txt|success"
)

# 用户数据目录（避免 .campus_network_auth 路径多处硬编码）
AUTH_DATA_DIR: Path = Path.home() / ".campus_network_auth"

# ── 超时常量（秒）──
WORKER_SUBMIT_TIMEOUT = 300  # Worker 命令提交超时
WORKER_READY_TIMEOUT = 5  # Worker 就绪等待
WORKER_JOIN_TIMEOUT = 3  # Worker 线程 join
WORKER_QUEUE_PUT_TIMEOUT = 10  # 命令入队超时
DEFAULT_STEP_TIMEOUT_MS = 10000  # 步骤默认超时（毫秒）
DEFAULT_TASK_TIMEOUT_MS = 30000  # 任务默认超时（毫秒）

# ── 容量常量 ──
LOG_BUFFER_MAXLEN = 500  # 日志环形缓冲
STATUS_LOG_MAXLEN = 200  # 状态日志缓冲

# ── 日志级别 ──
VALID_LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR"})

# ── 正则 ──
URL_PATTERN = re.compile(r"^https?://")
