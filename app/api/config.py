"""配置路由 — 配置的读取和保存。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from app.deps import get_monitor_service, get_profile_service
from app.schemas import ActionResponse, RuntimeConfig
from app.services.config_service import save_and_apply
from app.services.engine import ScheduleEngine
from app.services.profile_service import ProfileService
from app.utils.logging import get_logger

router = APIRouter()
api_logger = get_logger("api", source="backend")
config_logger = get_logger("config", source="backend")


@router.get("/api/config/log-levels")
def get_log_levels():
    """获取日志级别配置"""
    from app.utils.logging import LogConfigCenter

    config = LogConfigCenter.get_instance()
    return {
        "global_level": config.get_config().get("level", "INFO"),
        "source_levels": config.get_all_source_levels(),
    }


@router.put("/api/config/source-level")
def set_source_level(payload: dict, request: Request):
    """设置日志级别。source='global' 时设置全局级别，否则设置来源级别。"""
    from app.utils.logging import LogConfigCenter

    source = payload.get("source")
    level = payload.get("level")

    if not source or not level:
        raise HTTPException(400, "缺少 source 或 level 参数")

    config = LogConfigCenter.get_instance()

    if source == "global":
        config.set_level(level)
    else:
        try:
            config.set_source_level(source, level)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e

    _persist_source_levels(request, config)

    return {"success": True, "message": f"已设置 {source} 级别为 {level}"}


def _persist_source_levels(request: Request, config):
    """将 source_levels 持久化到 settings.json"""
    profile_service = request.app.state.services.profile_service
    profile_service.update(
        lambda d: setattr(d.global_config, "logging", d.global_config.logging.model_copy(update={"source_levels": config.get_all_source_levels()}))
    )


@router.get("/api/config", response_model=RuntimeConfig)
def get_config(
    svc: ScheduleEngine = Depends(get_monitor_service),
    profile_svc: ProfileService = Depends(get_profile_service),
) -> RuntimeConfig:
    config = svc.get_config()

    # 从活跃方案注入凭据（credentials 存在 profile 中，不在 config 中）
    try:
        profile = profile_svc.get_active_profile()
        if profile and hasattr(profile, "password"):
            from app.utils.crypto import decrypt_password_field

            password, _ = decrypt_password_field(profile.password)
            config = config.model_copy(update={
                "credentials": config.credentials.model_copy(update={
                    "username": profile.username or "",
                    "password": password or "",
                    "auth_url": profile.auth_url or "",
                    "isp": str(profile.carrier or "无"),
                    "carrier_custom": profile.carrier_custom or "",
                }),
                "active_task": profile.active_task or "",
            })
    except Exception:
        api_logger.debug("从活跃方案注入凭据失败，使用配置中的凭据", exc_info=True)

    # 掩码密码，不暴露加密密文（save_password_field 已识别 "•" 前缀为掩码）
    if config.credentials.password:
        config = config.model_copy(update={
            "credentials": config.credentials.model_copy(update={"password": "••••••••"})
        })
    return config


@router.get("/api/config/default-stealth-script")
def get_default_stealth_script() -> dict:
    """获取默认反检测脚本内容。"""
    from app.utils.browser import STEALTH_INIT_SCRIPT

    return {"script": STEALTH_INIT_SCRIPT}


def _flatten_dict(d: dict, parent_key: str = "", sep: str = ".") -> dict:
    """将嵌套字典扁平化为点分键。"""
    items: list[tuple[str, object]] = []
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.extend(_flatten_dict(v, new_key, sep).items())
        else:
            items.append((new_key, v))
    return dict(items)


def _log_config_changes(old_dict: dict, new_payload: RuntimeConfig) -> None:
    """记录配置变更日志

    规则：
    - bool 字段：显示前后状态（开启/关闭）
    - int/float/string 字段：只记录"已修改"
    - password 字段：完全忽略
    """
    FIELD_NAMES = {
        "browser.headless": "无头模式",
        "browser.pure_mode": "纯净模式",
        "browser.stealth_mode": "反检测模式",
        "browser.low_resource_mode": "低资源模式",
        "browser.disable_web_security": "禁用同源策略",
        "monitor.enable_tcp_check": "TCP检测",
        "monitor.enable_http_check": "HTTP检测",
        "monitor.enable_local_check": "本地网络检测",
        "monitor.check_auth_url": "认证地址检测",
        "pause.enabled": "暂停时段",
        "block_proxy": "屏蔽系统代理",
        "minimize_to_tray": "最小化到托盘",
        "auto_open_browser": "自动打开浏览器",
        "autostart_lightweight": "自启动轻量模式",
        "logging.access_log": "HTTP访问日志",
        "browser.channel": "浏览器类型",
        "browser.timeout": "浏览器超时",
        "browser.navigation_timeout": "页面加载超时",
        "browser.login_timeout": "登录超时",
        "monitor.check_interval_seconds": "检测间隔",
        "retry.max_retries": "最大重试次数",
        "retry.retry_interval": "重试间隔",
        "logging.log_retention_days": "日志保留天数",
        "logging.backend_log_level": "后端日志级别",
        "logging.frontend_log_level": "前端日志级别",
        "app_port": "网页端口",
        "proxy": "网络代理",
        "shell_path": "Shell路径",
        "browser.viewport_width": "视口宽度",
        "browser.viewport_height": "视口高度",
        "pause.start_hour": "暂停开始时间",
        "pause.end_hour": "暂停结束时间",
        "monitor.network_check_timeout": "网络检测超时",
    }

    # 直接忽略的字段（不记录变更）
    IGNORE_FIELDS = {"credentials.password"}

    # BUG-005 修复：扁平化嵌套字典后再比较
    flat_old = _flatten_dict(old_dict)
    flat_new = _flatten_dict(new_payload.model_dump())

    changes = []

    # BUG-006 修复：使用正确路径获取密码
    new_pw = flat_new.get("credentials.password", "")
    old_pw = flat_old.get("credentials.password", "")
    if new_pw and old_pw != new_pw:
        changes.append("密码已修改")

    for field_name in flat_old:
        if field_name in IGNORE_FIELDS:
            continue

        old_val = flat_old.get(field_name)
        new_val = flat_new.get(field_name)

        if old_val == new_val:
            continue

        name = FIELD_NAMES.get(field_name, field_name)

        # 布尔字段显示前后状态
        if isinstance(new_val, bool):
            old_status = "开启" if old_val else "关闭"
            new_status = "开启" if new_val else "关闭"
            changes.append(f"{name}: {old_status} → {new_status}")
        else:
            changes.append(f"{name}已修改")

    if changes:
        config_logger.info("配置变更: {}", "; ".join(changes))


@router.put("/api/config", response_model=ActionResponse)
def save_config(
    payload: RuntimeConfig,
    svc: ScheduleEngine = Depends(get_monitor_service),
    profile_svc: ProfileService = Depends(get_profile_service),
) -> ActionResponse:
    try:
        # 获取当前配置用于变更日志
        old_dict = svc.get_config().model_dump()

        # 保存 + 重载 + 失败回滚（事务逻辑在 config_service 中）
        result = save_and_apply(payload, profile_svc, svc.reload_config)
        if not result.success:
            raise ValueError(result.message)

        # 记录配置变更
        _log_config_changes(old_dict, payload)

        api_logger.info("配置已保存 -> success=True")
        return ActionResponse(success=True, message="配置保存成功")
    except ValueError as exc:
        api_logger.warning("配置更新被拒绝: {}", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        api_logger.error("配置保存失败: {}", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"配置保存失败: {exc}") from exc
