#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
浏览器上下文管理器
"""

import json

from .logging import LoggerSetup


class BrowserContextManager:
    """浏览器上下文管理器 - 使用异步上下文管理器确保资源正确释放"""

    def __init__(self, config: dict):
        """
        初始化浏览器上下文管理器

        参数:
            config: 配置字典
        """
        self.config = config
        self.browser_settings = config.get("browser_settings", {})
        self.logger = LoggerSetup.setup_logger(
            f"{__name__}_browser", config.get("logging", {})
        )

        # 浏览器相关属性
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None

    async def __aenter__(self):
        """异步上下文管理器入口"""
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
            low_resource_mode = bool(
                self.browser_settings.get("low_resource_mode", False)
            )

            # 统一的浏览器启动参数
            browser_args = self._get_browser_args()

            self.browser = await self.playwright.chromium.launch(
                headless=headless, args=browser_args
            )

            # 创建浏览器上下文 - 优化视口大小减少内存占用
            extra_headers = self._get_extra_http_headers()
            self.context = await self.browser.new_context(
                viewport={"width": 1280, "height": 720},
                user_agent=self.browser_settings.get(
                    "user_agent",
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                ),
                extra_http_headers=extra_headers,
            )

            if low_resource_mode:
                await self.context.route("**/*", self._handle_low_resource_request)

            # 创建页面
            self.page = await self.context.new_page()

            self.logger.info(
                f"浏览器已启动，无头模式: {headless}, 低资源模式: {low_resource_mode}"
            )

        except Exception as e:
            self.logger.error(f"启动浏览器失败: {e}")
            # 启动失败时也要清理资源
            await self._cleanup_browser()
            raise

    def _get_browser_args(self) -> list[str]:
        """获取优化的浏览器启动参数，减少内存和资源占用"""
        args = [
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--disable-extensions",
            "--disable-plugins",
            "--memory-pressure-off",
            "--max_old_space_size=256",
        ]
        # 同源策略：仅在配置明确启用时禁用（默认保留浏览器安全策略）
        disable_web_security = self.browser_settings.get("disable_web_security", False)
        if disable_web_security:
            args.append("--disable-web-security")
        if self.browser_settings.get("low_resource_mode", False):
            args.append("--blink-settings=imagesEnabled=false")
        return args

    def _get_extra_http_headers(self) -> dict[str, str]:
        """合并默认请求头和用户自定义请求头"""
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }

        raw_headers = str(
            self.browser_settings.get("extra_headers_json", "") or ""
        ).strip()
        if not raw_headers:
            return headers

        try:
            custom_headers = json.loads(raw_headers)
            if isinstance(custom_headers, dict):
                for key, value in custom_headers.items():
                    if key is None:
                        continue
                    headers[str(key)] = str(value)
            else:
                self.logger.warning("浏览器自定义请求头必须是 JSON 对象，已忽略")
        except Exception as exc:
            self.logger.warning(f"解析浏览器自定义请求头失败，已忽略: {exc}")

        return headers

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

    async def navigate_to(self, url: str, timeout: int = None) -> bool:
        """导航到指定URL"""
        if not self.page:
            raise RuntimeError("浏览器未启动，请在上下文管理器中使用")

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
