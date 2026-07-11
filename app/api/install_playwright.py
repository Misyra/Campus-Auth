"""安装 Playwright Chromium API 路由。"""

import asyncio
import sys
import time

from fastapi import APIRouter

from app.schemas import ApiResponse
from app.utils.logging import get_logger
from app.utils.platform import CREATE_NO_WINDOW_FLAG, is_windows

logger = get_logger("install_playwright", source="backend")

router = APIRouter()

# 并发保护
_install_lock = asyncio.Lock()
_IDLE_TIMEOUT_SECONDS = 300  # 安装进程无输出超时（秒）


@router.post("/api/browsers/install-playwright", response_model=ApiResponse)
async def install_playwright_chromium() -> ApiResponse:
    """安装 Playwright Chromium 浏览器（异步执行）。"""
    if _install_lock.locked():
        logger.debug("Playwright 安装进行中，跳过重复请求")
        return ApiResponse(success=False, message="安装正在进行中，请稍后再试")

    async with _install_lock:
        try:
            cmd = [sys.executable, "-m", "playwright", "install", "chromium"]

            kwargs = {}
            if is_windows():
                kwargs["creationflags"] = CREATE_NO_WINDOW_FLAG

            logger.debug("开始安装 Playwright Chromium")

            # 使用异步子进程，避免阻塞事件循环
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,  # 合并 stdout 和 stderr
                **kwargs,
            )

            # 实时读取输出（带空闲超时保护）
            output_lines = []
            last_output = time.monotonic()
            while True:
                try:
                    async with asyncio.timeout(30):
                        line = await process.stdout.readline()
                        if line:
                            last_output = time.monotonic()
                except asyncio.TimeoutError:
                    idle = time.monotonic() - last_output
                    if idle > _IDLE_TIMEOUT_SECONDS:
                        logger.warning("安装 Playwright 失败: {}秒无输出", _IDLE_TIMEOUT_SECONDS)
                        process.kill()
                        raise
                    logger.debug("Playwright 安装 30 秒无输出，继续等待")
                    continue
                if not line:
                    break
                line_str = line.decode().strip()
                if line_str:
                    logger.info("[playwright] {}", line_str)
                    output_lines.append(line_str)

            # 等待进程完成
            await process.wait()

            if process.returncode == 0:
                logger.info("安装 Playwright Chromium 成功")
                return ApiResponse(success=True, message="Playwright Chromium 安装成功")
            else:
                error_msg = "\n".join(output_lines)
                logger.warning("安装 Playwright Chromium 失败: {}", error_msg)
                return ApiResponse(success=False, message=error_msg)
        except Exception as e:
            logger.exception("安装 Playwright Chromium 异常: {}", e)
            return ApiResponse(success=False, message=str(e))
