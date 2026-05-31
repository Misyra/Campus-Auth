"""登录历史路由 — 查询登录记录。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ..deps import get_login_history_service
from ..login_history_service import LoginHistoryEntry, LoginHistoryService

router = APIRouter()


@router.get("/api/login-history", response_model=list[LoginHistoryEntry])
def get_login_history(
    limit: int = Query(default=30, ge=1, le=500),
    svc: LoginHistoryService = Depends(get_login_history_service),
) -> list[LoginHistoryEntry]:
    """获取最近的登录历史记录。"""
    return svc.list_recent(limit=limit)
