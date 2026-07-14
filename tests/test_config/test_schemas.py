"""schemas 模型测试。"""

from __future__ import annotations

from app.schemas import MonitorSettings


class TestMonitorSettingsPostLoginDelay:
    """MonitorSettings.post_login_delay 字段测试。"""

    def test_default_value(self):
        """MonitorSettings.post_login_delay 默认值为 5。"""
        m = MonitorSettings()
        assert m.post_login_delay == 5

    def test_configurable(self):
        """MonitorSettings.post_login_delay 可配置。"""
        m = MonitorSettings(post_login_delay=10)
        assert m.post_login_delay == 10

    def test_zero_allowed(self):
        """MonitorSettings.post_login_delay 允许 0（跳过等待）。"""
        m = MonitorSettings(post_login_delay=0)
        assert m.post_login_delay == 0
