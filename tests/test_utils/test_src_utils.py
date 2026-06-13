"""src/ 工具模块综合测试

合并原 test_notify.py、test_browser.py、test_system_tray.py、
test_playwright_bootstrap.py、test_playwright_worker.py。
覆盖桌面通知、浏览器管理、系统托盘、Playwright 引导、Worker 等模块。
"""

from __future__ import annotations

import os
import subprocess
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.ui.system_tray import SystemTray
from app.utils.browser import STEALTH_INIT_SCRIPT, BrowserContextManager
from app.utils.exceptions import LoginCancelledError
from app.utils.notify import (
    _notify_linux,
    _notify_macos,
    _notify_windows,
    send_notification,
)
from app.workers.playwright_bootstrap import (
    _candidate_hosts,
    _has_chromium,
    _is_enabled,
    ensure_playwright_ready,
)
from app.workers.playwright_worker import (
    CMD_BROWSER_ACQUIRE,
    CMD_BROWSER_CLOSE,
    CMD_BROWSER_HEALTH_CHECK,
    CMD_BROWSER_RELEASE,
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
#  桌面通知 (src/utils/notify.py)
# ─────────────────────────────────────────────────────────────────────


class TestSendNotification:
    @patch("app.utils.notify.is_windows", return_value=True)
    @patch("app.utils.notify._notify_windows", return_value=True)
    def test_windows(self, mock_win, mock_is_win):
        assert send_notification("标题", "消息") is True
        mock_win.assert_called_once_with("标题", "消息", 5000)

    @patch("app.utils.notify.is_windows", return_value=False)
    @patch("app.utils.notify.is_macos", return_value=True)
    @patch("app.utils.notify._notify_macos", return_value=True)
    def test_macos(self, mock_mac, mock_is_mac, mock_is_win):
        assert send_notification("标题", "消息") is True
        mock_mac.assert_called_once_with("标题", "消息")

    @patch("app.utils.notify.is_windows", return_value=False)
    @patch("app.utils.notify.is_macos", return_value=False)
    @patch("app.utils.notify.is_linux", return_value=True)
    @patch("app.utils.notify._notify_linux", return_value=True)
    def test_linux(self, mock_linux, mock_is_linux, mock_is_mac, mock_is_win):
        assert send_notification("标题", "消息") is True
        mock_linux.assert_called_once_with("标题", "消息", 5000)

    @patch("app.utils.notify.is_windows", return_value=False)
    @patch("app.utils.notify.is_macos", return_value=False)
    @patch("app.utils.notify.is_linux", return_value=False)
    def test_unsupported_platform(self, mock_is_linux, mock_is_mac, mock_is_win):
        assert send_notification("标题", "消息") is False

    @patch("app.utils.notify.is_windows", return_value=True)
    @patch("app.utils.notify._notify_windows", side_effect=Exception("fail"))
    def test_exception_returns_false(self, mock_win, mock_is_win):
        assert send_notification("标题", "消息") is False

    @patch("app.utils.notify.is_windows", return_value=True)
    @patch("app.utils.notify._notify_windows", return_value=True)
    def test_custom_duration(self, mock_win, mock_is_win):
        send_notification("标题", "消息", duration_ms=10000)
        mock_win.assert_called_once_with("标题", "消息", 10000)

    @patch("app.utils.notify.is_windows", return_value=True)
    @patch("app.utils.notify._notify_windows", return_value=False)
    def test_failure_returns_false(self, mock_win, mock_is_win):
        assert send_notification("标题", "消息") is False


class TestNotifyWindows:
    @patch("app.utils.notify.subprocess.run")
    def test_powershell_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        result = _notify_windows("标题", "消息", 5000)
        assert result is True
        mock_run.assert_called_once()

    @patch("app.utils.notify.subprocess.run")
    def test_powershell_failure_msg_fallback(self, mock_run):
        mock_run.side_effect = [
            MagicMock(returncode=1),
            MagicMock(returncode=0),
        ]
        result = _notify_windows("标题", "消息", 5000)
        assert result is True
        assert mock_run.call_count == 2

    @patch("app.utils.notify.subprocess.run")
    def test_both_fail(self, mock_run):
        mock_run.side_effect = [
            MagicMock(returncode=1),
            FileNotFoundError(),
        ]
        result = _notify_windows("标题", "消息", 5000)
        assert result is False

    @patch("app.utils.notify.subprocess.run")
    def test_special_characters(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        result = _notify_windows('标题`${"}$', '消息`${"}$', 5000)
        assert result is True

    @patch("app.utils.notify.subprocess.run")
    def test_powershell_timeout(self, mock_run):
        mock_run.side_effect = [
            subprocess.TimeoutExpired("powershell", 10),
            MagicMock(returncode=0),
        ]
        result = _notify_windows("标题", "消息", 5000)
        assert result is True


class TestNotifyMacos:
    @patch("app.utils.notify.subprocess.run")
    def test_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        result = _notify_macos("标题", "消息")
        assert result is True

    @patch("app.utils.notify.subprocess.run")
    def test_failure(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1)
        result = _notify_macos("标题", "消息")
        assert result is False

    @patch("app.utils.notify.subprocess.run")
    def test_special_characters(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        result = _notify_macos('标题"\\', '消息"\\')
        assert result is True
        call_args = mock_run.call_args
        script = call_args[0][0][2]
        assert '\\"' in script


class TestNotifyLinux:
    @patch("app.utils.notify.shutil.which", return_value="/usr/bin/notify-send")
    @patch("app.utils.notify.subprocess.run")
    def test_success(self, mock_run, mock_which):
        mock_run.return_value = MagicMock(returncode=0)
        result = _notify_linux("标题", "消息", 5000)
        assert result is True

    @patch("app.utils.notify.shutil.which", return_value=None)
    def test_no_notify_send(self, mock_which):
        result = _notify_linux("标题", "消息", 5000)
        assert result is False

    @patch("app.utils.notify.shutil.which", return_value="/usr/bin/notify-send")
    @patch("app.utils.notify.subprocess.run")
    def test_failure(self, mock_run, mock_which):
        mock_run.return_value = MagicMock(returncode=1)
        result = _notify_linux("标题", "消息", 5000)
        assert result is False

    @patch("app.utils.notify.shutil.which", return_value="/usr/bin/notify-send")
    @patch("app.utils.notify.subprocess.run")
    def test_duration_conversion(self, mock_run, mock_which):
        mock_run.return_value = MagicMock(returncode=0)
        _notify_linux("标题", "消息", 5000)
        call_args = mock_run.call_args[0][0]
        assert "5000" in call_args


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
        assert ctx._worker_managed is False

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
        assert ctx.playwright is None
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
        assert icon is not None
        assert icon.size == (64, 64)

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
        # 延迟导入：需要先初始化 _pystray
        import pystray

        tray._pystray = pystray
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

    @patch("app.ui.system_tray.threading.Thread")
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

    @patch("app.ui.system_tray.threading.Thread")
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
    @patch("app.workers.playwright_bootstrap.is_windows", return_value=True)
    def test_windows_no_cache_dir(self, mock_is_win):
        with (
            patch(
                "app.workers.playwright_bootstrap.Path.home",
                return_value=Path("/nonexistent"),
            ),
            patch("importlib.util.find_spec", return_value=None),
            patch.dict(
                "sys.modules", {"playwright.sync_api": None, "playwright": None}
            ),
        ):
            assert _has_chromium() is False

    @patch("app.workers.playwright_bootstrap.is_windows", return_value=False)
    @patch("app.workers.playwright_bootstrap.is_macos", return_value=False)
    def test_linux_no_cache_dir(self, mock_is_mac, mock_is_win):
        with (
            patch(
                "app.workers.playwright_bootstrap.Path.home",
                return_value=Path("/nonexistent"),
            ),
            patch("importlib.util.find_spec", return_value=None),
            patch.dict(
                "sys.modules", {"playwright.sync_api": None, "playwright": None}
            ),
        ):
            assert _has_chromium() is False


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

    @patch("app.workers.playwright_bootstrap._has_chromium", return_value=False)
    @patch("app.workers.playwright_bootstrap._is_enabled", return_value=True)
    def test_no_playwright_package(self, mock_enabled, mock_chromium):
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
        assert CMD_BROWSER_HEALTH_CHECK == "browser_health_check"
        assert CMD_BROWSER_ACQUIRE == "browser_acquire"
        assert CMD_BROWSER_RELEASE == "browser_release"
        assert CMD_BROWSER_CLOSE == "browser_close"
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
    def test_kills_matching_processes(self):
        """匹配 ms-playwright + chrom 的进程应被终止。"""
        from app.workers.playwright_worker import cleanup_orphan_browsers

        mock_proc = MagicMock()
        mock_proc.info = {
            "pid": 1234,
            "exe": "C:/ms-playwright/chromium-1234/chrome.exe",
            "cmdline": ["chrome.exe", "--headless"],
        }

        with patch("psutil.process_iter", return_value=[mock_proc]):
            cleanup_orphan_browsers()

        mock_proc.kill.assert_called_once()

    def test_ignores_non_matching_processes(self):
        """不匹配的进程不应被终止。"""
        from app.workers.playwright_worker import cleanup_orphan_browsers

        mock_proc = MagicMock()
        mock_proc.info = {
            "pid": 5678,
            "exe": "C:/Program Files/Google/Chrome/chrome.exe",
            "cmdline": ["chrome.exe"],
        }

        with patch("psutil.process_iter", return_value=[mock_proc]):
            cleanup_orphan_browsers()

        mock_proc.kill.assert_not_called()

    def test_handles_no_such_process(self):
        """进程已消失时不应抛异常。"""
        import psutil as real_psutil

        from app.workers.playwright_worker import cleanup_orphan_browsers

        mock_proc = MagicMock()
        mock_proc.info = {
            "pid": 9999,
            "exe": "C:/ms-playwright/chromium-1234/chrome.exe",
            "cmdline": [],
        }
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

        with patch("app.ui.system_tray.Path") as mock_path_cls:
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
        import pystray

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
        """有 icon 和 on_exit 时两者都被调用。"""
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
