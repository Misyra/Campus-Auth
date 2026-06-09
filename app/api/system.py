"""系统管理路由 — 健康检查、更新检测、关机、卸载。"""

from __future__ import annotations

import os

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request

from app.constants import AUTH_DATA_DIR, PROJECT_ROOT
from app.deps import get_monitor_service
from app.schemas import ActionResponse
from app.services.monitor import MonitorService
from app.utils.logging import get_logger
from app.version import compare_versions, get_project_version

router = APIRouter()
api_logger = get_logger("backend.api", side="BACKEND")


# ── 健康检查 / 更新检测 ──


@router.get("/api/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "version": get_project_version(PROJECT_ROOT),
        "python_version": f"{os.sys.version_info.major}.{os.sys.version_info.minor}.{os.sys.version_info.micro}",
    }


@router.get("/api/check-update")
async def check_update() -> dict:
    current = get_project_version(PROJECT_ROOT)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://api.github.com/repos/Misyra/Campus-Auth/releases/latest",
                headers={
                    "Accept": "application/vnd.github.v3+json",
                    "User-Agent": "Campus-Auth",
                },
            )
        resp.raise_for_status()
        data = resp.json()
        tag = data.get("tag_name", "").lstrip("v")
        return {
            "current": current,
            "latest": tag,
            "has_update": compare_versions(tag, current) > 0,
            "url": data.get("html_url", ""),
            "body": data.get("body", ""),
            "published_at": data.get("published_at", ""),
        }
    except Exception as e:
        return {
            "current": current,
            "latest": None,
            "has_update": False,
            "error": str(e),
        }


# ── 初始化状态 ──


@router.get("/api/init-status")
def get_init_status(
    svc: MonitorService = Depends(get_monitor_service),
) -> dict:
    from app.utils.crypto import has_decryption_error

    config = svc.get_config()
    is_initialized = bool(config.username and config.password)
    if not is_initialized:
        api_logger.info(
            "初始化状态: 未完成 — username={}, password={}, auth_url={}",
            f"'{config.username}'" if config.username else "空",
            "已设置" if config.password else "空",
            f"'{config.auth_url}'" if config.auth_url else "空",
        )
    return {
        "initialized": is_initialized,
        "password_decryption_failed": has_decryption_error(),
    }


# ── 关机 ──


@router.post("/api/shutdown", response_model=ActionResponse)
def shutdown_server(
    request: Request,
    svc: MonitorService = Depends(get_monitor_service),
) -> ActionResponse:
    """关闭服务器 — 通过 shutdown_event 触发 lifespan 正常清理"""
    api_logger.warning("收到关机请求")

    # 停止监控服务
    try:
        svc.stop_monitoring()
    except Exception:
        api_logger.warning("关闭监控服务失败", exc_info=True)

    # 停止 PlaywrightWorker
    try:
        from app.workers.playwright_worker import get_worker

        get_worker().stop(timeout=3)
    except Exception:
        api_logger.warning("关闭 PlaywrightWorker 失败", exc_info=True)

    # 清理孤儿浏览器
    try:
        from app.workers.playwright_worker import cleanup_orphan_browsers

        cleanup_orphan_browsers()
    except Exception:
        api_logger.warning("清理孤儿浏览器失败", exc_info=True)

    # 清理 PID 文件
    try:
        (AUTH_DATA_DIR / "campus_network_auth.pid").unlink(missing_ok=True)
    except Exception:
        api_logger.warning("PID 文件清理失败", exc_info=True)

    # 通过 shutdown_event 触发 lifespan 正常关闭
    if hasattr(request.app.state, "shutdown_event"):
        request.app.state.shutdown_event.set()

    return ActionResponse(success=True, message="服务器正在关闭...")


# ── 卸载 ──


@router.get("/api/uninstall/detect")
def uninstall_detect() -> list[dict]:
    """检测可清理的外部残留项目"""
    from app.services.uninstall import detect

    items = detect()
    return [
        {
            "key": it.key,
            "label": it.label,
            "exists": it.exists,
            "path": it.path,
            "size_mb": round(it.size_mb, 1),
        }
        for it in items
    ]


@router.post("/api/uninstall")
def uninstall_perform(payload: dict) -> dict:
    """执行卸载清理"""
    from app.services.uninstall import perform

    keys = payload.get("keys", [])
    if not isinstance(keys, list):
        raise HTTPException(400, "keys 必须是列表")
    api_logger.warning("收到卸载请求, keys={}", keys)
    results = perform(keys)
    return {
        "success": all(r.success for r in results),
        "results": [
            {"key": r.key, "label": r.label, "success": r.success, "message": r.message}
            for r in results
        ],
    }
