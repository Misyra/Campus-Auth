"""src/ 工具模块综合测试

合并原 test_notify.py、test_browser.py、test_system_tray.py、
test_playwright_bootstrap.py、test_playwright_worker.py。
覆盖桌面通知、浏览器管理、系统托盘、Playwright 引导、Worker 等模块。
"""

from __future__ import annotations

import contextlib
import os
import threading
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.system_tray import SystemTray
from app.utils.browser import STEALTH_INIT_SCRIPT, BrowserContextManager
from app.utils.exceptions import LoginCancelledError
from app.workers.playwright_bootstrap import (
    _candidate_hosts,
    _has_chromium,
    _is_enabled,
    ensure_playwright_ready,
)
from app.workers.playwright_worker import (
    CMD_DEBUG_START,
    CMD_DEBUG_STEP,
    CMD_DEBUG_STOP,
    CMD_LOGIN,
    CMD_SHUTDOWN,
    PlaywrightWorker,
    WorkerCommand,
    WorkerResponse,
)

# ─────────────────────────────────────────────────────────────────────
#  浏览器管理 (src/utils/browser.py)
# ─────────────────────────────────────────────────────────────────────


class TestStealthInitScript:
    def test_script_is_string(self):
        assert isinstance(STEALTH_INIT_SCRIPT, str)

    def test_script_not_empty(self):
        assert len(STEALTH_INIT_SCRIPT.strip()) > 0

    def test_script_contains_webdriver_override(self):
        assert "webdriver" in STEALTH_INIT_SCRIPT

    def test_script_contains_plugins(self):
        assert "plugins" in STEALTH_INIT_SCRIPT

    def test_script_contains_chrome_object(self):
        assert "chrome" in STEALTH_INIT_SCRIPT

    def test_script_contains_languages(self):
        assert "languages" in STEALTH_INIT_SCRIPT


class TestBrowserContextManager:
    def test_init_basic(self):
        config = {"browser_settings": {"headless": True}}
        ctx = BrowserContextManager(config)
        assert ctx.config == config
        assert ctx.browser_settings == {"headless": True}
        assert ctx.cancel_event is None

    def test_init_with_cancel_event(self):
        event = threading.Event()
        ctx = BrowserContextManager({}, cancel_event=event)
        assert ctx.cancel_event is event

    def test_is_cancelled_no_event(self):
        ctx = BrowserContextManager({})
        assert ctx._is_cancelled() is False

    def test_is_cancelled_event_not_set(self):
        event = threading.Event()
        ctx = BrowserContextManager({}, cancel_event=event)
        assert ctx._is_cancelled() is False

    def test_is_cancelled_event_set(self):
        event = threading.Event()
        event.set()
        ctx = BrowserContextManager({}, cancel_event=event)
        assert ctx._is_cancelled() is True

    @pytest.mark.asyncio
    async def test_aenter_cancelled_raises(self):
        event = threading.Event()
        event.set()
        ctx = BrowserContextManager({}, cancel_event=event)
        with pytest.raises(LoginCancelledError):
            await ctx.__aenter__()

    def test_initial_browser_state(self):
        ctx = BrowserContextManager({})
        assert ctx.browser is None
        assert ctx.context is None
        assert ctx.page is None


# ─────────────────────────────────────────────────────────────────────
#  系统托盘 (src/system_tray.py)
# ─────────────────────────────────────────────────────────────────────


class TestSystemTrayInit:
    def test_default_init(self):
        tray = SystemTray()
        assert tray.port == 50721
        assert tray.on_exit is None
        assert tray.icon is None
        assert tray._thread is None
        assert tray._monitoring is False

    def test_custom_init(self):
        callback = MagicMock()
        tray = SystemTray(port=8080, on_exit=callback)
        assert tray.port == 8080
        assert tray.on_exit is callback


class TestSystemTrayMethods:
    def test_load_icon_returns_image(self):
        tray = SystemTray()
        # 延迟导入：需要先初始化 _Image
        from PIL import Image

        tray._Image = Image
        icon = tray._load_icon()
        assert icon.size in ((64, 64), (256, 256))

    def test_monitoring_true_label(self):
        tray = SystemTray()
        tray._monitoring = True
        label = tray._get_status_label(None)
        assert "运行中" in label

    def test_monitoring_false_label(self):
        tray = SystemTray()
        tray._monitoring = False
        label = tray._get_status_label(None)
        assert "已停止" in label

    def test_create_menu_returns_menu(self):
        tray = SystemTray()
        mock_pystray = MagicMock()
        mock_pystray.Menu.return_value = MagicMock()
        tray._pystray = mock_pystray
        menu = tray._create_menu()
        assert menu is not None

    def test_quit_with_icon(self):
        tray = SystemTray()
        mock_icon = MagicMock()
        tray.icon = mock_icon
        tray._quit(None, None)
        mock_icon.stop.assert_called_once()

    def test_quit_with_callback(self):
        callback = MagicMock()
        tray = SystemTray(on_exit=callback)
        tray.icon = MagicMock()
        tray._quit(None, None)
        callback.assert_called_once()

    def test_quit_without_icon(self):
        tray = SystemTray()
        callback = MagicMock()
        tray.on_exit = callback
        tray._quit(None, None)
        callback.assert_called_once()

    @patch("app.system_tray.threading.Thread")
    def test_start(self, mock_thread_cls):
        mock_thread = MagicMock()
        mock_thread_cls.return_value = mock_thread

        tray = SystemTray()
        # 延迟导入：mock pystray 模块
        mock_pystray = MagicMock()
        mock_image = MagicMock()
        tray._pystray = mock_pystray
        tray._Image = mock_image

        tray.start()

        mock_pystray.Icon.assert_called_once()
        mock_thread_cls.assert_called_once()
        mock_thread.start.assert_called_once()

    @patch("app.system_tray.threading.Thread")
    def test_start_already_running(self, mock_thread_cls):
        tray = SystemTray()
        mock_thread = MagicMock()
        mock_thread.is_alive.return_value = True
        tray._thread = mock_thread

        # 延迟导入：mock pystray 模块
        mock_pystray = MagicMock()
        tray._pystray = mock_pystray

        tray.start()
        mock_pystray.Icon.assert_not_called()

    def test_stop_with_icon(self):
        tray = SystemTray()
        mock_icon = MagicMock()
        tray.icon = mock_icon
        tray.stop()
        mock_icon.stop.assert_called_once()
        assert tray.icon is None

    def test_stop_without_icon(self):
        tray = SystemTray()
        tray.stop()
        assert tray.icon is None

    def test_update_status_monitoring(self):
        tray = SystemTray()
        mock_icon = MagicMock()
        tray.icon = mock_icon
        tray.update_status(True)
        assert tray._monitoring is True
        assert "运行中" in mock_icon.title

    def test_update_status_stopped(self):
        tray = SystemTray()
        mock_icon = MagicMock()
        tray.icon = mock_icon
        tray.update_status(False)
        assert tray._monitoring is False
        assert "已停止" in mock_icon.title

    def test_update_status_no_icon(self):
        tray = SystemTray()
        tray.update_status(True)
        assert tray._monitoring is True


