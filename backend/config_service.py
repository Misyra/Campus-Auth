from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from src.utils import ConfigLoader
from src.utils.crypto import decrypt_password, encrypt_password, is_encrypted, mask_password

from .schemas import DEFAULT_BROWSER_USER_AGENT, MonitorConfigPayload

CARRIER_MAP = {
    "移动": "@cmcc",
    "联通": "@unicom",
    "电信": "@telecom",
    "教育网": "@xyw",
    "无": "",
}

VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
_ENV_HEADER = "# Campus-Auth managed settings"


def _normalize_level(raw: str, default: str = "INFO") -> str:
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


def load_ui_config() -> MonitorConfigPayload:
    config = ConfigLoader.load_config_from_env()
    isp_code = config.get("isp", "")

    carrier = "无"
    for cn, code in CARRIER_MAP.items():
        if code == isp_code:
            carrier = cn
            break

    interval_seconds = int(config.get("monitor", {}).get("interval", 300))

    pause_config = config.get("pause_login", {})
    browser_config = config.get("browser_settings", {})
    monitor_config = config.get("monitor", {})
    ping_targets = monitor_config.get("ping_targets", [])
    network_targets = _normalize_targets(
        ",".join(str(item) for item in ping_targets) if ping_targets else ""
    )

    return MonitorConfigPayload(
        username=config.get("username", ""),
        password=mask_password(config.get("password", "")),
        auth_url=str(config.get("auth_url", "http://172.29.0.2")),
        carrier=carrier,
        check_interval_minutes=max(1, interval_seconds // 60),
        auto_start=bool(config.get("auto_start_monitoring", False)),
        headless=bool(browser_config.get("headless", False)),
        browser_timeout=int(browser_config.get("timeout", 8000)),
        browser_user_agent=str(
            browser_config.get("user_agent", DEFAULT_BROWSER_USER_AGENT)
        ),
        browser_low_resource_mode=bool(browser_config.get("low_resource_mode", False)),
        browser_disable_web_security=bool(browser_config.get("disable_web_security", False)),
        browser_extra_headers_json=str(browser_config.get("extra_headers_json", "")),
        pause_enabled=bool(pause_config.get("enabled", True)),
        pause_start_hour=int(pause_config.get("start_hour", 0)),
        pause_end_hour=int(pause_config.get("end_hour", 6)),
        network_targets=network_targets,
        backend_log_level=_normalize_level(
            config.get("logging", {}).get("level", "INFO")
        ),
        frontend_log_level=_normalize_level(
            config.get("frontend_logging", {}).get("level", "INFO")
        ),
        access_log=bool(config.get("access_log", False)),
        minimize_to_tray=bool(config.get("minimize_to_tray", False)),
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
    base["isp"] = CARRIER_MAP.get(payload.carrier, "")
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

    return base


def _save_password(raw: str) -> str:
    """处理前端提交的密码：掩码不更新，明文则加密存储"""
    if not raw or raw.startswith("•"):
        existing = os.getenv("PASSWORD", "")
        return existing if existing else raw
    return encrypt_password(raw)


def write_env_file(payload: MonitorConfigPayload, env_path: Path) -> None:
    network_targets = _normalize_targets(payload.network_targets)
    backend_level = _normalize_level(payload.backend_log_level)
    frontend_level = _normalize_level(payload.frontend_log_level)
    browser_user_agent = (
        payload.browser_user_agent.strip() or DEFAULT_BROWSER_USER_AGENT
    )
    browser_headers_json = _normalize_headers_json(payload.browser_extra_headers_json)

    managed_values = {
        "USERNAME": payload.username.strip(),
        "PASSWORD": _save_password(payload.password.strip()),
        "LOGIN_URL": payload.auth_url.strip() or "http://172.29.0.2",
        "ISP": CARRIER_MAP.get(payload.carrier, ""),
        "BROWSER_HEADLESS": str(payload.headless).lower(),
        "BROWSER_TIMEOUT": str(payload.browser_timeout),
        "BROWSER_USER_AGENT": browser_user_agent,
        "BROWSER_LOW_RESOURCE_MODE": str(payload.browser_low_resource_mode).lower(),
        "BROWSER_DISABLE_WEB_SECURITY": str(payload.browser_disable_web_security).lower(),
        "BROWSER_EXTRA_HEADERS_JSON": browser_headers_json,
        "MONITOR_INTERVAL": str(payload.check_interval_minutes * 60),
        "AUTO_START_MONITORING": str(payload.auto_start).lower(),
        "PING_TARGETS": network_targets,
        "PAUSE_LOGIN_ENABLED": str(payload.pause_enabled).lower(),
        "PAUSE_LOGIN_START_HOUR": str(payload.pause_start_hour),
        "PAUSE_LOGIN_END_HOUR": str(payload.pause_end_hour),
        "LOG_LEVEL": backend_level,
        "BACKEND_LOG_LEVEL": backend_level,
        "FRONTEND_LOG_LEVEL": frontend_level,
        "UVICORN_ACCESS_LOG": str(payload.access_log).lower(),
        "MINIMIZE_TO_TRAY": str(payload.minimize_to_tray).lower(),
    }

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

    env_path.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")
