"""配置服务 — 系统设置的读写与保存。"""

from __future__ import annotations

from typing import Any

from app.schemas import (
    GlobalSettings,
    MonitorConfigPayload,
    ProfilesData,
    ProfileSettings,
)
from app.utils.logging import get_logger, normalize_level

from .profile_service import ProfileService

config_logger = get_logger("config_service", source="backend")


def _update_global_settings(
    global_settings: GlobalSettings, payload: MonitorConfigPayload
) -> None:
    """更新全局系统设置（不包含凭证）"""
    global_settings.backend_log_level = normalize_level(
        payload.backend_log_level, "WARNING"
    )
    global_settings.frontend_log_level = normalize_level(
        payload.frontend_log_level, "WARNING"
    )
    global_settings.access_log = payload.access_log
    global_settings.log_retention_days = payload.log_retention_days
    global_settings.minimize_to_tray = payload.minimize_to_tray
    global_settings.auto_open_browser = payload.auto_open_browser
    global_settings.startup_action = payload.startup_action
    global_settings.autostart_lightweight = payload.autostart_lightweight
    global_settings.proxy = payload.proxy.strip()
    global_settings.block_proxy = payload.block_proxy
    global_settings.app_port = payload.app_port
    global_settings.shell_path = payload.shell_path
    global_settings.max_retries = payload.max_retries
    global_settings.retry_interval = payload.retry_interval

    # 监控配置
    global_settings.check_interval_seconds = payload.check_interval_seconds
    global_settings.pause_enabled = payload.pause_enabled
    global_settings.pause_start_hour = payload.pause_start_hour
    global_settings.pause_end_hour = payload.pause_end_hour
    global_settings.network_targets = payload.network_targets
    global_settings.http_targets = payload.http_targets
    global_settings.enable_tcp_check = payload.enable_tcp_check
    global_settings.enable_http_check = payload.enable_http_check
    global_settings.enable_local_check = payload.enable_local_check
    global_settings.check_auth_url = payload.check_auth_url
    global_settings.auth_url_targets = payload.auth_url_targets
    global_settings.url_check_urls = payload.url_check_urls
    global_settings.network_check_timeout = payload.network_check_timeout

    # 浏览器配置
    global_settings.browser_channel = payload.browser_channel
    global_settings.browser_custom_path = payload.browser_custom_path.strip()
    global_settings.headless = payload.headless
    global_settings.browser_timeout = payload.browser_timeout
    global_settings.browser_navigation_timeout = payload.browser_navigation_timeout
    global_settings.login_timeout = payload.login_timeout
    global_settings.browser_user_agent = payload.browser_user_agent
    global_settings.browser_low_resource_mode = payload.browser_low_resource_mode
    global_settings.browser_disable_web_security = payload.browser_disable_web_security
    global_settings.browser_extra_headers_json = payload.browser_extra_headers_json
    global_settings.browser_args = payload.browser_args
    global_settings.stealth_mode = payload.stealth_mode
    global_settings.stealth_custom_script = payload.stealth_custom_script
    global_settings.browser_locale = payload.browser_locale
    global_settings.browser_timezone = payload.browser_timezone
    global_settings.browser_viewport_width = payload.browser_viewport_width
    global_settings.browser_viewport_height = payload.browser_viewport_height
    global_settings.pure_mode = payload.pure_mode

    # 轻量模式托盘
    global_settings.lightweight_tray = payload.lightweight_tray

    # 自定义变量
    global_settings.custom_variables = payload.custom_variables


def save_config_combined(
    payload: MonitorConfigPayload,
    profile_service: ProfileService,
) -> None:
    """原子化保存配置到活动 profile 和 global_settings。"""

    def _apply(data: ProfilesData) -> None:
        # 更新全局设置（不包含凭证）
        _update_global_settings(data.global_settings, payload)

        # 确保活动 profile 存在
        active_profile = data.active_profile
        if active_profile not in data.profiles:
            data.profiles[active_profile] = ProfileSettings()
            config_logger.info("已自动初始化活动方案: {}", active_profile)

        # 更新活动 profile
        profile = data.profiles[active_profile]

        # 更新凭证
        from app.utils.crypto import save_password_field
        profile.username = payload.username.strip()
        profile.password = save_password_field(payload.password, profile.password)
        profile.auth_url = payload.auth_url.strip()
        profile.carrier = str(payload.carrier or "无").strip()
        profile.carrier_custom = str(payload.carrier_custom or "").strip()
        profile.active_task = payload.active_task.strip()

        config_logger.info(
            "配置已保存: profile={}, 用户={}",
            active_profile,
            profile.username,
        )

    profile_service.update(_apply)


