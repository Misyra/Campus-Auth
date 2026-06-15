#!/usr/bin/env python3
"""Task 21: main.py 五项修复的测试"""
import os
import signal
import threading
from unittest.mock import MagicMock, patch

import pytest


# ==================== 修复 1: _open_browser 逻辑简化 ====================


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
            # 确认日志内容包含关键词
            args, kwargs = mock_logger.debug.call_args
            assert "加载配置失败" in args[0]
            assert kwargs.get("exc_info") is True


# ==================== 修复 3: lambda 逻辑（on_exit） ====================


class TestLambdaLogic:
    """验证 SystemTray on_exit lambda 的正确性。"""

    def test_on_exit_lambda_has_correct_structure(self):
        """lambda 应当：SIGTERM 可用时用 SIGTERM，否则用 os._exit(0)。"""
        # 这是一个结构性测试，验证 lambda 源码不包含 cleanup_pid
        import inspect
        import main as main_mod

        source = inspect.getsource(main_mod)
        # 提取 on_exit=lambda 开始到 tray_icon.start() 结束的代码块
        on_exit_start = source.index("on_exit=lambda")
        on_exit_section = source[on_exit_start : source.index("tray_icon.start()", on_exit_start)]
        # 修复后不应在 on_exit lambda 中出现 cleanup_pid
        assert "cleanup_pid" not in on_exit_section, (
            "on_exit lambda 中不应包含 cleanup_pid 调用"
        )
        assert "SIGTERM" in on_exit_section
        assert "os._exit(0)" in on_exit_section


# ==================== 修复 4: ensure_playwright_ready 使用 logger ====================


class TestPlaywrightReadyCallback:
    """验证 ensure_playwright_ready 使用 logger 而非 print。"""

    def test_ensure_playwright_not_called_with_print(self):
        """ensure_playwright_ready 不应直接传入 print。"""
        import inspect
        import main as main_mod

        source = inspect.getsource(main_mod)
        # 查找 ensure_playwright_ready 调用行
        for line in source.split("\n"):
            if "ensure_playwright_ready" in line and "import" not in line:
                assert "print" not in line, (
                    "ensure_playwright_ready 不应直接使用 print，应使用 logger"
                )


# ==================== 修复 5: 重复 import threading ====================


class TestDuplicateImport:
    """验证 _setup_exception_hooks 中不重复 import threading。"""

    def test_no_redundant_threading_import(self):
        """_setup_exception_hooks 中不应重复 import threading（顶部已导入）。"""
        import inspect
        import main as main_mod

        source = inspect.getsource(main_mod._setup_exception_hooks)
        # 函数体内不应有 import threading
        assert "import threading" not in source, (
            "_setup_exception_hooks 中不应重复 import threading，顶部已导入"
        )
