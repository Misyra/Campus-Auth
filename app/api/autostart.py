"""自动启动路由 — Shell 列表查询、自启动状态/启用/禁用。"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.deps import get_autostart_service
from app.schemas import ActionResponse, AutoStartStatusResponse
from app.utils.logging import get_logger
from app.utils.shell_utils import detect_shells as detect_available_shells
from app.utils.shell_utils import get_default_shell

router = APIRouter()
api_logger = get_logger("api", source="backend")


@router.get("/api/shells")
def list_shells() -> dict:
    """获取系统可用的 Shell 列表。"""
    shells = detect_available_shells()
    default_shell = get_default_shell()
    return {
        "shells": shells,
        "default": default_shell,
    }


@router.get("/api/autostart/status", response_model=AutoStartStatusResponse)
def autostart_status(
    autostart_svc=Depends(get_autostart_service),
) -> AutoStartStatusResponse:
    status = autostart_svc.status()
    return AutoStartStatusResponse(
        platform=str(status.get("platform", "")),
        enabled=bool(status.get("enabled", False)),
        method=str(status.get("method", "")),
        location=str(status.get("location", "")),
    )


@router.post("/api/autostart/enable", response_model=ActionResponse)
def enable_autostart(
    autostart_svc=Depends(get_autostart_service),
) -> ActionResponse:
    ok, message = autostart_svc.enable()
    api_logger.info("启用自启动 -> success={}, message={}", ok, message)
    return ActionResponse(success=ok, message=message)


@router.post("/api/autostart/disable", response_model=ActionResponse)
def disable_autostart(
    autostart_svc=Depends(get_autostart_service),
) -> ActionResponse:
    ok, message = autostart_svc.disable()
    api_logger.info("禁用自启动 -> success={}, message={}", ok, message)
    return ActionResponse(success=ok, message=message)
