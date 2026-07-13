"""配置路由 — 配置的读取和保存。"""

from __future__ import annotations


from fastapi import APIRouter, HTTPException, Request

from app.deps import MonitorServiceDep, ProfileServiceDep
from app.schemas import (
    ApiResponse,
    AppSettings,
    BrowserSettings,
    ConfigPatchRequest,
    ConfigResponse,
    ConfigSaveRequest,
    LoggingSettings,
    LogLevelRequest,
    LogLevelResponse,
    MonitorSettings,
    PauseSettings,
    RetrySettings,
    StealthScriptResponse,
)
from app.services.profile_service import save_global_and_profile
from app.utils.logging import get_logger

router = APIRouter(tags=["配置"])
api_logger = get_logger("api", source="backend")
config_logger = get_logger("config", source="backend")




@router.get("/api/config/log-levels", response_model=LogLevelResponse)
def get_log_levels() -> LogLevelResponse:
    from app.utils.logging import LogConfigCenter

    config = LogConfigCenter.get_instance()
    return LogLevelResponse(level=config.get_config().get("level", "INFO"))


@router.put("/api/config/log-level", response_model=ApiResponse)
def set_log_level(payload: LogLevelRequest, request: Request) -> ApiResponse:
    from app.utils.logging import VALID_LOG_LEVELS, LogConfigCenter

    requested = payload.level.strip().upper()
    if requested not in VALID_LOG_LEVELS:
        # 无效级别直接拒绝，避免 set_level 静默降级后仍返回 success=True（BUG-081）
        raise HTTPException(status_code=400, detail=f"无效的日志级别: {payload.level}")
    config = LogConfigCenter.get_instance()
    config.set_level(requested)
    actual = config.get_config().get("level", "INFO")
    profile_service = request.app.state.services.profile_service
    profile_service.update(
        lambda d: d.model_copy(
            update={
                "global_config": d.global_config.model_copy(
                    update={
                        "logging": d.global_config.logging.model_copy(
                            update={"level": actual}
                        ),
                    }
                ),
            }
        )
    )
    # 同步更新引擎运行时配置（经公共方法，不再裸改私有属性）
    engine = request.app.state.services.engine
    engine.update_log_level(actual)
    return ApiResponse(success=True, message=f"已设置全局日志级别为 {actual}")


@router.get("/api/config", response_model=ConfigResponse)
def get_config(
    svc: MonitorServiceDep,
    profile_svc: ProfileServiceDep,
) -> ConfigResponse:
    data = profile_svc.load()
    cfg = profile_svc.build_runtime_config(data)

    profile = profile_svc.get_active_profile()
    carrier = profile.carrier or "无"
    isp = "" if carrier == "无" else carrier

    return ConfigResponse(
        browser=cfg.browser.model_dump(),
        monitor=cfg.monitor.model_dump(),
        retry=cfg.retry.model_dump(),
        pause=cfg.pause.model_dump(),
        logging=cfg.logging.model_dump(),
        app_settings=cfg.app_settings.model_dump(),
        username=cfg.credentials.username,
        password="",
        has_password=bool(profile.password),
        auth_url=cfg.credentials.auth_url,
        isp=isp,
        carrier_custom=cfg.credentials.carrier_custom,
        active_task=cfg.active_task,
    )


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






@router.put("/api/config", response_model=ApiResponse)
def save_config(
    payload: ConfigSaveRequest,
    svc: MonitorServiceDep,
    profile_svc: ProfileServiceDep,
) -> ApiResponse:
    result = save_global_and_profile(payload, profile_svc, svc.reload_config)
    if not result.success:
        raise ValueError(result.message)
    api_logger.info("保存配置成功")
    return ApiResponse(success=True, message="配置保存成功")


@router.patch("/api/config", response_model=ApiResponse)
def patch_config(
    payload: ConfigPatchRequest,
    svc: MonitorServiceDep,
    profile_svc: ProfileServiceDep,
) -> ApiResponse:
    """增量更新配置 — 仅修改 payload 中非 None 的字段。"""
    old_data = profile_svc.load()
    old_cfg = profile_svc.build_runtime_config(old_data)

    current = old_cfg.model_dump()
    # 将 credentials 扁平化到顶层，与 ConfigSaveRequest/ConfigPatchRequest 的平铺结构对齐
    # 否则 merged 顶层缺失 username/auth_url/isp/carrier_custom，ConfigSaveRequest 取默认空串，
    # save_global_and_profile 会用空串覆盖已有凭据（BUG-027）
    creds = current.pop("credentials", {})
    current.update(creds)
    # password 空串语义为不修改（见 save_password_field），不回填运行时明文以免无谓重新加密
    current["password"] = None

    patch_data = payload.model_dump(exclude_none=True)

    merged = {**current, **patch_data}
    for key in ("browser", "monitor", "retry", "pause", "logging", "app_settings"):
        if key in patch_data:
            merged[key] = {**current.get(key, {}), **patch_data[key]}

    full_request = ConfigSaveRequest.model_validate(merged)
    result = save_global_and_profile(full_request, profile_svc, svc.reload_config)
    if not result.success:
        raise ValueError(result.message)
    api_logger.info("配置增量保存成功 (fields={})", list(patch_data.keys()))
    return ApiResponse(
        success=True,
        message="配置保存成功",
        data={"patched": list(patch_data.keys())},
    )
