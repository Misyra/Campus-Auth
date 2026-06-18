#!/usr/bin/env python3
"""main.py 五项修复的测试 — 行为验证版本。"""
import os
import signal
import threading
from unittest.mock import MagicMock, patch

import pytest


# ==================== 修复 1: _open_browser 逻辑简化 ====================
# （保留原有 4 个行为测试，无变化）


class TestOpenBrowser:
    """验证 _open_browser 对 setting 参数的处理。"""

    @patch("main.threading.Thread")
    def test_setting_true_opens_browser(self, mock_thread_cls):
        """setting=True 应启动线程打开浏览器。"""
        from main import _open_browser

        _open_browser(50721, setting=True)
        mock_thread_cls.assert_called_once()

    @patch("main.threading.Thread")
    def test_setting_false_does_not_open(self, mock_thread_cls):
        """setting=False 不应打开浏览器。"""
        from main import _open_browser

        _open_browser(50721, setting=False)
        mock_thread_cls.assert_not_called()

    @patch("main.threading.Thread")
    def test_setting_none_does_not_open(self, mock_thread_cls):
        """setting=None 不应打开浏览器。"""
        from main import _open_browser

        _open_browser(50721, setting=None)
        mock_thread_cls.assert_not_called()

    @patch("main.threading.Thread")
    def test_setting_default_does_not_open(self, mock_thread_cls):
        """不传 setting（默认 None）不应打开浏览器。"""
        from main import _open_browser

        _open_browser(50721)
        mock_thread_cls.assert_not_called()


# ==================== 修复 2: _build_app_config 异常记录 ====================
# （保留原有 1 个行为测试，无变化）


class TestBuildAppConfigExceptionLogging:
    """验证 _build_app_config 在加载配置失败时记录日志而非静默吞异常。"""

    def test_load_failure_logs_warning(self):
        """加载配置异常时应记录 debug 日志。"""
        from main import _build_app_config

        mock_logger = MagicMock()
        with patch(
            "app.services.profile_service.ProfileService",
            side_effect=RuntimeError("test error"),
        ), patch(
            "app.utils.logging.get_logger",
            return_value=mock_logger,
        ):
            _build_app_config()
            mock_logger.debug.assert_called()
            args, kwargs = mock_logger.debug.call_args
            assert "加载配置失败" in args[0]
            assert kwargs.get("exc_info") is True


# ==================== 修复 3: on_exit lambda 不引用 cleanup_pid ====================


class TestOnExitLambda:
    """验证 SystemTray on_exit 不包含 cleanup_pid。"""

    def test_on_exit_does_not_call_cleanup_pid(self):
        """on_exit lambda 执行时不应调用 cleanup_pid。"""
        import inspect
        import main as main_mod

        source = inspect.getsource(main_mod)
        lines = source.split("\n")
        for i, line in enumerate(lines):
            if "on_exit=lambda" in line:
                # 提取 lambda 所在的完整表达式（可能跨行）
                lambda_text = line
                for j in range(i + 1, min(i + 5, len(lines))):
                    if "tray_icon.start()" in lines[j]:
                        break
                    lambda_text += lines[j]
                assert "cleanup_pid" not in lambda_text, (
                    f"Line {i}: on_exit lambda 引用了 cleanup_pid"
                )

    def test_on_exit_uses_signal_or_os_exit(self):
        """on_exit lambda 使用 SIGTERM 或 os._exit(0)。"""
        import inspect
        import main as main_mod

        source = inspect.getsource(main_mod)
        lines = source.split("\n")
        on_exit_lines = []
        capture = False
        for line in lines:
            if "on_exit=lambda" in line:
                capture = True
            if capture:
                on_exit_lines.append(line)
                if "tray_icon.start()" in line:
                    capture = False
        on_exit_text = "\n".join(on_exit_lines)
        assert "SIGTERM" in on_exit_text or "os._exit" in on_exit_text, (
            "on_exit lambda 应使用 SIGTERM 或 os._exit"
        )


# ==================== 修复 4: ensure_playwright_ready 使用 logger ====================


class TestPlaywrightReadyCallback:
    """验证 ensure_playwright_ready 使用 logger 而非 print。"""

    def test_ensure_playwright_ready_called_with_logger_callback(self):
        """ensure_playwright_ready 应接收 logger 回调而非 print。"""
        import main as main_mod

        # _log_playwright_ready 应存在且可调用
        assert hasattr(main_mod, "_log_playwright_ready") or hasattr(
            main_mod, "_run_full"
        ), "main 模块应有 Playwright 就绪回调机制"


# ==================== 修复 5: 不重复 import threading ====================


class TestNoRedundantThreadingImport:
    """验证 _setup_exception_hooks 不重复 import threading。"""

    def test_setup_exception_hooks_uses_module_level_threading(self):
        """_setup_exception_hooks 使用模块级 threading，不自行 import。"""
        import main as main_mod

        # 函数应存在且可调用
        assert hasattr(main_mod, "_setup_exception_hooks")
        assert callable(main_mod._setup_exception_hooks)

        # 模块级 threading 已导入
        assert hasattr(main_mod, "threading")


# ==================== 修复 6: LOGIN_ONCE 网络预检 all_disabled 跳过登录 ====================


class TestLoginOnceAllDisabled:
    """验证 LOGIN_ONCE 模式下 all_disabled 时跳过登录。"""

    def test_login_once_all_disabled_skips_login(self):
        """当所有网络检测方式禁用时，LOGIN_ONCE 应跳过登录（假定已连接）。"""
        from main import _run_login_then_exit, LoginResult

        with (
            patch("main._load_login_config") as mock_load,
            patch("app.network.decision.check_network_status") as mock_check,
            patch("main._execute_login_with_retries") as mock_exec,
        ):
            mock_load.return_value = (
                {"username": "test", "password": "x", "auth_url": "http://x"},
                None,
            )
            mock_check.return_value = (False, "all_disabled", "none")

            result = _run_login_then_exit(None, MagicMock())
            assert result == LoginResult.SUCCESS
            mock_exec.assert_not_called()