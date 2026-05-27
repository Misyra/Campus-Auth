#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
浏览器上下文管理器 — Worker 代理模式

浏览器生命周期现由 PlaywrightWorker（src/playwright_worker.py）管理。
BrowserContextManager 作为轻量代理:

- __aenter__: 通过 Worker 确保浏览器已就绪，获取浏览器对象引用
- __aexit__: 通知 Worker 释放引用（浏览器常驻 Worker 不实际关闭）
- Worker 线程内浏览器对象可通过 Worker 的内部状态直接访问（同线程安全）

原始的直接管理路径（_start_browser / _cleanup_browser）已弃用，
仅保留为降级回退的桩方法。
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

        # Worker 管理模式标志 — True 时表示浏览器由 Worker 管理生命周期
        self._worker_managed = False

    def _is_cancelled(self) -> bool:
        return self.cancel_event is not None and self.cancel_event.is_set()

    async def __aenter__(self):
        """异步上下文管理器入口 — 通过 Worker 获取浏览器

        Worker 管理浏览器生命周期，不再直接调用 _start_browser()。
        从 Worker 获取浏览器对象引用（同线程安全，因为 LoginAttemptHandler
        始终在 Worker 的事件循环线程中执行）。
        """
        if self._is_cancelled():
            raise LoginCancelledError("浏览器启动已取消")

        from src.playwright_worker import get_worker

        worker = get_worker()
        # 确保 Worker 中的浏览器已就绪（直接调用，同一事件循环线程）
        await worker.ensure_browser(self.config)

        # 从 Worker 获取浏览器对象引用（同线程，安全）
        self._worker_managed = True
        self.playwright = worker._playwright
        self.browser = worker._browser
        self.context = worker._context
        self.page = worker._page

        self.logger.info("浏览器已通过 Worker 就绪")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口 - 通知 Worker 释放浏览器引用

        浏览器常驻 Worker 生命周期内，不会实际关闭。
        向 Worker 提交 CMD_BROWSER_RELEASE（fire-and-forget）即可。
        """
        self._worker_managed = True

        # 通知 Worker 释放引用（无需等待结果）
        from src.playwright_worker import get_worker, CMD_BROWSER_RELEASE

        worker = get_worker()
        worker.submit(CMD_BROWSER_RELEASE, wait=False)

        # 清空本地引用
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None

        # 如果有异常，记录但不抑制
        if exc_type:
            self.logger.error(f"浏览器操作异常: {exc_type.__name__}: {exc_val}")
        return False  # 不抑制异常

    async def _start_browser(self) -> None:
        """[已弃用] 浏览器生命周期现由 Worker 管理，此方法不再使用"""
        self.logger.warning(
            "_start_browser 已弃用，浏览器由 PlaywrightWorker 管理"
        )
        # 若 Worker 管理标志已设置但此方法仍被调用（降级回退），
        # 输出警告后直接返回，不执行任何浏览器操作
        if self._worker_managed:
            return
        self.logger.warning("_start_browser 被调用但 Worker 不可用（空操作）")

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
        """[已弃用] 浏览器清理由 Worker 管理，此方法不再使用"""
        self.logger.warning(
            "_cleanup_browser 已弃用，浏览器由 PlaywrightWorker 管理"
        )
        # 若 Worker 管理标志已设置，清空本地引用后直接返回
        if self._worker_managed:
            self.playwright = None
            self.browser = None
            self.context = None
            self.page = None
            return
        self.logger.warning("_cleanup_browser 被调用但 Worker 不可用（空操作）")
