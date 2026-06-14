"""运行时配置合并 — 从 SystemSettings + ProfileSettings 合并出 MonitorConfigPayload。"""

from __future__ import annotations

from app.constants import DEFAULT_NETWORK_TARGETS
from app.schemas import MonitorConfigPayload, ProfileSettings, ProfilesData
from app.utils.crypto import decrypt_password, mask_password
from app.utils.exceptions import DecryptionError
from app.utils.logging import get_logger, normalize_level

from .profile_service import ProfileService

config_logger = get_logger("runtime_config", source="backend")

def _safe_decrypt(ciphertext: str) -> tuple[str, bool]:
    """解密密码。返回 (解密结果, 是否有错误)"""
    if not ciphertext:
        return ("", False)
    try:
        return (decrypt_password(ciphertext), False)
    except DecryptionError:
        config_logger.error("密码解密失败，使用空密码")
        return ("", True)


def _decrypt_password_field(
    raw_pwd: str,
    fallback_pwd: str = "",
    label: str = "",
) -> tuple[str, bool]:
    """解密密码字段，支持 ENC: 前缀和掩码回退。"""
    if raw_pwd.startswith("ENC:"):
        return _safe_decrypt(raw_pwd)
    elif raw_pwd.startswith("•"):
        if fallback_pwd:
            return _safe_decrypt(fallback_pwd)
        else:
            if label:
                config_logger.warning("{} 密码为掩码但回退密码为空", label)
            return ("", False)
    elif raw_pwd:
        return (raw_pwd, False)
    else:
        if fallback_pwd:
            if label:
                config_logger.warning("{} 密码为空，使用回退密码", label)
            return _safe_decrypt(fallback_pwd)
        else:
            return ("", False)


def _normalize_targets(raw: str) -> str:
    parts = [item.strip() for item in str(raw or "").split(",") if item.strip()]
    if not parts:
        return DEFAULT_NETWORK_TARGETS
    return ",".join(parts)


def _build_config_payload(
    profile_service: ProfileService,
    data: ProfilesData | None = None,
    *,
    apply_overrides: bool = False,
) -> tuple[MonitorConfigPayload, bool]:
    """构建配置 payload 的通用逻辑。

    Args:
        profile_service: 方案服务
        data: 已加载的方案数据（为 None 时自动加载）
        apply_overrides: 是否应用活动方案的覆盖值（运行时配置）

    Returns:
        (MonitorConfigPayload, has_decrypt_error)
    """
    if data is None:
        data = profile_service.load()

    # 执行迁移（如果需要）
    data = migrate_config_if_needed(data)

    # 获取活动 profile
    profile = data.profiles.get(data.active_profile)
    if profile is None:
        profile = data.profiles.get("default", ProfileSettings())

    config_logger.debug("加载配置: profile={}", data.active_profile)

    # 从 profile 构建 payload
    payload_dict = profile.model_dump()

    # 处理密码
    any_error = False
    if apply_overrides:
        pwd, err = _decrypt_password_field(profile.password)
        payload_dict["password"] = pwd
        any_error = err
    else:
        payload_dict["password"] = mask_password(profile.password)

    # 合并 global_settings 中的系统配置
    payload_dict.update({
        "backend_log_level": data.global_settings.backend_log_level,
        "frontend_log_level": data.global_settings.frontend_log_level,
        "access_log": data.global_settings.access_log,
        "log_retention_days": data.global_settings.log_retention_days,
        "minimize_to_tray": data.global_settings.minimize_to_tray,
        "auto_open_browser": data.global_settings.auto_open_browser,
        "startup_action": data.global_settings.startup_action,
        "autostart_lightweight": data.global_settings.autostart_lightweight,
        "proxy": data.global_settings.proxy,
        "block_proxy": data.global_settings.block_proxy,
        "app_port": data.global_settings.app_port,
        "shell_path": data.global_settings.shell_path,
        "pure_mode": data.global_settings.pure_mode,
        "max_retries": data.global_settings.max_retries,
        "retry_interval": data.global_settings.retry_interval,
        "source_levels": data.global_settings.source_levels,
    })

    # 归一化
    payload_dict["backend_log_level"] = normalize_level(
        payload_dict.get("backend_log_level", "INFO"), "WARNING"
    )
    payload_dict["frontend_log_level"] = normalize_level(
        payload_dict.get("frontend_log_level", "INFO"), "WARNING"
    )

    result = MonitorConfigPayload(**payload_dict)
    return (result, any_error)


def load_ui_config(
    profile_service: ProfileService,
    data: ProfilesData | None = None,
) -> MonitorConfigPayload:
    """加载 UI 配置 —— 始终返回全局设置。"""
    payload, _ = _build_config_payload(profile_service, data, apply_overrides=False)
    return payload


def load_runtime_config(
    profile_service: ProfileService,
    data: ProfilesData | None = None,
) -> tuple[MonitorConfigPayload, bool]:
    """加载运行时配置 —— 根据活动方案的 use_global_* 标志合并全局与方案独立值。"""
    return _build_config_payload(profile_service, data, apply_overrides=True)


def migrate_config_if_needed(data: ProfilesData) -> ProfilesData:
    """迁移旧配置到新格式

    将 SystemSettings 中的凭证迁移到 default profile。
    """
    migration_logger = get_logger("config_migration", source="backend")

    # 检查是否有旧的 system 字段需要迁移
    # 注意：旧格式使用 data.system，新格式使用 data.global_settings
    if not hasattr(data, 'system'):
        return data

    system = data.system

    # 检查是否有凭证需要迁移
    has_credentials = any([
        getattr(system, 'username', None),
        getattr(system, 'password', None),
        getattr(system, 'auth_url', None),
        getattr(system, 'carrier', None) and getattr(system, 'carrier', None) != "无",
    ])

    if has_credentials:
        # 确保 default profile 存在
        if "default" not in data.profiles:
            data.profiles["default"] = ProfileSettings()

        default_profile = data.profiles["default"]

        # 迁移凭证到 default profile
        if getattr(system, 'username', None) and not default_profile.username:
            default_profile.username = system.username
        if getattr(system, 'password', None) and not default_profile.password:
            default_profile.password = system.password
        if getattr(system, 'auth_url', None) and not default_profile.auth_url:
            default_profile.auth_url = system.auth_url
        if getattr(system, 'carrier', None) and system.carrier != "无":
            default_profile.carrier = system.carrier
            default_profile.carrier_custom = getattr(system, 'carrier_custom', '')

        # 清空 system 中的凭证
        system.username = ""
        system.password = ""
        system.auth_url = ""
        system.carrier = "无"
        system.carrier_custom = ""

        migration_logger.info("已迁移凭证到 default profile")

    return data
