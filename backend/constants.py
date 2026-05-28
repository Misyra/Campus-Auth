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
