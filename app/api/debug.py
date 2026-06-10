"""调试路由 — 调试会话的启动、单步执行、全部执行、停止、状态查询。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.deps import get_debug_manager, get_monitor_service
from app.services.debug import DebugSessionManager
from app.services.engine import ScheduleEngine

router = APIRouter()


@router.post("/api/debug/start")
async def debug_start(
    request: Request,
    debug_mgr: DebugSessionManager = Depends(get_debug_manager),
    monitor_svc: ScheduleEngine = Depends(get_monitor_service),
) -> dict[str, object]:
    return await debug_mgr.start(request, monitor_svc)


@router.post("/api/debug/next")
async def debug_next(
    debug_mgr: DebugSessionManager = Depends(get_debug_manager),
) -> dict[str, object]:
    return await debug_mgr.next_step()


@router.post("/api/debug/run-all")
async def debug_run_all(
    debug_mgr: DebugSessionManager = Depends(get_debug_manager),
) -> dict[str, object]:
    return await debug_mgr.run_all()


@router.post("/api/debug/stop")
async def debug_stop(
    debug_mgr: DebugSessionManager = Depends(get_debug_manager),
) -> dict[str, object]:
    return await debug_mgr.stop()


@router.get("/api/debug/status")
async def debug_status(
    debug_mgr: DebugSessionManager = Depends(get_debug_manager),
) -> dict[str, object]:
    return debug_mgr.get_status()
