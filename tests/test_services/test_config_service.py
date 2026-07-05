"""测试 config_service.py 中的配置保存逻辑。"""

from __future__ import annotations

import copy
from unittest.mock import MagicMock

from app.schemas import (
    BrowserSettings,
    GlobalConfig,
    LoginCredentials,
    Profile,
    ProfilesData,
    RuntimeConfig,
)
from app.services.profile_service import (
    SaveResult,
    _rollback_config,
)
from app.services.config_builder import build_runtime_config


class TestConfigBuilderBuild:
    """build_runtime_config 测试。"""

    def test_build_from_config_and_profile(self):
        config = RuntimeConfig()
        profile = Profile(
            username="student",
            password="ENC:abc",
            auth_url="http://10.0.0.1/login",
            carrier="移动",
        )
        result = build_runtime_config(config, profile)

        assert result.credentials.username == "student"
        assert result.credentials.password == "ENC:abc"
        assert result.credentials.auth_url == "http://10.0.0.1/login"
        assert result.credentials.isp == "移动"

    def test_carrier_custom_mapping(self):
        config = RuntimeConfig()
        profile = Profile(carrier="自定义", carrier_custom="myisp")
        result = build_runtime_config(config, profile)
        assert result.credentials.isp == "myisp"
        assert result.credentials.carrier_custom == "myisp"

    def test_carrier_none_mapping(self):
        config = RuntimeConfig()
        profile = Profile(carrier="无")
        result = build_runtime_config(config, profile)
        assert result.credentials.isp == ""

    def test_browser_config_preserved(self):
        config = RuntimeConfig(browser=BrowserSettings(headless=False, timeout=15))
        profile = Profile(username="u", password="p", auth_url="http://x")
        result = build_runtime_config(config, profile)

        assert result.browser.headless is False
        assert result.browser.timeout == 15

    def test_masked_password_cleared(self):
        """以 • 开头的密码被清空（掩码值）。"""
        config = RuntimeConfig()
        profile = Profile(username="u", password="••••••••", auth_url="http://x")
        result = build_runtime_config(config, profile)
        assert result.credentials.password == ""

    def test_active_task_from_profile(self):
        config = RuntimeConfig()
        profile = Profile(active_task="  my_task  ")
        result = build_runtime_config(config, profile)
        assert result.active_task == "my_task"

    def test_credentials_replaced_not_merged(self):
        """ConfigBuilder.build 替换 credentials，不与 config 中的合并。"""
        config = RuntimeConfig(
            credentials=LoginCredentials(username="old", password="old_pwd")
        )
        profile = Profile(username="new", password="new_pwd", auth_url="http://y")
        result = build_runtime_config(config, profile)
        assert result.credentials.username == "new"
        assert result.credentials.password == "new_pwd"


class TestRollbackConfig:
    """测试 _rollback_config 函数。"""

    def test_rollback_restores_fields(self):
        data = ProfilesData(
            global_config=GlobalConfig(browser=BrowserSettings(timeout=60)),
        )
        backup = ProfilesData(
            global_config=GlobalConfig(browser=BrowserSettings(timeout=30)),
        )

        result = _rollback_config(data, backup)
        assert result.global_config.browser.timeout == 30

    def test_rollback_all_fields(self):
        """回滚应恢复 ProfilesData 的所有字段。"""
        data = ProfilesData(auto_switch=True, active_profile="custom")
        backup = ProfilesData(auto_switch=False, active_profile="default")

        result = _rollback_config(data, backup)
        assert result.auto_switch is False
        assert result.active_profile == "default"
