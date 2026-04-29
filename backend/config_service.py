from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from src.utils import ConfigLoader
from src.utils.crypto import decrypt_password, encrypt_password, mask_password

from .schemas import DEFAULT_BROWSER_USER_AGENT, MonitorConfigPayload, ProfileSettings

BUILTIN_CARRIERS = {"移动", "联通", "电信"}

VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
_ENV_HEADER = "# Campus-Auth managed settings"


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

    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("浏览器请求头必须是 JSON 对象")

    return json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))


def load_ui_config(project_root: Path | None = None) -> MonitorConfigPayload:
    config = ConfigLoader.load_config_from_env()

    # 尝试从 settings.json 加载活动方案的 profile 设置
    profile: ProfileSettings | None = None
    if project_root is not None:
        try:
            from .profile_service import ProfileService

            ps = ProfileService(project_root)
            profile = ps.get_active_profile()
        except Exception:
            profile = None

    # 账号密码：方案独立 > 全局
    use_global = True
    if profile and not profile.use_global_credentials and profile.username:
        username = profile.username
        use_global = False
        # 方案密码：如果是加密的则解密，如果是掩码则保留
        raw_pwd = profile.password or ""
        if raw_pwd.startswith("ENC:"):
            password = mask_password(decrypt_password(raw_pwd))
        elif raw_pwd.startswith("•"):
            password = raw_pwd
        elif raw_pwd:
            password = mask_password(raw_pwd)
        else:
            password = mask_password(config.get("password", ""))
    else:
        username = config.get("username", "")
        password = mask_password(config.get("password", ""))

    # 基本设置：auth_url、carrier 始终来自 profile（如有）
    if profile:
        auth_url = profile.auth_url or str(config.get("auth_url", "http://172.29.0.2"))
        carrier = profile.carrier
        carrier_custom = profile.carrier_custom
    else:
        isp_value = str(config.get("isp", "") or "").strip()
        carrier = "无"
        carrier_custom = ""
        if isp_value in BUILTIN_CARRIERS:
            carrier = isp_value
        elif isp_value:
            carrier = "自定义"
            carrier_custom = isp_value
        auth_url = str(config.get("auth_url", "http://172.29.0.2"))

    # 高级设置：跟随全局时从 .env 读取，否则使用 profile 值
    use_advanced_from_env = not profile or profile.use_global_advanced
    if use_advanced_from_env:
        interval_seconds = int(config.get("monitor", {}).get("interval", 300))
        pause_config = config.get("pause_login", {})
        browser_config = config.get("browser_settings", {})
        monitor_config = config.get("monitor", {})
        ping_targets = monitor_config.get("ping_targets", [])
        network_targets = _normalize_targets(
            ",".join(str(item) for item in ping_targets) if ping_targets else ""
        )

        custom_vars_str = os.getenv("CUSTOM_VARIABLES", "")
        custom_variables = {}
        if custom_vars_str:
            try:
                custom_variables = json.loads(custom_vars_str)
                if not isinstance(custom_variables, dict):
                    custom_variables = {}
            except json.JSONDecodeError:
                custom_variables = {}

        check_interval_minutes = max(1, interval_seconds // 60)
        auto_start = bool(config.get("auto_start_monitoring", False))
        headless = bool(browser_config.get("headless", True))
        browser_timeout = int(browser_config.get("timeout", 8000))
        browser_user_agent = str(
            browser_config.get("user_agent", DEFAULT_BROWSER_USER_AGENT)
        )
        browser_low_resource_mode = bool(
            browser_config.get("low_resource_mode", True)
        )
        browser_disable_web_security = bool(
            browser_config.get("disable_web_security", False)
        )
        browser_extra_headers_json = str(
            browser_config.get("extra_headers_json", "")
        )
        pause_enabled = bool(pause_config.get("enabled", True))
        pause_start_hour = int(pause_config.get("start_hour", 0))
        pause_end_hour = int(pause_config.get("end_hour", 6))
    else:
        check_interval_minutes = profile.check_interval_minutes
        auto_start = profile.auto_start
        headless = profile.headless
        browser_timeout = profile.browser_timeout
        browser_user_agent = profile.browser_user_agent or DEFAULT_BROWSER_USER_AGENT
        browser_low_resource_mode = profile.browser_low_resource_mode
        browser_disable_web_security = profile.browser_disable_web_security
        browser_extra_headers_json = profile.browser_extra_headers_json
        pause_enabled = profile.pause_enabled
        pause_start_hour = profile.pause_start_hour
        pause_end_hour = profile.pause_end_hour
        network_targets = _normalize_targets(profile.network_targets)
        custom_variables = profile.custom_variables

    # 系统设置始终从 .env 读取
    backend_log_level = _normalize_level(
        config.get("logging", {}).get("level", "WARNING")
    )
    frontend_log_level = _normalize_level(
        config.get("frontend_logging", {}).get("level", "WARNING")
    )
    access_log = bool(config.get("access_log", False))
    minimize_to_tray = bool(config.get("minimize_to_tray", True))

    return MonitorConfigPayload(
        username=username,
        password=password,
        use_global_credentials=use_global,
        auth_url=auth_url,
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
        pause_enabled=pause_enabled,
        pause_start_hour=pause_start_hour,
        pause_end_hour=pause_end_hour,
        network_targets=network_targets,
        backend_log_level=backend_log_level,
        frontend_log_level=frontend_log_level,
        access_log=access_log,
        minimize_to_tray=minimize_to_tray,
        custom_variables=custom_variables,
    )


def build_runtime_config(payload: MonitorConfigPayload) -> dict[str, Any]:
    base = ConfigLoader.load_config_from_env()

    base["username"] = payload.username.strip()
    # 如果前端返回的是掩码，说明密码未修改，保留 .env 中的原值
    raw_password = payload.password.strip()
    if raw_password and not raw_password.startswith("•"):
        base["password"] = raw_password
    # 否则 base["password"] 已由 ConfigLoader.load_config_from_env() 正确解密

    base["auth_url"] = payload.auth_url.strip() or "http://172.29.0.2"
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
    browser["user_agent"] = (
        payload.browser_user_agent.strip() or DEFAULT_BROWSER_USER_AGENT
    )
    browser["low_resource_mode"] = payload.browser_low_resource_mode
    browser["disable_web_security"] = payload.browser_disable_web_security
    browser["extra_headers_json"] = _normalize_headers_json(
        payload.browser_extra_headers_json
    )

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

    # 添加自定义变量
    base["custom_variables"] = payload.custom_variables

    return base


def _save_password(raw: str) -> str:
    """处理前端提交的密码：掩码不更新，明文则加密存储"""
    if not raw or raw.startswith("•"):
        existing = os.getenv("PASSWORD", "")
        return existing if existing else raw
    return encrypt_password(raw)


def write_env_file(payload: MonitorConfigPayload, env_path: Path) -> None:
    """只写入敏感数据和系统设置到 .env（非敏感设置由 profile 管理）"""
    backend_level = _normalize_level(payload.backend_log_level)
    frontend_level = _normalize_level(payload.frontend_log_level)

    managed_values: dict[str, str] = {}

    # 只有使用全局凭证时才写入 .env
    if payload.use_global_credentials:
        managed_values["USERNAME"] = payload.username.strip()
        managed_values["PASSWORD"] = _save_password(payload.password.strip())

    managed_values.update({
        "LOG_LEVEL": backend_level,
        "BACKEND_LOG_LEVEL": backend_level,
        "FRONTEND_LOG_LEVEL": frontend_level,
        "UVICORN_ACCESS_LOG": str(payload.access_log).lower(),
        "MINIMIZE_TO_TRAY": str(payload.minimize_to_tray).lower(),
    })

    existing_lines: list[str] = []
    if env_path.exists():
        existing_lines = env_path.read_text(encoding="utf-8").splitlines()

    updated_lines: list[str] = []
    seen_keys: set[str] = set()

    for line in existing_lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            updated_lines.append(line)
            continue

        key, _ = line.split("=", 1)
        key = key.strip()
        if key in managed_values and key not in seen_keys:
            updated_lines.append(f"{key}={managed_values[key]}")
            seen_keys.add(key)
        else:
            updated_lines.append(line)

    missing_keys = [k for k in managed_values if k not in seen_keys]
    if missing_keys:
        if updated_lines and updated_lines[-1].strip():
            updated_lines.append("")
        updated_lines.append(_ENV_HEADER)
        for key in missing_keys:
            updated_lines.append(f"{key}={managed_values[key]}")

    if not updated_lines:
        updated_lines = [_ENV_HEADER]
        for key, value in managed_values.items():
            updated_lines.append(f"{key}={value}")

    # 原子写入：先写临时文件，再替换，防止崩溃导致 .env 损坏
    content = "\n".join(updated_lines) + "\n"
    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=env_path.parent, suffix=".tmp", prefix=".env."
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, env_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def save_profile_from_payload(
    payload: MonitorConfigPayload, project_root: Path
) -> None:
    """从 MonitorConfigPayload 提取 profile 字段并保存到 settings.json"""
    from .profile_service import ProfileService

    ps = ProfileService(project_root)
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
        auth_url=payload.auth_url.strip() or "http://172.29.0.2",
        carrier=str(payload.carrier or "无").strip(),
        carrier_custom=str(payload.carrier_custom or "").strip(),
        check_interval_minutes=payload.check_interval_minutes,
        auto_start=payload.auto_start,
        headless=payload.headless,
        browser_timeout=payload.browser_timeout,
        browser_user_agent=(
            payload.browser_user_agent.strip() or DEFAULT_BROWSER_USER_AGENT
        ),
        browser_low_resource_mode=payload.browser_low_resource_mode,
        browser_disable_web_security=payload.browser_disable_web_security,
        browser_extra_headers_json=_normalize_headers_json(
            payload.browser_extra_headers_json
        ),
        pause_enabled=payload.pause_enabled,
        pause_start_hour=payload.pause_start_hour,
        pause_end_hour=payload.pause_end_hour,
        network_targets=_normalize_targets(payload.network_targets),
        custom_variables=payload.custom_variables,
    )

    ps.save_profile(active_id, updated)
