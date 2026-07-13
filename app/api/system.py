"""系统管理路由 — 健康检查、更新检测、关机、卸载。"""

from __future__ import annotations

import asyncio
import os
import sys
import time

import httpx
import psutil
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from app.constants import AUTH_DATA_DIR, PROJECT_ROOT
from app.deps import MonitorServiceDep
from app.schemas import (
    ApiResponse,
    HealthResponse,
    InitStatusResponse,
    UninstallItem,
    UninstallRequest,
    UpdateCheckResponse,
)
from app.utils.logging import get_logger
from app.version import compare_versions, get_project_version

router = APIRouter()
api_logger = get_logger("api", source="backend")

# 更新检查缓存（避免触发 GitHub API 速率限制）
# 注意：全局可变状态，单用户桌面应用场景下无并发风险
_update_cache: dict | None = None
_update_cache_time: float = 0
_UPDATE_CACHE_TTL = 12 * 60 * 60  # 12 小时
_update_lock = asyncio.Lock()


# ── 健康检查 / 更新检测 ──




@router.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    proc = psutil.Process(os.getpid())
    mem = proc.memory_info()

    return HealthResponse(
        status="ok",
        version=get_project_version(PROJECT_ROOT),
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        memory={
            "rss_mb": round(mem.rss / 1024 / 1024, 1),
            "vms_mb": round(mem.vms / 1024 / 1024, 1),
        },
        process={
            "pid": proc.pid,
        },
    )


@router.get("/api/check-update", response_model=UpdateCheckResponse)
async def check_update() -> UpdateCheckResponse:
    global _update_cache, _update_cache_time

    current = get_project_version(PROJECT_ROOT)

    async with _update_lock:
        # 缓存命中直接返回
        if (
            _update_cache
            and (time.monotonic() - _update_cache_time) < _UPDATE_CACHE_TTL
        ):
            return UpdateCheckResponse(**_update_cache, current=current)

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
            result = UpdateCheckResponse(
                current=current,
                latest=tag,
                has_update=compare_versions(tag, current) > 0,
                url=data.get("html_url", ""),
                body=data.get("body", ""),
                published_at=data.get("published_at", ""),
            )
            # 更新缓存（排除 current，避免重建时重复传参）
            _update_cache = result.model_dump(exclude={"current"})
            _update_cache_time = time.monotonic()
            return result
        except Exception as e:
            api_logger.warning("检查更新失败: {}", e)
            # 请求失败但有旧缓存，返回旧缓存 + 错误信息
            if _update_cache:
                return UpdateCheckResponse(
                    **_update_cache,
                    current=current,
                    cached=True,
                    error=str(e),
                )
            return UpdateCheckResponse(
                current=current,
                latest=None,
                has_update=False,
                error=str(e),
            )


# ── 初始化状态 ──


@router.get("/api/init-status", response_model=InitStatusResponse)
def get_init_status(
    svc: MonitorServiceDep,
) -> InitStatusResponse:
    from app.utils.crypto import has_decryption_error

    config = svc.get_runtime_config()
    is_initialized = bool(config.credentials.username and config.credentials.password)

    # 检查用户是否已同意使用协议
    agree_file = svc.project_root / "config" / ".agree"
    agreed = agree_file.exists()

    return InitStatusResponse(
        initialized=is_initialized,
        agreed=agreed,
        password_decryption_failed=has_decryption_error(),
    )


@router.post("/api/agree", response_model=ApiResponse)
def agree_to_terms(
    svc: MonitorServiceDep,
) -> ApiResponse:
    """用户同意使用协议，生成 .agree 标记文件。"""
    try:
        agree_file = svc.project_root / "config" / ".agree"
        agree_file.parent.mkdir(parents=True, exist_ok=True)
        agree_file.write_text("", encoding="utf-8")
        api_logger.info("用户已同意使用协议")
        return ApiResponse(success=True, message="已同意协议")
    except Exception as exc:
        api_logger.warning("保存协议同意状态失败: {}", exc)
        raise HTTPException(status_code=500, detail=f"保存失败: {exc}") from exc


# ── 关机 ──


@router.post("/api/shutdown", response_model=ApiResponse)
def shutdown_server(
    request: Request,
    bg_tasks: BackgroundTasks,
    svc: MonitorServiceDep,
) -> ApiResponse:
    """关闭服务器 — 通过 shutdown_event 触发 lifespan 正常清理"""
    api_logger.info("收到关机请求")

    # 停止监控服务
    try:
        svc.stop_monitoring()
    except Exception:
        api_logger.warning("关闭监控服务失败", exc_info=True)

    # 清理 PID 文件
    try:
        (AUTH_DATA_DIR / "campus_network_auth.pid").unlink(missing_ok=True)
    except Exception:
        api_logger.warning("PID 文件清理失败", exc_info=True)

    # Playwright Worker 和孤儿浏览器清理由 lifespan 的 container.shutdown() 统一处理

    # 通过 shutdown_event 触发 lifespan 正常关闭
    bg_tasks.add_task(lambda: request.app.state.shutdown_event.set())

    return ApiResponse(success=True, message="服务器正在关闭，请稍候，页面将自动断开")




# ── 卸载 ──


@router.get("/api/uninstall/detect", response_model=list[UninstallItem])
def uninstall_detect() -> list[UninstallItem]:
    """检测可清理的外部残留项目"""
    from app.services.uninstall import detect

    items = detect()
    return [
        UninstallItem(
            key=it.key,
            label=it.label,
            exists=it.exists,
            path=it.path,
            size_mb=round(it.size_mb, 1),
        )
        for it in items
    ]


@router.post("/api/uninstall", response_model=ApiResponse)
def uninstall_perform(payload: UninstallRequest) -> ApiResponse:
    """执行卸载清理"""
    from app.services.uninstall import perform

    api_logger.info("收到卸载请求, keys={}", payload.keys)
    results = perform(payload.keys)
    all_ok = all(r.success for r in results)
    detail = [
        {"key": r.key, "label": r.label, "success": r.success, "message": r.message}
        for r in results
    ]
    return ApiResponse(
        success=all_ok,
        message=f"清理完成（{sum(1 for r in results if r.success)}/{len(results)}）",
        data={"results": detail},
    )
