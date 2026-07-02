from .browser import BrowserContextManager
from .config_utils import validate_env_config
from .exceptions import LoginCancelledError
from .logging import (
    DashboardSink,
    LogConfigCenter,
    get_logger,
)
from .time_utils import is_in_pause_period, is_pause_enabled


def str_to_bool(value: str) -> bool:
    """将字符串值转换为布尔值。接受: true/1/yes/on（大小写不敏感）"""
    return str(value).strip().lower() in ("true", "1", "yes", "on")


__all__ = [
    "BrowserContextManager",
    "DashboardSink",
    "LogConfigCenter",
    "LoginCancelledError",
    "get_logger",
    "is_in_pause_period",
    "is_pause_enabled",
    "str_to_bool",
    "validate_env_config",
]
