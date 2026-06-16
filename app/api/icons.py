"""图标 API 路由。"""

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from app.constants import PROJECT_ROOT

router = APIRouter()

# 图标目录
ICONS_DIR = PROJECT_ROOT / "res" / "icons"


@router.get("/api/icons/{filename}")
async def get_icon(filename: str):
    """获取 SVG 图标文件。"""
    # 安全检查：只允许 .svg 文件
    if not filename.endswith(".svg"):
        raise HTTPException(400, "只支持 SVG 文件")

    icon_path = ICONS_DIR / filename
    if not icon_path.exists():
        raise HTTPException(404, "图标不存在")

    content = icon_path.read_text(encoding="utf-8")
    return Response(content, media_type="image/svg+xml")
