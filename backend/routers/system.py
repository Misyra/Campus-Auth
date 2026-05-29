"""系统管理路由 — 健康检查、更新检测、自动启动、卸载、关机。"""

from __future__ import annotations

import os
import threading
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends

from src.utils.logging import get_logger
from src.version import compare_versions, get_project_version

from ..constants import AUTH_DATA_DIR, PROJECT_ROOT
from ..deps import get_autostart_service, get_monitor_service
from ..monitor_service import MonitorService
from ..schemas import ActionResponse, AutoStartStatusResponse

router = APIRouter()
api_logger = get_logger("backend.api", side="BACKEND")


# ── 健康检查 / 更新检测 ──


@router.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": get_project_version(PROJECT_ROOT)}


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
    from src.utils.crypto import has_decryption_error

    config = svc.get_config()
    is_initialized = bool(config.username and config.password)
    if not is_initialized:
        api_logger.info(
            "初始化状态: 未完成 — username=%s, password=%s, auth_url=%s",
            f"'{config.username}'" if config.username else "空",
            "已设置" if config.password else "空",
            f"'{config.auth_url}'" if config.auth_url else "空",
        )
    return {
        "initialized": is_initialized,
        "password_decryption_failed": has_decryption_error(),
    }


# ── 自动启动 ──


@router.get("/api/autostart/status", response_model=AutoStartStatusResponse)
def autostart_status(
    autostart_svc=Depends(get_autostart_service),
) -> AutoStartStatusResponse:
    status = autostart_svc.status()
    return AutoStartStatusResponse(
        platform=str(status.get("platform", "")),
        enabled=bool(status.get("enabled", False)),
        method=str(status.get("method", "")),
        location=str(status.get("location", "")),
    )


@router.post("/api/autostart/enable", response_model=ActionResponse)
def enable_autostart(
    autostart_svc=Depends(get_autostart_service),
) -> ActionResponse:
    ok, message = autostart_svc.enable()
    api_logger.info("Autostart enable requested -> success=%s, message=%s", ok, message)
    return ActionResponse(success=ok, message=message)


@router.post("/api/autostart/disable", response_model=ActionResponse)
def disable_autostart(
    autostart_svc=Depends(get_autostart_service),
) -> ActionResponse:
    ok, message = autostart_svc.disable()
    api_logger.info("Autostart disable requested -> success=%s, message=%s", ok, message)
    return ActionResponse(success=ok, message=message)


# ── 关机 ──


@router.post("/api/shutdown", response_model=ActionResponse)
def shutdown_server(
    svc: MonitorService = Depends(get_monitor_service),
) -> ActionResponse:
    """关闭服务器"""
    api_logger.warning("Shutdown requested")

    def _do_shutdown():
        try:
            svc.stop_monitoring()
        except Exception:
            api_logger.debug("关闭监控服务失败", exc_info=True)
        try:
            from src.playwright_worker import get_worker
            get_worker().stop(timeout=3)
        except Exception:
            api_logger.debug("关闭 PlaywrightWorker 失败", exc_info=True)
        try:
            from src.playwright_worker import cleanup_orphan_browsers
            cleanup_orphan_browsers()
        except Exception:
            api_logger.debug("清理孤儿浏览器失败", exc_info=True)
        try:
            (AUTH_DATA_DIR / "campus_network_auth.pid").unlink(missing_ok=True)
        except Exception:
            api_logger.debug("PID 文件清理失败", exc_info=True)
        os._exit(0)

    threading.Thread(target=_do_shutdown, daemon=True).start()

    return ActionResponse(success=True, message="服务器正在关闭...")


# ── 卸载 ──


@router.get("/api/uninstall/detect")
def uninstall_detect() -> list[dict]:
    """检测可清理的外部残留项目"""
    from ..uninstall_service import detect

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
    from ..uninstall_service import perform

    keys = payload.get("keys", [])
    api_logger.warning("Uninstall requested, keys=%s", keys)
    results = perform(keys)
    return {
        "success": all(r.success for r in results),
        "results": [
            {"key": r.key, "label": r.label, "success": r.success, "message": r.message}
            for r in results
        ],
    }
