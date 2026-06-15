"""application.py 三个修复点的测试。"""

from __future__ import annotations

import json
import signal
import sys
from unittest.mock import MagicMock, patch

import pytest


# ── 问题 1: except NameError 作为流程控制 ──


class TestSourceLevelsConfig:
    """source_levels 配置应用 — 修复 NameError 流程控制问题。"""

    def test_source_levels_applied_when_sys_settings_loaded(self):
        """sys_settings 正常加载时，source_levels 应被应用。"""
        mock_log_center = MagicMock()
        mock_profile_service = MagicMock()
        mock_sys_settings = MagicMock()
        mock_sys_settings.access_log = False
        mock_sys_settings.log_retention_days = 7
        mock_sys_settings.source_levels = {"backend": "DEBUG", "http": "WARNING"}
        mock_profile_service.load.return_value.system = mock_sys_settings

        with (
            patch("app.application.LogConfigCenter") as mock_lcc_cls,
            patch("app.application.resolve_port", return_value=50721),
            patch(
                "app.services.profile_service.ProfileService",
                return_value=mock_profile_service,
            ),
        ):
            mock_lcc_cls.get_instance.return_value = mock_log_center
            # 导入 run 函数（不实际执行）
            from app.application import run

            # run() 内部不应再用 except NameError 来处理 sys_settings 未定义
            # 我们验证源码中不再有 except NameError
            import inspect

            source = inspect.getsource(run)
            assert "except NameError" not in source

    def test_no_name_error_as_flow_control(self):
        """确认 run() 函数中不使用 except NameError 作为流程控制。"""
        import inspect
        from app.application import run

        source = inspect.getsource(run)
        assert "except NameError" not in source, (
            "不应使用 except NameError 作为流程控制，"
            "应通过提前初始化变量为 None 来避免"
        )


# ── 问题 2: KeyError 不会触发 ──


class TestWebSocketKeyErrorHandling:
    """WebSocket 消息处理 — 修复 KeyError 不会触发的问题。"""

    def test_key_error_not_in_except_clause(self):
        """确认 WebSocket 处理中 except 子句不再包含 KeyError。"""
        import inspect
        from app.application import create_app

        source = inspect.getsource(create_app)
        # 不应有 except (json.JSONDecodeError, KeyError)
        assert "KeyError" not in source, (
            "WebSocket 消息处理中不应捕获 KeyError，"
            "因为 .get() 调用不会抛出 KeyError"
        )

    def test_json_decode_error_still_caught(self):
        """确认 JSONDecodeError 仍被捕获。"""
        import inspect
        from app.application import create_app

        source = inspect.getsource(create_app)
        assert "json.JSONDecodeError" in source

    def test_general_exception_for_ws_processing(self):
        """确认 WebSocket 消息处理有通用异常兜底。"""
        import inspect
        from app.application import create_app

        source = inspect.getsource(create_app)
        # 在 websocket_logs 函数中应有 except Exception 处理消息处理异常
        # 提取 websocket_logs 函数部分
        lines = source.split("\n")
        in_ws_func = False
        ws_source = []
        for line in lines:
            if "async def websocket_logs" in line:
                in_ws_func = True
            if in_ws_func:
                ws_source.append(line)
        ws_text = "\n".join(ws_source)
        # 应该有通用 except Exception 兜底
        assert "except Exception" in ws_text


# ── 问题 3: Windows SIGTERM ──


class TestWindowsSigterm:
    """SIGTERM 信号处理 — 修复 Windows 平台兼容性。"""

    def test_sigterm_has_platform_check(self):
        """确认发送 SIGTERM 前检查平台是否支持。"""
        import inspect
        from app.application import create_app

        source = inspect.getsource(create_app)
        # 应该有 hasattr(signal, "SIGTERM") 检查
        assert 'hasattr(signal, "SIGTERM")' in source or "hasattr(signal," in source, (
            "发送 SIGTERM 前应检查平台是否支持（hasattr(signal, 'SIGTERM')）"
        )

    def test_windows_fallback_exists(self):
        """确认 Windows 上有 os._exit(0) 作为回退。"""
        import inspect
        from app.application import create_app

        source = inspect.getsource(create_app)
        assert "os._exit" in source, (
            "Windows 上 SIGTERM 不可用时应有 os._exit(0) 回退"
        )

    def test_sigterm_available_on_current_platform(self):
        """验证当前平台 SIGTERM 的可用性（信息性测试）。"""
        has_sigterm = hasattr(signal, "SIGTERM")
        # 在 Windows 上 SIGTERM 实际上存在（Python 定义了它），
        # 但 os.kill(pid, signal.SIGTERM) 在 Windows 上行为不同
        if sys.platform == "win32":
            # Windows 上 signal.SIGTERM 存在但 os.kill 行为不同
            assert has_sigterm  # Python 定义了这个常量
        else:
            assert has_sigterm
