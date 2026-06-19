"""配置服务 — 系统设置的读写与保存。"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

from app.schemas import (
    AuthProfile,
    GLOBAL_SETTINGS_FIELDS,
    MonitorConfigPayload,
    ProfilesData,
    SystemSettings,
)
from app.utils.logging import get_logger, normalize_level

from .profile_service import ProfileService

config_logger = get_logger("config_service", source="backend")

# 需要 .strip() 处理的字段
_STRIP_FIELDS = frozenset({"proxy", "browser_custom_path"})
# 需要 normalize_level() 处理的字段
_LOG_LEVEL_FIELDS = frozenset({"backend_log_level", "frontend_log_level"})


def _update_global_settings(
    global_settings: SystemSettings, payload: MonitorConfigPayload
) -> None:
    """更新全局系统设置（不包含凭证）。

    使用 GLOBAL_SETTINGS_FIELDS（SystemSettings 与 MonitorConfigPayload 的字段交集）
    驱动循环赋值，替代逐字段手写。特殊字段（strip、log level）在循环内单独处理。
    """
    for field in GLOBAL_SETTINGS_FIELDS:
        value = getattr(payload, field)
        if field in _STRIP_FIELDS and isinstance(value, str):
            value = value.strip()
        elif field in _LOG_LEVEL_FIELDS:
            value = normalize_level(value, "WARNING")
        setattr(global_settings, field, value)


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
            data.profiles[active_profile] = AuthProfile()
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


@dataclass
class SaveResult:
    """配置保存结果。"""

    success: bool
    message: str


def save_and_apply(
    payload: MonitorConfigPayload,
    profile_service: ProfileService,
    reload_fn,
) -> SaveResult:
    """保存配置并重载运行时状态。失败时自动回滚。

    Args:
        payload: 新配置
        profile_service: 方案服务
        reload_fn: 重载回调，返回 (ok: bool, msg: str)

    Returns:
        SaveResult 包含 success 和 message
    """
    # 备份当前配置，用于 reload 失败时回滚
    backup_data = copy.deepcopy(profile_service.load())

    # 原子化保存：系统设置 + 活动方案
    save_config_combined(payload, profile_service)

    # 重载运行时配置
    ok, msg = reload_fn()
    if not ok:
        config_logger.error("配置重载失败，正在回滚: {}", msg)
        try:
            profile_service.update(
                lambda data: _rollback_config(data, backup_data)
            )
            reload_fn()
        except Exception as rollback_exc:
            config_logger.error(
                "回滚失败（磁盘配置已回滚，运行时状态可能不一致）: {}",
                rollback_exc,
                exc_info=True,
            )
        return SaveResult(success=False, message=f"配置重载失败: {msg}")

    return SaveResult(success=True, message="配置保存成功")


def _rollback_config(data: ProfilesData, backup_data: ProfilesData) -> None:
    """回滚配置到备份状态。

    使用逐字段赋值而非 __dict__.update，确保 Pydantic 内部状态
    （如 model_fields_set）保持一致。
    """
    for field_name in ProfilesData.model_fields:
        setattr(data, field_name, getattr(backup_data, field_name))


def build_runtime_dict_from_payload(
    payload: MonitorConfigPayload,
    global_settings: SystemSettings | None = None,
) -> dict[str, Any]:
    """从 MonitorConfigPayload 构建运行时配置字典。

    ⚠ 返回字典包含明文 password 字段，切勿整体记录到日志中。
    """
    from app.utils.config_utils import PROFILE_RUNTIME_FIELDS, assign_profile_fields
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

    # 浏览器配置 — 从 SystemSettings 获取（无则使用默认实例）
    gs = global_settings or SystemSettings()
    base["browser_settings"] = {
        "headless": gs.headless,
        "timeout": gs.browser_timeout,
        "navigation_timeout": gs.browser_navigation_timeout,
        "user_agent": gs.browser_user_agent.strip(),
        "low_resource_mode": gs.browser_low_resource_mode,
        "disable_web_security": gs.browser_disable_web_security,
        "extra_headers_json": gs.browser_extra_headers_json,
        "browser_args": gs.browser_args.strip(),
        "stealth_mode": gs.stealth_mode,
        "stealth_custom_script": gs.stealth_custom_script.strip(),
        "locale": gs.browser_locale.strip(),
        "timezone_id": gs.browser_timezone.strip(),
        "viewport_width": gs.browser_viewport_width,
        "viewport_height": gs.browser_viewport_height,
        "pure_mode": gs.pure_mode,
        "browser_channel": gs.browser_channel,
        "browser_custom_path": gs.browser_custom_path.strip(),
        "custom_browser_engine": gs.custom_browser_engine,
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
    assign_profile_fields(base, payload.model_dump(), list(PROFILE_RUNTIME_FIELDS))

    # 重试策略
    base["retry_settings"] = {
        "max_retries": gs.max_retries,
        "retry_interval": gs.retry_interval,
    }

    return base
