"""自动启动路由 — Shell 列表查询、自启动状态/启用/禁用/模式切换。"""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.deps import AutoStartServiceDep
from app.schemas import (
    ApiResponse,
    AutostartModeRequest,
    AutoStartStatusResponse,
    RuntimeMode,
    ShellInfo,
    ShellListResponse,
)
from app.utils.logging import get_logger
from app.utils.shell_utils import detect_shells as detect_available_shells
from app.utils.shell_utils import get_default_shell

router = APIRouter()
api_logger = get_logger("api", source="backend")


@router.get("/api/shells", response_model=ShellListResponse)
def list_shells() -> ShellListResponse:
    """获取系统可用的 Shell 列表。"""
    shells = detect_available_shells()
    default_shell = get_default_shell()
    return ShellListResponse(
        shells=[ShellInfo(**s) for s in shells],
        default=default_shell,
    )


def _read_runtime_mode(request: Request) -> RuntimeMode:
    """从配置中读取自启动运行模式。"""
    try:
        ps = request.app.state.services.profile_service
        return RuntimeMode(ps.load().global_config.app_settings.runtime_mode)
    except Exception as e:
        api_logger.warning("读取自启动运行模式失败，使用默认值: {}", e)
        return RuntimeMode.LIGHTWEIGHT


def _save_runtime_mode(request: Request, runtime_mode: RuntimeMode) -> None:
    """保存自启动运行模式到配置。"""
    ps = request.app.state.services.profile_service
    ps.update(
        lambda d: setattr(
            d.global_config,
            "app_settings",
            d.global_config.app_settings.model_copy(
                update={"runtime_mode": runtime_mode}
            ),
        )
    )


@router.get("/api/autostart/status", response_model=AutoStartStatusResponse)
def autostart_status(
    request: Request,
    autostart_svc: AutoStartServiceDep,
) -> AutoStartStatusResponse:
    status = autostart_svc.status()
    return AutoStartStatusResponse(
        platform=str(status.get("platform", "")),
        enabled=bool(status.get("enabled", False)),
        method=str(status.get("method", "")),
        location=str(status.get("location", "")),
        runtime_mode=_read_runtime_mode(request).value,
    )


@router.post("/api/autostart/enable", response_model=ApiResponse)
def enable_autostart(
    autostart_svc: AutoStartServiceDep,
) -> ApiResponse:
    ok, message = autostart_svc.enable()
    if ok:
        api_logger.info("启用自启动成功")
    else:
        api_logger.warning("启用自启动失败: {}", message)
    return ApiResponse(success=ok, message=message)


@router.post("/api/autostart/disable", response_model=ApiResponse)
def disable_autostart(
    autostart_svc: AutoStartServiceDep,
) -> ApiResponse:
    ok, message = autostart_svc.disable()
    if ok:
        api_logger.info("禁用自启动成功")
    else:
        api_logger.warning("禁用自启动失败: {}", message)
    return ApiResponse(success=ok, message=message)


@router.post("/api/autostart/mode", response_model=ApiResponse)
def set_autostart_mode(
    request: Request,
    body: AutostartModeRequest,
) -> ApiResponse:
    """切换自启动运行模式（仅保存配置，不重新生成脚本）。"""
    _save_runtime_mode(request, body.runtime_mode)
    api_logger.info("切换自启动模式: {}", body.runtime_mode.value)
    return ApiResponse(
        success=True, message=f"自启动模式已切换为 {body.runtime_mode.value}"
    )
