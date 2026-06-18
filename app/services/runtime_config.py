"""运行时配置合并 — 从 SystemSettings + AuthProfile 合并出 MonitorConfigPayload。"""

from __future__ import annotations

from app.schemas import AuthProfile, GLOBAL_SETTINGS_FIELDS, MonitorConfigPayload, ProfilesData
from app.utils.crypto import decrypt_password, mask_password
from app.utils.exceptions import DecryptionError
from app.utils.logging import get_logger, normalize_level

from .profile_service import ProfileService

config_logger = get_logger("runtime_config", source="backend")

# Profile override fields: profile values take precedence over global defaults.
# See GLOBAL_SETTINGS_FIELDS for the complete set.
# Global values act as defaults when profile values are empty.
PROFILE_OVERRIDE_FIELDS = frozenset({
    "auth_url",
    "carrier",
    "carrier_custom",
    "active_task",
})

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

    # 获取活动 profile
    profile = data.profiles.get(data.active_profile)
    if profile is None:
        profile = data.profiles.get("default", AuthProfile())

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

    # 合并 global_settings 中的系统配置和监控配置
    # 使用 GLOBAL_SETTINGS_FIELDS 选取 SystemSettings 与 MonitorConfigPayload 的共享字段，
    # 一次 model_dump 替代 53 行逐字段取值。
    # 注：source_levels 仅在 SystemSettings 中，不在 MonitorConfigPayload 中，
    # 因此不在交集中——这与重构前行为一致（MonitorConfigPayload(**payload_dict) 同样会丢弃该键）。
    # 先用全局值填充，再用 profile 的非空值覆盖 PROFILE_OVERRIDE_FIELDS 中的字段。
    # 这实现了"留空则使用全局"的语义。
    gs_dict = data.global_settings.model_dump(include=GLOBAL_SETTINGS_FIELDS)
    payload_dict.update(gs_dict)

    # Profile override: profile 非空值优先于全局值
    for field in PROFILE_OVERRIDE_FIELDS:
        profile_val = getattr(profile, field, "")
        if profile_val:
            payload_dict[field] = profile_val

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
    """加载运行时配置 —— 从 profile 和 global_settings 合并。"""
    return _build_config_payload(profile_service, data, apply_overrides=True)
