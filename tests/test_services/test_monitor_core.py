"""NetworkMonitorCore 内部方法测试。"""

from __future__ import annotations

from unittest.mock import MagicMock

from app.schemas import RuntimeConfig


class TestProfileSwitchFlag:
    """测试自动切换方案的标志位逻辑。"""

    def test_check_profile_switch_sets_flag(self):
        """测试自动切换方案设置标志位"""
        from app.services.monitor_service import NetworkMonitorCore

        core = NetworkMonitorCore(config=RuntimeConfig())
        mock_profile_service = MagicMock()
        mock_profile_service.load.return_value.auto_switch = True
        mock_profile_service.detect_matching_profile.return_value = "new_profile"
        mock_profile_service.set_active_profile.return_value = (True, "ok")
        core._profile_service = mock_profile_service
        core._last_profile_id = "old_profile"

        core._check_profile_switch()

        assert core._profile_switch_needed is True
        assert core._last_profile_id == "new_profile"

    def test_check_profile_switch_no_change(self):
        """测试方案未变化时不设置标志位"""
        from app.services.monitor_service import NetworkMonitorCore

        core = NetworkMonitorCore(config=RuntimeConfig())
        mock_profile_service = MagicMock()
        mock_profile_service.load.return_value.auto_switch = True
        mock_profile_service.detect_matching_profile.return_value = "same_profile"
        core._profile_service = mock_profile_service
        core._last_profile_id = "same_profile"

        core._check_profile_switch()

        assert core._profile_switch_needed is False

    def test_consume_profile_switch_flag(self):
        """测试消费标志位"""
        from app.services.monitor_service import NetworkMonitorCore

        core = NetworkMonitorCore(config=RuntimeConfig())
        core._profile_switch_needed = True

        assert core.consume_profile_switch_flag() is True
        assert core._profile_switch_needed is False
        assert core.consume_profile_switch_flag() is False
