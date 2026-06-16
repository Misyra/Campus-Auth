"""安装 Playwright Chromium API 路由。"""

import asyncio
import sys

from fastapi import APIRouter

from app.utils.logging import get_logger
from app.utils.platform import CREATE_NO_WINDOW_FLAG, is_windows

logger = get_logger("install_playwright", source="backend")

router = APIRouter()

# 并发保护
_install_lock = asyncio.Lock()


@router.post("/api/browsers/install-playwright")
async def install_playwright_chromium():
    """安装 Playwright Chromium 浏览器（异步执行）。"""
    if _install_lock.locked():
        return {"success": False, "message": "安装正在进行中，请稍后再试"}

    async with _install_lock:
        try:
            cmd = [sys.executable, "-m", "playwright", "install", "chromium"]

            kwargs = {}
            if is_windows():
                kwargs["creationflags"] = CREATE_NO_WINDOW_FLAG

            logger.info("开始安装 Playwright Chromium...")

            # 使用异步子进程，避免阻塞事件循环
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,  # 合并 stdout 和 stderr
                **kwargs,
            )

            # 实时读取输出
            output_lines = []
            while True:
                line = await process.stdout.readline()
                if not line:
                    break
                line_str = line.decode().strip()
                if line_str:
                    logger.info("[playwright] {}", line_str)
                    output_lines.append(line_str)

            # 等待进程完成
            await process.wait()

            if process.returncode == 0:
                logger.info("Playwright Chromium 安装成功")
                return {"success": True, "message": "Playwright Chromium 安装成功"}
            else:
                error_msg = "\n".join(output_lines)
                logger.error("Playwright Chromium 安装失败: {}", error_msg)
                return {"success": False, "message": error_msg}
        except Exception as e:
            logger.exception("Playwright Chromium 安装异常")
            return {"success": False, "message": str(e)}
