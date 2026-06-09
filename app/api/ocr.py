"""OCR 依赖管理路由 — ddddocr 安装状态查询、安装、卸载。"""

from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi import APIRouter

from app.constants import PROJECT_ROOT
from app.schemas import ActionResponse
from app.utils.logging import get_logger
from app.utils.platform_utils import CREATE_NO_WINDOW_FLAG

router = APIRouter()
api_logger = get_logger("backend.api", source="backend")


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
