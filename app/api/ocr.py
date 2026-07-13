"""OCR 依赖管理路由 — ddddocr 安装状态查询、安装、卸载。"""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.constants import PROJECT_ROOT
from app.schemas import ApiResponse, OcrStatusResponse
from app.utils.files import dir_size_mb
from app.utils.logging import get_logger
from app.utils.platform import CREATE_NO_WINDOW_FLAG

router = APIRouter()
api_logger = get_logger("api", source="backend")




def _estimate_pkg_size_mb(pkg_name: str) -> float:
    """估算已安装包的磁盘占用（MB），不实际导入模块"""
    import importlib.util

    spec = importlib.util.find_spec(pkg_name)
    if spec is None or not spec.origin:
        return 0.0

    pkg_path = Path(spec.origin)
    if pkg_path.name == "__init__.py":
        pkg_path = pkg_path.parent

    return dir_size_mb(pkg_path).size_mb


@router.get("/api/ocr/status", response_model=OcrStatusResponse)
def ocr_status() -> OcrStatusResponse:
    """获取 OCR 依赖安装状态"""
    installed = importlib.util.find_spec("ddddocr") is not None
    size_mb = 0.0
    if installed:
        size_mb = round(
            _estimate_pkg_size_mb("ddddocr") + _estimate_pkg_size_mb("onnxruntime"), 1
        )
    return OcrStatusResponse(
        installed=installed,
        size_mb=size_mb,
    )


@router.post("/api/ocr/install", response_model=ApiResponse)
def ocr_install() -> ApiResponse:
    """安装 ddddocr 依赖"""
    if importlib.util.find_spec("ddddocr") is not None:
        return ApiResponse(success=True, message="ddddocr 已安装")

    api_logger.debug("开始安装 ddddocr")
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
            api_logger.info("安装 ddddocr 成功")
            return ApiResponse(success=True, message="ddddocr 安装成功")
        else:
            error_msg = result.stderr.strip() or result.stdout.strip() or "未知错误"
            api_logger.warning("安装 ddddocr 失败: {}", error_msg)
            return ApiResponse(success=False, message=f"安装失败: {error_msg}")
    except subprocess.TimeoutExpired:
        api_logger.warning("安装 ddddocr 失败: 超时")
        return ApiResponse(
            success=False, message="安装超时（超过 5 分钟），请检查网络后重试"
        )
    except FileNotFoundError:
        api_logger.warning("安装 ddddocr 失败: uv 未找到")
        return ApiResponse(
            success=False,
            message="未找到 uv 包管理器，请先通过 https://docs.astral.sh/uv/ 安装",
        )
    except Exception as e:
        api_logger.exception("安装 ddddocr 异常: {}", e)
        raise HTTPException(status_code=500, detail=f"安装异常: {e}") from e


@router.post("/api/ocr/uninstall", response_model=ApiResponse)
def ocr_uninstall() -> ApiResponse:
    """卸载 ddddocr 依赖"""
    if importlib.util.find_spec("ddddocr") is None:
        return ApiResponse(success=True, message="ddddocr 未安装，无需卸载")

    api_logger.debug("开始卸载 ddddocr")
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
            api_logger.info("卸载 ddddocr 成功")
            return ApiResponse(success=True, message="ddddocr 已卸载")
        else:
            error_msg = result.stderr.strip() or result.stdout.strip() or "未知错误"
            api_logger.warning("卸载 ddddocr 失败: {}", error_msg)
            return ApiResponse(success=False, message=f"卸载失败: {error_msg}")
    except subprocess.TimeoutExpired:
        api_logger.warning("卸载 ddddocr 失败: 超时")
        return ApiResponse(success=False, message="卸载超时，请稍后重试")
    except FileNotFoundError:
        return ApiResponse(success=False, message="未找到 uv 包管理器")
    except Exception as e:
        api_logger.exception("卸载 ddddocr 异常: {}", e)
        raise HTTPException(status_code=500, detail=f"卸载异常: {e}") from e
