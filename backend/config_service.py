from __future__ import annotations

import json
from typing import Any

from src.utils.config_helpers import (
    assign_profile_fields,
    extract_profile_fields,
    PROFILE_FIELDS,
)
from src.utils.crypto import decrypt_password, mask_password, save_password_field
from src.utils.logging import get_logger
from src.utils.exceptions import DecryptionError

from .profile_service import ProfileService
from .schemas import (
    VALID_LOG_LEVELS,
    MonitorConfigPayload,
    ProfileSettings,
    SystemSettings,
)


config_logger = get_logger("backend.config_service", side="BACKEND")


def _safe_decrypt(ciphertext: str) -> str:
    """解密密码，失败时返回空字符串并记录警告。"""
    if not ciphertext:
        config_logger.warning("_safe_decrypt 收到空密码，返回空字符串 (调用栈: %s)", __name__)
        return ""
    try:
        return decrypt_password(ciphertext)
    except DecryptionError:
        config_logger.warning("密码解密失败，使用空密码")
        return ""


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
    """加载 UI 配置 —— 始终返回全局设置。

    设置页面展示和修改的都是全局配置（system + default 方案），
    不随活动方案变化。方案独立的覆盖值在方案页面单独管理。
    """
    data = profile_service.load()
    sys_cfg = data.system
    config_logger.debug("加载 UI 配置（全局）: active_profile=%s", data.active_profile)

    global_profile = data.profiles.get("default", ProfileSettings())

    # 合并 sys 和 default 方案字段；重叠字段以 sys 为准（始终显示全局值）
    pld = {}
    pld.update(extract_profile_fields(global_profile.__dict__, PROFILE_FIELDS))
    pld.update(extract_profile_fields(sys_cfg.__dict__, PROFILE_FIELDS))

    # UI 专属覆盖
    pld["password"] = mask_password(sys_cfg.password)
    pld["active_task"] = ""
    pld["use_global_credentials"] = True
    pld["network_targets"] = _normalize_targets(global_profile.network_targets)
    pld["backend_log_level"] = _normalize_level(sys_cfg.backend_log_level)
    pld["frontend_log_level"] = _normalize_level(sys_cfg.frontend_log_level)

    return MonitorConfigPayload(**pld)


def load_runtime_config(profile_service: ProfileService) -> MonitorConfigPayload:
    """加载运行时配置 —— 根据活动方案的 use_global_* 标志合并全局与方案独立值。

    与 load_ui_config 不同，此函数会按活动方案的覆盖标志来决定使用全局值还是方案独立值，
    确保运行时实际生效的配置与方案设置一致。
    """
    data = profile_service.load()
    sys_cfg = data.system
    profile = data.profiles.get(data.active_profile)
    config_logger.debug("加载运行时配置: profile=%s", data.active_profile)

    # 从系统设置作为基础
    pld = extract_profile_fields(sys_cfg.__dict__, PROFILE_FIELDS)

    # 账号密码：方案独立 > 全局；运行时使用解密明文
    use_global = True
    if profile and not profile.use_global_credentials and profile.username:
        pld["username"] = profile.username
        use_global = False
        raw_pwd = profile.password or ""
        if raw_pwd.startswith("ENC:"):
            pld["password"] = _safe_decrypt(raw_pwd)
        elif raw_pwd.startswith("•"):
            if sys_cfg.password:
                pld["password"] = _safe_decrypt(sys_cfg.password)
            else:
                config_logger.warning(
                    "方案 '%s' 密码为掩码但全局密码为空，无法解析",
                    data.active_profile,
                )
                pld["password"] = ""
        elif raw_pwd:
            pld["password"] = raw_pwd
        else:
            config_logger.warning(
                "方案 '%s' 使用独立账号但密码为空，回退到全局密码",
                data.active_profile,
            )
            pld["password"] = _safe_decrypt(sys_cfg.password) if sys_cfg.password else ""
    else:
        pld["username"] = sys_cfg.username
        pld["password"] = _safe_decrypt(sys_cfg.password) if sys_cfg.password else ""
    pld["use_global_credentials"] = use_global

    # 认证地址：跟随全局或使用方案独立值
    if not profile or profile.use_global_auth_url:
        pld["auth_url"] = sys_cfg.auth_url
    else:
        pld["auth_url"] = profile.auth_url

    # 任务：跟随全局或使用方案独立任务
    if not profile or profile.use_global_task:
        pld["active_task"] = ""
    else:
        pld["active_task"] = profile.active_task

    # 运营商：跟随 use_global_credentials 标志
    if not profile or profile.use_global_credentials:
        pld["carrier"] = sys_cfg.carrier
        pld["carrier_custom"] = sys_cfg.carrier_custom
    else:
        pld["carrier"] = profile.carrier
        pld["carrier_custom"] = profile.carrier_custom

    # 高级设置：从活动方案或 default 方案提取非凭证字段
    adv_source = (
        profile
        if profile and not profile.use_global_advanced
        else data.profiles.get("default", ProfileSettings())
    )
    _PROTECTED_KEYS = {
        "username", "password", "auth_url", "active_task",
        "carrier", "carrier_custom", "use_global_credentials",
        "backend_log_level", "frontend_log_level",
    }
    pld.update(
        {
            k: v
            for k, v in extract_profile_fields(
                adv_source.__dict__, PROFILE_FIELDS
            ).items()
            if k not in _PROTECTED_KEYS
        }
    )

    pld["network_targets"] = _normalize_targets(pld.get("network_targets", ""))
    pld["backend_log_level"] = _normalize_level(sys_cfg.backend_log_level)
    pld["frontend_log_level"] = _normalize_level(sys_cfg.frontend_log_level)

    return MonitorConfigPayload(**pld)


