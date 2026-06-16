"""浏览器上下文管理器 — Worker 代理模式。

浏览器生命周期由 PlaywrightWorker 管理，BrowserContextManager 作为轻量代理:
- __aenter__: 通过 Worker 确保浏览器已就绪，获取浏览器对象引用
- __aexit__: 通知 Worker 释放引用（浏览器常驻 Worker 不实际关闭）
"""

import threading

from .exceptions import LoginCancelledError
from .logging import get_logger

# 浏览器反检测初始化脚本（stealth_mode 用）
# 隐藏 webdriver / 模拟 plugins / 模拟 chrome / 覆盖 languages / 清除 Playwright 痕迹
STEALTH_INIT_SCRIPT = r"""// 隐藏 webdriver 标志
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
""".lstrip()


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
        self.logger = get_logger("browser", source="backend")

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

        from app.workers.playwright_worker import get_worker

        worker = get_worker()
        # 确保 Worker 中的浏览器已就绪（直接调用，同一事件循环线程）
        await worker.ensure_browser(self.config)

        # 从 Worker 获取浏览器对象引用（同线程，通过只读属性访问）
        self._worker_managed = True
        self.playwright = worker.playwright_instance
        self.browser = worker.browser
        self.context = worker.context
        self.page = worker.page

        self.logger.info("浏览器已通过 Worker 就绪")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口 - 关闭浏览器并释放资源。"""
        # 关闭浏览器
        import queue as _queue_mod

        from app.workers.playwright_worker import (
            CMD_BROWSER_CLOSE,
            get_worker,
        )

        worker = get_worker()
        try:
            worker.submit_nowait(CMD_BROWSER_CLOSE)
        except _queue_mod.Full:
            self.logger.warning("Worker 队列已满，无法发送 CMD_BROWSER_CLOSE")

        # 清空本地引用
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None

        # 如果有异常，记录但不抑制
        if exc_type:
            try:
                self.logger.error(
                    "浏览器操作异常: {}: {}", exc_type.__name__, str(exc_val)[:200]
                )
            except Exception:
                self.logger.error(
                    "浏览器操作异常: {} (详情无法格式化)", exc_type.__name__
                )
        return False  # 将异常传播给调用者（不抑制）
