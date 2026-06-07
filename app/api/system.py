"""系统管理路由 — 健康检查、更新检测、自动启动、卸载、关机、OCR 依赖管理。"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request

from app.utils.logging import get_logger
from app.utils.platform_utils import CREATE_NO_WINDOW_FLAG
from app.version import compare_versions, get_project_version

from app.constants import AUTH_DATA_DIR, PROJECT_ROOT
from app.deps import get_autostart_service, get_monitor_service
from app.services.monitor import MonitorService
from app.utils.shell_utils import (
    detect_shells as detect_available_shells,
    get_default_shell,
)
from app.schemas import ActionResponse, AutoStartStatusResponse

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


# ── 自动启动 ──


@router.get("/api/shells")
def list_shells() -> dict:
    """获取系统可用的 Shell 列表。"""
    shells = detect_available_shells()
    default_shell = get_default_shell()
    return {
        "shells": shells,
        "default": default_shell,
    }


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
    api_logger.info("启用自启动 -> success={}, message={}", ok, message)
    return ActionResponse(success=ok, message=message)


@router.post("/api/autostart/disable", response_model=ActionResponse)
def disable_autostart(
    autostart_svc=Depends(get_autostart_service),
) -> ActionResponse:
    ok, message = autostart_svc.disable()
    api_logger.info("禁用自启动 -> success={}, message={}", ok, message)
    return ActionResponse(success=ok, message=message)


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


# ── OCR 依赖管理 ──


def _check_ddddocr_installed() -> bool:
    """检测 ddddocr 是否已安装"""
    try:
        import ddddocr  # noqa: F401

        return True
    except ImportError:
        return False


def _estimate_pkg_size_mb(pkg_name: str) -> float:
    """估算已安装包的磁盘占用（MB），不实际导入模块"""
    import importlib.util

    spec = importlib.util.find_spec(pkg_name)
    if spec is None or not spec.origin:
        return 0.0

    pkg_path = Path(spec.origin)
    # 包目录的 __init__.py → 取父目录；单文件模块直接用
    if pkg_path.name == "__init__.py":
        pkg_path = pkg_path.parent

    if not pkg_path.exists():
        return 0.0

    if pkg_path.is_file():
        return round(pkg_path.stat().st_size / (1024 * 1024), 1)

    total = 0
    try:
        for f in pkg_path.rglob("*"):
            if f.is_file():
                total += f.stat().st_size
    except OSError:
        pass
    return round(total / (1024 * 1024), 1)


@router.get("/api/ocr/status")
def ocr_status() -> dict:
    """获取 OCR 依赖安装状态"""
    installed = _check_ddddocr_installed()
    size_mb = 0.0
    if installed:
        size_mb = round(
            _estimate_pkg_size_mb("ddddocr") + _estimate_pkg_size_mb("onnxruntime"), 1
        )
    return {
        "installed": installed,
        "size_mb": size_mb,
    }


@router.post("/api/ocr/install", response_model=ActionResponse)
def ocr_install() -> ActionResponse:
    """安装 ddddocr 依赖"""
    if _check_ddddocr_installed():
        return ActionResponse(success=True, message="ddddocr 已安装")

    api_logger.info("开始安装 ddddocr")
    try:
        uv_exe = "uv"
        result = subprocess.run(
            [uv_exe, "add", "ddddocr", "onnxruntime"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=300,
            creationflags=CREATE_NO_WINDOW_FLAG,
        )
        if result.returncode == 0:
            api_logger.info("ddddocr 安装成功")
            # 清除模块缓存，确保下次 import 能找到
            return ActionResponse(success=True, message="ddddocr 安装成功")
        else:
            error_msg = result.stderr.strip() or result.stdout.strip() or "未知错误"
            api_logger.error("ddddocr 安装失败: {}", error_msg)
            return ActionResponse(success=False, message=f"安装失败: {error_msg}")
    except subprocess.TimeoutExpired:
        api_logger.error("ddddocr 安装超时")
        return ActionResponse(
            success=False, message="安装超时（超过 5 分钟），请检查网络后重试"
        )
    except FileNotFoundError:
        api_logger.error("uv 未找到")
        return ActionResponse(success=False, message="未找到 uv 包管理器，请先安装 uv")
    except Exception as e:
        api_logger.error("ddddocr 安装异常: {}", e)
        return ActionResponse(success=False, message=f"安装异常: {e}")


@router.post("/api/ocr/uninstall", response_model=ActionResponse)
def ocr_uninstall() -> ActionResponse:
    """卸载 ddddocr 依赖"""
    if not _check_ddddocr_installed():
        return ActionResponse(success=True, message="ddddocr 未安装，无需卸载")

    api_logger.info("开始卸载 ddddocr")
    try:
        uv_exe = "uv"
        result = subprocess.run(
            [uv_exe, "remove", "ddddocr", "onnxruntime"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=60,
            creationflags=CREATE_NO_WINDOW_FLAG,
        )
        if result.returncode == 0:
            api_logger.info("ddddocr 卸载成功")
            return ActionResponse(success=True, message="ddddocr 已卸载")
        else:
            error_msg = result.stderr.strip() or result.stdout.strip() or "未知错误"
            api_logger.error("ddddocr 卸载失败: {}", error_msg)
            return ActionResponse(success=False, message=f"卸载失败: {error_msg}")
    except FileNotFoundError:
        return ActionResponse(success=False, message="未找到 uv 包管理器")
    except Exception as e:
        api_logger.error("ddddocr 卸载异常: {}", e)
        return ActionResponse(success=False, message=f"卸载异常: {e}")


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
