"""监控路由 — 监控启停、状态查询、日志、网络测试、纯净模式。"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Query

from app.deps import MonitorServiceDep
from app.network.interfaces import InterfaceManager
from app.schemas import ApiResponse, LogEntry, MonitorStatusResponse, PureModeResponse
from app.utils.logging import get_logger

router = APIRouter()
api_logger = get_logger("api", source="backend")


@router.get("/api/status", response_model=MonitorStatusResponse)
def get_status(
    svc: MonitorServiceDep,
) -> MonitorStatusResponse:
    return svc.get_status()


@router.get("/api/logs", response_model=list[LogEntry])
def get_logs(
    svc: MonitorServiceDep,
    limit: int = Query(default=200, ge=1, le=1000),
) -> list[LogEntry]:
    return svc.list_logs(limit=limit)


@router.post("/api/monitor/start", response_model=ApiResponse)
def start_monitoring(
    svc: MonitorServiceDep,
) -> ApiResponse:
    ok, message = svc.start_monitoring()
    if ok:
        api_logger.info("启动监控成功")
    else:
        api_logger.warning("启动监控失败: {}", message)
    return ApiResponse(success=ok, message=message)


@router.post("/api/monitor/stop", response_model=ApiResponse)
def stop_monitoring(
    svc: MonitorServiceDep,
) -> ApiResponse:
    ok, message = svc.stop_monitoring()
    if ok:
        api_logger.info("停止监控成功")
    else:
        api_logger.warning("停止监控失败: {}", message)
    return ApiResponse(success=ok, message=message)


@router.post("/api/actions/login", response_model=ApiResponse)
async def manual_login(
    svc: MonitorServiceDep,
) -> ApiResponse:
    ok, message = await asyncio.to_thread(svc.run_manual_login)
    if ok:
        api_logger.info("手动登录成功")
    else:
        api_logger.warning("手动登录失败: {}", message)
    return ApiResponse(success=ok, message=message)


@router.post("/api/actions/cancel-login", response_model=ApiResponse)
def cancel_login(
    svc: MonitorServiceDep,
) -> ApiResponse:
    ok, message = svc.cancel_login()
    if ok:
        api_logger.info("取消登录成功")
    else:
        api_logger.warning("取消登录失败: {}", message)
    return ApiResponse(success=ok, message=message)


@router.post("/api/actions/test-network", response_model=ApiResponse)
def test_network(
    svc: MonitorServiceDep,
) -> ApiResponse:
    ok, message = svc.test_network()
    if ok:
        api_logger.info("网络测试成功: {}", message)
    else:
        api_logger.warning("网络测试失败: {}", message)
    return ApiResponse(success=ok, message=message)


# ── 纯净模式 ──


@router.get("/api/pure-mode", response_model=PureModeResponse)
def get_pure_mode(
    svc: MonitorServiceDep,
) -> PureModeResponse:
    return PureModeResponse(enabled=svc.pure_mode)


@router.post("/api/pure-mode", response_model=ApiResponse)
def toggle_pure_mode(
    svc: MonitorServiceDep,
) -> ApiResponse:
    try:
        new_value = svc.toggle_pure_mode()
        api_logger.info("切换纯净模式成功: {}", new_value)
        return ApiResponse(
            success=True,
            message=f"纯净模式: {'开启' if new_value else '关闭'}",
            data={"enabled": new_value},
        )
    except Exception as exc:
        api_logger.warning("切换纯净模式失败: {}", exc)
        raise HTTPException(status_code=500, detail=f"切换纯净模式失败: {exc}") from exc


# ── 网卡枚举 ──


@router.get("/api/network/interfaces")
async def get_network_interfaces() -> list[dict[str, object]]:
    """枚举可用物理网卡。"""
    mgr = InterfaceManager()
    interfaces = mgr.list_interfaces()
    return [
        {
            "id": info.name,
            "name": info.name,
            "ip": info.ip,
            "gateway": info.gateway,
            "is_up": info.is_up,
        }
        for info in interfaces
    ]