def build_runtime_config(
    payload: MonitorConfigPayload, sys: SystemSettings | None = None
) -> dict[str, Any]:
    """从 MonitorConfigPayload 构建运行时配置字典。

    Args:
        payload: 前端传来的合并配置
        sys: settings.json 中的系统设置（用于读取重试策略等非 UI 字段）
    """
    config_logger.debug(
        "构建运行时配置: user=%s, url=%s", payload.username, payload.auth_url
    )
    base: dict[str, Any] = {"password": ""}

    base["username"] = payload.username.strip()
    raw_password = payload.password.strip()
    if raw_password and not raw_password.startswith("•"):
        base["password"] = raw_password
    elif sys:
        base["password"] = _safe_decrypt(sys.password) if sys.password else ""

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
    browser["stealth_mode"] = payload.stealth_mode
    browser["stealth_custom_script"] = payload.stealth_custom_script.strip()
    browser["locale"] = payload.browser_locale.strip()  # 浏览器语言区域
    browser["timezone_id"] = payload.browser_timezone.strip()  # 浏览器时区 ID
    browser["viewport_width"] = payload.browser_viewport_width
    browser["viewport_height"] = payload.browser_viewport_height

    pause = base.setdefault("pause_login", {})
    pause["enabled"] = payload.pause_enabled
    pause["start_hour"] = payload.pause_start_hour
    pause["end_hour"] = payload.pause_end_hour

    monitor = base.setdefault("monitor", {})
    monitor["interval"] = payload.check_interval_seconds
    monitor["ping_targets"] = [
        item.strip() for item in payload.network_targets.split(",") if item.strip()
    ]
    monitor["enable_tcp_check"] = payload.enable_tcp_check
    monitor["enable_http_check"] = payload.enable_http_check
    monitor["check_auth_url"] = payload.check_auth_url
    # 解析 portal 检测 URL 列表
    portal_entries = []
    for line in payload.portal_check_urls.splitlines():
        line = line.strip()
        if "|" in line:
            url, _, expected = line.partition("|")
            url = url.strip()
            expected = expected.strip()
            if url and expected:
                portal_entries.append((url, expected))
    monitor["portal_check_urls"] = portal_entries
    monitor["network_check_timeout"] = payload.network_check_timeout

    backend_level = _normalize_level(payload.backend_log_level)
    frontend_level = _normalize_level(payload.frontend_log_level)

    logging_config = base.setdefault("logging", {})
    logging_config["level"] = backend_level

    frontend_logging = base.setdefault("frontend_logging", {})
    frontend_logging["level"] = frontend_level

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
        ],
    )

    # 重试策略从系统设置读取
    if sys:
        base["retry_settings"] = {
            "max_retries": sys.max_retries,
            "retry_interval": sys.retry_interval,
        }

    return base




