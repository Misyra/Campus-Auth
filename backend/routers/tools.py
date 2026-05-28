"""工具下载路由 — 任务录制器脚本和文档下载。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ..constants import PROJECT_ROOT

router = APIRouter()


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
