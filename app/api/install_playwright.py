"""安装 Playwright Chromium API 路由。"""

import subprocess
import sys
import threading

from fastapi import APIRouter

from app.utils.logging import get_logger
from app.utils.platform import CREATE_NO_WINDOW_FLAG, is_windows

logger = get_logger("install_playwright", source="backend")

router = APIRouter()

# 并发保护锁
_install_lock = threading.Lock()


@router.post("/api/browsers/install-playwright")
async def install_playwright_chromium():
    """安装 Playwright Chromium 浏览器。"""
    if not _install_lock.acquire(blocking=False):
        return {"success": False, "message": "安装正在进行中，请稍后再试"}

    try:
        kwargs = {
            "capture_output": True,
            "text": True,
            "timeout": 300,  # 5 分钟超时
        }
        if is_windows():
            kwargs["creationflags"] = CREATE_NO_WINDOW_FLAG

        result = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            **kwargs,
        )
        if result.returncode == 0:
            logger.info("Playwright Chromium 安装成功")
            return {"success": True, "message": "Playwright Chromium 安装成功"}
        else:
            logger.error("Playwright Chromium 安装失败: {}", result.stderr)
            return {"success": False, "message": result.stderr or result.stdout}
    except subprocess.TimeoutExpired:
        logger.error("Playwright Chromium 安装超时")
        return {"success": False, "message": "安装超时，请重试"}
    except Exception as e:
        logger.exception("Playwright Chromium 安装异常")
        return {"success": False, "message": str(e)}
    finally:
        _install_lock.release()
