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

    base["access_log"] = payload.access_log
    base["minimize_to_tray"] = payload.minimize_to_tray

    return base


def write_env_file(payload: MonitorConfigPayload, env_path: Path) -> None:
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
PING_TARGETS=8.8.8.8,114.114.114.114,baidu.com

# 重试策略配置
RETRY_MAX_RETRIES=3
RETRY_INTERVAL=5

# 暂停登录时段配置
PAUSE_LOGIN_ENABLED={str(payload.pause_enabled).lower()}
PAUSE_LOGIN_START_HOUR={payload.pause_start_hour}
PAUSE_LOGIN_END_HOUR={payload.pause_end_hour}

# 日志配置
LOG_LEVEL=INFO
LOG_FORMAT=%(asctime)s - %(levelname)s - %(message)s
LOG_FILE=logs/campus_auth.log

# HTTP请求日志（控制台是否显示API请求）
UVICORN_ACCESS_LOG={str(payload.access_log).lower()}

# 系统托盘配置
MINIMIZE_TO_TRAY={str(payload.minimize_to_tray).lower()}
"""
    env_path.write_text(env_content, encoding="utf-8")
