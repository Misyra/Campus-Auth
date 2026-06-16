"""安装 Playwright Chromium API 路由。"""

import asyncio
import sys

from fastapi import APIRouter

from app.utils.logging import get_logger
from app.utils.platform import CREATE_NO_WINDOW_FLAG, is_windows

logger = get_logger("install_playwright", source="backend")

router = APIRouter()

# 并发保护
_installing = False


@router.post("/api/browsers/install-playwright")
async def install_playwright_chromium():
    """安装 Playwright Chromium 浏览器（异步执行）。"""
    global _installing
    if _installing:
        return {"success": False, "message": "安装正在进行中，请稍后再试"}

    _installing = True
    try:
        cmd = [sys.executable, "-m", "playwright", "install", "chromium"]

        kwargs = {}
        if is_windows():
            kwargs["creationflags"] = CREATE_NO_WINDOW_FLAG

        # 使用异步子进程，避免阻塞事件循环
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            **kwargs,
        )

        # 等待完成，设置超时
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=300
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            logger.error("Playwright Chromium 安装超时")
            return {"success": False, "message": "安装超时，请重试"}

        if process.returncode == 0:
            logger.info("Playwright Chromium 安装成功")
            return {"success": True, "message": "Playwright Chromium 安装成功"}
        else:
            error_msg = stderr.decode() if stderr else stdout.decode()
            logger.error("Playwright Chromium 安装失败: {}", error_msg)
            return {"success": False, "message": error_msg}
    except Exception as e:
        logger.exception("Playwright Chromium 安装异常")
        return {"success": False, "message": str(e)}
    finally:
        _installing = False