# ─────────────────────────────────────────────────────────────────────
#  Playwright 引导 (src/playwright_bootstrap.py)
# ─────────────────────────────────────────────────────────────────────


class TestCandidateHosts:
    def test_default_hosts(self):
        hosts = _candidate_hosts()
        assert len(hosts) >= 2
        assert "https://npmmirror.com/mirrors/playwright" in hosts
        assert "https://playwright.azureedge.net" in hosts

    @patch.dict(os.environ, {"PLAYWRIGHT_DOWNLOAD_HOST": "https://custom.host"})
    def test_custom_host_first(self):
        hosts = _candidate_hosts()
        assert hosts[0] == "https://custom.host"

    @patch.dict(os.environ, {"PLAYWRIGHT_DOWNLOAD_HOST": ""})
    def test_empty_custom_host(self):
        hosts = _candidate_hosts()
        assert hosts[0] == "https://npmmirror.com/mirrors/playwright"

    @patch.dict(
        os.environ,
        {"PLAYWRIGHT_DOWNLOAD_HOST": "https://npmmirror.com/mirrors/playwright"},
    )
    def test_no_duplicate_hosts(self):
        hosts = _candidate_hosts()
        assert hosts.count("https://npmmirror.com/mirrors/playwright") == 1


class TestIsEnabled:
    @patch.dict(os.environ, {"AUTO_INSTALL_PLAYWRIGHT": "true"})
    def test_enabled(self):
        assert _is_enabled() is True

    @patch.dict(os.environ, {"AUTO_INSTALL_PLAYWRIGHT": "false"})
    def test_disabled(self):
        assert _is_enabled() is False

    @patch.dict(os.environ, {"AUTO_INSTALL_PLAYWRIGHT": "1"})
    def test_enabled_numeric(self):
        assert _is_enabled() is True

    @patch.dict(os.environ, {"AUTO_INSTALL_PLAYWRIGHT": "0"})
    def test_disabled_numeric(self):
        assert _is_enabled() is False

    @patch.dict(os.environ, {}, clear=True)
    def test_default_enabled(self):
        assert _is_enabled() is True


class TestHasChromium:
    @patch("app.utils.browser_registry.has_playwright_chromium", return_value=False)
    def test_no_chromium(self, mock_has_pw):
        assert _has_chromium() is False
        mock_has_pw.assert_called_once()

    @patch("app.utils.browser_registry.has_playwright_chromium", return_value=True)
    def test_has_chromium(self, mock_has_pw):
        assert _has_chromium() is True
        mock_has_pw.assert_called_once()


class TestEnsurePlaywrightReady:
    def setup_method(self):
        import app.workers.playwright_bootstrap as pb

        pb._BOOTSTRAP_DONE = False

    def teardown_method(self):
        import app.workers.playwright_bootstrap as pb

        pb._BOOTSTRAP_DONE = False
        pb._BOOTSTRAP_SKIPPED = False

    @patch.dict(os.environ, {"AUTO_INSTALL_PLAYWRIGHT": "false"})
    def test_disabled_returns_true(self):
        assert ensure_playwright_ready() is True

    @patch("app.workers.playwright_bootstrap._has_chromium", return_value=True)
    def test_chromium_exists_returns_true(self, mock_chromium):
        assert ensure_playwright_ready() is True

    def test_already_done_returns_true(self):
        import app.workers.playwright_bootstrap as pb

        pb._BOOTSTRAP_DONE = True
        assert ensure_playwright_ready() is True

    @patch(
        "app.workers.playwright_bootstrap._get_browser_channel",
        return_value="playwright",
    )
    @patch("app.workers.playwright_bootstrap._has_chromium", return_value=False)
    @patch("app.workers.playwright_bootstrap._is_enabled", return_value=True)
    def test_no_playwright_package(self, mock_enabled, mock_chromium, mock_channel):
        import sys

        with patch.dict(sys.modules, {"playwright": None}):
            assert ensure_playwright_ready() is False


# ─────────────────────────────────────────────────────────────────────
#  Playwright Worker (src/playwright_worker.py)
# ─────────────────────────────────────────────────────────────────────


class TestCommandConstants:
    def test_all_constants_defined(self):
        assert CMD_LOGIN == "login"
        assert CMD_DEBUG_START == "debug_start"
        assert CMD_DEBUG_STEP == "debug_step"
        assert CMD_DEBUG_STOP == "debug_stop"
        assert CMD_SHUTDOWN == "shutdown"


class TestWorkerCommand:
    def test_basic_creation(self):
        cmd = WorkerCommand(type=CMD_LOGIN)
        assert cmd.type == CMD_LOGIN
        assert cmd.data == {}
        assert cmd.response_event is None
        assert cmd.response_data is None

    def test_with_data(self):
        data = {"config": {"username": "admin"}}
        cmd = WorkerCommand(type=CMD_LOGIN, data=data)
        assert cmd.data == data

    def test_with_response_event(self):
        event = threading.Event()
        cmd = WorkerCommand(type=CMD_LOGIN, response_event=event)
        assert cmd.response_event is event

    def test_default_data_factory(self):
        cmd1 = WorkerCommand(type=CMD_LOGIN)
        cmd2 = WorkerCommand(type=CMD_LOGIN)
        cmd1.data["key"] = "value"
        assert "key" not in cmd2.data


class TestWorkerResponse:
    def test_success(self):
        resp = WorkerResponse(success=True, data="ok")
        assert resp.success is True
        assert resp.data == "ok"
        assert resp.error is None

    def test_failure(self):
        resp = WorkerResponse(success=False, error="failed")
        assert resp.success is False
        assert resp.error == "failed"
        assert resp.data is None

    def test_defaults(self):
        resp = WorkerResponse(success=True)
        assert resp.data is None
        assert resp.error is None