def build_runtime_config(
    payload: MonitorConfigPayload,
    global_settings: GlobalSettings | None = None,
) -> dict[str, Any]:
    """从 MonitorConfigPayload 构建运行时配置字典。

    ⚠ 返回字典包含明文 password 字段，切勿整体记录到日志中。
    """
    from app.utils.config_utils import assign_profile_fields
    from app.utils.network import parse_url_checks

    config_logger.debug(
        "构建运行时配置: 用户={}, 认证地址={}", payload.username, payload.auth_url
    )

    # 账号密码
    base: dict[str, Any] = {"password": ""}
    base["username"] = payload.username.strip()
    raw_password = payload.password.strip()
    if raw_password and not raw_password.startswith("•"):
        base["password"] = raw_password
    # GlobalSettings 没有 password 字段，删除不可达的回退代码

    base["auth_url"] = payload.auth_url.strip()
    base["active_task"] = payload.active_task.strip()

    # 运营商
    carrier = str(payload.carrier or "无").strip() or "无"
    custom_isp = str(payload.carrier_custom or "").strip()
    if carrier == "自定义":
        base["isp"] = custom_isp
    elif carrier == "无":
        base["isp"] = ""
    else:
        base["isp"] = carrier

    # 浏览器配置 — 从 GlobalSettings 获取
    if global_settings:
        base["browser_settings"] = {
            "headless": global_settings.headless,
            "timeout": global_settings.browser_timeout,
            "navigation_timeout": global_settings.browser_navigation_timeout,
            "user_agent": global_settings.browser_user_agent.strip(),
            "low_resource_mode": global_settings.browser_low_resource_mode,
            "disable_web_security": global_settings.browser_disable_web_security,
            "extra_headers_json": global_settings.browser_extra_headers_json,
            "browser_args": global_settings.browser_args.strip(),
            "stealth_mode": global_settings.stealth_mode,
            "stealth_custom_script": global_settings.stealth_custom_script.strip(),
            "locale": global_settings.browser_locale.strip(),
            "timezone_id": global_settings.browser_timezone.strip(),
            "viewport_width": global_settings.browser_viewport_width,
            "viewport_height": global_settings.browser_viewport_height,
            "pure_mode": global_settings.pure_mode,
            "browser_channel": global_settings.browser_channel,
            "browser_custom_path": global_settings.browser_custom_path.strip(),
        }
    else:
        # 回退：使用默认值
        base["browser_settings"] = {
            "headless": True,
            "timeout": 8,
            "navigation_timeout": 15,
            "user_agent": "",
            "low_resource_mode": False,
            "disable_web_security": False,
            "extra_headers_json": "",
            "browser_args": "",
            "stealth_mode": False,
            "stealth_custom_script": "",
            "locale": "zh-CN",
            "timezone_id": "Asia/Shanghai",
            "viewport_width": 1280,
            "viewport_height": 720,
            "pure_mode": True,
            "browser_channel": "playwright",
            "browser_custom_path": "",
        }

    # 暂停时段
    base["pause_login"] = {
        "enabled": payload.pause_enabled,
        "start_hour": payload.pause_start_hour,
        "end_hour": payload.pause_end_hour,
    }

    # 监控检测
    base["monitor"] = {
        "interval": payload.check_interval_seconds,
        "ping_targets": [
            item.strip() for item in payload.network_targets.split(",") if item.strip()
        ],
        "enable_tcp_check": payload.enable_tcp_check,
        "enable_http_check": payload.enable_http_check,
        "enable_local_check": payload.enable_local_check,
        "test_urls": [
            item.strip() for item in payload.http_targets.split(",") if item.strip()
        ],
        "check_auth_url": payload.check_auth_url,
        "auth_url_targets": [
            item.strip() for item in payload.auth_url_targets.split(",") if item.strip()
        ],
        "url_check_urls": parse_url_checks(payload.url_check_urls),
        "network_check_timeout": payload.network_check_timeout,
    }

    # 日志级别
    base["logging"] = {"level": normalize_level(payload.backend_log_level, "WARNING")}
    base["frontend_logging"] = {
        "level": normalize_level(payload.frontend_log_level, "WARNING")
    }

    # 其他字段
    assign_profile_fields(
        base,
        payload.model_dump(),
        [
            "access_log",
            "minimize_to_tray",
            "startup_action",
            "autostart_lightweight",
            "log_retention_days",
            "custom_variables",
            "block_proxy",
            "shell_path",
        ],
    )

    # 重试策略从全局设置读取
    if global_settings:
        base["retry_settings"] = {
            "max_retries": global_settings.max_retries,
            "retry_interval": global_settings.retry_interval,
        }

    return base
