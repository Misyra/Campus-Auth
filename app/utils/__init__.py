from .browser import BrowserContextManager
from .config import ConfigValidator
from .crypto import decrypt_password, encrypt_password, mask_password
from .exceptions import LoginCancelledError
from .logging import (
    DashboardSink,
    LogConfigCenter,
    get_logger,
)
from .login import LoginAttemptHandler
from .time_utils import get_runtime_stats, is_in_pause_period


def str_to_bool(value: str) -> bool:
    """将字符串值转换为布尔值。接受: true/1/yes/on（大小写不敏感）"""
    return str(value).strip().lower() in ("true", "1", "yes", "on")


__all__ = [
    "BrowserContextManager",
    "ConfigValidator",
    "DashboardSink",
    "LogConfigCenter",
    "LoginAttemptHandler",
    "LoginCancelledError",
    "decrypt_password",
    "encrypt_password",
    "get_logger",
    "get_runtime_stats",
    "is_in_pause_period",
    "mask_password",
    "str_to_bool",
]