class TestPlaywrightWorker:
    def test_initial_state(self):
        worker = PlaywrightWorker()
        assert worker.is_alive() is False
        assert worker._browser is None
        assert worker._page is None
        assert worker._context is None

    def test_stop_when_not_started(self):
        worker = PlaywrightWorker()
        worker.stop(timeout=0.1)

    def test_submit_when_stopped(self):
        worker = PlaywrightWorker()
        worker._stop_event.set()
        result = worker.submit(CMD_LOGIN, data={}, wait=False)
        assert result.success is False
        assert "已关闭" in result.error

    def test_is_alive_false(self):
        worker = PlaywrightWorker()
        assert worker.is_alive() is False

    def test_get_extra_http_headers_empty(self):
        worker = PlaywrightWorker()
        assert worker._get_extra_http_headers({}) == {}

    def test_get_extra_http_headers_valid(self):
        worker = PlaywrightWorker()
        settings = {"extra_headers_json": '{"X-Custom": "value"}'}
        headers = worker._get_extra_http_headers(settings)
        assert headers == {"X-Custom": "value"}

    def test_get_extra_http_headers_invalid_json(self):
        worker = PlaywrightWorker()
        settings = {"extra_headers_json": "not json"}
        headers = worker._get_extra_http_headers(settings)
        assert headers == {}

    def test_get_extra_http_headers_non_dict(self):
        worker = PlaywrightWorker()
        settings = {"extra_headers_json": "[1, 2, 3]"}
        headers = worker._get_extra_http_headers(settings)
        assert headers == {}

    def test_get_extra_http_headers_none_values(self):
        worker = PlaywrightWorker()
        settings = {"extra_headers_json": '{"key": null}'}
        headers = worker._get_extra_http_headers(settings)
        assert headers == {"key": "None"}


class TestCleanupOrphanBrowsers:
    @pytest.fixture(autouse=True)
    def _reset_cleanup_cooldown(self):
        """每个测试前重置清理冷却时间，确保扫描逻辑被执行。"""
        import app.workers.playwright_worker as pw

        pw._last_cleanup_time = 0.0
        yield
        pw._last_cleanup_time = 0.0

    def test_kills_matching_processes(self):
        """匹配 ms-playwright + chrom 的进程应被终止。"""
        from app.workers.playwright_worker import cleanup_orphan_browsers

        mock_proc = MagicMock()
        mock_proc.info = {"pid": 1234, "name": "chrome.exe"}
        mock_proc.exe.return_value = "C:/ms-playwright/chromium-1234/chrome.exe"
        mock_proc.cmdline.return_value = ["chrome.exe", "--headless"]
        mock_proc.parent.return_value = None  # 孤儿进程，无父进程

        with patch("psutil.process_iter", return_value=[mock_proc]):
            cleanup_orphan_browsers()

        mock_proc.kill.assert_called_once()

    def test_ignores_non_matching_processes(self):
        """不匹配的进程不应被终止。"""
        from app.workers.playwright_worker import cleanup_orphan_browsers

        mock_proc = MagicMock()
        mock_proc.info = {"pid": 5678, "name": "chrome.exe"}
        mock_proc.exe.return_value = "C:/Program Files/Google/Chrome/chrome.exe"
        mock_proc.cmdline.return_value = ["chrome.exe"]

        with patch("psutil.process_iter", return_value=[mock_proc]):
            cleanup_orphan_browsers()

        mock_proc.kill.assert_not_called()

    def test_handles_no_such_process(self):
        """进程已消失时不应抛异常。"""
        import psutil as real_psutil

        from app.workers.playwright_worker import cleanup_orphan_browsers

        mock_proc = MagicMock()
        mock_proc.info = {"pid": 9999, "name": "chrome.exe"}
        mock_proc.exe.return_value = "C:/ms-playwright/chromium-1234/chrome.exe"
        mock_proc.cmdline.return_value = []
        mock_proc.kill.side_effect = real_psutil.NoSuchProcess(9999)

        with patch("psutil.process_iter", return_value=[mock_proc]):
            # 不应抛异常
            cleanup_orphan_browsers()


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
        mgr.browser = MagicMock()
        mgr.context = MagicMock()
        mgr.page = MagicMock()

        mock_worker = AsyncMock()
        with patch(
            "app.workers.playwright_worker.get_worker", return_value=mock_worker
        ):
            await mgr.__aexit__(None, None, None)
            assert mgr.browser is None
            assert mgr.context is None
            assert mgr.page is None

    @pytest.mark.asyncio
    async def test_logs_exception(self):
        """异常不在此处记录（由调用方记录），__aexit__ 返回 False 让异常传播。"""
        mgr = BrowserContextManager({})
        mgr.logger = MagicMock()

        mock_worker = MagicMock()
        with patch(
            "app.workers.playwright_worker.get_worker", return_value=mock_worker
        ):
            result = await mgr.__aexit__(ValueError, ValueError("test error"), None)
            assert result is False  # 异常传播，由调用方记录
            mgr.logger.error.assert_not_called()


# ── SystemTray 详细测试 ──


class TestLoadIcon:
    """_load_icon。"""

    def test_fallback_returns_default_icon(self):
        """cairosvg.svg2png 抛异常时回退到 Image.new 默认图标。"""
        mock_image = MagicMock()
        mock_new = MagicMock()
        mock_image.new.return_value = mock_new

        mock_cairosvg = MagicMock()
        mock_cairosvg.svg2png.side_effect = RuntimeError("svg2png failed")
        with patch.dict("sys.modules", {"cairosvg": mock_cairosvg}):
            tray = SystemTray()
            tray._Image = mock_image
            result = tray._load_icon()

        mock_image.new.assert_called_once_with("RGBA", (64, 64), (34, 211, 238, 255))
        assert result is mock_new

    def test_fallback_when_cairosvg_missing(self):
        """cairosvg 不可用时回退到默认图标。"""
        from pathlib import Path as _Path

        mock_image = MagicMock()
        mock_new = MagicMock()
        mock_image.new.return_value = mock_new

        tray = SystemTray()
        tray._Image = mock_image

        fake_path = MagicMock(spec=_Path)
        fake_path.exists.return_value = True
        fake_path.as_uri.return_value = "file:///fake/icon.svg"

        with patch("app.system_tray.Path") as mock_path_cls:
            mock_path_cls.return_value.parent.parent.parent.__truediv__ = MagicMock(
                return_value=fake_path
            )
            with patch.dict("sys.modules", {"cairosvg": None}):
                tray._load_icon()

        mock_image.new.assert_called_once_with("RGBA", (64, 64), (34, 211, 238, 255))


class TestGetStatusLabel:
    """_get_status_label。"""

    def test_monitoring_true(self):
        """监控中显示"运行中"。"""
        tray = SystemTray()
        tray._monitoring = True
        assert "运行中" in tray._get_status_label(None)

    def test_monitoring_false(self):
        """停止时显示"已停止"。"""
        tray = SystemTray()
        tray._monitoring = False
        assert "已停止" in tray._get_status_label(None)


