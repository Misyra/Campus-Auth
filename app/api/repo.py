"""仓库代理路由 — 代理获取远程任务仓库索引和任务配置。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.utils.logging import get_logger
from app.utils.repo_proxy import async_repo_fetch_json, validate_url

router = APIRouter()
api_logger = get_logger("api", source="backend")


@router.get("/api/repo/fetch")
async def repo_fetch_index(
    url: str = Query(..., description="索引 JSON 地址"),
) -> list:
    """代理获取任务仓库索引，避免前端跨域问题"""
    validate_url(url)
    return await async_repo_fetch_json(url, list, "索引")


@router.get("/api/repo/task")
async def repo_fetch_task(
    url: str = Query(..., description="任务 JSON 地址"),
) -> dict:
    """代理获取单个任务配置"""
    try:
        validate_url(url)
        return await async_repo_fetch_json(url, dict, "任务")
    except HTTPException as e:
        api_logger.warning("仓库代理请求失败: {} ({})", e.detail, url)
        raise
