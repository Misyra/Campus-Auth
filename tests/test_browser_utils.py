"""浏览器工具测试 — 覆盖 BrowserContextManager 和 STEALTH_INIT_SCRIPT。"""

from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

import pytest

from app.utils.browser import STEALTH_INIT_SCRIPT, BrowserContextManager

# ── STEALTH_INIT_SCRIPT ──


class TestStealthInitScript:
    """反检测脚本内容验证。"""

    def test_hides_webdriver(self):
        """隐藏 webdriver 标志。"""
        assert "webdriver" in STEALTH_INIT_SCRIPT
        assert "undefined" in STEALTH_INIT_SCRIPT

    def test_mocks_plugins(self):
        """模拟 plugins 对象。"""
        assert "plugins" in STEALTH_INIT_SCRIPT
        assert "Chrome PDF Plugin" in STEALTH_INIT_SCRIPT

    def test_mocks_chrome(self):
        """模拟 chrome 对象。"""
        assert "window.chrome" in STEALTH_INIT_SCRIPT
        assert "runtime" in STEALTH_INIT_SCRIPT

    def test_overrides_languages(self):
        """覆盖 languages。"""
        assert "languages" in STEALTH_INIT_SCRIPT
        assert "zh-CN" in STEALTH_INIT_SCRIPT

    def test_removes_playwright痕迹(self):
        """删除 Playwright 痕迹。"""
        assert "__playwright" in STEALTH_INIT_SCRIPT
        assert "__pw_manual" in STEALTH_INIT_SCRIPT


# ── BrowserContextManager._is_cancelled ──


class TestIsCancelled:
    """取消状态检查。"""

    def test_no_event(self):
        """无 cancel_event 时返回 False。"""
        mgr = BrowserContextManager({}, cancel_event=None)
        assert mgr._is_cancelled() is False

    def test_event_not_set(self):
        """event 未 set 时返回 False。"""
        event = threading.Event()
        mgr = BrowserContextManager({}, cancel_event=event)
        assert mgr._is_cancelled() is False

    def test_event_set(self):
        """event 已 set 时返回 True。"""
        event = threading.Event()
        event.set()
        mgr = BrowserContextManager({}, cancel_event=event)
        assert mgr._is_cancelled() is True


# ── BrowserContextManager 初始化 ──


class TestBrowserContextManagerInit:
    """初始化逻辑。"""

    def test_basic_init(self):
        """基本初始化。"""
        config = {"browser_settings": {"headless": True}}
        mgr = BrowserContextManager(config)
        assert mgr.config == config
        assert mgr.browser_settings == {"headless": True}
        assert mgr.browser is None
        assert mgr.context is None
        assert mgr.page is None
        assert mgr._worker_managed is False

    def test_empty_config(self):
        """空配置。"""
        mgr = BrowserContextManager({})
        assert mgr.browser_settings == {}

    def test_cancel_event_stored(self):
        """cancel_event 被保存。"""
        event = threading.Event()
        mgr = BrowserContextManager({}, cancel_event=event)
        assert mgr.cancel_event is event


# ── BrowserContextManager.__aexit__ ──


class TestBrowserContextManagerAexit:
    """异步上下文管理器出口。"""

    @pytest.mark.asyncio
    async def test_returns_false(self):
        """返回 False（不抑制异常）。"""
        mgr = BrowserContextManager({})
        mock_worker = MagicMock()
        with patch(
            "app.workers.playwright_worker.get_worker", return_value=mock_worker
        ):
            result = await mgr.__aexit__(None, None, None)
            assert result is False

    @pytest.mark.asyncio
    async def test_clears_references(self):
        """清空引用。"""
        mgr = BrowserContextManager({})
        mgr.playwright = MagicMock()
        mgr.browser = MagicMock()
        mgr.context = MagicMock()
        mgr.page = MagicMock()

        mock_worker = MagicMock()
        with patch(
            "app.workers.playwright_worker.get_worker", return_value=mock_worker
        ):
            await mgr.__aexit__(None, None, None)
            assert mgr.playwright is None
            assert mgr.browser is None
            assert mgr.context is None
            assert mgr.page is None

    @pytest.mark.asyncio
    async def test_logs_exception(self):
        """异常被记录。"""
        mgr = BrowserContextManager({})
        mgr.logger = MagicMock()

        mock_worker = MagicMock()
        with patch(
            "app.workers.playwright_worker.get_worker", return_value=mock_worker
        ):
            await mgr.__aexit__(ValueError, ValueError("test error"), None)
            mgr.logger.error.assert_called()