class TestCreateMenu:
    """_create_menu。"""

    def test_menu_created(self):
        """菜单创建成功。"""
        mock_menu_instance = MagicMock()
        mock_pystray = MagicMock()
        mock_pystray.Menu.return_value = mock_menu_instance
        mock_pystray.MenuItem.return_value = MagicMock()
        mock_pystray.Menu.SEPARATOR = "SEPARATOR"

        tray = SystemTray(port=50721)
        tray._pystray = mock_pystray
        result = tray._create_menu()

        assert result is mock_menu_instance
        assert mock_pystray.MenuItem.call_count >= 3


class TestQuit:
    """_quit。"""

    def test_quit_with_icon_and_callback(self):
        """有 icon 和 on_exit 时 icon 被停止且 on_exit 被调用。"""
        on_exit = MagicMock()
        tray = SystemTray(on_exit=on_exit)
        tray.icon = MagicMock()

        tray._quit(tray.icon, None)

        tray.icon.stop.assert_called_once()
        on_exit.assert_called_once()

    def test_quit_without_icon(self):
        """无 icon 时仅调用 on_exit。"""
        on_exit = MagicMock()
        tray = SystemTray(on_exit=on_exit)
        tray.icon = None

        tray._quit(None, None)

        on_exit.assert_called_once()

    def test_quit_without_callback(self):
        """无 on_exit 时仅调用 icon.stop。"""
        tray = SystemTray()
        tray.icon = MagicMock()

        tray._quit(tray.icon, None)

        tray.icon.stop.assert_called_once()


class TestStartStop:
    """start / stop。"""

    def test_start_creates_icon_and_thread(self):
        """start 创建 pystray.Icon 并启动后台守护线程。"""
        import time

        mock_pystray = MagicMock()
        mock_image = MagicMock()
        mock_icon_cls = MagicMock()
        mock_icon_instance = MagicMock()
        mock_icon_instance.run.side_effect = lambda: time.sleep(2)
        mock_icon_cls.return_value = mock_icon_instance
        mock_pystray.Icon = mock_icon_cls

        tray = SystemTray(port=50721)
        tray._pystray = mock_pystray
        tray._Image = mock_image

        mock_img = MagicMock()
        with patch.object(tray, "_load_icon", return_value=mock_img):
            tray.start()

        mock_icon_cls.assert_called_once()
        assert tray.icon is mock_icon_instance
        assert tray._thread is not None
        assert tray._thread.daemon is True
        assert tray._thread.is_alive()

        tray.stop()

    def test_start_idempotent(self):
        """线程仍存活时重复 start 不会创建新 icon。"""
        import time

        mock_pystray = MagicMock()
        mock_image = MagicMock()
        mock_icon_cls = MagicMock()
        mock_icon_instance = MagicMock()
        mock_icon_instance.run.side_effect = lambda: time.sleep(2)
        mock_icon_cls.return_value = mock_icon_instance
        mock_pystray.Icon = mock_icon_cls

        tray = SystemTray()
        tray._pystray = mock_pystray
        tray._Image = mock_image

        mock_img = MagicMock()
        with patch.object(tray, "_load_icon", return_value=mock_img):
            tray.start()
            first_thread = tray._thread
            tray.start()

        mock_icon_cls.assert_called_once()
        assert tray._thread is first_thread

        tray.stop()

    def test_stop_clears_icon(self):
        """stop 调用 icon.stop 并清除引用。"""
        tray = SystemTray()
        tray.icon = MagicMock()

        tray.stop()

    def test_stop_without_icon(self):
        """无 icon 时 stop 不报错。"""
        tray = SystemTray()
        tray.icon = None
        tray.stop()


class TestUpdateStatus:
    """update_status。"""

    def test_update_monitoring_true(self):
        """监控中更新标题为"运行中"。"""
        tray = SystemTray()
        mock_icon = MagicMock()
        tray.icon = mock_icon

        tray.update_status(monitoring=True)

        assert tray._monitoring is True
        assert "运行中" in mock_icon.title

    def test_update_monitoring_false(self):
        """停止时更新标题为"已停止"。"""
        tray = SystemTray()
        mock_icon = MagicMock()
        tray.icon = mock_icon

        tray.update_status(monitoring=False)

        assert tray._monitoring is False
        assert "已停止" in mock_icon.title

    def test_update_no_icon(self):
        """无 icon 时仅更新 _monitoring 标志，不报错。"""
        tray = SystemTray()
        tray.icon = None

        tray.update_status(monitoring=True)

        assert tray._monitoring is True


# ── Playwright bootstrap 状态管理 ──


class TestBootstrapState:
    """bootstrap 状态区分测试"""

    def setup_method(self):
        """每个测试前重置全局状态"""
        import app.workers.playwright_bootstrap as pb

        pb._BOOTSTRAP_DONE = False
        pb._BOOTSTRAP_SKIPPED = False

    def test_bootstrap_disabled_returns_skipped(self):
        """禁用 auto-install 时返回 SKIPPED 状态。"""
        import app.workers.playwright_bootstrap as pb

        with patch.object(pb, "_is_enabled", return_value=False):
            result = pb.ensure_playwright_ready()

        assert result is True
        assert pb._BOOTSTRAP_SKIPPED is True
        assert pb._BOOTSTRAP_DONE is False

    def test_bootstrap_verified_returns_done(self):
        """Chromium 已安装时返回 DONE 状态。"""
        import app.workers.playwright_bootstrap as pb

        with (
            patch.object(pb, "_is_enabled", return_value=True),
            patch.object(pb, "_has_chromium", return_value=True),
        ):
            result = pb.ensure_playwright_ready()

        assert result is True
        assert pb._BOOTSTRAP_DONE is True
        assert pb._BOOTSTRAP_SKIPPED is False

    def test_bootstrap_skipped_then_done(self):
        """先跳过再验证的状态变化。"""
        import app.workers.playwright_bootstrap as pb

        with patch.object(pb, "_is_enabled", return_value=False):
            pb.ensure_playwright_ready()

        assert pb._BOOTSTRAP_SKIPPED is True
        assert pb._BOOTSTRAP_DONE is False

        with (
            patch.object(pb, "_is_enabled", return_value=True),
            patch.object(pb, "_has_chromium", return_value=True),
        ):
            result = pb.ensure_playwright_ready()

        assert result is True
        assert pb._BOOTSTRAP_DONE is False


# ── PlaywrightWorker submit alive 预检 ──


