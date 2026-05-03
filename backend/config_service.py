from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.utils.crypto import decrypt_password, encrypt_password, mask_password

from .profile_service import ProfileService
from .schemas import (
    VALID_LOG_LEVELS,
    MonitorConfigPayload,
    ProfileSettings,
    SystemSettings,
)


def _normalize_level(raw: str, default: str = "WARNING") -> str:
    level = str(raw or default).upper().strip()
    return level if level in VALID_LOG_LEVELS else default


def _normalize_targets(raw: str) -> str:
    parts = [item.strip() for item in str(raw or "").split(",") if item.strip()]
    if not parts:
        return "8.8.8.8:53,114.114.114.114:53,www.baidu.com:443"
    return ",".join(parts)


def _normalize_headers_json(raw: str) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"浏览器请求头 JSON 格式错误: {e}") from e
    if not isinstance(parsed, dict):
        raise ValueError("浏览器请求头必须是 JSON 对象")

    return json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))


def load_ui_config(profile_service: ProfileService) -> MonitorConfigPayload:
    data = profile_service.load()
    sys = data.system
    profile = profile_service.get_active_profile()

    # 账号密码：方案独立 > 全局
    use_global = True
    if profile and not profile.use_global_credentials and profile.username:
        username = profile.username
        use_global = False
        raw_pwd = profile.password or ""
        if raw_pwd.startswith("ENC:"):
            password = mask_password(decrypt_password(raw_pwd))
        elif raw_pwd.startswith("•"):
            password = raw_pwd
        elif raw_pwd:
            password = mask_password(raw_pwd)
        else:
            password = mask_password(sys.password)
    else:
        username = sys.username
        password = mask_password(sys.password)

    # 认证地址：跟随全局或使用方案独立值
    if not profile or profile.use_global_auth_url:
        auth_url = sys.auth_url
    else:
        auth_url = profile.auth_url

    # 任务：跟随全局或使用方案独立任务
    if not profile or profile.use_global_task:
        active_task = ""
    else:
        active_task = profile.active_task
    # 运营商：跟随全局账号密码开关
    if not profile or profile.use_global_credentials:
        carrier = sys.carrier
        carrier_custom = sys.carrier_custom
    else:
        carrier = profile.carrier
        carrier_custom = profile.carrier_custom

    # 高级设置：use_global_advanced 时使用 default 方案的值，否则使用方案独立值
    if profile and not profile.use_global_advanced:
        check_interval_minutes = profile.check_interval_minutes
        auto_start = profile.auto_start
        headless = profile.headless
        browser_timeout = profile.browser_timeout
        browser_user_agent = profile.browser_user_agent
        browser_low_resource_mode = profile.browser_low_resource_mode
        browser_disable_web_security = profile.browser_disable_web_security
        browser_extra_headers_json = profile.browser_extra_headers_json
        browser_args = profile.browser_args
        pause_enabled = profile.pause_enabled
        pause_start_hour = profile.pause_start_hour
        pause_end_hour = profile.pause_end_hour
        network_targets = _normalize_targets(profile.network_targets)
        custom_variables = profile.custom_variables
    else:
        # 使用 default 方案的实际配置值（而非硬编码默认值）
        global_profile = data.profiles.get("default", ProfileSettings())
        check_interval_minutes = global_profile.check_interval_minutes
        auto_start = global_profile.auto_start
        headless = global_profile.headless
        browser_timeout = global_profile.browser_timeout
        browser_user_agent = global_profile.browser_user_agent
        browser_low_resource_mode = global_profile.browser_low_resource_mode
        browser_disable_web_security = global_profile.browser_disable_web_security
        browser_extra_headers_json = global_profile.browser_extra_headers_json
        browser_args = global_profile.browser_args
        pause_enabled = global_profile.pause_enabled
        pause_start_hour = global_profile.pause_start_hour
        pause_end_hour = global_profile.pause_end_hour
        network_targets = _normalize_targets(global_profile.network_targets)
        custom_variables = global_profile.custom_variables

    return MonitorConfigPayload(
        username=username,
        password=password,
        use_global_credentials=use_global,
        auth_url=auth_url,
        active_task=active_task,
        carrier=carrier,
        carrier_custom=carrier_custom,
        check_interval_minutes=check_interval_minutes,
        auto_start=auto_start,
        headless=headless,
        browser_timeout=browser_timeout,
        browser_user_agent=browser_user_agent,
        browser_low_resource_mode=browser_low_resource_mode,
        browser_disable_web_security=browser_disable_web_security,
        browser_extra_headers_json=browser_extra_headers_json,
        browser_args=browser_args,
        pause_enabled=pause_enabled,
        pause_start_hour=pause_start_hour,
        pause_end_hour=pause_end_hour,
        network_targets=network_targets,
        backend_log_level=_normalize_level(sys.backend_log_level),
        frontend_log_level=_normalize_level(sys.frontend_log_level),
        access_log=sys.access_log,
        minimize_to_tray=sys.minimize_to_tray,
        custom_variables=custom_variables,
    )


