"""端口解析工具 — 从环境变量读取应用端口。

独立于 FastAPI，避免加载 app.application 时引入不必要的依赖。
"""

from __future__ import annotations

import os

from app.utils.logging import get_logger

_startup_logger = get_logger("startup", source="backend")

# 默认端口
_DEFAULT_PORT = 50721


def resolve_port() -> int:
    """解析应用监听端口。

    优先级：环境变量 APP_PORT > 默认 50721。

    settings.json 中没有 app_port 字段，端口仅通过环境变量配置。
    """
    raw = os.getenv("APP_PORT", "").strip()
    if raw:
        try:
            port = int(raw)
            if 1 <= port <= 65535:
                return port
            _startup_logger.warning(
                "端口 {} 超出范围 1-65535，使用默认 {}", port, _DEFAULT_PORT
            )
        except ValueError:
            _startup_logger.warning("端口解析失败，使用默认 {}", _DEFAULT_PORT)

    return _DEFAULT_PORT
