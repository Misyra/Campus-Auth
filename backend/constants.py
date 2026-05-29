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
