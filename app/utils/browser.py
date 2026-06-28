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

// 隐藏 Playwright 注入的属性（Object.defineProperty 防止 non-configurable 属性 delete 静默失败）
Object.defineProperty(window, '__playwright', {value: undefined, writable: false, configurable: false});
Object.defineProperty(window, '__pw_manual', {value: undefined, writable: false, configurable: false});
""".lstrip()


class BrowserContextManager:
    """浏览器上下文管理器 - 使用异步上下文管理器确保资源正确释放。

    设计约束：只能在 PlaywrightWorker 事件循环内使用（通过 _handle_login → attempt_login 调用链）。
    不支持跨线程调用，不支持在 FastAPI 路由中直接使用。
    """

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
        self.playwright = worker.playwright_instance
        self.browser = worker.browser
        self.context = worker.context
        self.page = worker.page

        self.logger.info("浏览器已通过 Worker 就绪")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口 — 关闭浏览器并释放资源。

        必须在 PlaywrightWorker 事件循环内调用（架构约束）。
        """
        from app.workers.playwright_worker import get_worker

        worker = get_worker()
        try:
            await worker._close_browser()
        except Exception:
            self.logger.warning("关闭浏览器异常", exc_info=True)

        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None

        if exc_type:
            self.logger.error(
                "浏览器操作异常: {}: {}", exc_type.__name__, str(exc_val)[:200]
            )
        return False
