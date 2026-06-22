"""自动启动路由 — Shell 列表查询、自启动状态/启用/禁用/模式切换。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

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


def _read_autostart_lightweight() -> bool:
    """从 settings.json 读取自启动轻量模式偏好。"""
    try:
        from app.services.profile_service import ProfileService
        from pathlib import Path

        ps = ProfileService(Path(__file__).parent.parent.parent.resolve())
        return bool(ps.load().global_config.autostart_lightweight)
    except Exception:
        return True  # 默认轻量


def _save_autostart_lightweight(lightweight: bool) -> None:
    """保存自启动轻量模式偏好到 settings.json。"""
    from app.services.profile_service import ProfileService
    from pathlib import Path

    # NOTE: 每次 new ProfileService 实例，与全局注入实例的锁不同。
    # 理论上与 config.py 的 save_and_apply 并发写 settings.json 会丢更新，
    # 但单用户桌面应用场景下触发概率极低，暂不修复。
    ps = ProfileService(Path(__file__).parent.parent.parent.resolve())
    ps.update(lambda d: setattr(d, "global_config", d.global_config.model_copy(update={"autostart_lightweight": lightweight})))


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
        lightweight=_read_autostart_lightweight(),
    )


class _EnableBody(BaseModel):
    lightweight: bool = True


@router.post("/api/autostart/enable", response_model=ActionResponse)
def enable_autostart(
    body: _EnableBody | None = None,
    autostart_svc=Depends(get_autostart_service),
) -> ActionResponse:
    lightweight = body.lightweight if body else True
    _save_autostart_lightweight(lightweight)
    ok, message = autostart_svc.enable(lightweight=lightweight)
    api_logger.info("启用自启动 -> success={}, lightweight={}, message={}", ok, lightweight, message)
    return ActionResponse(success=ok, message=message)


@router.post("/api/autostart/disable", response_model=ActionResponse)
def disable_autostart(
    autostart_svc=Depends(get_autostart_service),
) -> ActionResponse:
    ok, message = autostart_svc.disable()
    api_logger.info("禁用自启动 -> success={}, message={}", ok, message)
    return ActionResponse(success=ok, message=message)


@router.post("/api/autostart/mode", response_model=ActionResponse)
def set_autostart_mode(
    body: _EnableBody,
    autostart_svc=Depends(get_autostart_service),
) -> ActionResponse:
    """切换自启动运行模式（重新生成脚本）。"""
    _save_autostart_lightweight(body.lightweight)
    status = autostart_svc.status()
    if not status.get("enabled"):
        return ActionResponse(success=True, message="自启动未启用，模式已保存")
    ok, message = autostart_svc.enable(lightweight=body.lightweight)
    api_logger.info("切换自启动模式 -> lightweight={}, success={}", body.lightweight, ok)
    return ActionResponse(success=ok, message=message)
