"""自动启动路由 — Shell 列表查询、自启动状态/启用/禁用/模式切换。"""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.deps import AutoStartServiceDep
from app.schemas import ApiResponse, AutoStartStatusResponse, AutostartEnableRequest, ShellListResponse
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
    return ShellListResponse(shells=[s["path"] for s in shells], default=default_shell)


def _read_autostart_lightweight(request: Request) -> bool:
    """从 container 共享的 ProfileService 读取自启动轻量模式偏好。"""
    try:
        ps = request.app.state.services.profile_service
        return bool(ps.load().global_config.app_settings.autostart_lightweight)
    except Exception as e:
        api_logger.warning("读取自启动轻量模式失败，使用默认值: {}", e)
        return True  # 默认轻量


def _save_autostart_lightweight(request: Request, lightweight: bool) -> None:
    """通过 container 共享的 ProfileService 保存自启动轻量模式偏好。"""
    ps = request.app.state.services.profile_service
    ps.update(lambda d: setattr(d.global_config, "app_settings",
        d.global_config.app_settings.model_copy(update={"autostart_lightweight": lightweight})))


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
        lightweight=_read_autostart_lightweight(request),
    )


@router.post("/api/autostart/enable", response_model=ApiResponse)
def enable_autostart(
    autostart_svc: AutoStartServiceDep,
    request: Request,
    body: AutostartEnableRequest | None = None,
) -> ApiResponse:
    lightweight = body.lightweight if body else True
    _save_autostart_lightweight(request, lightweight)
    ok, message = autostart_svc.enable(lightweight=lightweight)
    if ok:
        api_logger.info("启用自启动成功 (轻量={})", lightweight)
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
    body: AutostartEnableRequest,
    autostart_svc: AutoStartServiceDep,
) -> ApiResponse:
    """切换自启动运行模式（重新生成脚本）。"""
    _save_autostart_lightweight(request, body.lightweight)
    status = autostart_svc.status()
    if not status.get("enabled"):
        return ApiResponse(success=True, message="自启动未启用，模式已保存")
    ok, message = autostart_svc.enable(lightweight=body.lightweight)
    if ok:
        api_logger.info("切换自启动模式成功 (轻量={})", body.lightweight)
    else:
        api_logger.warning("切换自启动模式失败: {}", message)
    return ApiResponse(success=ok, message=message)
