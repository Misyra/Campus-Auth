"""NetworkMonitorCore 内部方法测试。"""

from __future__ import annotations

from unittest.mock import MagicMock

from app.schemas import RuntimeConfig
from app.services.monitor_service import NetworkMonitorCore


class TestProfileSwitchFlag:
    """测试自动切换方案的标志位逻辑。"""

    def test_check_profile_switch_sets_flag(self):
        """测试自动切换方案设置标志位"""

        core = NetworkMonitorCore(get_config=lambda: RuntimeConfig())
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

        core = NetworkMonitorCore(get_config=lambda: RuntimeConfig())
        mock_profile_service = MagicMock()
        mock_profile_service.load.return_value.auto_switch = True
        mock_profile_service.detect_matching_profile.return_value = "same_profile"
        core._profile_service = mock_profile_service
        core._last_profile_id = "same_profile"

        core._check_profile_switch()

        assert core._profile_switch_needed is False

    def test_consume_profile_switch_flag(self):
        """测试消费标志位"""

        core = NetworkMonitorCore(get_config=lambda: RuntimeConfig())
        core._profile_switch_needed = True

        assert core.consume_profile_switch_flag() is True
        assert core._profile_switch_needed is False
        assert core.consume_profile_switch_flag() is False


class TestGetterInjection:
    """getter 注入：config 通过 getter 实时获取，不持有副本。"""

    def test_config_via_getter(self):
        """config 应通过 getter 实时获取，不持有副本。"""
        config1 = RuntimeConfig()
        config2 = config1.model_copy(
            update={
                "monitor": config1.monitor.model_copy(
                    update={"check_interval_seconds": 99}
                )
            }
        )
        current = [config1]

        core = NetworkMonitorCore(
            get_config=lambda: current[0],
            logger=None,
        )
        assert core._get_monitor_interval() != 99  # 初始配置
        current[0] = config2
        assert core._get_monitor_interval() == 99  # getter 返回新配置

    def test_no_config_attribute(self):
        """不应持有 self.config 副本。"""
        core = NetworkMonitorCore(
            get_config=lambda: RuntimeConfig(),
            logger=None,
        )
        assert not hasattr(core, "config") or core.config is None

    def test_needs_bind_proxy_rebuild(self):
        """bind_interface_name 变化时应返回 True。"""
        from app.schemas import MonitorSettings

        config1 = RuntimeConfig()
        config2 = config1.model_copy(
            update={"monitor": MonitorSettings(bind_interface_name="eth0")}
        )
        current = [config1]

        core = NetworkMonitorCore(
            get_config=lambda: current[0],
            logger=None,
        )
        # 初始状态：无 bind_interface_name，不需要重建
        assert core._needs_bind_proxy_rebuild() is False

        # 改变 bind_interface_name
        current[0] = config2
        assert core._needs_bind_proxy_rebuild() is True
