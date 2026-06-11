#!/usr/bin/env python3
"""
配置工具模块 — 验证、字段提取与赋值、常量定义

合并自原 config.py（ConfigValidator）和 config_helpers.py
（PROFILE_FIELDS / extract / assign / validate）。
"""

from __future__ import annotations

from typing import Any

from app.utils.logging import get_logger

# ── 常量 ──────────────────────────────────────────────────────────────

# 配置文件中跨 load_ui_config / load_runtime_config / build_runtime_config /
# save_config_combined 四函数重复出现的所有字段名
# 源自 MonitorConfigPayload / ProfileSettings 交集
PROFILE_FIELDS: list[str] = [  # 常量，不应在运行时修改
    "username",
    "password",
    "auth_url",
    "active_task",
    "carrier",
    "carrier_custom",
    "check_interval_seconds",
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
    "stealth_custom_script",
    "browser_locale",
    "browser_timezone",
    "pause_enabled",
    "pause_start_hour",
    "pause_end_hour",
    "network_targets",
    "http_targets",
    "enable_tcp_check",
    "enable_http_check",
    "enable_local_check",
    "check_auth_url",
    "auth_url_targets",
    "url_check_urls",
    "backend_log_level",
    "frontend_log_level",
    "access_log",
    "minimize_to_tray",
    "auto_open_browser",
    "login_then_exit",
    "max_retries",
    "retry_interval",
    "log_retention_days",
    "custom_variables",
    "proxy",
    "block_proxy",
    "app_port",
    "network_check_timeout",
    "use_global_credentials",
    "shell_path",
    "browser_viewport_width",
    "browser_viewport_height",
    "browser_navigation_timeout",
]


# ── 字段提取 / 赋值 ──────────────────────────────────────────────────


def extract_profile_fields(source: dict, field_names: list[str]) -> dict[str, Any]:
    """从 source 字典中提取指定字段，返回新字典。

    Args:
        source: 源字典（通常为 MonitorConfigPayload.model_dump() 结果）
        field_names: 需要提取的字段名列表

    Returns:
        仅包含 source 中存在的指定字段的新字典
    """
    return {name: source[name] for name in field_names if name in source}


def assign_profile_fields(target: dict, source: dict, field_names: list[str]) -> None:
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


def validate_profile_fields() -> None:
    """验证 PROFILE_FIELDS 与 ProfileSettings 模型字段是否同步。

    在服务启动时调用，检测两者不一致时记录警告日志。
    """
    from app.schemas import ProfileSettings

    model_fields = set(ProfileSettings.model_fields.keys())
    hardcoded = set(PROFILE_FIELDS)

    only_in_model = model_fields - hardcoded
    only_in_hardcoded = hardcoded - model_fields

    logger = get_logger("config_helpers", source="backend")
    if only_in_model:
        logger.warning(
            "PROFILE_FIELDS 缺少以下 ProfileSettings 字段: {}",
            sorted(only_in_model),
        )
    if only_in_hardcoded:
        logger.warning(
            "PROFILE_FIELDS 中以下字段不在 ProfileSettings 中: {}",
            sorted(only_in_hardcoded),
        )


# ── 验证器 ────────────────────────────────────────────────────────────


class ConfigValidator:
    """配置验证工具类 - 统一管理配置验证逻辑"""

    @staticmethod
    def validate_gui_config(
        username: str, password: str, check_interval: str | int
    ) -> tuple[bool, str]:
        """
        验证GUI配置是否有效

        参数:
            username: 用户名
            password: 密码
            check_interval: 检测间隔（字符串或整数）

        返回:
            tuple[bool, str]: (是否有效, 错误信息)
        """
        # 验证必填字段
        username = username.strip()
        password = password.strip()

        # 掩码密码（"••••••••"）表示服务端已有加密密码，无需校验
        is_masked = password.startswith("•")

        if not username:
            return False, "账号不能为空"
        if not password and not is_masked:
            return False, "密码不能为空"

        # 验证账号格式（基本验证）
        if len(username) < 2:
            return False, "账号长度不能少于2位"

        # 验证密码格式（基本验证）— 跳过掩码
        if not is_masked and len(password) < 2:
            return False, "密码长度不能少于2位"

        # 验证检测间隔
        try:
            interval_int = int(check_interval)
            if interval_int < 1:
                return False, "检测间隔必须大于0"
            if interval_int > 86400:  # 24小时
                return False, "检测间隔不能超过 24 小时（86400 秒）"
        except (ValueError, TypeError):
            return False, "检测间隔必须是正整数"

        return True, ""

    @staticmethod
    def validate_env_config(config: dict) -> tuple[bool, str]:
        """
        验证环境配置是否完整

        参数:
            config: 配置字典

        返回:
            tuple[bool, str]: (是否有效, 错误信息)
        """
        # 检查必要配置
        username = config.get("username")
        password = config.get("password")
        auth_url = config.get("auth_url")

        if not username or not password:
            return False, "缺少用户名或密码"

        if not auth_url:
            return False, "缺少认证地址"

        if not auth_url.startswith(("http://", "https://")):
            return False, "认证地址必须以 http:// 或 https:// 开头"

        return True, ""