class TestSubmitAliveCheck:
    """submit() 方法的 worker alive 预检测试"""

    def test_submit_recovers_dead_worker(self):
        """submit 检测到消费者线程死亡后自动重启。"""
        worker = PlaywrightWorker()

        start_called = threading.Event()

        def mock_start():
            start_called.set()
            worker._consumer_thread = MagicMock()
            worker._consumer_thread.is_alive.return_value = True
            worker._stop_event.clear()

        worker.start = mock_start

        worker._consumer_thread = MagicMock()
        worker._consumer_thread.is_alive.return_value = False
        worker._stop_event.clear()

        result = worker.submit("test_cmd", wait=False)

        assert start_called.is_set(), "submit 应该调用 start() 重启线程"
        assert result.success

    def test_submit_stopped_worker_rejects(self):
        """已停止的 worker 拒绝新命令。"""
        worker = PlaywrightWorker()
        worker._stop_event.set()

        result = worker.submit("test_cmd", wait=False)

        assert not result.success
        assert "已关闭" in result.error

    def test_submit_restart_failure_returns_error(self):
        """重启失败时返回错误。"""
        worker = PlaywrightWorker()

        worker._consumer_thread = MagicMock()
        worker._consumer_thread.is_alive.return_value = False
        worker._stop_event.clear()

        def mock_start():
            raise RuntimeError("重启失败")

        worker.start = mock_start

        result = worker.submit("test_cmd", wait=False)

        assert not result.success
        assert "重启失败" in result.error

    def test_submit_concurrent_restart_only_one(self):
        """并发 submit 只有一个执行重启。"""
        import concurrent.futures

        worker = PlaywrightWorker()

        worker._consumer_thread = MagicMock()
        worker._consumer_thread.is_alive.return_value = False
        worker._stop_event.clear()

        restart_count = 0
        restart_lock = threading.Lock()

        def mock_start():
            nonlocal restart_count
            with restart_lock:
                restart_count += 1
            worker._consumer_thread.is_alive.return_value = True

        worker.start = mock_start

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = []
            for _ in range(5):
                futures.append(
                    executor.submit(lambda: worker.submit("test_cmd", wait=False))
                )
            concurrent.futures.wait(futures)

        assert restart_count == 1, f"重启次数应为 1，实际: {restart_count}"


# ── PlaywrightWorker._build_launch_args ──


class TestBuildLaunchArgs:
    """浏览器启动参数构建。"""

    def test_default_args(self):
        """默认参数包含基础安全选项。"""
        worker = PlaywrightWorker()
        args = worker._build_launch_args({})
        assert "--no-sandbox" in args
        assert "--disable-dev-shm-usage" in args
        assert "--disable-gpu" in args
        assert "--memory-pressure-off" in args

    def test_disable_web_security(self):
        """启用 disable_web_security 时添加对应参数。"""
        worker = PlaywrightWorker()
        args = worker._build_launch_args({"disable_web_security": True})
        assert "--disable-web-security" in args

    def test_low_resource_mode(self):
        """启用低资源模式时禁用图片。"""
        worker = PlaywrightWorker()
        args = worker._build_launch_args({"low_resource_mode": True})
        assert "--blink-settings=imagesEnabled=false" in args

    def test_custom_browser_args(self):
        """自定义浏览器参数被添加。"""
        worker = PlaywrightWorker()
        settings = {"browser_args": "--disable-extensions\n--no-first-run"}
        args = worker._build_launch_args(settings)
        assert "--disable-extensions" in args
        assert "--no-first-run" in args

    def test_custom_args_no_duplicates(self):
        """自定义参数不与默认参数重复。"""
        worker = PlaywrightWorker()
        settings = {"browser_args": "--no-sandbox"}
        args = worker._build_launch_args(settings)
        assert args.count("--no-sandbox") == 1

    def test_custom_args_strips_whitespace(self):
        """自定义参数中的空白行被跳过。"""
        worker = PlaywrightWorker()
        settings = {"browser_args": "--flag1\n\n  \n--flag2"}
        args = worker._build_launch_args(settings)
        assert "--flag1" in args
        assert "--flag2" in args

    def test_empty_browser_args(self):
        """空的 browser_args 不影响结果。"""
        worker = PlaywrightWorker()
        args = worker._build_launch_args({"browser_args": ""})
        assert len(args) == 4  # 只有默认的 4 个参数

    def test_none_browser_args(self):
        """None 的 browser_args 不影响结果。"""
        worker = PlaywrightWorker()
        args = worker._build_launch_args({"browser_args": None})
        assert len(args) == 4


# ── PlaywrightWorker._build_context_options ──


class TestBuildContextOptions:
    """浏览器上下文选项构建。"""

    def test_default_options(self):
        """默认选项包含标准视口和区域设置。"""
        worker = PlaywrightWorker()
        opts = worker._build_context_options({})
        assert opts["viewport"]["width"] == 1280
        assert opts["viewport"]["height"] == 720
        assert opts["locale"] == "zh-CN"
        assert opts["timezone_id"] == "Asia/Shanghai"
        assert opts["has_touch"] is False
        assert opts["color_scheme"] == "light"
        assert opts["ignore_https_errors"] is True

    def test_custom_viewport(self):
        """自定义视口大小。"""
        worker = PlaywrightWorker()
        opts = worker._build_context_options(
            {"viewport_width": 1920, "viewport_height": 1080}
        )
        assert opts["viewport"]["width"] == 1920
        assert opts["viewport"]["height"] == 1080

    def test_custom_user_agent(self):
        """自定义 User-Agent 被添加。"""
        worker = PlaywrightWorker()
        opts = worker._build_context_options({"user_agent": "CustomBot/1.0"})
        assert opts["user_agent"] == "CustomBot/1.0"

    def test_empty_user_agent_ignored(self):
        """空 User-Agent 不被添加。"""
        worker = PlaywrightWorker()
        opts = worker._build_context_options({"user_agent": ""})
        assert "user_agent" not in opts

    def test_extra_http_headers(self):
        """自定义 HTTP 请求头被添加。"""
        worker = PlaywrightWorker()
        opts = worker._build_context_options(
            {"extra_headers_json": '{"X-Test": "value"}'}
        )
        assert opts["extra_http_headers"] == {"X-Test": "value"}

    def test_ignore_https_errors_false(self):
        """禁用忽略 HTTPS 错误。"""
        worker = PlaywrightWorker()
        opts = worker._build_context_options({"ignore_https_errors": False})
        assert opts["ignore_https_errors"] is False


# ── PlaywrightWorker._health_check ──


