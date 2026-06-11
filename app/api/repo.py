"""仓库代理路由 — 代理获取远程任务仓库索引和任务配置。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.deps import get_profile_service
from app.services.profile_service import ProfileService
from app.utils.repo_proxy import repo_fetch_json

router = APIRouter()


@router.get("/api/repo/fetch")
def repo_fetch_index(
    url: str = Query(..., description="索引 JSON 地址"),
    profile_svc: ProfileService = Depends(get_profile_service),
) -> list:
    """代理获取任务仓库索引，避免前端跨域问题"""
    proxy = (profile_svc.load().system.proxy or "").strip()
    return repo_fetch_json(url, list, "索引", proxy=proxy)


@router.get("/api/repo/task")
def repo_fetch_task(
    url: str = Query(..., description="任务 JSON 地址"),
    profile_svc: ProfileService = Depends(get_profile_service),
) -> dict:
    """代理获取单个任务配置"""
    proxy = (profile_svc.load().system.proxy or "").strip()
    return repo_fetch_json(url, dict, "任务", proxy=proxy)