def save_config_combined(
    payload: MonitorConfigPayload,
    profile_service: ProfileService,
) -> None:
    """原子化保存全局设置（system + default 方案）。

    设置页面始终修改全局配置，不涉及活动方案的独立字段。
    方案页面的独立设置通过 /api/profiles/{id} 单独保存。
    """
    data = profile_service.load()
    sys_cfg = data.system
    active_id = data.active_profile

    # ── 更新系统设置（始终写入全局）──
    pwd_raw = payload.password.strip()
    old_user = sys_cfg.username
    sys_cfg.username = payload.username.strip()
    sys_cfg.password = save_password_field(pwd_raw, sys_cfg.password)
    config_logger.info(
        "保存系统设置: 用户=%s (旧=%s), 密码=%s",
        sys_cfg.username,
        old_user,
        "已更新" if (pwd_raw and not pwd_raw.startswith("•")) else "保留",
    )

    # 直接映射的系统字段（无归一化处理）
    pld = payload.model_dump()
    assign_profile_fields(
        sys_cfg.__dict__,
        pld,
        [
            "access_log",
            "minimize_to_tray",
            "auto_open_browser",
            "login_then_exit",
            "max_retries",
            "retry_interval",
            "log_retention_days",
            "block_proxy",
            "network_check_timeout",
            "app_port",
        ],
    )
    # 需要归一化处理的系统字段
    sys_cfg.auth_url = payload.auth_url.strip()
    sys_cfg.carrier = str(payload.carrier or "无").strip()
    sys_cfg.carrier_custom = str(payload.carrier_custom or "").strip()
    sys_cfg.backend_log_level = _normalize_level(payload.backend_log_level)
    sys_cfg.frontend_log_level = _normalize_level(payload.frontend_log_level)
    sys_cfg.proxy = payload.proxy.strip()

    data.system = sys_cfg

    # ── 更新 default 方案的高级设置（始终写入全局）──
    if "default" in data.profiles:
        glob = data.profiles["default"]
        # 直接映射的 profile 字段（无归一化处理）
        assign_profile_fields(
            glob.__dict__,
            pld,
            [
                "check_interval_seconds",
                "auto_start",
                "headless",
                "browser_timeout",
                "login_timeout",
                "browser_low_resource_mode",
                "browser_disable_web_security",
                "pause_enabled",
                "pause_start_hour",
                "pause_end_hour",
                "enable_tcp_check",
                "enable_http_check",
                "check_auth_url",
                "portal_check_urls",
                "stealth_mode",
                "stealth_custom_script",
                "custom_variables",
            ],
        )
        # 需要归一化处理的 profile 字段
        glob.browser_user_agent = payload.browser_user_agent.strip()
        glob.browser_extra_headers_json = _normalize_headers_json(
            payload.browser_extra_headers_json
        )
        glob.browser_args = payload.browser_args.strip()
        glob.browser_locale = payload.browser_locale.strip()  # 浏览器语言区域
        glob.browser_timezone = payload.browser_timezone.strip()  # 浏览器时区 ID
        glob.network_targets = _normalize_targets(payload.network_targets)

    # 活动方案保持不变 —— 设置页面不修改方案独立配置

    # ── 单次写入 ──
    profile_service.save(data)
    config_logger.info(
        "配置已原子保存: system(user=%s, pwd=%s, auth=%s), active_profile=%s",
        sys_cfg.username,
        "ENC" if sys_cfg.password else "空",
        sys_cfg.auth_url,
        active_id,
    )
