"""调试路由 — 调试会话的启动、单步执行、全部执行、停止、状态查询。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.deps import get_debug_manager, get_monitor_service
from app.schemas import DebugSessionResponse
from app.services.debug_service import DebugSessionManager
from app.services.engine import ScheduleEngine

router = APIRouter()


@router.post("/api/debug/start", response_model=DebugSessionResponse)
async def debug_start(
    request: Request,
    debug_mgr: DebugSessionManager = Depends(get_debug_manager),
    monitor_svc: ScheduleEngine = Depends(get_monitor_service),
) -> DebugSessionResponse:
    result = await debug_mgr.start(request, monitor_svc)
    return DebugSessionResponse(**result)


@router.post("/api/debug/next", response_model=DebugSessionResponse)
async def debug_next(
    debug_mgr: DebugSessionManager = Depends(get_debug_manager),
) -> DebugSessionResponse:
    result = await debug_mgr.next_step()
    return DebugSessionResponse(**result)


@router.post("/api/debug/run-all", response_model=DebugSessionResponse)
async def debug_run_all(
    debug_mgr: DebugSessionManager = Depends(get_debug_manager),
) -> DebugSessionResponse:
    result = await debug_mgr.run_all()
    return DebugSessionResponse(**result)


@router.post("/api/debug/stop", response_model=DebugSessionResponse)
async def debug_stop(
    debug_mgr: DebugSessionManager = Depends(get_debug_manager),
) -> DebugSessionResponse:
    result = await debug_mgr.stop()
    return DebugSessionResponse(**result)
