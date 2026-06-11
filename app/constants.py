"""共享常量 — 集中管理项目路径，避免各模块重复计算或循环导入。"""

from __future__ import annotations

import os
from pathlib import Path

_ENV_PROJECT_ROOT = os.getenv("CAMPUS_AUTH_PROJECT_ROOT", "").strip()
PROJECT_ROOT = (
    Path(_ENV_PROJECT_ROOT).expanduser().resolve()
    if _ENV_PROJECT_ROOT
    else Path(__file__).resolve().parents[1]
)

FRONTEND_DIR = PROJECT_ROOT / "frontend"
LOGS_DIR = PROJECT_ROOT / "logs"
TEMP_DIR = PROJECT_ROOT / "temp"
BACKUP_DIR = PROJECT_ROOT / "backups"
MAX_BACKUPS = 20

# 备份文件名正则（供 backup 路由校验）
BACKUP_FILENAME_PATTERN = r"^settings_\d{8}_\d{6}(?:_\d{6})?(?:_autosave)?\.json$"

# 默认网络检测目标（单一来源，避免 schemas/config_service/monitor_core 重复）
DEFAULT_NETWORK_TARGETS: str = "8.8.8.8:53,114.114.114.114:53,www.baidu.com:443"
DEFAULT_HTTP_TARGETS: str = "https://www.baidu.com,https://www.qq.com"

# 用户数据目录（避免 .campus_network_auth 路径多处硬编码）
AUTH_DATA_DIR: Path = Path.home() / ".campus_network_auth"

# ── 超时常量（秒）──
WORKER_SUBMIT_TIMEOUT = 300  # Worker 命令提交超时
WORKER_READY_TIMEOUT = 5  # Worker 就绪等待
WORKER_JOIN_TIMEOUT = 3  # Worker 线程 join
WORKER_QUEUE_PUT_TIMEOUT = 10  # 命令入队超时
MONITOR_THREAD_JOIN_TIMEOUT = 8  # 监控线程 join
MONITOR_STOP_TIMEOUT = 10  # 监控停止等待
PORTAL_WAIT_AFTER_LOGIN = 5  # 登录后等待 Portal 更新
DEFAULT_STEP_TIMEOUT_MS = 10000  # 步骤默认超时（毫秒）
DEFAULT_TASK_TIMEOUT_MS = 30000  # 任务默认超时（毫秒）

# ── 容量常量 ──
LOG_BUFFER_MAXLEN = 1200  # 日志环形缓冲
STATUS_LOG_MAXLEN = 200  # 状态日志缓冲
DEBUG_LOG_MAXLEN = 1000  # 调试日志缓冲
CMD_QUEUE_MAXSIZE = 50  # 命令队列容量

# ── 默认端口 ──
DEFAULT_APP_PORT = 50721  # 应用默认端口