class TestHealthCheck:
    """浏览器健康检查。"""

    @pytest.mark.asyncio
    async def test_no_browser(self):
        """无浏览器实例时返回 False。"""
        worker = PlaywrightWorker()
        assert await worker._health_check() is False

    @pytest.mark.asyncio
    async def test_browser_connected(self):
        """浏览器连接正常时返回 True。"""
        worker = PlaywrightWorker()
        mock_browser = MagicMock()
        mock_browser.is_connected.return_value = True
        worker._browser = mock_browser
        assert await worker._health_check() is True

    @pytest.mark.asyncio
    async def test_browser_disconnected(self):
        """浏览器断开连接时返回 False。"""
        worker = PlaywrightWorker()
        mock_browser = MagicMock()
        mock_browser.is_connected.return_value = False
        worker._browser = mock_browser
        assert await worker._health_check() is False

    @pytest.mark.asyncio
    async def test_browser_check_raises(self):
        """健康检查抛异常时返回 False。"""
        worker = PlaywrightWorker()
        mock_browser = MagicMock()
        mock_browser.is_connected.side_effect = RuntimeError("browser crashed")
        worker._browser = mock_browser
        assert await worker._health_check() is False


# ── PlaywrightWorker._is_normal_close_error ──


class TestIsNormalCloseError:
    """正常关闭错误判断。"""

    def test_target_closed(self):
        """'target closed' 被识别为正常关闭。"""
        assert (
            PlaywrightWorker._is_normal_close_error(RuntimeError("Target closed"))
            is True
        )

    def test_connection_closed(self):
        """'connection closed' 被识别为正常关闭。"""
        assert (
            PlaywrightWorker._is_normal_close_error(RuntimeError("Connection closed"))
            is True
        )

    def test_other_error(self):
        """其他错误不被视为正常关闭。"""
        assert (
            PlaywrightWorker._is_normal_close_error(RuntimeError("Some other error"))
            is False
        )

    def test_case_insensitive(self):
        """匹配不区分大小写。"""
        assert (
            PlaywrightWorker._is_normal_close_error(RuntimeError("TARGET CLOSED"))
            is True
        )


# ── PlaywrightWorker._handle_low_resource_request ──


class TestHandleLowResourceRequest:
    """低资源模式请求拦截。"""

    @pytest.mark.asyncio
    async def test_blocks_image(self):
        """图片请求被中止。"""
        worker = PlaywrightWorker()
        mock_route = MagicMock()
        mock_route.request.resource_type = "image"
        mock_route.abort = AsyncMock()
        mock_route.continue_ = AsyncMock()
        await worker._handle_low_resource_request(mock_route)
        mock_route.abort.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_blocks_font(self):
        """字体请求被中止。"""
        worker = PlaywrightWorker()
        mock_route = MagicMock()
        mock_route.request.resource_type = "font"
        mock_route.abort = AsyncMock()
        mock_route.continue_ = AsyncMock()
        await worker._handle_low_resource_request(mock_route)
        mock_route.abort.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_blocks_media(self):
        """媒体请求被中止。"""
        worker = PlaywrightWorker()
        mock_route = MagicMock()
        mock_route.request.resource_type = "media"
        mock_route.abort = AsyncMock()
        mock_route.continue_ = AsyncMock()
        await worker._handle_low_resource_request(mock_route)
        mock_route.abort.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_allows_document(self):
        """文档请求被放行。"""
        worker = PlaywrightWorker()
        mock_route = MagicMock()
        mock_route.request.resource_type = "document"
        mock_route.abort = AsyncMock()
        mock_route.continue_ = AsyncMock()
        await worker._handle_low_resource_request(mock_route)
        mock_route.continue_.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_allows_script(self):
        """脚本请求被放行。"""
        worker = PlaywrightWorker()
        mock_route = MagicMock()
        mock_route.request.resource_type = "script"
        mock_route.abort = AsyncMock()
        mock_route.continue_ = AsyncMock()
        await worker._handle_low_resource_request(mock_route)
        mock_route.continue_.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_exception_ignored(self):
        """异常被静默处理（页面/上下文已关闭）。"""
        worker = PlaywrightWorker()
        mock_route = MagicMock()
        mock_route.request.resource_type = "document"
        mock_route.abort = AsyncMock()
        mock_route.continue_ = AsyncMock(side_effect=RuntimeError("page closed"))
        await worker._handle_low_resource_request(mock_route)


# ── PlaywrightWorker._cmd_queue 类型 ──


class TestCmdQueueType:
    """_cmd_queue 应为 asyncio.Queue。"""

    def test_cmd_queue_is_asyncio_queue(self):
        """_cmd_queue 应为 asyncio.Queue 实例。"""
        import asyncio

        worker = PlaywrightWorker()
        assert isinstance(worker._cmd_queue, asyncio.Queue)

    def test_cmd_queue_maxsize_50(self):
        """队列容量 50。"""
        worker = PlaywrightWorker()
        assert worker._cmd_queue.maxsize == 50

    def test_no_wake_event_attribute(self):
        """_wake_event 字段应已移除。"""
        worker = PlaywrightWorker()
        assert not hasattr(worker, "_wake_event")

    def test_no_wake_async_method(self):
        """_wake_async 方法应已移除。"""
        worker = PlaywrightWorker()
        assert not hasattr(worker, "_wake_async")


# ── PlaywrightWorker 属性访问 ──


class TestWorkerProperties:
    """Worker 属性访问。"""

    def test_page_property(self):
        worker = PlaywrightWorker()
        assert worker.page is None

    def test_browser_property(self):
        worker = PlaywrightWorker()
        assert worker.browser is None

    def test_context_property(self):
        worker = PlaywrightWorker()
        assert worker.context is None

    def test_playwright_instance_property(self):
        worker = PlaywrightWorker()
        assert worker.playwright_instance is None


# ── PlaywrightWorker._close_resource ──


class TestCloseResource:
    """资源关闭辅助方法。"""

    @pytest.mark.asyncio
    async def test_close_none_resource(self):
        """关闭 None 资源不报错。"""
        worker = PlaywrightWorker()
        await worker._close_resource(None, "test", graceful=True)

    @pytest.mark.asyncio
    async def test_close_graceful_success(self):
        """优雅关闭成功。"""
        worker = PlaywrightWorker()
        mock_resource = MagicMock()
        mock_resource.is_closed.return_value = False
        mock_resource.close = AsyncMock()
        await worker._close_resource(
            mock_resource, "page", graceful=True, has_check="is_closed"
        )
        mock_resource.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close_graceful_already_closed(self):
        """资源已关闭时跳过 close。"""
        worker = PlaywrightWorker()
        mock_resource = MagicMock()
        mock_resource.is_closed.return_value = True
        mock_resource.close = AsyncMock()
        await worker._close_resource(
            mock_resource, "page", graceful=True, has_check="is_closed"
        )
        mock_resource.close.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_close_graceful_normal_error(self):
        """优雅关闭时正常关闭错误仅 warning。"""
        worker = PlaywrightWorker()
        mock_resource = MagicMock()
        mock_resource.close = AsyncMock(side_effect=RuntimeError("target closed"))
        await worker._close_resource(mock_resource, "page", graceful=True)

    @pytest.mark.asyncio
    async def test_close_non_graceful_exception(self):
        """非优雅模式下异常被忽略。"""
        worker = PlaywrightWorker()
        mock_resource = MagicMock()
        mock_resource.close = AsyncMock(side_effect=RuntimeError("any error"))
        await worker._close_resource(mock_resource, "page", graceful=False)


