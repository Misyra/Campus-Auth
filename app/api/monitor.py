"""监控路由 — 监控启停、状态查询、日志、网络测试、纯净模式。"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query

from app.deps import get_monitor_service
from app.schemas import ApiResponse, LogEntry, MonitorStatusResponse, PureModeResponse
from app.services.engine import ScheduleEngine
from app.utils.logging import get_logger

router = APIRouter()
api_logger = get_logger("api", source="backend")


@router.get("/api/status", response_model=MonitorStatusResponse)
def get_status(
    svc: ScheduleEngine = Depends(get_monitor_service),
) -> MonitorStatusResponse:
    return svc.get_status()


@router.get("/api/logs", response_model=list[LogEntry])
def get_logs(
    limit: int = Query(default=200, ge=1, le=1000),
    svc: ScheduleEngine = Depends(get_monitor_service),
) -> list[LogEntry]:
    return svc.list_logs(limit=limit)


@router.post("/api/monitor/start", response_model=ApiResponse)
def start_monitoring(
    svc: ScheduleEngine = Depends(get_monitor_service),
) -> ApiResponse:
    ok, message = svc.start_monitoring()
    api_logger.info("启动监控 -> success={}, message={}", ok, message)
    return ApiResponse(success=ok, message=message)


@router.post("/api/monitor/stop", response_model=ApiResponse)
def stop_monitoring(
    svc: ScheduleEngine = Depends(get_monitor_service),
) -> ApiResponse:
    ok, message = svc.stop_monitoring()
    api_logger.info("停止监控 -> success={}, message={}", ok, message)
    return ApiResponse(success=ok, message=message)


@router.post("/api/actions/login", response_model=ApiResponse)
async def manual_login(
    svc: ScheduleEngine = Depends(get_monitor_service),
) -> ApiResponse:
    ok, message = await asyncio.to_thread(svc.run_manual_login)
    api_logger.info("手动登录 -> success={}, message={}", ok, message)
    return ApiResponse(success=ok, message=message)


@router.post("/api/actions/cancel-login", response_model=ApiResponse)
def cancel_login(
    svc: ScheduleEngine = Depends(get_monitor_service),
) -> ApiResponse:
    ok, message = svc.cancel_login()
    api_logger.info("取消登录 -> success={}, message={}", ok, message)
    return ApiResponse(success=ok, message=message)


@router.post("/api/actions/test-network", response_model=ApiResponse)
def test_network(
    svc: ScheduleEngine = Depends(get_monitor_service),
) -> ApiResponse:
    ok, message = svc.test_network()
    api_logger.info("网络测试 -> success={}, message={}", ok, message)
    return ApiResponse(success=ok, message=message)


# ── 纯净模式 ──


@router.get("/api/pure-mode", response_model=PureModeResponse)
def get_pure_mode(
    svc: ScheduleEngine = Depends(get_monitor_service),
) -> PureModeResponse:
    return PureModeResponse(enabled=svc.pure_mode)


@router.post("/api/pure-mode", response_model=ApiResponse)
def toggle_pure_mode(
    svc: ScheduleEngine = Depends(get_monitor_service),
) -> ApiResponse:
    try:
        new_value = svc.toggle_pure_mode()
        api_logger.info("纯净模式已切换 -> {}", new_value)
        return ApiResponse(success=True, message=f"纯净模式: {'开启' if new_value else '关闭'}", data={"enabled": new_value})
    except Exception as exc:
        api_logger.error("切换纯净模式失败: {}", exc)
        raise HTTPException(status_code=500, detail=f"切换纯净模式失败: {exc}") from exc
