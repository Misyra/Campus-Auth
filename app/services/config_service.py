"""配置服务 — 系统设置的读写与保存。"""

from __future__ import annotations

from typing import Any

from app.schemas import GlobalSettings, MonitorConfigPayload, ProfilesData, ProfileSettings, SystemSettings
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
        pwd_raw = payload.password.strip()
        if pwd_raw and not pwd_raw.startswith("•"):
            profile.password = save_password_field(pwd_raw, profile.password)
        profile.auth_url = payload.auth_url.strip()
        profile.carrier = str(payload.carrier or "无").strip()
        profile.carrier_custom = str(payload.carrier_custom or "").strip()
        profile.active_task = payload.active_task.strip()

        # 更新监控配置
        profile.check_interval_seconds = payload.check_interval_seconds
        profile.pause_enabled = payload.pause_enabled
        profile.pause_start_hour = payload.pause_start_hour
        profile.pause_end_hour = payload.pause_end_hour
        profile.network_targets = payload.network_targets
        profile.http_targets = payload.http_targets
        profile.enable_tcp_check = payload.enable_tcp_check
        profile.enable_http_check = payload.enable_http_check
        profile.enable_local_check = payload.enable_local_check
        profile.check_auth_url = payload.check_auth_url
        profile.auth_url_targets = payload.auth_url_targets
        profile.url_check_urls = payload.url_check_urls
        profile.network_check_timeout = payload.network_check_timeout

        # 更新浏览器配置
        profile.headless = payload.headless
        profile.browser_timeout = payload.browser_timeout
        profile.browser_navigation_timeout = payload.browser_navigation_timeout
        profile.login_timeout = payload.login_timeout
        profile.browser_user_agent = payload.browser_user_agent
        profile.browser_low_resource_mode = payload.browser_low_resource_mode
        profile.browser_disable_web_security = payload.browser_disable_web_security
        profile.browser_extra_headers_json = payload.browser_extra_headers_json
        profile.browser_args = payload.browser_args
        profile.stealth_mode = payload.stealth_mode
        profile.stealth_custom_script = payload.stealth_custom_script
        profile.browser_locale = payload.browser_locale
        profile.browser_timezone = payload.browser_timezone
        profile.browser_viewport_width = payload.browser_viewport_width
        profile.browser_viewport_height = payload.browser_viewport_height

        # 更新自定义变量
        profile.custom_variables = payload.custom_variables

        config_logger.info(
            "配置已保存: profile={}, 用户={}",
            active_profile,
            profile.username,
        )

    profile_service.update(_apply)


def build_runtime_config(
    payload: MonitorConfigPayload, system_settings: SystemSettings | None = None
) -> dict[str, Any]:
    """从 MonitorConfigPayload 构建运行时配置字典。

    ⚠ 返回字典包含明文 password 字段，切勿整体记录到日志中。
    """
    from app.utils.config_utils import assign_profile_fields
    from app.utils.crypto import decrypt_password
    from app.utils.exceptions import DecryptionError
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
    elif system_settings:
        pwd = ""
        if system_settings.password:
            try:
                pwd = decrypt_password(system_settings.password)
            except DecryptionError:
                config_logger.error("系统密码解密失败")
        base["password"] = pwd

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

    # 浏览器配置
    base["browser_settings"] = {
        "headless": payload.headless,
        "timeout": payload.browser_timeout,
        "navigation_timeout": payload.browser_navigation_timeout,
        "user_agent": payload.browser_user_agent.strip(),
        "low_resource_mode": payload.browser_low_resource_mode,
        "disable_web_security": payload.browser_disable_web_security,
        "extra_headers_json": payload.browser_extra_headers_json,
        "browser_args": payload.browser_args.strip(),
        "stealth_mode": payload.stealth_mode,
        "stealth_custom_script": payload.stealth_custom_script.strip(),
        "locale": payload.browser_locale.strip(),
        "timezone_id": payload.browser_timezone.strip(),
        "viewport_width": payload.browser_viewport_width,
        "viewport_height": payload.browser_viewport_height,
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

    # 重试策略从系统设置读取
    if system_settings:
        base["retry_settings"] = {
            "max_retries": system_settings.max_retries,
            "retry_interval": system_settings.retry_interval,
        }

    return base
