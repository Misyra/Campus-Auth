"""配置服务 — 系统设置的读写与保存。"""

from __future__ import annotations

from typing import Any

from app.schemas import MonitorConfigPayload, ProfilesData, ProfileSettings, SystemSettings
from app.utils.logging import get_logger, normalize_level

from .profile_service import ProfileService

config_logger = get_logger("config_service", source="backend")


def _update_system_settings(
    system_settings: SystemSettings, payload: MonitorConfigPayload
) -> None:
    """更新系统设置字段。"""
    from app.utils.crypto import save_password_field

    pwd_raw = payload.password.strip()
    old_user = system_settings.username
    system_settings.username = payload.username.strip()
    system_settings.password = save_password_field(pwd_raw, system_settings.password)
    pwd_status = "已更新" if (pwd_raw and not pwd_raw.startswith("•")) else "保留"
    config_logger.info("系统设置已保存: 用户={}", system_settings.username)
    config_logger.debug("密码状态: {}, 旧用户名: {}", pwd_status, old_user)

    # 直接映射的系统字段
    field_list = [
        "access_log",
        "minimize_to_tray",
        "startup_action",
        "autostart_lightweight",
        "auto_open_browser",
        "max_retries",
        "retry_interval",
        "log_retention_days",
        "block_proxy",
        "network_check_timeout",
        "app_port",
        "shell_path",
    ]
    update_data = {
        k: v
        for k, v in payload.model_dump().items()
        if k in field_list and v is not None
    }
    merged = {**system_settings.model_dump(), **update_data}
    validated = type(system_settings).model_validate(merged)
    for field in field_list:
        if field in update_data:
            setattr(system_settings, field, getattr(validated, field))
    # 需要归一化处理的系统字段
    system_settings.auth_url = payload.auth_url.strip()
    system_settings.carrier = str(payload.carrier or "无").strip()
    system_settings.carrier_custom = str(payload.carrier_custom or "").strip()
    system_settings.backend_log_level = normalize_level(
        payload.backend_log_level, "WARNING"
    )
    system_settings.frontend_log_level = normalize_level(
        payload.frontend_log_level, "WARNING"
    )
    system_settings.proxy = payload.proxy.strip()


def save_config_combined(
    payload: MonitorConfigPayload,
    profile_service: ProfileService,
) -> None:
    """原子化保存全局设置（system + default 方案）。

    设置页面始终修改全局配置，不涉及活动方案的独立字段。
    使用 profile_service.update() 保证 load→modify→save 原子性。
    """

    def _apply(data: ProfilesData) -> None:
        # 更新系统设置
        _update_system_settings(data.system, payload)

        # 确保 default 方案存在
        if "default" not in data.profiles:
            data.profiles["default"] = ProfileSettings()
            config_logger.info("已自动初始化默认方案")

        # 在锁内写日志，data 就是即将持久化的内容
        config_logger.info(
            "配置已保存: 用户={}, 活动方案={}",
            data.system.username,
            data.active_profile,
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