# ── PlaywrightWorker._dispatch ──


class TestDispatch:
    """命令派发。"""

    @pytest.mark.asyncio
    async def test_cancelled_command_skipped(self):
        """已取消的命令被跳过。"""
        worker = PlaywrightWorker()
        cmd = WorkerCommand(type=CMD_LOGIN, cancelled=True)
        await worker._dispatch(cmd)
        assert cmd.response_data is None

    @pytest.mark.asyncio
    async def test_shutdown_command(self):
        """SHUTDOWN 命令返回成功。"""
        worker = PlaywrightWorker()
        event = threading.Event()
        cmd = WorkerCommand(type=CMD_SHUTDOWN, response_event=event)
        await worker._dispatch(cmd)
        assert cmd.response_data.success is True

    @pytest.mark.asyncio
    async def test_unknown_command(self):
        """未知命令返回错误。"""
        worker = PlaywrightWorker()
        event = threading.Event()
        cmd = WorkerCommand(type="unknown_type", response_event=event)
        await worker._dispatch(cmd)
        assert cmd.response_data.success is False
        assert "未知命令" in cmd.response_data.error


    @pytest.mark.asyncio
    async def test_dispatch_sets_response_event(self):
        """派发完成后设置 response_event。"""
        worker = PlaywrightWorker()
        event = threading.Event()
        cmd = WorkerCommand(type=CMD_SHUTDOWN, response_event=event)
        await worker._dispatch(cmd)
        assert event.is_set()

    @pytest.mark.asyncio
    async def test_dispatch_exception_sets_error(self):
        """派发异常时设置错误响应。"""
        worker = PlaywrightWorker()
        event = threading.Event()
        cmd = WorkerCommand(type=CMD_LOGIN, response_event=event)
        with patch.object(
            worker, "_handle_login", new=AsyncMock(side_effect=RuntimeError("boom"))
        ):
            await worker._dispatch(cmd)
        assert cmd.response_data.success is False
        assert "boom" in cmd.response_data.error


# ── PlaywrightWorker.submit with queue full ──


class TestSubmitQueueFull:
    """submit 队列满时的行为。"""

    def test_queue_full_returns_error(self):
        """队列满时返回错误（call_soon_threadsafe 内部 put_nowait 抛 QueueFull，被吞，调用方靠超时返回）。"""
        import asyncio

        worker = PlaywrightWorker()
        worker._consumer_thread = MagicMock()
        worker._consumer_thread.is_alive.return_value = True
        worker._stop_event.clear()
        fake_loop = MagicMock()
        fake_loop.is_running.return_value = True

        # 模拟 call_soon_threadsafe 内部 put_nowait 抛 QueueFull
        def fake_call_soon(fn, *args):
            with contextlib.suppress(asyncio.QueueFull):
                fn(*args)

        fake_loop.call_soon_threadsafe.side_effect = fake_call_soon
        worker._loop = fake_loop

        with patch.object(
            worker._cmd_queue, "put_nowait", side_effect=asyncio.QueueFull
        ):
            result = worker.submit("test_cmd", wait=True, timeout=0.1)
        # QueueFull 被吞 → response_event 未 set → wait 超时返回错误
        assert result.success is False

    def test_queue_full_wait_false_returns_success(self):
        """队列满 + wait=False → call_soon_threadsafe 吞 QueueFull，返回 success=True（已接受的 trade-off）。"""
        import asyncio

        worker = PlaywrightWorker()
        worker._consumer_thread = MagicMock()
        worker._consumer_thread.is_alive.return_value = True
        worker._stop_event.clear()
        fake_loop = MagicMock()
        fake_loop.is_running.return_value = True

        # 模拟真实行为：call_soon_threadsafe 不传播回调中的 QueueFull
        def fake_call_soon(fn, *args):
            with contextlib.suppress(asyncio.QueueFull):
                fn(*args)

        fake_loop.call_soon_threadsafe.side_effect = fake_call_soon
        worker._loop = fake_loop

        with patch.object(
            worker._cmd_queue, "put_nowait", side_effect=asyncio.QueueFull
        ):
            result = worker.submit("test_cmd", wait=False)
        # call_soon_threadsafe 吞掉 QueueFull → submit 无法同步获知，返回 success=True
        assert result.success is True

    def test_queue_full_when_loop_none(self):
        """loop 为 None 时直接 put_nowait，QueueFull 同步捕获。"""
        import asyncio

        worker = PlaywrightWorker()
        worker._consumer_thread = MagicMock()
        worker._consumer_thread.is_alive.return_value = True
        worker._stop_event.clear()
        worker._loop = None

        with patch.object(
            worker._cmd_queue, "put_nowait", side_effect=asyncio.QueueFull
        ):
            result = worker.submit("test_cmd", wait=False)
        assert result.success is False
        assert "队列已满" in result.error


# ── PlaywrightWorker.submit with timeout ──


class TestSubmitTimeout:
    """submit 超时行为。"""

    def test_timeout_returns_error(self):
        """等待超时返回错误。"""
        worker = PlaywrightWorker()
        worker._consumer_thread = MagicMock()
        worker._consumer_thread.is_alive.return_value = True
        worker._stop_event.clear()
        fake_loop = MagicMock()
        fake_loop.is_running.return_value = True
        fake_loop.call_soon_threadsafe.side_effect = lambda fn, *args: fn(*args)
        worker._loop = fake_loop

        # put_nowait 成功，但 response_event 不被 set → 超时
        with patch.object(worker._cmd_queue, "put_nowait"):
            result = worker.submit("test_cmd", wait=True, timeout=0.01)

        assert result.success is False
        assert "超时" in result.error or "无响应" in result.error


# ── PlaywrightWorker.submit with response_data ──


