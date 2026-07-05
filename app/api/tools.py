"""工具路由 — 任务录制器脚本、文档下载、背景图片管理。"""

from __future__ import annotations

import contextlib
import uuid
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.constants import PROJECT_ROOT
from app.schemas import ApiResponse, FetchUrlRequest
from app.utils.logging import get_logger
from app.utils.repo_proxy import validate_url

router = APIRouter()
api_logger = get_logger("api")

# 背景图片目录
BG_DIR = PROJECT_ROOT / "resources" / "background"
BG_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg"}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB


def _serve_doc(relative_path: str, media_type: str, filename: str) -> FileResponse:
    """检查文档文件存在性并返回 FileResponse。"""
    doc_path = PROJECT_ROOT / relative_path
    if not doc_path.exists():
        raise HTTPException(
            status_code=404, detail="文档文件缺失，可能需要重新安装或更新软件"
        )
    return FileResponse(doc_path, media_type=media_type, filename=filename)


def _cleanup_old_backgrounds(exclude_filename: str) -> None:
    """清理旧的背景图片，保留指定文件。"""
    for old_file in BG_DIR.iterdir():
        if old_file.name != exclude_filename:
            with contextlib.suppress(OSError):
                old_file.unlink()


def _save_background(content: bytes, ext: str) -> dict:
    """保存背景图片并清理旧文件，返回 {filename, url}。"""
    filename = f"{uuid.uuid4().hex}{ext}"
    filepath = BG_DIR / filename
    filepath.write_bytes(content)
    _cleanup_old_backgrounds(filename)
    return {"filename": filename, "url": f"/api/background/{filename}"}


@router.get("/api/tools/task-recorder.user.js")
def download_task_recorder():
    """下载任务录制器用户脚本"""
    script_path = PROJECT_ROOT / "resources" / "tools" / "task-recorder.user.js"
    if not script_path.exists():
        raise HTTPException(
            status_code=404, detail="任务录制器脚本文件缺失，可能需要重新安装或更新软件"
        )
    return FileResponse(script_path, media_type="text/javascript")


@router.get("/api/docs/task-writing-guide")
def download_task_writing_guide():
    """下载任务编写指南文档"""
    return _serve_doc(
        "docs/guides/task-writing-guide.md", "text/markdown", "task-writing-guide.md"
    )


@router.get("/api/docs/task-manual")
def download_task_manual():
    """下载任务手册文档"""
    return _serve_doc("docs/dev/architecture.md", "text/markdown", "task-manual.md")


# ── 背景图片管理 ──


@router.post("/api/background/upload", response_model=ApiResponse)
async def upload_background(file: UploadFile) -> ApiResponse:
    """上传背景图片"""
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"不支持的文件格式: {ext}")

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(400, "文件大小不能超过 5MB")

    data = _save_background(content, ext)
    return ApiResponse(success=True, message="背景图片已上传", data=data)


@router.post("/api/background/fetch-url", response_model=ApiResponse)
async def fetch_background_url(body: FetchUrlRequest) -> ApiResponse:
    """从远程 URL 下载图片并保存到本地"""
    url = body.url.strip()
    validate_url(url)

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
            async with client.stream("GET", url) as resp:
                resp.raise_for_status()

                content_type = resp.headers.get("content-type", "")
                if "image" not in content_type and not url.lower().endswith(
                    (".jpg", ".jpeg", ".png", ".gif", ".webp")
                ):
                    raise HTTPException(
                        400, "该地址返回的内容不是图片格式，请确认地址指向的是图片文件"
                    )

                # 从 Content-Type 或 URL 推断扩展名
                ext_map = {
                    "image/jpeg": ".jpg",
                    "image/png": ".png",
                    "image/gif": ".gif",
                    "image/webp": ".webp",
                    "image/svg+xml": ".svg",
                }
                ext = ext_map.get(content_type.split(";")[0].strip(), "")
                if not ext:
                    ext = Path(url.split("?")[0]).suffix.lower() or ".jpg"
                if ext not in ALLOWED_EXTENSIONS:
                    ext = ".jpg"

                # 检查 Content-Length
                cl = int(resp.headers.get("content-length", 0))
                if cl > MAX_FILE_SIZE:
                    raise HTTPException(400, "图片大小超过 5MB 限制")

                # 流式读取，超限立即中断
                chunks = []
                total = 0
                async for chunk in resp.aiter_bytes(8192):
                    total += len(chunk)
                    if total > MAX_FILE_SIZE:
                        raise HTTPException(400, "图片大小超过 5MB 限制")
                    chunks.append(chunk)
                content = b"".join(chunks)
    except httpx.HTTPError as e:
        api_logger.warning("下载失败: url={}, error={}", url, e)
        raise HTTPException(
            400, "下载图片失败，请检查网络连接或确认地址是否正确"
        ) from e

    data = _save_background(content, ext)
    api_logger.info("下载背景图片成功: {}", data.get("filename"))
    return ApiResponse(success=True, message="图片已下载", data=data)


@router.get("/api/background/{filename}")
async def get_background(filename: str):
    """获取背景图片"""
    safe_name = Path(filename).name
    if safe_name != filename or not safe_name:
        raise HTTPException(status_code=400, detail="文件名包含非法字符")
    filepath = BG_DIR / safe_name
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="图片不存在")
    return FileResponse(filepath)


@router.delete("/api/background/{filename}", response_model=ApiResponse)
async def delete_background(filename: str) -> ApiResponse:
    """删除背景图片"""
    safe_name = Path(filename).name
    if safe_name != filename or not safe_name:
        raise HTTPException(status_code=400, detail="文件名包含非法字符")
    filepath = BG_DIR / safe_name
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="文件不存在")
    try:
        filepath.unlink()
    except PermissionError as exc:
        raise HTTPException(
            status_code=409, detail=f"文件被占用，无法删除: {exc}"
        ) from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"删除文件失败: {exc}") from exc
    return ApiResponse(success=True, message="背景图片已删除")
