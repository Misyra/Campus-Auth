"""RuntimeConfigProvider 测试"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.schemas import MonitorConfigPayload, ProfilesData, SystemSettings
from app.services.config_provider import RuntimeConfigProvider


@pytest.fixture
def profile_service(tmp_path: Path) -> MagicMock:
    """创建 mock ProfileService。"""
    svc = MagicMock()
    svc.load.return_value = ProfilesData(system=SystemSettings())
    return svc


@pytest.fixture
def provider(profile_service: MagicMock) -> RuntimeConfigProvider:
    """创建 RuntimeConfigProvider 实例。"""
    return RuntimeConfigProvider(profile_service)


class TestGetRuntimeConfigReturnsCopy:
    """get_runtime_config 返回副本，修改不影响原始。"""

    def test_modify_result_does_not_affect_cache(
        self, provider: RuntimeConfigProvider
    ) -> None:
        # 首先加载配置
        with (
            patch("app.services.config_provider.load_ui_config") as mock_ui,
            patch("app.services.config_provider.load_runtime_config") as mock_rt,
            patch("app.services.config_provider.build_runtime_config") as mock_build,
        ):
            mock_ui.return_value = MonitorConfigPayload()
            mock_rt.return_value = (MonitorConfigPayload(), False)
            mock_build.return_value = {"key": "original"}
            provider.reload()

        result1 = provider.get_runtime_config()
        result1["key"] = "modified"

        result2 = provider.get_runtime_config()
        assert result2["key"] == "original"

    def test_two_calls_return_different_objects(
        self, provider: RuntimeConfigProvider
    ) -> None:
        with (
            patch("app.services.config_provider.load_ui_config") as mock_ui,
            patch("app.services.config_provider.load_runtime_config") as mock_rt,
            patch("app.services.config_provider.build_runtime_config") as mock_build,
        ):
            mock_ui.return_value = MonitorConfigPayload()
            mock_rt.return_value = (MonitorConfigPayload(), False)
            mock_build.return_value = {"nested": {"inner": 1}}
            provider.reload()

        result1 = provider.get_runtime_config()
        result2 = provider.get_runtime_config()
        assert result1 is not result2
        assert result1["nested"] is not result2["nested"]


class TestGetUiConfigReturnsCopy:
    """get_ui_config 返回副本。"""

    def test_modify_result_does_not_affect_cache(
        self, provider: RuntimeConfigProvider
    ) -> None:
        with (
            patch("app.services.config_provider.load_ui_config") as mock_ui,
            patch("app.services.config_provider.load_runtime_config") as mock_rt,
            patch("app.services.config_provider.build_runtime_config"),
        ):
            mock_ui.return_value = MonitorConfigPayload(username="test_user")
            mock_rt.return_value = (MonitorConfigPayload(), False)
            provider.reload()

        result1 = provider.get_ui_config()
        # model_copy(deep=True) 返回的也是新对象
        assert result1.username == "test_user"

        result2 = provider.get_ui_config()
        assert result2.username == "test_user"
        assert result1 is not result2

    def test_returns_monitor_config_payload(
        self, provider: RuntimeConfigProvider
    ) -> None:
        result = provider.get_ui_config()
        assert isinstance(result, MonitorConfigPayload)


class TestReload:
    """reload 正常工作。"""

    def test_reload_calls_build_runtime_config(
        self, provider: RuntimeConfigProvider, profile_service: MagicMock
    ) -> None:
        with (
            patch("app.services.config_provider.load_ui_config") as mock_ui,
            patch("app.services.config_provider.load_runtime_config") as mock_rt,
            patch("app.services.config_provider.build_runtime_config") as mock_build,
        ):
            mock_ui.return_value = MonitorConfigPayload()
            mock_payload = MonitorConfigPayload(username="u")
            mock_rt.return_value = (mock_payload, False)
            mock_build.return_value = {"username": "u"}
            provider.reload()

        mock_build.assert_called_once_with(mock_payload, profile_service.load().system)

    def test_reload_updates_runtime_config(
        self, provider: RuntimeConfigProvider
    ) -> None:
        with (
            patch("app.services.config_provider.load_ui_config"),
            patch("app.services.config_provider.load_runtime_config") as mock_rt,
            patch("app.services.config_provider.build_runtime_config") as mock_build,
        ):
            mock_rt.return_value = (MonitorConfigPayload(), False)
            mock_build.return_value = {"version": 1}
            provider.reload()

        assert provider.get_runtime_config()["version"] == 1

        with (
            patch("app.services.config_provider.load_ui_config"),
            patch("app.services.config_provider.load_runtime_config") as mock_rt,
            patch("app.services.config_provider.build_runtime_config") as mock_build,
        ):
            mock_rt.return_value = (MonitorConfigPayload(), False)
            mock_build.return_value = {"version": 2}
            provider.reload()

        assert provider.get_runtime_config()["version"] == 2

    def test_reload_updates_ui_config(self, provider: RuntimeConfigProvider) -> None:
        with (
            patch("app.services.config_provider.load_ui_config") as mock_ui,
            patch("app.services.config_provider.load_runtime_config") as mock_rt,
            patch("app.services.config_provider.build_runtime_config"),
        ):
            mock_ui.return_value = MonitorConfigPayload(username="first")
            mock_rt.return_value = (MonitorConfigPayload(), False)
            provider.reload()

        assert provider.get_ui_config().username == "first"

        with (
            patch("app.services.config_provider.load_ui_config") as mock_ui,
            patch("app.services.config_provider.load_runtime_config") as mock_rt,
            patch("app.services.config_provider.build_runtime_config"),
        ):
            mock_ui.return_value = MonitorConfigPayload(username="second")
            mock_rt.return_value = (MonitorConfigPayload(), False)
            provider.reload()

        assert provider.get_ui_config().username == "second"

    def test_reload_logs_warning_on_decrypt_error(
        self, provider: RuntimeConfigProvider
    ) -> None:
        with (
            patch("app.services.config_provider.load_ui_config"),
            patch("app.services.config_provider.load_runtime_config") as mock_rt,
            patch("app.services.config_provider.build_runtime_config"),
            patch("app.services.config_provider.provider_logger") as mock_logger,
        ):
            mock_rt.return_value = (MonitorConfigPayload(), True)
            provider.reload()

        mock_logger.warning.assert_called_once_with("配置重载时部分密码解密失败")


class TestInitialValues:
    """初始值测试。"""

    def test_runtime_config_initially_empty(
        self, provider: RuntimeConfigProvider
    ) -> None:
        assert provider.get_runtime_config() == {}

    def test_ui_config_initially_default(self, provider: RuntimeConfigProvider) -> None:
        result = provider.get_ui_config()
        assert isinstance(result, MonitorConfigPayload)
