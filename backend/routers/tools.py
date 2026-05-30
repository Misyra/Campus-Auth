"""工具路由 — 任务录制器脚本、文档下载、背景图片管理。"""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import FileResponse

from ..constants import PROJECT_ROOT

router = APIRouter()

# 背景图片目录
BG_DIR = PROJECT_ROOT / "tools" / "background"
BG_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB


@router.get("/api/tools/task-recorder.user.js")
def download_task_recorder():
    """下载任务录制器用户脚本"""
    script_path = PROJECT_ROOT / "tools" / "task-recorder.user.js"
    if not script_path.exists():
        raise HTTPException(status_code=404, detail="任务录制器脚本不存在")
    return FileResponse(script_path, media_type="text/javascript")


@router.get("/api/docs/task-writing-guide")
def download_task_writing_guide():
    """下载任务编写指南文档"""
    doc_path = PROJECT_ROOT / "doc" / "task-writing-guide.md"
    if not doc_path.exists():
        raise HTTPException(status_code=404, detail="文档不存在")
    return FileResponse(
        doc_path, media_type="text/markdown", filename="task-writing-guide.md"
    )


# ── 背景图片管理 ──


@router.post("/api/background/upload")
async def upload_background(file: UploadFile) -> dict:
    """上传背景图片"""
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"不支持的文件格式: {ext}")

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(400, "文件大小不能超过 5MB")

    filename = f"{uuid.uuid4().hex}{ext}"
    filepath = BG_DIR / filename
    filepath.write_bytes(content)

    return {"filename": filename, "url": f"/api/background/{filename}"}


@router.get("/api/background/{filename}")
async def get_background(filename: str):
    """获取背景图片"""
    safe_name = Path(filename).name
    if safe_name != filename or not safe_name:
        raise HTTPException(status_code=400, detail="无效的文件名")
    filepath = BG_DIR / safe_name
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="图片不存在")
    return FileResponse(filepath)


@router.delete("/api/background/{filename}")
async def delete_background(filename: str) -> dict:
    """删除背景图片"""
    safe_name = Path(filename).name
    if safe_name != filename or not safe_name:
        raise HTTPException(status_code=400, detail="无效的文件名")
    filepath = BG_DIR / safe_name
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="文件不存在")
    filepath.unlink()
    return {"success": True, "message": "背景图片已删除"}
