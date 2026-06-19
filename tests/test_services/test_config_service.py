"""测试 config_service.py 中的配置保存逻辑。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.schemas import (
    AuthProfile,
    MonitorConfigPayload,
    ProfilesData,
    SystemSettings,
)
from app.services.config_service import (
    SaveResult,
    _update_global_settings,
    save_and_apply,
    save_config_combined,
)


class TestUpdateSystemSettings:
    """测试 _update_global_settings 函数"""

    def test_updates_global_settings_fields(self):
        """测试更新全局设置字段"""
        global_settings = SystemSettings()
        payload = MonitorConfigPayload(
            backend_log_level="DEBUG",
            frontend_log_level="INFO",
            access_log=True,
            log_retention_days=14,
            minimize_to_tray=False,
            auto_open_browser=True,
            startup_action="monitor",
            autostart_lightweight=False,
            proxy="http://proxy:8080",
            block_proxy=False,
            app_port=8080,
            shell_path="/bin/bash",
            max_retries=5,
            retry_interval=10,
        )

        _update_global_settings(global_settings, payload)

        assert global_settings.backend_log_level == "DEBUG"
        assert global_settings.frontend_log_level == "INFO"
        assert global_settings.access_log is True
        assert global_settings.log_retention_days == 14
        assert global_settings.minimize_to_tray is False
        assert global_settings.auto_open_browser is True
        assert global_settings.startup_action == "monitor"
        assert global_settings.autostart_lightweight is False
        assert global_settings.proxy == "http://proxy:8080"
        assert global_settings.block_proxy is False
        assert global_settings.app_port == 8080
        assert global_settings.shell_path == "/bin/bash"
        assert global_settings.max_retries == 5
        assert global_settings.retry_interval == 10

    def test_normalizes_log_levels(self):
        """测试日志级别归一化"""
        global_settings = SystemSettings()
        payload = MonitorConfigPayload(
            backend_log_level="  debug  ",
            frontend_log_level="  warning  ",
        )

        _update_global_settings(global_settings, payload)

        assert global_settings.backend_log_level == "DEBUG"
        assert global_settings.frontend_log_level == "WARNING"

    def test_strips_proxy_whitespace(self):
        """测试代理地址去除空白"""
        global_settings = SystemSettings()
        payload = MonitorConfigPayload(proxy="  http://proxy:8080  ")

        _update_global_settings(global_settings, payload)

        assert global_settings.proxy == "http://proxy:8080"

    def test_does_not_update_credentials(self):
        """测试不更新凭证字段（凭证应保存到 profile）"""
        global_settings = SystemSettings()
        payload = MonitorConfigPayload(
            username="testuser",
            password="testpass",
            auth_url="http://example.com",
            carrier="移动",
        )

        _update_global_settings(global_settings, payload)

        # SystemSettings 不应包含纯凭证字段（仅在 _SystemFieldsMixin 中）
        assert not hasattr(global_settings, "username")
        assert not hasattr(global_settings, "password")
        # auth_url/carrier/carrier_custom 现在在 _MonitorFieldsMixin 中，
        # 属于 SystemSettings 与 MonitorConfigPayload 的共享字段，会被同步更新
        assert global_settings.auth_url == "http://example.com"
        assert global_settings.carrier == "移动"


class TestSaveConfigCombined:
    """测试 save_config_combined 函数"""

    def test_saves_to_active_profile(self):
        """测试保存到活动 profile"""
        mock_profile_service = MagicMock()
        payload = MonitorConfigPayload(
            username="testuser",
            password="testpass",
            auth_url="http://example.com",
            carrier="移动",
            active_task="task1",
            check_interval_seconds=600,
            headless=False,
        )

        # 模拟 profile_service.update 的行为
        def mock_update(func):
            data = ProfilesData()
            data.active_profile = "default"
            func(data)
            return data

        mock_profile_service.update.side_effect = mock_update

        save_config_combined(payload, mock_profile_service)

        # 验证 update 被调用
        mock_profile_service.update.assert_called_once()

    def test_creates_active_profile_if_missing(self):
        """测试活动 profile 不存在时自动创建"""
        mock_profile_service = MagicMock()
        payload = MonitorConfigPayload(
            username="testuser",
            password="testpass",
        )

        captured_data = None

        def mock_update(func):
            nonlocal captured_data
            data = ProfilesData()
            data.active_profile = "custom_profile"
            # 确保 custom_profile 不存在
            assert "custom_profile" not in data.profiles
            func(data)
            captured_data = data

        mock_profile_service.update.side_effect = mock_update

        save_config_combined(payload, mock_profile_service)

        # 验证 profile 被创建
        assert captured_data is not None
        assert "custom_profile" in captured_data.profiles
        assert captured_data.profiles["custom_profile"].username == "testuser"

    def test_updates_global_settings(self):
        """测试更新全局设置"""
        mock_profile_service = MagicMock()
        payload = MonitorConfigPayload(
            backend_log_level="DEBUG",
            proxy="http://proxy:8080",
            app_port=8080,
        )

        captured_data = None

        def mock_update(func):
            nonlocal captured_data
            data = ProfilesData()
            func(data)
            captured_data = data

        mock_profile_service.update.side_effect = mock_update

        save_config_combined(payload, mock_profile_service)

        # 验证全局设置被更新
        assert captured_data is not None
        assert captured_data.global_settings.backend_log_level == "DEBUG"
        assert captured_data.global_settings.proxy == "http://proxy:8080"
        assert captured_data.global_settings.app_port == 8080

    def test_saves_credentials_to_profile(self):
        """测试凭证保存到 profile"""
        mock_profile_service = MagicMock()
        payload = MonitorConfigPayload(
            username="testuser",
            password="testpass",
            auth_url="http://example.com",
            carrier="移动",
            carrier_custom="custom_isp",
            active_task="task1",
        )

        captured_data = None

        def mock_update(func):
            nonlocal captured_data
            data = ProfilesData()
            func(data)
            captured_data = data

        mock_profile_service.update.side_effect = mock_update

        save_config_combined(payload, mock_profile_service)

        # 验证凭证保存到 profile
        assert captured_data is not None
        profile = captured_data.profiles["default"]
        assert profile.username == "testuser"
        assert profile.auth_url == "http://example.com"
        assert profile.carrier == "移动"
        assert profile.carrier_custom == "custom_isp"
        assert profile.active_task == "task1"

    def test_updates_monitor_config(self):
        """测试更新监控配置 — 监控配置保存到 global_settings"""
        mock_profile_service = MagicMock()
        payload = MonitorConfigPayload(
            check_interval_seconds=600,
            pause_enabled=False,
            pause_start_hour=22,
            pause_end_hour=8,
            network_targets="8.8.8.8,114.114.114.114",
            http_targets="http://example.com",
            enable_tcp_check=True,
            enable_http_check=True,
            enable_local_check=False,
            check_auth_url=True,
            auth_url_targets="example.com:80",
            url_check_urls="http://example.com|Success",
            network_check_timeout=5,
        )

        captured_data = None

        def mock_update(func):
            nonlocal captured_data
            data = ProfilesData()
            func(data)
            captured_data = data

        mock_profile_service.update.side_effect = mock_update

        save_config_combined(payload, mock_profile_service)

        # 验证监控配置被更新到 global_settings
        assert captured_data is not None
        gs = captured_data.global_settings
        assert gs.check_interval_seconds == 600
        assert gs.pause_enabled is False
        assert gs.pause_start_hour == 22
        assert gs.pause_end_hour == 8
        assert gs.network_targets == "8.8.8.8,114.114.114.114"
        assert gs.http_targets == "http://example.com"
        assert gs.enable_tcp_check is True
        assert gs.enable_http_check is True
        assert gs.enable_local_check is False
        assert gs.check_auth_url is True
        assert gs.auth_url_targets == "example.com:80"
        assert gs.url_check_urls == "http://example.com|Success"
        assert gs.network_check_timeout == 5

    def test_updates_browser_config(self):
        """测试浏览器配置现在保存在 global_settings 中"""
        mock_profile_service = MagicMock()
        payload = MonitorConfigPayload()

        captured_data = None

        def mock_update(func):
            nonlocal captured_data
            data = ProfilesData()
            # 浏览器配置现在在 global_settings 中，不在 MonitorConfigPayload 中
            # 所以 save_config_combined 不会更新浏览器配置
            func(data)
            captured_data = data

        mock_profile_service.update.side_effect = mock_update

        save_config_combined(payload, mock_profile_service)

        # 验证 global_settings 中的浏览器配置保持默认值
        assert captured_data is not None
        global_settings = captured_data.global_settings
        assert global_settings.headless is True
        assert global_settings.browser_timeout == 8
        assert global_settings.browser_navigation_timeout == 15
        assert global_settings.login_timeout == 90
        assert global_settings.browser_locale == "zh-CN"
        assert global_settings.browser_timezone == "Asia/Shanghai"
        assert global_settings.browser_viewport_width == 1280
        assert global_settings.browser_viewport_height == 720

    def test_updates_custom_variables(self):
        """测试更新自定义变量"""
        mock_profile_service = MagicMock()
        custom_vars = {"KEY1": "value1", "KEY2": "value2"}
        payload = MonitorConfigPayload(custom_variables=custom_vars)

        captured_data = None

        def mock_update(func):
            nonlocal captured_data
            data = ProfilesData()
            func(data)
            captured_data = data

        mock_profile_service.update.side_effect = mock_update

        save_config_combined(payload, mock_profile_service)

        # 验证自定义变量被更新到 global_settings
        assert captured_data is not None
        assert captured_data.global_settings.custom_variables == custom_vars

    @patch("app.utils.crypto.save_password_field")
    def test_encrypts_password(self, mock_save_password):
        """测试密码加密"""
        mock_save_password.return_value = "encrypted_password"
        mock_profile_service = MagicMock()
        payload = MonitorConfigPayload(
            username="testuser",
            password="testpass",
        )

        captured_data = None

        def mock_update(func):
            nonlocal captured_data
            data = ProfilesData()
            func(data)
            captured_data = data

        mock_profile_service.update.side_effect = mock_update

        save_config_combined(payload, mock_profile_service)

        # 验证密码被加密
        mock_save_password.assert_called_once_with("testpass", "")
        assert captured_data is not None
        assert captured_data.profiles["default"].password == "encrypted_password"

    @patch("app.utils.crypto.save_password_field")
    def test_preserves_existing_password_if_not_provided(self, mock_save_password):
        """测试未提供密码时保留现有密码"""
        mock_save_password.return_value = "existing_encrypted"
        mock_profile_service = MagicMock()
        payload = MonitorConfigPayload(
            username="testuser",
            password="••••••••",  # 前端掩码
        )

        captured_data = None

        def mock_update(func):
            nonlocal captured_data
            data = ProfilesData()
            data.profiles["default"].password = "existing_encrypted"
            func(data)
            captured_data = data

        mock_profile_service.update.side_effect = mock_update

        save_config_combined(payload, mock_profile_service)

        # 验证密码被保留（save_password_field 处理掩码值后返回原密码）
        assert captured_data is not None
        assert captured_data.profiles["default"].password == "existing_encrypted"
        mock_save_password.assert_called_once_with("••••••••", "existing_encrypted")

    def test_strips_whitespace_from_credentials(self):
        """测试凭证去除空白"""
        mock_profile_service = MagicMock()
        payload = MonitorConfigPayload(
            username="  testuser  ",
            password="testpass",
            auth_url="  http://example.com  ",
            carrier="  移动  ",
            carrier_custom="  custom  ",
            active_task="  task1  ",
        )

        captured_data = None

        def mock_update(func):
            nonlocal captured_data
            data = ProfilesData()
            func(data)
            captured_data = data

        mock_profile_service.update.side_effect = mock_update

        save_config_combined(payload, mock_profile_service)

        # 验证空白被去除
        assert captured_data is not None
        profile = captured_data.profiles["default"]
        assert profile.username == "testuser"
        assert profile.auth_url == "http://example.com"
        assert profile.carrier == "移动"
        assert profile.carrier_custom == "custom"
        assert profile.active_task == "task1"


class TestSaveAndApply:
    """测试 save_and_apply 事务函数。"""

    @patch("app.services.config_service.save_config_combined")
    def test_success(self, mock_save):
        mock_ps = MagicMock()
        mock_ps.load.return_value = ProfilesData()
        mock_reload = MagicMock(return_value=(True, "ok"))

        result = save_and_apply(
            MonitorConfigPayload(), mock_ps, mock_reload
        )
        assert result.success is True
        assert result.message == "配置保存成功"
        mock_save.assert_called_once()
        mock_reload.assert_called_once()

    @patch("app.services.config_service.save_config_combined")
    def test_reload_failure_triggers_rollback(self, mock_save):
        backup = ProfilesData()
        mock_ps = MagicMock()
        mock_ps.load.return_value = backup
        # 第一次 reload 失败，第二次 reload（回滚后）成功
        mock_reload = MagicMock(side_effect=[(False, "重载失败"), (True, "ok")])

        result = save_and_apply(
            MonitorConfigPayload(), mock_ps, mock_reload
        )
        assert result.success is False
        assert "配置重载失败" in result.message
        assert "已回滚" in result.message
        # 验证回滚调用了 update
        mock_ps.update.assert_called_once()

    @patch("app.services.config_service.save_config_combined")
    def test_reload_failure_and_rollback_reload_also_fails(self, mock_save):
        """回滚后重载也失败时，message 应同时包含两次失败信息。"""
        mock_ps = MagicMock()
        mock_ps.load.return_value = ProfilesData()
        # 第一次 reload 失败，回滚后第二次 reload 也失败
        mock_reload = MagicMock(
            side_effect=[(False, "超时"), (False, "又超时")]
        )

        result = save_and_apply(
            MonitorConfigPayload(), mock_ps, mock_reload
        )
        assert result.success is False
        assert "超时" in result.message
        assert "又超时" in result.message
        # 验证回滚调用了 update
        mock_ps.update.assert_called_once()
        # 验证 reload_fn 被调用了两次（第一次 + 回滚后）
        assert mock_reload.call_count == 2

    @patch("app.services.config_service.save_config_combined")
    def test_reload_failure_and_rollback_also_fails(self, mock_save):
        mock_ps = MagicMock()
        mock_ps.load.return_value = ProfilesData()
        mock_ps.update.side_effect = RuntimeError("磁盘故障")
        mock_reload = MagicMock(return_value=(False, "重载失败"))

        result = save_and_apply(
            MonitorConfigPayload(), mock_ps, mock_reload
        )
        assert result.success is False
        # 回滚异常不抛出，只记录日志
