"""配置路由 — 配置的读取和保存。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from app.deps import get_monitor_service, get_profile_service
from app.schemas import (
    ApiResponse,
    AppSettings,
    BrowserSettings,
    ConfigPatchRequest,
    ConfigSaveRequest,
    LogLevelResponse,
    LoggingSettings,
    MonitorSettings,
    PauseSettings,
    RetrySettings,
    SourceLevelRequest,
    StealthScriptResponse,
)
from app.services.profile_service import save_global_and_profile
from app.services.engine import ScheduleEngine
from app.services.profile_service import ProfileService
from app.utils.logging import get_logger

router = APIRouter(tags=["配置"])
api_logger = get_logger("api", source="backend")
config_logger = get_logger("config", source="backend")


@router.get("/api/config/log-levels", response_model=LogLevelResponse)
def get_log_levels() -> LogLevelResponse:
    """获取日志级别配置"""
    from app.utils.logging import LogConfigCenter

    config = LogConfigCenter.get_instance()
    return LogLevelResponse(
        global_level=config.get_config().get("level", "INFO"),
        source_levels=config.get_all_source_levels(),
    )


@router.put("/api/config/source-level", response_model=ApiResponse)
def set_source_level(payload: SourceLevelRequest, request: Request) -> ApiResponse:
    """设置日志级别。source='global' 时设置全局级别，否则设置来源级别。"""
    from app.utils.logging import LogConfigCenter

    config = LogConfigCenter.get_instance()

    if payload.source == "global":
        config.set_level(payload.level)
        actual = config.get_config().get("level", "INFO")
        if actual != payload.level.upper():
            return ApiResponse(success=True, message=f"无效级别 '{payload.level}'，已降级为 {actual}")
    else:
        try:
            config.set_source_level(payload.source, payload.level)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e

    _persist_source_levels(request, config)
    return ApiResponse(success=True, message=f"已设置 {payload.source} 级别为 {payload.level}")


def _persist_source_levels(request: Request, config):
    """将 source_levels 持久化到 settings.json"""
    profile_service = request.app.state.services.profile_service
    profile_service.update(
        lambda d: setattr(d.global_config, "logging", d.global_config.logging.model_copy(update={"source_levels": config.get_all_source_levels()}))
    )


@router.get("/api/config")
def get_config(
    svc: ScheduleEngine = Depends(get_monitor_service),
    profile_svc: ProfileService = Depends(get_profile_service),
) -> dict:
    data = profile_svc.load()
    cfg = profile_svc.build_runtime_config(data)

    profile = profile_svc.get_active_profile()
    carrier = profile.carrier or "无"
    isp = "" if carrier == "无" else carrier

    return {
        "browser": cfg.browser.model_dump(),
        "monitor": cfg.monitor.model_dump(),
        "retry": cfg.retry.model_dump(),
        "pause": cfg.pause.model_dump(),
        "logging": cfg.logging.model_dump(),
        "app_settings": cfg.app_settings.model_dump(),
        # 凭据平铺（与 ConfigSaveRequest 对齐）
        "username": cfg.credentials.username,
        "password": "",  # 始终返回空串，前端以空串表示"未修改"
        "auth_url": cfg.credentials.auth_url,
        "isp": isp,
        "carrier_custom": cfg.credentials.carrier_custom,
        "active_task": cfg.active_task,
    }


@router.get("/api/config/default-stealth-script", response_model=StealthScriptResponse)
def get_default_stealth_script() -> StealthScriptResponse:
    """获取默认反检测脚本内容。"""
    from app.utils.browser import STEALTH_INIT_SCRIPT

    return StealthScriptResponse(script=STEALTH_INIT_SCRIPT)


@router.get("/api/config/defaults")
def get_config_defaults() -> dict:
    """获取所有配置字段的默认值。"""
    return {
        "browser": BrowserSettings().model_dump(),
        "monitor": MonitorSettings().model_dump(),
        "retry": RetrySettings().model_dump(),
        "pause": PauseSettings().model_dump(),
        "logging": LoggingSettings().model_dump(),
        "app_settings": AppSettings().model_dump(),
    }


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


def _log_config_changes(old_dict: dict, new_payload: ConfigSaveRequest) -> None:
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
        "app_settings.block_proxy": "屏蔽系统代理",
        "app_settings.minimize_to_tray": "最小化到托盘",
        "app_settings.auto_open_browser": "自动打开浏览器",
        "app_settings.autostart_lightweight": "自启动轻量模式",
        "logging.access_log": "HTTP访问日志",
        "browser.browser_channel": "浏览器类型",
        "browser.timeout": "浏览器超时",
        "browser.navigation_timeout": "页面加载超时",
        "browser.login_timeout": "登录超时",
        "monitor.check_interval_seconds": "检测间隔",
        "retry.max_retries": "最大重试次数",
        "retry.retry_interval": "重试间隔",
        "logging.log_retention_days": "日志保留天数",
        "logging.level": "后端日志级别",
        "logging.frontend_level": "前端日志级别",
        "app_settings.app_port": "网页端口",
        "app_settings.proxy": "网络代理",
        "app_settings.shell_path": "Shell路径",
        "browser.viewport_width": "视口宽度",
        "browser.viewport_height": "视口高度",
        "pause.start_hour": "暂停开始时间",
        "pause.end_hour": "暂停结束时间",
        "monitor.network_check_timeout": "网络检测超时",
        "isp": "运营商",
        "carrier_custom": "自定义运营商",
    }

    # 直接忽略的字段（不记录变更）
    IGNORE_FIELDS = {"password"}

    # BUG-005 修复：扁平化嵌套字典后再比较
    # old_dict 来自 RuntimeConfig（credentials 嵌套），new_payload 来自 ConfigSaveRequest（凭据平铺）
    # 需要将 old_dict 的 credentials 扁平化到顶层后再比较
    _old = dict(old_dict)
    _old_creds = _old.pop("credentials", {})
    _old.update(_old_creds)
    flat_old = _flatten_dict(_old)
    flat_new = _flatten_dict(new_payload.model_dump())

    changes = []

    # 密码变更检测（顶层 password，不再嵌套在 credentials 下）
    new_pw = flat_new.get("password", "")
    old_pw = flat_old.get("password", "")
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

    for field_name in flat_new:
        if field_name in flat_old or field_name in IGNORE_FIELDS:
            continue
        new_val = flat_new.get(field_name)
        if new_val:
            name = FIELD_NAMES.get(field_name, field_name)
            changes.append(f"{name}已设置")

    if changes:
        config_logger.info("配置变更: {}", "; ".join(changes))


@router.put("/api/config", response_model=ApiResponse)
def save_config(
    payload: ConfigSaveRequest,
    svc: ScheduleEngine = Depends(get_monitor_service),
    profile_svc: ProfileService = Depends(get_profile_service),
) -> ApiResponse:
    try:
        old_data = profile_svc.load()
        old_cfg = profile_svc.build_runtime_config(old_data)
        old_dict = old_cfg.model_dump()

        result = save_global_and_profile(payload, profile_svc, svc.reload_config)
        if not result.success:
            raise ValueError(result.message)

        _log_config_changes(old_dict, payload)

        api_logger.info("配置已保存 -> success=True")
        return ApiResponse(success=True, message="配置保存成功")
    except ValueError as exc:
        api_logger.warning("配置更新被拒绝: {}", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        api_logger.error("配置保存失败: {}", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"配置保存失败: {exc}") from exc


@router.patch("/api/config", response_model=ApiResponse)
def patch_config(
    payload: ConfigPatchRequest,
    svc: ScheduleEngine = Depends(get_monitor_service),
    profile_svc: ProfileService = Depends(get_profile_service),
) -> ApiResponse:
    """增量更新配置 — 仅修改 payload 中非 None 的字段。"""
    try:
        old_data = profile_svc.load()
        old_cfg = profile_svc.build_runtime_config(old_data)

        current = old_cfg.model_dump()
        patch_data = payload.model_dump(exclude_none=True)

        merged = {**current, **patch_data}
        for key in ("browser", "monitor", "retry", "pause", "logging", "app_settings"):
            if key in patch_data:
                merged[key] = {**current.get(key, {}), **patch_data[key]}

        full_request = ConfigSaveRequest.model_validate(merged)
        result = save_global_and_profile(full_request, profile_svc, svc.reload_config)
        if not result.success:
            raise ValueError(result.message)

        _log_config_changes(old_cfg.model_dump(), full_request)
        api_logger.info("配置增量保存 -> success=True, fields={}", list(patch_data.keys()))
        return ApiResponse(success=True, message="配置保存成功", data={"patched": list(patch_data.keys())})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        api_logger.error("配置增量保存失败: {}", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"配置保存失败: {exc}") from exc