def build_runtime_config(payload: MonitorConfigPayload, sys: SystemSettings | None = None) -> dict[str, Any]:
    """从 MonitorConfigPayload 构建运行时配置字典。

    Args:
        payload: 前端传来的合并配置
        sys: settings.json 中的系统设置（用于读取重试策略等非 UI 字段）
    """
    base: dict[str, Any] = {}

    base["username"] = payload.username.strip()
    raw_password = payload.password.strip()
    if raw_password and not raw_password.startswith("•"):
        base["password"] = raw_password
    elif sys:
        base["password"] = decrypt_password(sys.password) if sys.password else ""

    base["auth_url"] = payload.auth_url.strip()
    base["active_task"] = payload.active_task.strip()
    carrier = str(payload.carrier or "无").strip() or "无"
    custom_isp = str(payload.carrier_custom or "").strip()
    if carrier == "自定义":
        base["isp"] = custom_isp
    elif carrier == "无":
        base["isp"] = ""
    else:
        base["isp"] = carrier
    base["auto_start_monitoring"] = payload.auto_start

    browser = base.setdefault("browser_settings", {})
    browser["headless"] = payload.headless
    browser["timeout"] = payload.browser_timeout
    browser["user_agent"] = payload.browser_user_agent.strip()
    browser["low_resource_mode"] = payload.browser_low_resource_mode
    browser["disable_web_security"] = payload.browser_disable_web_security
    browser["extra_headers_json"] = _normalize_headers_json(
        payload.browser_extra_headers_json
    )
    browser["browser_args"] = payload.browser_args.strip()

    pause = base.setdefault("pause_login", {})
    pause["enabled"] = payload.pause_enabled
    pause["start_hour"] = payload.pause_start_hour
    pause["end_hour"] = payload.pause_end_hour

    monitor = base.setdefault("monitor", {})
    monitor["interval"] = payload.check_interval_minutes * 60
    monitor["ping_targets"] = [
        item.strip() for item in payload.network_targets.split(",") if item.strip()
    ]

    backend_level = _normalize_level(payload.backend_log_level)
    frontend_level = _normalize_level(payload.frontend_log_level)

    logging_config = base.setdefault("logging", {})
    logging_config["level"] = backend_level

    frontend_logging = base.setdefault("frontend_logging", {})
    frontend_logging["level"] = frontend_level

    base["access_log"] = payload.access_log
    base["minimize_to_tray"] = payload.minimize_to_tray
    base["custom_variables"] = payload.custom_variables

    # 重试策略从系统设置读取
    if sys:
        base["retry_settings"] = {
            "max_retries": sys.max_retries,
            "retry_interval": sys.retry_interval,
        }

    return base


def _save_password_field(raw: str, existing_encrypted: str) -> str:
    """处理前端提交的密码：掩码不更新，明文则加密存储"""
    if not raw or raw.startswith("•"):
        return existing_encrypted or ""
    return encrypt_password(raw)


def write_system_settings(payload: MonitorConfigPayload, profile_service: ProfileService) -> None:
    """将系统级设置写入 settings.json 的 system 字段"""
    data = profile_service.load()
    sys = data.system

    if payload.use_global_credentials:
        sys.username = payload.username.strip()
        sys.password = _save_password_field(payload.password.strip(), sys.password)

    sys.auth_url = payload.auth_url.strip()
    sys.carrier = str(payload.carrier or "无").strip()
    sys.carrier_custom = str(payload.carrier_custom or "").strip()
    sys.backend_log_level = _normalize_level(payload.backend_log_level)
    sys.frontend_log_level = _normalize_level(payload.frontend_log_level)
    sys.access_log = payload.access_log
    sys.minimize_to_tray = payload.minimize_to_tray

    data.system = sys
    profile_service.save(data)


def save_profile_from_payload(
    payload: MonitorConfigPayload, project_root: Path,
    profile_service: ProfileService | None = None,
) -> None:
    """从 MonitorConfigPayload 提取 profile 字段并保存到 settings.json"""
    ps = profile_service or ProfileService(project_root)
    active_id = ps.get_active_profile_id()
    existing = ps.get_active_profile()

    # 保留原有的匹配规则和凭证设置
    updated = ProfileSettings(
        name=existing.name,
        match_gateway_ip=existing.match_gateway_ip,
        match_ssid=existing.match_ssid,
        username=existing.username,
        password=existing.password,
        use_global_credentials=existing.use_global_credentials,
        use_global_advanced=existing.use_global_advanced,
        use_global_auth_url=existing.use_global_auth_url,
        use_global_task=existing.use_global_task,
        auth_url=existing.auth_url if existing.use_global_auth_url else payload.auth_url.strip(),
        active_task=existing.active_task,
        carrier=existing.carrier if existing.use_global_credentials else str(payload.carrier or "无").strip(),
        carrier_custom=existing.carrier_custom if existing.use_global_credentials else str(payload.carrier_custom or "").strip(),
        check_interval_minutes=payload.check_interval_minutes,
        auto_start=payload.auto_start,
        headless=payload.headless,
        browser_timeout=payload.browser_timeout,
        browser_user_agent=payload.browser_user_agent.strip(),
        browser_low_resource_mode=payload.browser_low_resource_mode,
        browser_disable_web_security=payload.browser_disable_web_security,
        browser_extra_headers_json=_normalize_headers_json(
            payload.browser_extra_headers_json
        ),
        browser_args=payload.browser_args.strip(),
        pause_enabled=payload.pause_enabled,
        pause_start_hour=payload.pause_start_hour,
        pause_end_hour=payload.pause_end_hour,
        network_targets=_normalize_targets(payload.network_targets),
        custom_variables=payload.custom_variables,
    )

    ps.save_profile(active_id, updated)
