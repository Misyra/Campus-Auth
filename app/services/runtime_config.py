"""运行时配置合并 — 从 SystemSettings + ProfileSettings 合并出 MonitorConfigPayload。"""

from __future__ import annotations

from app.constants import DEFAULT_NETWORK_TARGETS
from app.schemas import MonitorConfigPayload, ProfilesData, ProfileSettings, SystemSettings
from app.utils.config_utils import PROFILE_FIELDS, extract_profile_fields
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
    system_settings = data.system

    if apply_overrides:
        profile = data.profiles.get(data.active_profile)
        config_logger.debug("加载运行时配置: profile={}", data.active_profile)
    else:
        profile = None
        config_logger.debug("加载 UI 配置: profile={}", data.active_profile)

    # 从系统设置作为基础
    payload_dict = extract_profile_fields(system_settings.model_dump(), PROFILE_FIELDS)

    any_error = False

    if apply_overrides:
        # 账号密码：方案独立 > 全局；运行时使用解密明文
        use_global = True
        if profile and not profile.use_global_credentials and profile.username:
            payload_dict["username"] = profile.username
            use_global = False
            pwd, err = _decrypt_password_field(
                profile.password or "",
                fallback_pwd=system_settings.password or "",
                label=f"方案 '{data.active_profile}'",
            )
            payload_dict["password"] = pwd
            any_error = err
        else:
            payload_dict["username"] = system_settings.username
            pwd, err = _decrypt_password_field(system_settings.password or "")
            payload_dict["password"] = pwd
            any_error = err
        payload_dict["use_global_credentials"] = use_global

        # 认证地址：跟随全局或使用方案独立值
        if not profile or profile.use_global_auth_url:
            payload_dict["auth_url"] = system_settings.auth_url
        else:
            payload_dict["auth_url"] = profile.auth_url

        # 任务：跟随全局或使用方案独立任务
        if not profile or profile.use_global_task:
            payload_dict["active_task"] = ""
        else:
            payload_dict["active_task"] = profile.active_task

        # 运营商：跟随 use_global_credentials 标志
        if not profile or profile.use_global_credentials:
            payload_dict["carrier"] = system_settings.carrier
            payload_dict["carrier_custom"] = system_settings.carrier_custom
        else:
            payload_dict["carrier"] = profile.carrier
            payload_dict["carrier_custom"] = profile.carrier_custom
    else:
        # UI 模式：使用全局系统设置
        payload_dict["password"] = mask_password(system_settings.password)
        payload_dict["active_task"] = ""
        payload_dict["use_global_credentials"] = True

    # 公共归一化
    payload_dict["network_targets"] = _normalize_targets(
        payload_dict.get("network_targets", "")
    )
    payload_dict["http_targets"] = _normalize_targets(
        payload_dict.get("http_targets", "")
    )
    payload_dict["backend_log_level"] = normalize_level(
        system_settings.backend_log_level, "WARNING"
    )
    payload_dict["frontend_log_level"] = normalize_level(
        system_settings.frontend_log_level, "WARNING"
    )

    result = MonitorConfigPayload(**payload_dict)
    return (result, any_error if apply_overrides else False)


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
