"""测试 config_service.py 中的配置保存逻辑。"""

from __future__ import annotations

import copy
from unittest.mock import MagicMock

from app.schemas import (
    BrowserSettings,
    LoginCredentials,
    Profile,
    ProfilesData,
    RuntimeConfig,
)
from app.services.config_service import (
    SaveResult,
    _rollback_config,
    save_and_apply,
)
from app.services.config_builder import ConfigBuilder


class TestConfigBuilderBuild:
    """ConfigBuilder.build 测试（原 build_runtime_config 测试）。"""

    def test_build_from_config_and_profile(self):
        config = RuntimeConfig()
        profile = Profile(
            username="student",
            password="ENC:abc",
            auth_url="http://10.0.0.1/login",
            carrier="移动",
        )
        result = ConfigBuilder.build(config, profile)

        assert result.credentials.username == "student"
        assert result.credentials.password == "ENC:abc"
        assert result.credentials.auth_url == "http://10.0.0.1/login"
        assert result.credentials.isp == "移动"

    def test_carrier_custom_mapping(self):
        config = RuntimeConfig()
        profile = Profile(carrier="自定义", carrier_custom="myisp")
        result = ConfigBuilder.build(config, profile)
        assert result.credentials.isp == "myisp"
        assert result.credentials.carrier_custom == "myisp"

    def test_carrier_none_mapping(self):
        config = RuntimeConfig()
        profile = Profile(carrier="无")
        result = ConfigBuilder.build(config, profile)
        assert result.credentials.isp == ""

    def test_browser_config_preserved(self):
        config = RuntimeConfig(browser=BrowserSettings(headless=False, timeout=15))
        profile = Profile(username="u", password="p", auth_url="http://x")
        result = ConfigBuilder.build(config, profile)

        assert result.browser.headless is False
        assert result.browser.timeout == 15

    def test_masked_password_cleared(self):
        """以 • 开头的密码被清空（掩码值）。"""
        config = RuntimeConfig()
        profile = Profile(username="u", password="••••••••", auth_url="http://x")
        result = ConfigBuilder.build(config, profile)
        assert result.credentials.password == ""

    def test_active_task_from_profile(self):
        config = RuntimeConfig()
        profile = Profile(active_task="  my_task  ")
        result = ConfigBuilder.build(config, profile)
        assert result.active_task == "my_task"

    def test_credentials_replaced_not_merged(self):
        """ConfigBuilder.build 替换 credentials，不与 config 中的合并。"""
        config = RuntimeConfig(
            credentials=LoginCredentials(username="old", password="old_pwd")
        )
        profile = Profile(username="new", password="new_pwd", auth_url="http://y")
        result = ConfigBuilder.build(config, profile)
        assert result.credentials.username == "new"
        assert result.credentials.password == "new_pwd"


class TestSaveAndApply:
    """测试 save_and_apply 事务函数。"""

    def test_success(self):
        mock_ps = MagicMock()
        mock_ps.load.return_value = ProfilesData()
        mock_reload = MagicMock(return_value=(True, "ok"))

        result = save_and_apply(
            RuntimeConfig(), mock_ps, mock_reload
        )
        assert result.success is True
        assert result.message == "配置保存成功"
        mock_ps.update.assert_called_once()
        mock_reload.assert_called_once()

    def test_save_failure(self):
        mock_ps = MagicMock()
        mock_ps.load.return_value = ProfilesData()
        mock_ps.update.side_effect = OSError("磁盘满")
        mock_reload = MagicMock(return_value=(True, "ok"))

        result = save_and_apply(
            RuntimeConfig(), mock_ps, mock_reload
        )
        assert result.success is False
        assert "保存失败" in result.message
        mock_reload.assert_not_called()

    def test_reload_failure_triggers_rollback(self):
        backup = ProfilesData()
        mock_ps = MagicMock()
        mock_ps.load.return_value = backup
        # 第一次 reload 失败，第二次 reload（回滚后）成功
        mock_reload = MagicMock(side_effect=[(False, "重载失败"), (True, "ok")])

        result = save_and_apply(
            RuntimeConfig(), mock_ps, mock_reload
        )
        assert result.success is False
        assert "配置重载失败" in result.message
        assert "已回滚" in result.message
        # 验证回滚调用了 update（第一次 save + 第二次 rollback）
        assert mock_ps.update.call_count == 2

    def test_reload_failure_and_rollback_reload_also_fails(self):
        """回滚后重载也失败时，message 应同时包含两次失败信息。"""
        mock_ps = MagicMock()
        mock_ps.load.return_value = ProfilesData()
        # 第一次 reload 失败，回滚后第二次 reload 也失败
        mock_reload = MagicMock(
            side_effect=[(False, "超时"), (False, "又超时")]
        )

        result = save_and_apply(
            RuntimeConfig(), mock_ps, mock_reload
        )
        assert result.success is False
        assert "超时" in result.message
        assert "又超时" in result.message
        # 验证回滚调用了 update（第一次 save + 第二次 rollback）
        assert mock_ps.update.call_count == 2
        # 验证 reload_fn 被调用了两次（第一次 + 回滚后）
        assert mock_reload.call_count == 2

    def test_reload_failure_and_rollback_also_fails(self):
        """回滚过程中抛异常，不抛出，只记录日志。"""
        mock_ps = MagicMock()
        mock_ps.load.return_value = ProfilesData()
        # 第一次 update 成功，第二次 update（rollback）抛异常
        mock_ps.update.side_effect = [None, RuntimeError("磁盘故障")]
        mock_reload = MagicMock(return_value=(False, "重载失败"))

        result = save_and_apply(
            RuntimeConfig(), mock_ps, mock_reload
        )
        assert result.success is False
        assert "回滚异常" in result.message


class TestRollbackConfig:
    """测试 _rollback_config 函数。"""

    def test_rollback_restores_fields(self):
        data = ProfilesData()
        data.global_config = RuntimeConfig(active_task="new")
        backup = ProfilesData()
        backup.global_config = RuntimeConfig(active_task="old")

        _rollback_config(data, backup)
        assert data.global_config.active_task == "old"

    def test_rollback_all_fields(self):
        """回滚应恢复 ProfilesData 的所有字段。"""
        data = ProfilesData()
        data.auto_switch = True
        data.active_profile = "custom"
        backup = ProfilesData()
        backup.auto_switch = False
        backup.active_profile = "default"

        _rollback_config(data, backup)
        assert data.auto_switch is False
        assert data.active_profile == "default"
