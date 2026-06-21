"""settings.json 版本迁移。"""

from __future__ import annotations

from typing import Any


def migrate_v2_to_v3(data: dict[str, Any]) -> dict[str, Any]:
    """将 v2 格式（global_settings 扁平）迁移到 v3 格式（config 结构化 + Profile 独立凭证）。

    v2 格式：
        { global_settings: {headless, username, ...}, profiles: {default: {username, ...}} }

    v3 格式：
        { config_version: 3, config: {browser: {...}, monitor: {...}, ...}, profiles: {default: {username, ...}} }
    """
    if data.get("config_version") == 3:
        return data

    gs = data.get("global_settings", {})

    # 从扁平字段构建结构化 config
    config = _build_config_from_flat(gs)

    # 迁移 profiles：合并 global_settings 的凭证到留空的 profile
    profiles = {}
    for pid, p in data.get("profiles", {}).items():
        profiles[pid] = _merge_credential(p, gs)

    # 确保 default profile 存在
    if "default" not in profiles:
        profiles["default"] = _merge_credential({"name": "默认方案"}, gs)

    return {
        "config_version": 3,
        "config": config,
        "auto_switch": data.get("auto_switch", False),
        "active_profile": data.get("active_profile", "default"),
        "profiles": profiles,
    }


def _build_config_from_flat(gs: dict) -> dict:
    """从扁平 global_settings 构建 RuntimeConfig 结构。"""
    return {
        "browser": {
            "headless": gs.get("headless", True),
            "timeout": gs.get("browser_timeout", 8),
            "navigation_timeout": gs.get("browser_navigation_timeout", 15),
            "login_timeout": gs.get("login_timeout", 90),
            "user_agent": gs.get("browser_user_agent", ""),
            "low_resource_mode": gs.get("browser_low_resource_mode", False),
            "disable_web_security": gs.get("browser_disable_web_security", False),
            "extra_headers_json": gs.get("browser_extra_headers_json", ""),
            "browser_args": gs.get("browser_args", ""),
            "stealth_mode": gs.get("stealth_mode", False),
            "stealth_custom_script": gs.get("stealth_custom_script", ""),
            "locale": gs.get("browser_locale", "zh-CN"),
            "timezone_id": gs.get("browser_timezone", "Asia/Shanghai"),
            "viewport_width": gs.get("browser_viewport_width", 1280),
            "viewport_height": gs.get("browser_viewport_height", 720),
            "pure_mode": gs.get("pure_mode", True),
            "browser_channel": str(gs.get("browser_channel", "playwright")),
            "browser_custom_path": gs.get("browser_custom_path", ""),
            "custom_browser_engine": gs.get("custom_browser_engine", "auto"),
        },
        "monitor": {
            "check_interval_seconds": gs.get("check_interval_seconds", 300),
            "network_check_timeout": gs.get("network_check_timeout", 2),
            "ping_targets": [
                t.strip() for t in gs.get("network_targets", "").split(",") if t.strip()
            ],
            "enable_tcp_check": gs.get("enable_tcp_check", False),
            "enable_http_check": gs.get("enable_http_check", False),
            "enable_local_check": gs.get("enable_local_check", True),
            "test_urls": [
                t.strip() for t in gs.get("http_targets", "").split(",") if t.strip()
            ],
            "check_auth_url": gs.get("check_auth_url", False),
            "auth_url_targets": [
                t.strip() for t in gs.get("auth_url_targets", "").split(",") if t.strip()
            ],
            "url_check_urls": _parse_url_check_urls(gs.get("url_check_urls", "")),
        },
        "pause": {
            "enabled": gs.get("pause_enabled", True),
            "start_hour": gs.get("pause_start_hour", 0),
            "end_hour": gs.get("pause_end_hour", 6),
        },
        "logging": {
            "level": gs.get("backend_log_level", "INFO"),
            "frontend_level": gs.get("frontend_log_level", "INFO"),
            "log_retention_days": gs.get("log_retention_days", 7),
            "access_log": gs.get("access_log", False),
        },
        "retry": {
            "max_retries": gs.get("max_retries", 3),
            "retry_interval": gs.get("retry_interval", 5),
        },
        "active_task": gs.get("active_task", ""),
        "custom_variables": gs.get("custom_variables", {}),
        "block_proxy": gs.get("block_proxy", True),
        "shell_path": gs.get("shell_path", ""),
        "minimize_to_tray": gs.get("minimize_to_tray", True),
        "startup_action": str(gs.get("startup_action", "none")),
        "autostart_lightweight": gs.get("autostart_lightweight", True),
    }


def _merge_credential(profile: dict, gs: dict) -> dict:
    """将 global_settings 的凭证合并到 profile 的留空字段。"""
    return {
        "name": profile.get("name", "默认方案"),
        "match_gateway_ip": profile.get("match_gateway_ip", ""),
        "match_ssid": profile.get("match_ssid", ""),
        "username": profile.get("username") or gs.get("username", ""),
        "password": profile.get("password") or gs.get("password", ""),
        "auth_url": profile.get("auth_url") or gs.get("auth_url", ""),
        "carrier": _resolve_carrier(profile.get("carrier"), gs.get("carrier", "无")),
        "carrier_custom": profile.get("carrier_custom") or gs.get("carrier_custom", ""),
        "active_task": profile.get("active_task") or gs.get("active_task", ""),
    }


def _resolve_carrier(profile_val: str | None, global_val: str) -> str:
    """carrier 字段回退逻辑："无" 视为未设置，回退到全局值。"""
    if profile_val and profile_val != "无":
        return profile_val
    return global_val


def _parse_url_check_urls(raw: str) -> list[dict]:
    """解析 url_check_urls 字符串为字典列表。"""
    result = []
    for line in raw.split("\n"):
        line = line.strip()
        if not line:
            continue
        parts = line.split("|", 1)
        if len(parts) == 2:
            result.append({"url": parts[0].strip(), "expected": parts[1].strip()})
    return result
