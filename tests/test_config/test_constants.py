"""常量存在性测试"""

from __future__ import annotations


class TestWSConstant:
    """WS_DRAIN_INTERVAL_SECONDS 常量测试"""

    def test_ws_drain_interval_constant_exists(self):
        """websocket_manager 中应存在 WS_DRAIN_INTERVAL_SECONDS 常量"""
        from app.services.websocket_manager import WS_DRAIN_INTERVAL_SECONDS

        assert WS_DRAIN_INTERVAL_SECONDS == 0.05

    def test_ws_drain_interval_reexport_from_engine(self):
        """engine 模块应向后兼容 re-export WS_DRAIN_INTERVAL_SECONDS"""
        from app.services.engine import WS_DRAIN_INTERVAL_SECONDS

        assert WS_DRAIN_INTERVAL_SECONDS == 0.05


class TestLoginConstant:
    """LOGIN_SUCCESS_SETTLE_SECONDS 常量测试"""

    def test_login_settle_seconds_constant_exists(self):
        """login 模块中应存在 LOGIN_SUCCESS_SETTLE_SECONDS 常量"""
        from app.services.login_handler import LOGIN_SUCCESS_SETTLE_SECONDS

        assert LOGIN_SUCCESS_SETTLE_SECONDS == 2
