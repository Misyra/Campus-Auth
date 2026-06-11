from __future__ import annotations

import json
from typing import Any

from app.constants import DEFAULT_NETWORK_TARGETS
from app.schemas import (
    MonitorConfigPayload,
    ProfilesData,
    ProfileSettings,
    SystemSettings,
)
from app.utils.config_utils import (
    PROFILE_FIELDS,
    assign_profile_fields,
    extract_profile_fields,
)
from app.utils.crypto import decrypt_password, mask_password, save_password_field
from app.utils.exceptions import DecryptionError
from app.utils.logging import get_logger, normalize_level

from .profile_service import ProfileService

config_logger = get_logger("config_service", source="backend")

# 运行时配置中不应被方案高级设置覆盖的字段
_PROTECTED_KEYS = frozenset(
    {
        "username",
        "password",
        "auth_url",
        "active_task",
        "carrier",
        "carrier_custom",
        "use_global_credentials",
        "backend_log_level",
        "frontend_log_level",
    }
)


def _safe_decrypt(ciphertext: str) -> tuple[str, bool]:
    """解密密码。

    返回:
        (解密结果, 是否有错误): 错误时返回 ("", True)
    """
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
    """解密密码字段，支持 ENC: 前缀和掩码回退。

    参数:
        raw_pwd: 原始密码值（可能为 ENC: 密文、掩码、明文或空）
        fallback_pwd: 回退密码（当 raw_pwd 为掩码或空时使用）
        label: 日志标签（如方案名称）

    返回: (明文密码, 是否有解密错误)
    """
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


def _normalize_headers_json(raw: str) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"浏览器请求头格式不正确，请确认输入的是合法的 JSON 对象: {exc}"
        ) from exc
    if not isinstance(parsed, dict):
        raise ValueError(
            '浏览器请求头格式不正确，应为键值对形式，例如: {"Referer": "https://example.com"}'
        )

    return json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))


def _build_config_payload(
    profile_service: ProfileService,
    data: ProfilesData | None = None,
    *,
    apply_overrides: bool = False,
) -> MonitorConfigPayload | tuple[MonitorConfigPayload, bool]:
    """构建配置 payload 的通用逻辑。

    Args:
        profile_service: 方案服务
        data: 已加载的方案数据（为 None 时自动加载）
        apply_overrides: 是否应用活动方案的覆盖值（运行时配置）

    Returns:
        apply_overrides=False: MonitorConfigPayload
        apply_overrides=True: (MonitorConfigPayload, has_decrypt_error)
    """
    if data is None:
        data = profile_service.load()
    system_settings = data.system

    if apply_overrides:
        profile = data.profiles.get(data.active_profile)
        config_logger.debug("加载运行时配置: profile={}", data.active_profile)
    else:
        profile = None
        config_logger.debug(
            "加载 UI 配置（全局）: active_profile={}", data.active_profile
        )

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

        # 高级设置：从活动方案或 default 方案提取非凭证字段
        adv_source = (
            profile
            if profile and not profile.use_global_advanced
            else data.profiles.get("default", ProfileSettings())
        )
        payload_dict.update(
            {
                k: v
                for k, v in extract_profile_fields(
                    adv_source.model_dump(), PROFILE_FIELDS
                ).items()
                if k not in _PROTECTED_KEYS
            }
        )
    else:
        # UI 模式：合并 sys 和 default 方案字段
        global_profile = data.profiles.get("default", ProfileSettings())
        payload_dict.update(
            extract_profile_fields(global_profile.model_dump(), PROFILE_FIELDS)
        )
        payload_dict.update(
            extract_profile_fields(system_settings.model_dump(), PROFILE_FIELDS)
        )

        # UI 专属覆盖
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
    if apply_overrides:
        return (result, any_error)
    return result


def load_ui_config(
    profile_service: ProfileService,
    data: ProfilesData | None = None,
) -> MonitorConfigPayload:
    """加载 UI 配置 —— 始终返回全局设置。

    设置页面展示和修改的都是全局配置（system + default 方案），
    不随活动方案变化。方案独立的覆盖值在方案页面单独管理。
    """
    return _build_config_payload(profile_service, data, apply_overrides=False)


def load_runtime_config(
    profile_service: ProfileService,
    data: ProfilesData | None = None,
) -> tuple[MonitorConfigPayload, bool]:
    """加载运行时配置 —— 根据活动方案的 use_global_* 标志合并全局与方案独立值。

    与 load_ui_config 不同，此函数会按活动方案的覆盖标志来决定使用全局值还是方案独立值，
    确保运行时实际生效的配置与方案设置一致。

    返回:
        (配置, 是否有解密错误): 解密错误时配置中密码为空字符串
    """
    return _build_config_payload(profile_service, data, apply_overrides=True)


def _build_credential_config(
    payload: MonitorConfigPayload, system_settings: SystemSettings | None
) -> dict[str, Any]:
    """构建账号密码相关配置。"""
    credential_config: dict[str, Any] = {"password": ""}
    credential_config["username"] = payload.username.strip()
    raw_password = payload.password.strip()
    if raw_password and not raw_password.startswith("•"):
        credential_config["password"] = raw_password
    elif system_settings:
        pwd, _ = (
            _safe_decrypt(system_settings.password)
            if system_settings.password
            else ("", False)
        )
        credential_config["password"] = pwd
    return credential_config