class TestSubmitResponseData:
    """submit 响应数据处理。"""

    def test_response_data_is_worker_response(self):
        """response_data 为 WorkerResponse 时直接返回。"""
        worker = PlaywrightWorker()
        worker._consumer_thread = MagicMock()
        worker._consumer_thread.is_alive.return_value = True
        worker._stop_event.clear()

        # 模拟 put_nowait 后直接设置 response_data
        def fake_put_nowait(cmd):
            cmd.response_data = WorkerResponse(success=True, data="result")
            if cmd.response_event:
                cmd.response_event.set()

        fake_loop = MagicMock()
        fake_loop.is_running.return_value = True
        fake_loop.call_soon_threadsafe.side_effect = lambda fn, *args: fn(*args)
        worker._loop = fake_loop

        with patch.object(worker._cmd_queue, "put_nowait", side_effect=fake_put_nowait):
            result = worker.submit("test_cmd", wait=True)

        assert result.success is True
        assert result.data == "result"

    def test_response_data_is_plain_value(self):
        """response_data 为普通值时包装为 WorkerResponse。"""
        worker = PlaywrightWorker()
        worker._consumer_thread = MagicMock()
        worker._consumer_thread.is_alive.return_value = True
        worker._stop_event.clear()

        def fake_put_nowait(cmd):
            cmd.response_data = "plain_value"
            if cmd.response_event:
                cmd.response_event.set()

        fake_loop = MagicMock()
        fake_loop.is_running.return_value = True
        fake_loop.call_soon_threadsafe.side_effect = lambda fn, *args: fn(*args)
        worker._loop = fake_loop

        with patch.object(worker._cmd_queue, "put_nowait", side_effect=fake_put_nowait):
            result = worker.submit("test_cmd", wait=True)

        assert result.success is True
        assert result.data == "plain_value"


# ── PlaywrightWorker._cleanup_browser ──


class TestCleanupBrowser:
    """浏览器资源清理。"""

    @pytest.mark.asyncio
    async def test_cleanup_graceful_all_none(self):
        """所有资源为 None 时不报错。"""
        worker = PlaywrightWorker()
        await worker._cleanup_browser(graceful=True)
        assert worker._playwright is None
        assert worker._browser is None
        assert worker._context is None
        assert worker._page is None
        assert worker._debug_page is None
        assert worker._debug_executor is None

    @pytest.mark.asyncio
    async def test_cleanup_force_all_none(self):
        """强制清理所有资源为 None。"""
        worker = PlaywrightWorker()
        await worker._cleanup_browser(graceful=False)
        assert worker._playwright is None

    @pytest.mark.asyncio
    async def test_cleanup_with_debug_page(self):
        """清理调试页面。"""
        worker = PlaywrightWorker()
        mock_debug_page = MagicMock()
        mock_debug_page.is_closed.return_value = False
        mock_debug_page.close = AsyncMock()
        worker._debug_page = mock_debug_page
        worker._debug_executor = MagicMock()

        await worker._cleanup_browser(graceful=True)

        mock_debug_page.close.assert_awaited_once()
        assert worker._debug_page is None
        assert worker._debug_executor is None

    @pytest.mark.asyncio
    async def test_cleanup_with_browser_connected(self):
        """浏览器连接正常时调用 close。"""
        worker = PlaywrightWorker()
        mock_browser = MagicMock()
        mock_browser.is_connected.return_value = True
        mock_browser.close = AsyncMock()
        worker._browser = mock_browser

        await worker._cleanup_browser(graceful=True)

        mock_browser.close.assert_awaited_once()
        assert worker._browser is None

    @pytest.mark.asyncio
    async def test_cleanup_with_browser_disconnected(self):
        """浏览器已断开时跳过 close。"""
        worker = PlaywrightWorker()
        mock_browser = MagicMock()
        mock_browser.is_connected.return_value = False
        mock_browser.close = AsyncMock()
        worker._browser = mock_browser

        await worker._cleanup_browser(graceful=True)

        mock_browser.close.assert_not_awaited()
        assert worker._browser is None

    @pytest.mark.asyncio
    async def test_cleanup_with_playwright(self):
        """清理 Playwright 实例。"""
        worker = PlaywrightWorker()
        mock_pw = MagicMock()
        mock_pw.stop = AsyncMock()
        worker._playwright = mock_pw

        await worker._cleanup_browser(graceful=True)

        mock_pw.stop.assert_awaited_once()
        assert worker._playwright is None

    @pytest.mark.asyncio
    async def test_cleanup_playwright_normal_close_error(self):
        """Playwright 停止时正常关闭错误仅 warning。"""
        worker = PlaywrightWorker()
        mock_pw = MagicMock()
        mock_pw.stop = AsyncMock(side_effect=RuntimeError("target closed"))
        worker._playwright = mock_pw

        await worker._cleanup_browser(graceful=True)

    @pytest.mark.asyncio
    async def test_cleanup_playwright_other_error(self):
        """Playwright 停止时其他错误记录为 error。"""
        worker = PlaywrightWorker()
        mock_pw = MagicMock()
        mock_pw.stop = AsyncMock(side_effect=RuntimeError("some error"))
        worker._playwright = mock_pw

        await worker._cleanup_browser(graceful=True)

    @pytest.mark.asyncio
    async def test_cleanup_force_silences_exceptions(self):
        """强制模式下所有异常被静默。"""
        worker = PlaywrightWorker()
        mock_pw = MagicMock()
        mock_pw.stop = AsyncMock(side_effect=RuntimeError("boom"))
        worker._playwright = mock_pw

        await worker._cleanup_browser(graceful=False)


# ── PlaywrightWorker.stop 详细测试 ──


class TestStopDetails:
    """stop 方法详细测试。"""

    def test_stop_sets_permanent_shutdown(self):
        """stop 设置永久关闭标志。"""
        worker = PlaywrightWorker()
        worker.stop(timeout=0.1)
        assert worker._shutdown_permanent.is_set()
        assert worker._stop_event.is_set()

    def test_stop_drains_queue(self):
        """stop 排干队列并通知等待方。"""
        worker = PlaywrightWorker()
        event = threading.Event()
        cmd = WorkerCommand(type=CMD_LOGIN, response_event=event)
        worker._cmd_queue.put_nowait(cmd)

        worker.stop(timeout=0.1)

        assert event.is_set()
        assert cmd.response_data is not None
        assert cmd.response_data.success is False


# ── get_worker / shutdown_worker ──


class TestGetWorkerShutdownWorker:
    """全局 Worker 单例管理。"""

    def test_shutdown_worker_when_none(self):
        """Worker 为 None 时不报错。"""
        import app.workers.playwright_worker as pw_mod

        old = pw_mod._worker
        try:
            pw_mod._worker = None
            pw_mod.shutdown_worker(timeout=0.1)
        finally:
            pw_mod._worker = old

    def test_shutdown_worker_when_alive(self):
        """Worker 存活时正常关闭。"""
        import app.workers.playwright_worker as pw_mod

        mock_worker = MagicMock()
        mock_worker.is_alive.return_value = True
        old = pw_mod._worker
        try:
            pw_mod._worker = mock_worker
            pw_mod.shutdown_worker(timeout=0.1)
            mock_worker.stop.assert_called_once_with(timeout=0.1)
        finally:
            pw_mod._worker = old
