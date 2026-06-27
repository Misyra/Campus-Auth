"""登录历史路由 — 查询、清空登录记录。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.deps import get_login_history_service
from app.schemas import ApiResponse
from app.services.login_history_service import LoginHistoryEntry, LoginHistoryService

router = APIRouter()


@router.get("/api/login-history", response_model=list[LoginHistoryEntry])
def get_login_history(
    limit: int = Query(default=30, ge=1, le=500),
    svc: LoginHistoryService = Depends(get_login_history_service),
) -> list[LoginHistoryEntry]:
    """获取最近的登录历史记录。"""
    return svc.list_recent(limit=limit)


@router.delete("/api/login-history", response_model=ApiResponse)
def clear_login_history(
    svc: LoginHistoryService = Depends(get_login_history_service),
) -> ApiResponse:
    """清空所有登录历史记录。"""
    count = svc.clear()
    return ApiResponse(success=True, message=f"已清空 {count} 条登录记录")
