from .browser import BrowserContextManager
from .config import ConfigValidator
from .crypto import decrypt_password, encrypt_password, mask_password
from .exceptions import LoginCancelledError
from .logging import (
    LogConfigCenter,
    get_logger,
    setup_logger,
)
from .login import LoginAttemptHandler
from .time_utils import TimeUtils, get_runtime_stats


def str_to_bool(value: str) -> bool:
    """将字符串值转换为布尔值。接受: true/1/yes/on（大小写不敏感）"""
    return str(value).strip().lower() in ("true", "1", "yes", "on")


__all__ = [
    "setup_logger",
    "get_logger",
    "LogConfigCenter",
    "LoginCancelledError",
    "TimeUtils",
    "get_runtime_stats",
    "ConfigValidator",
    "BrowserContextManager",
    "LoginAttemptHandler",
    "encrypt_password",
    "decrypt_password",
    "mask_password",
    "str_to_bool",
]