def _build_browser_config(payload: MonitorConfigPayload) -> dict[str, Any]:
    """构建浏览器相关配置。"""
    return {
        "headless": payload.headless,
        "timeout": payload.browser_timeout,
        "navigation_timeout": payload.browser_navigation_timeout,
        "user_agent": payload.browser_user_agent.strip(),
        "low_resource_mode": payload.browser_low_resource_mode,
        "disable_web_security": payload.browser_disable_web_security,
        "extra_headers_json": _normalize_headers_json(
            payload.browser_extra_headers_json
        ),
        "browser_args": payload.browser_args.strip(),
        "stealth_mode": payload.stealth_mode,
        "stealth_custom_script": payload.stealth_custom_script.strip(),
        "locale": payload.browser_locale.strip(),
        "timezone_id": payload.browser_timezone.strip(),
        "viewport_width": payload.browser_viewport_width,
        "viewport_height": payload.browser_viewport_height,
    }


def _build_monitor_config(payload: MonitorConfigPayload) -> dict[str, Any]:
    """构建监控检测相关配置。"""
    from app.utils.network import parse_url_checks

    return {
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


def build_runtime_config(
    payload: MonitorConfigPayload, system_settings: SystemSettings | None = None
) -> dict[str, Any]:
    """从 MonitorConfigPayload 构建运行时配置字典。

    ⚠ 返回字典包含明文 password 字段，切勿整体记录到日志中。
    仅可安全记录 username、auth_url 等非敏感字段。

    Args:
        payload: 前端传来的合并配置
        system_settings: settings.json 中的系统设置（用于读取重试策略等非 UI 字段）
    """
    config_logger.debug(
        "构建运行时配置: 用户={}, 认证地址={}", payload.username, payload.auth_url
    )

    # 账号密码
    base = _build_credential_config(payload, system_settings)
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
    base["auto_start_monitoring"] = payload.auto_start

    # 浏览器配置
    base["browser_settings"] = _build_browser_config(payload)

    # 暂停时段
    base["pause_login"] = {
        "enabled": payload.pause_enabled,
        "start_hour": payload.pause_start_hour,
        "end_hour": payload.pause_end_hour,
    }

    # 监控检测
    base["monitor"] = _build_monitor_config(payload)

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
            "login_then_exit",
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


def _update_system_settings(
    system_settings: SystemSettings, payload: MonitorConfigPayload
) -> None:
    """更新系统设置字段。"""
    pwd_raw = payload.password.strip()
    old_user = system_settings.username
    system_settings.username = payload.username.strip()
    system_settings.password = save_password_field(pwd_raw, system_settings.password)
    config_logger.info(
        "保存系统设置: 用户={} (旧={}), 密码={}",
        system_settings.username,
        old_user,
        "已更新" if (pwd_raw and not pwd_raw.startswith("•")) else "保留",
    )

    # 直接映射的系统字段
    assign_profile_fields(
        system_settings.__dict__,
        payload.model_dump(),
        [
            "access_log",
            "minimize_to_tray",
            "lightweight_mode",
            "auto_open_browser",
            "login_then_exit",
            "max_retries",
            "retry_interval",
            "log_retention_days",
            "block_proxy",
            "network_check_timeout",
            "app_port",
            "shell_path",
        ],
    )
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


def _update_default_profile(
    default_profile: ProfileSettings, payload: MonitorConfigPayload
) -> None:
    """更新 default 方案的高级设置。"""
    # 直接映射的 profile 字段
    assign_profile_fields(
        default_profile.__dict__,
        payload.model_dump(),
        [
            "check_interval_seconds",
            "auto_start",
            "headless",
            "browser_timeout",
            "browser_navigation_timeout",
            "login_timeout",
            "browser_low_resource_mode",
            "browser_disable_web_security",
            "pause_enabled",
            "pause_start_hour",
            "pause_end_hour",
            "enable_tcp_check",
            "enable_http_check",
            "enable_local_check",
            "check_auth_url",
            "auth_url_targets",
            "url_check_urls",
            "stealth_mode",
            "stealth_custom_script",
            "custom_variables",
            "browser_viewport_width",
            "browser_viewport_height",
        ],
    )
    # 需要归一化处理的 profile 字段
    default_profile.browser_user_agent = payload.browser_user_agent.strip()
    default_profile.browser_extra_headers_json = _normalize_headers_json(
        payload.browser_extra_headers_json
    )
    default_profile.browser_args = payload.browser_args.strip()
    default_profile.browser_locale = payload.browser_locale.strip()
    default_profile.browser_timezone = payload.browser_timezone.strip()
    default_profile.network_targets = _normalize_targets(payload.network_targets)
    default_profile.http_targets = _normalize_targets(payload.http_targets)


def save_config_combined(
    payload: MonitorConfigPayload,
    profile_service: ProfileService,
) -> None:
    """原子化保存全局设置（system + default 方案）。

    设置页面始终修改全局配置，不涉及活动方案的独立字段。
    方案页面的独立设置通过 /api/profiles/{id} 单独保存。
    使用 profile_service.update() 保证 load→modify→save 原子性。
    """

    def _apply(data: ProfilesData) -> None:
        # 更新系统设置
        _update_system_settings(data.system, payload)

        # 更新 default 方案
        if "default" not in data.profiles:
            data.profiles["default"] = ProfileSettings()
            config_logger.info(
                "自动初始化 default 方案（settings.json 中无 default 键）"
            )
        _update_default_profile(data.profiles["default"], payload)

        # 在锁内写日志，data 就是即将持久化的内容
        config_logger.info(
            "配置已原子保存: system(user={}, pwd={}, auth={}), active_profile={}",
            data.system.username,
            "ENC" if data.system.password else "空",
            data.system.auth_url,
            data.active_profile,
        )

    profile_service.update(_apply)
