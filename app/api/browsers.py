"""浏览器 API 路由。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.deps import ProfileServiceDep
from app.schemas import BrowserInfo, BrowserListResponse
from app.utils.browser_registry import detect_browsers
from app.utils.logging import get_logger

logger = get_logger("browsers_api", source="backend")

router = APIRouter()


@router.get("/api/browsers", response_model=BrowserListResponse)
async def get_browsers(
    profile_svc: ProfileServiceDep,
) -> BrowserListResponse:
    """获取浏览器列表和当前配置。"""
    try:
        import asyncio
        browsers = await asyncio.to_thread(detect_browsers)

        profile_data = profile_svc.load()
        current = "playwright"
        if profile_data and profile_data.global_config:
            current = profile_data.global_config.browser.browser_channel

        return BrowserListResponse(
            browsers=[
                BrowserInfo(
                    channel=b.channel,
                    name=b.name,
                    icon=b.icon,
                    installed=b.installed,
                    needs_download=b.needs_download,
                    description=b.description,
                )
                for b in browsers
            ],
            current=current,
        )
    except Exception as e:
        logger.warning("获取浏览器列表失败: {}", e, exc_info=True)
        raise HTTPException(500, f"获取浏览器列表失败: {e}")
