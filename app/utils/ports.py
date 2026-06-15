"""端口解析工具 — 从环境变量或 settings.json 读取应用端口。

独立于 FastAPI，避免加载 app.application 时引入不必要的依赖。
"""

from __future__ import annotations

import json
import os

from app.constants import PROJECT_ROOT
from app.utils.logging import get_logger

_startup_logger = get_logger("startup", source="backend")

# 默认端口
_DEFAULT_PORT = 50721


def resolve_port() -> int:
    """解析应用监听端口。

    优先级：环境变量 APP_PORT > config/settings.json global_settings.app_port > 默认 50721。
    """
    raw = os.getenv("APP_PORT", "").strip()
    if raw:
        try:
            port = int(raw)
            if 1 <= port <= 65535:
                return port
        except ValueError:
            _startup_logger.warning("端口解析失败，使用默认 {}", _DEFAULT_PORT)

    # 修正：读取 config/settings.json 而非 settings.json
    settings_path = PROJECT_ROOT / "config" / "settings.json"
    if settings_path.exists():
        try:
            data = json.loads(settings_path.read_text(encoding="utf-8"))
            # 修正：读取 global_settings.app_port 而非 system.app_port
            app_port = data.get("global_settings", {}).get("app_port")
            if app_port is not None:
                port = int(app_port)
                if 1 <= port <= 65535:
                    return port
        except (json.JSONDecodeError, ValueError, OSError) as exc:
            _startup_logger.warning(
                "读取 config/settings.json 端口配置失败，使用默认端口 {}: {}",
                _DEFAULT_PORT,
                exc,
            )

    return _DEFAULT_PORT
