#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
浏览器上下文管理器
"""

import json
import threading

from .exceptions import LoginCancelledError
from .logging import setup_logger

# 浏览器反检测初始化脚本（stealth_mode 用）
# 隐藏 webdriver / 模拟 plugins / 模拟 chrome / 覆盖 languages / 清除 Playwright 痕迹
STEALTH_INIT_SCRIPT = """
// 隐藏 webdriver 标志
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});

// 模拟真实的 plugins 对象
const makePlugin = (name, desc, filename) => ({
    name, description: desc, filename,
    length: 1,
    item: () => null,
    namedItem: () => null,
});
const fakePlugins = {
    0: makePlugin('Chrome PDF Plugin', 'Portable Document Format', 'internal-pdf-viewer'),
    1: makePlugin('Chrome PDF Viewer', '', 'mhjfbmdgcfjbbpaeojofohoefgiehjai'),
    2: makePlugin('Native Client', '', 'internal-nacl-plugin'),
    length: 3,
    item: function(i) { return this[i] || null; },
    namedItem: function(name) {
        for (let i = 0; i < this.length; i++) {
            if (this[i].name === name) return this[i];
        }
        return null;
    },
    refresh: function() {},
    [Symbol.iterator]: function*() {
        for (let i = 0; i < this.length; i++) yield this[i];
    },
};
Object.defineProperty(navigator, 'plugins', {get: () => fakePlugins});

// 模拟 chrome 对象
window.chrome = {
    runtime: { connect: function(){}, sendMessage: function(){} },
    loadTimes: function() { return {}; },
    csi: function() { return {}; },
};

// 覆盖 languages
Object.defineProperty(navigator, 'languages', {
    get: () => ['zh-CN', 'zh', 'en-US', 'en'],
});

// 隐藏 Playwright 注入的属性
delete window.__playwright;
delete window.__pw_manual;
"""


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
        self.logger = setup_logger(f"{__name__}_browser", config.get("logging", {}))

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
            raise LoginCancelledError("浏览器启动已取消")
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
            headless = self.browser_settings.get("headless", True)
            safe_mode = self.browser_settings.get("safe_mode", False)

            if safe_mode:
                self.logger.info("启动浏览器 (安全模式, headless=%s)", headless)
                self.browser = await self.playwright.chromium.launch(headless=headless)
                self.context = await self.browser.new_context(
                    viewport={"width": 1280, "height": 720},
                )
            else:
                low_resource = bool(
                    self.browser_settings.get("low_resource_mode", False)
                )
                browser_args = self._get_browser_args()
                self.logger.info(
                    "启动浏览器 (headless=%s, low_resource=%s, args=%d)",
                    headless,
                    low_resource,
                    len(browser_args),
                )
                self.browser = await self.playwright.chromium.launch(
                    headless=headless, args=browser_args
                )
                extra_headers = self._get_extra_http_headers()
                ua = (self.browser_settings.get("user_agent") or "").strip()
                ctx_opts: dict = {
                    "viewport": {"width": 1280, "height": 720},
                    "extra_http_headers": extra_headers,
                    "locale": self.browser_settings.get(
                        "locale", "zh-CN"
                    ),  # 从配置中读取语言区域
                    "timezone_id": self.browser_settings.get(
                        "timezone_id", "Asia/Shanghai"
                    ),  # 从配置中读取时区
                    "has_touch": False,
                    "color_scheme": "light",
                    "ignore_https_errors": self.browser_settings.get(
                        "ignore_https_errors", True
                    ),
                }
                if ua:
                    ctx_opts["user_agent"] = ua
                    self.logger.info("使用自定义 UA: %s...", ua[:80])
                if extra_headers:
                    self.logger.info("注入自定义请求头: %d 项", len(extra_headers))
                self.context = await self.browser.new_context(**ctx_opts)
                if low_resource:
                    await self.context.route("**/*", self._handle_low_resource_request)

            self.page = await self.context.new_page()
            # 反检测脚本（默认关闭，需在方案设置中启用 stealth_mode）
            if self.browser_settings.get("stealth_mode", False):
                await self.page.add_init_script(STEALTH_INIT_SCRIPT)
            self.logger.info("浏览器启动完成")

        except Exception as e:
            self.logger.error("启动浏览器失败: %s", e)
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
            for flag in custom.splitlines():
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
                return {
                    str(k): str(v) for k, v in custom_headers.items() if k is not None
                }
            self.logger.warning("浏览器自定义请求头必须是 JSON 对象，已忽略")
        except Exception as exc:
            self.logger.warning(f"解析浏览器自定义请求头失败，已忽略: {exc}")
        return {}

    async def _handle_low_resource_request(self, route) -> None:
        request = route.request
        # 低资源模式：屏蔽图片、字体、媒体文件，减少内存和带宽消耗
        blocked_types = {"image", "font", "media"}
        if request.resource_type in blocked_types:
            await route.abort()
            return
        await route.continue_()

    async def _cleanup_browser(self) -> None:
        """清理浏览器资源（内部方法）"""
        cleanup_errors = []

        # 关闭页面：页面可能因浏览器断开而自动关闭，
        # TargetClosedError 属于正常清理场景，其余异常记录为 ERROR
        try:
            if self.page:
                await self.page.close()
                self.page = None
        except Exception as e:
            err_msg = str(e).lower()
            if "target closed" in err_msg or "connection closed" in err_msg:
                self.logger.warning(f"关闭页面时连接已断开（正常）: {e}")
            else:
                self.logger.error(f"关闭页面异常: {e}")
                cleanup_errors.append(f"关闭页面失败: {e}")

        # 关闭上下文：与 page 采用相同的异常处理策略
        try:
            if self.context:
                await self.context.close()
                self.context = None
        except Exception as e:
            err_msg = str(e).lower()
            if "target closed" in err_msg or "connection closed" in err_msg:
                self.logger.warning(f"关闭上下文时连接已断开（正常）: {e}")
            else:
                self.logger.error(f"关闭上下文异常: {e}")
                cleanup_errors.append(f"关闭上下文失败: {e}")

        # 关闭浏览器：先通过 is_connected() 健康检查，
        # 确认浏览器实例仍存活再发起关闭，避免对已断开的实例误操作
        try:
            if self.browser and self.browser.is_connected():
                await self.browser.close()
                self.browser = None
            elif self.browser:
                # 浏览器已断开，无需 close 操作
                self.logger.debug("浏览器已断开连接，跳过 close")
                self.browser = None
        except Exception as e:
            # is_connected() 通过后仍失败属于意外异常
            self.logger.error(f"关闭浏览器异常: {e}")
            cleanup_errors.append(f"关闭浏览器失败: {e}")

        # 停止 Playwright 服务
        try:
            if self.playwright:
                await self.playwright.stop()
                self.playwright = None
        except Exception as e:
            self.logger.error(f"停止 Playwright 失败: {e}")
            cleanup_errors.append(f"停止 Playwright 失败: {e}")

        # 汇总所有意外异常，记录为 warning（仍不抛出以避免中断调用方）
        if cleanup_errors:
            self.logger.warning(
                f"浏览器资源清理时出现错误: {'; '.join(cleanup_errors)}"
            )
        else:
            self.logger.debug("浏览器资源已完全清理")
