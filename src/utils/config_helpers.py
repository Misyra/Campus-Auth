"""Configuration helper utilities — field extraction, assignment, and constants.

Provides shared utilities used by backend/config_service.py to reduce
repetitive field-by-field assignment across load/save/build functions.
"""

from __future__ import annotations

from typing import Any

# 备份文件名正则，与 backend/main.py 中 3 处备份路由的 inline 校验保持一致
BACKUP_FILENAME_PATTERN: str = (
    r"^settings_\d{8}_\d{6}(_\d{6})?(_autosave)?\.json$"
)

# 配置文件中跨 load_ui_config / load_runtime_config / build_runtime_config /
# save_config_combined 四函数重复出现的所有字段名
# 源自 MonitorConfigPayload / ProfileSettings 交集
PROFILE_FIELDS: list[str] = [
    "username",
    "password",
    "auth_url",
    "active_task",
    "carrier",
    "carrier_custom",
    "check_interval_minutes",
    "auto_start",
    "headless",
    "browser_timeout",
    "login_timeout",
    "browser_user_agent",
    "browser_low_resource_mode",
    "browser_disable_web_security",
    "browser_extra_headers_json",
    "browser_args",
    "stealth_mode",
    "browser_locale",
    "browser_timezone",
    "pause_enabled",
    "pause_start_hour",
    "pause_end_hour",
    "network_targets",
    "network_strict_mode",
    "backend_log_level",
    "frontend_log_level",
    "access_log",
    "minimize_to_tray",
    "auto_open_browser",
    "login_then_exit",
    "max_retries",
    "retry_interval",
    "log_retention_days",
    "screenshot_retention_days",
    "custom_variables",
    "proxy",
    "block_proxy",
    "app_port",
    "network_check_timeout",
    "use_global_credentials",
]


def extract_profile_fields(
    source: dict, field_names: list[str]
) -> dict[str, Any]:
    """从 source 字典中提取指定字段，返回新字典。

    Args:
        source: 源字典（通常为 MonitorConfigPayload.model_dump() 结果）
        field_names: 需要提取的字段名列表

    Returns:
        仅包含 source 中存在的指定字段的新字典
    """
    return {name: source[name] for name in field_names if name in source}


def assign_profile_fields(
    target: dict, source: dict, field_names: list[str]
) -> None:
    """将 source 字典中的指定字段原地赋值到 target 字典。

    对于 field_names 中每个字段，如果 source 中存在则覆盖 target 中同名键。
    Args:
        target: 目标字典（原地修改）
        source: 源字典（通常为 MonitorConfigPayload.model_dump() 结果）
        field_names: 需要复制的字段名列表
    """
    for name in field_names:
        if name in source:
            target[name] = source[name]
