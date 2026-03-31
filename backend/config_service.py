from __future__ import annotations

from pathlib import Path
from typing import Any

from src.utils import ConfigLoader

from .schemas import MonitorConfigPayload

CARRIER_MAP = {
    "移动": "@cmcc",
    "联通": "@unicom",
    "电信": "@telecom",
    "教育网": "@xyw",
    "无": "",
}

VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


def _normalize_level(raw: str, default: str = "INFO") -> str:
    level = str(raw or default).upper().strip()
    return level if level in VALID_LOG_LEVELS else default


def _normalize_targets(raw: str) -> str:
    parts = [item.strip() for item in str(raw or "").split(",") if item.strip()]
    if not parts:
        return "8.8.8.8:53,114.114.114.114:53,www.baidu.com:443"
    return ",".join(parts)


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
        password=config.get("password", ""),
        carrier=carrier,
        check_interval_minutes=max(1, interval_seconds // 60),
        auto_start=bool(config.get("auto_start_monitoring", False)),
        headless=bool(browser_config.get("headless", False)),
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
    base["password"] = payload.password.strip()
    base["isp"] = CARRIER_MAP.get(payload.carrier, "")
    base["auto_start_monitoring"] = payload.auto_start

    browser = base.setdefault("browser_settings", {})
    browser["headless"] = payload.headless

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


def write_env_file(payload: MonitorConfigPayload, env_path: Path) -> None:
    network_targets = _normalize_targets(payload.network_targets)
    backend_level = _normalize_level(payload.backend_log_level)
    frontend_level = _normalize_level(payload.frontend_log_level)
    env_content = f"""# 校园网认证配置
CAMPUS_USERNAME={payload.username.strip()}
CAMPUS_PASSWORD={payload.password.strip()}
CAMPUS_AUTH_URL=http://172.29.0.2
CAMPUS_ISP={CARRIER_MAP.get(payload.carrier, "")}

# 浏览器配置
BROWSER_HEADLESS={str(payload.headless).lower()}
BROWSER_TIMEOUT=8000
BROWSER_LOW_RESOURCE_MODE=true

# 网络检测配置
APP_PORT=50721
MONITOR_INTERVAL={payload.check_interval_minutes * 60}
AUTO_START_MONITORING={str(payload.auto_start).lower()}
PING_TARGETS={network_targets}

# 重试策略配置
RETRY_MAX_RETRIES=3
RETRY_INTERVAL=5

# 暂停登录时段配置
PAUSE_LOGIN_ENABLED={str(payload.pause_enabled).lower()}
PAUSE_LOGIN_START_HOUR={payload.pause_start_hour}
PAUSE_LOGIN_END_HOUR={payload.pause_end_hour}

# 日志配置
LOG_LEVEL={backend_level}
BACKEND_LOG_LEVEL={backend_level}
FRONTEND_LOG_LEVEL={frontend_level}
LOG_FORMAT=%(asctime)s | %(levelname)s | %(side)s | %(name)s | %(message)s
LOG_FILE=logs/campus_auth.log

# HTTP请求日志（控制台是否显示API请求）
UVICORN_ACCESS_LOG={str(payload.access_log).lower()}

# 系统托盘配置
MINIMIZE_TO_TRAY={str(payload.minimize_to_tray).lower()}
"""
    env_path.write_text(env_content, encoding="utf-8")
