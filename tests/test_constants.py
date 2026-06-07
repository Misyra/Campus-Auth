"""常量存在性测试"""
from __future__ import annotations



class TestWSConstant:
    """WS_DRAIN_INTERVAL_SECONDS 常量测试"""

    def test_ws_drain_interval_constant_exists(self):
        """monitor_service 中应存在 WS_DRAIN_INTERVAL_SECONDS 常量"""
        from app.services.monitor import WS_DRAIN_INTERVAL_SECONDS

        assert WS_DRAIN_INTERVAL_SECONDS == 0.05


class TestLoginConstant:
    """LOGIN_SUCCESS_SETTLE_SECONDS 常量测试"""

    def test_login_settle_seconds_constant_exists(self):
        """login 模块中应存在 LOGIN_SUCCESS_SETTLE_SECONDS 常量"""
        from app.utils.login import LOGIN_SUCCESS_SETTLE_SECONDS

        assert LOGIN_SUCCESS_SETTLE_SECONDS == 2
