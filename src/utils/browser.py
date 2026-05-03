#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
浏览器上下文管理器
"""

import json
import threading

from .logging import LoggerSetup


class BrowserContextManager:
    """浏览器上下文管理器 - 使用异步上下文管理器确保资源正确释放"""

    def __init__(self, config: dict, cancel_event: threading.Event | None = None):
        """
        初始化浏览器上下文管理器

        参数:
            config: 配置字典
            cancel_event: 取消事件，设置后中断浏览器操作
        """
        self.config = config
        self.cancel_event = cancel_event
        self.browser_settings = config.get("browser_settings", {})
        self.logger = LoggerSetup.setup_logger(
            f"{__name__}_browser", config.get("logging", {})
        )

        # 浏览器相关属性
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None

    def _is_cancelled(self) -> bool:
        return self.cancel_event is not None and self.cancel_event.is_set()

    async def __aenter__(self):
        """异步上下文管理器入口"""
        if self._is_cancelled():
            raise RuntimeError("浏览器启动已取消")
        await self._start_browser()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口 - 确保资源总是被释放"""
        await self._cleanup_browser()
        # 如果有异常，记录但不抑制
        if exc_type:
            self.logger.error(f"浏览器操作异常: {exc_type.__name__}: {exc_val}")
        return False  # 不抑制异常

    async def _start_browser(self) -> None:
        """启动浏览器（内部方法）"""
        try:
            from playwright.async_api import async_playwright

            self.playwright = await async_playwright().start()
            headless = self.browser_settings.get("headless", False)
            safe_mode = self.browser_settings.get("safe_mode", False)

            if safe_mode:
                # 安全模式：不注入任何自定义参数
                self.browser = await self.playwright.chromium.launch(
                    headless=headless
                )
                self.context = await self.browser.new_context(
                    viewport={"width": 1280, "height": 720},
                )
            else:
                low_resource_mode = bool(
                    self.browser_settings.get("low_resource_mode", False)
                )
                browser_args = self._get_browser_args()
                self.browser = await self.playwright.chromium.launch(
                    headless=headless, args=browser_args
                )
                extra_headers = self._get_extra_http_headers()
                ctx_opts: dict = {
                    "viewport": {"width": 1280, "height": 720},
                    "extra_http_headers": extra_headers,
                }
                user_agent = (self.browser_settings.get("user_agent") or "").strip()
                if user_agent:
                    ctx_opts["user_agent"] = user_agent
                self.context = await self.browser.new_context(**ctx_opts)
                if low_resource_mode:
                    await self.context.route("**/*", self._handle_low_resource_request)

            # 创建页面
            self.page = await self.context.new_page()

            self.logger.info(
                f"浏览器已启动，无头模式: {headless}, 安全模式: {safe_mode}"
            )

        except Exception as e:
            self.logger.error(f"启动浏览器失败: {e}")
            # 启动失败时也要清理资源
            await self._cleanup_browser()
            raise

    def _get_browser_args(self) -> list[str]:
        """获取浏览器启动参数：基础优化 + 用户自定义"""
        args = [
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--memory-pressure-off",
        ]
        if self.browser_settings.get("disable_web_security", False):
            args.append("--disable-web-security")
        if self.browser_settings.get("low_resource_mode", False):
            args.append("--blink-settings=imagesEnabled=false")
        # 用户自定义参数
        custom = str(self.browser_settings.get("browser_args", "") or "").strip()
        if custom:
            for flag in custom.split():
                flag = flag.strip()
                if flag and flag not in args:
                    args.append(flag)
        return args

    def _get_extra_http_headers(self) -> dict[str, str]:
        """返回用户自定义请求头"""
        raw_headers = str(
            self.browser_settings.get("extra_headers_json", "") or ""
        ).strip()
        if not raw_headers:
            return {}

        try:
            custom_headers = json.loads(raw_headers)
            if isinstance(custom_headers, dict):
                return {str(k): str(v) for k, v in custom_headers.items() if k is not None}
            self.logger.warning("浏览器自定义请求头必须是 JSON 对象，已忽略")
        except Exception as exc:
            self.logger.warning(f"解析浏览器自定义请求头失败，已忽略: {exc}")
        return {}

    async def _handle_low_resource_request(self, route) -> None:
        request = route.request
        if request.resource_type == "image":
            await route.abort()
            return
        await route.continue_()

    async def _cleanup_browser(self) -> None:
        """清理浏览器资源（内部方法）"""
        cleanup_errors = []

        # 按顺序清理资源
        try:
            if self.page:
                await self.page.close()
                self.page = None
        except Exception as e:
            cleanup_errors.append(f"关闭页面失败: {e}")

        try:
            if self.context:
                await self.context.close()
                self.context = None
        except Exception as e:
            cleanup_errors.append(f"关闭上下文失败: {e}")

        try:
            if self.browser:
                await self.browser.close()
                self.browser = None
        except Exception as e:
            cleanup_errors.append(f"关闭浏览器失败: {e}")

        try:
            if self.playwright:
                await self.playwright.stop()
                self.playwright = None
        except Exception as e:
            cleanup_errors.append(f"停止playwright失败: {e}")

        # 如果有清理错误，记录但不抛出异常
        if cleanup_errors:
            self.logger.warning(
                f"浏览器资源清理时出现错误: {'; '.join(cleanup_errors)}"
            )
        else:
            self.logger.debug("浏览器资源已完全清理")

    async def navigate_to(self, url: str, timeout: int | None = None) -> bool:
        """导航到指定URL"""
        if not self.page:
            raise RuntimeError("浏览器未启动，请在上下文管理器中使用")
        if self._is_cancelled():
            raise RuntimeError("浏览器操作已取消")

        try:
            timeout = timeout or self.browser_settings.get("timeout", 10000)
            await self.page.goto(url, timeout=timeout)
            await self.page.wait_for_load_state("networkidle", timeout=timeout)
            return True
        except Exception as e:
            self.logger.error(f"导航到 {url} 失败: {e}")
            return False

    async def take_screenshot(self, path: str = None) -> str:
        """截图功能"""
        if not self.page:
            raise RuntimeError("浏览器未启动，请在上下文管理器中使用")

        from pathlib import Path

        if not path:
            import time

            project_root = Path(__file__).resolve().parents[2]
            debug_dir = project_root / "debug"
            debug_dir.mkdir(parents=True, exist_ok=True)
            path = str(debug_dir / f"screenshot_{int(time.time())}.png")

        Path(path).parent.mkdir(parents=True, exist_ok=True)

        try:
            await self.page.screenshot(path=path)
            self.logger.info(f"截图已保存: {path}")
            return path
        except Exception as e:
            self.logger.error(f"截图失败: {e}")
            raise
