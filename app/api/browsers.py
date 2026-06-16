"""浏览器 API 路由。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.deps import get_profile_service
from app.services.profile_service import ProfileService
from app.utils.browser_registry import detect_browsers
from app.utils.logging import get_logger

logger = get_logger("browsers_api", source="backend")

router = APIRouter()


@router.get("/api/browsers")
async def get_browsers(
    profile_svc: ProfileService = Depends(get_profile_service),
):
    """获取浏览器列表和当前配置。"""
    try:
        browsers = detect_browsers()

        profile_data = profile_svc.load()
        current = "playwright"
        if profile_data and profile_data.global_settings:
            current = profile_data.global_settings.browser_channel

        return {
            "browsers": [
                {
                    "channel": b.channel,
                    "name": b.name,
                    "icon": b.icon,
                    "installed": b.installed,
                    "needs_download": b.needs_download,
                    "description": b.description,
                }
                for b in browsers
            ],
            "current": current,
        }
    except Exception as e:
        logger.exception("获取浏览器列表失败")
        raise HTTPException(500, f"获取浏览器列表失败: {e}")
