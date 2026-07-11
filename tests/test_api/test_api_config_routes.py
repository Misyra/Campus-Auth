"""配置路由 API 测试 — 覆盖 GET/PUT /api/config 端点。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.schemas import (
    BrowserSettings,
    LoggingSettings,
    LoginCredentials,
    MonitorSettings,
    RuntimeConfig,
)
from app.services.profile_service import SaveResult


class TestLogLevels:
    """测试日志级别配置 API。"""

    def test_get_log_levels(self, api_client):
        """测试获取日志级别配置"""
        test_client, _ = api_client
        response = test_client.get("/api/config/log-levels")

        assert response.status_code == 200
        data = response.json()
        assert "level" in data


def _make_runtime_config(**kwargs):
    """构建带凭据的 RuntimeConfig 用于 build_runtime_config mock 返回值。"""
    defaults = dict(
        browser=BrowserSettings(),
        monitor=MonitorSettings(),
        credentials=LoginCredentials(
            username="testuser",
            password="secret",
            auth_url="http://10.0.0.1",
        ),
    )
    defaults.update(kwargs)
    return RuntimeConfig(**defaults)


class TestGetConfig:
    """测试 GET /api/config 端点。"""

    def test_get_config_returns_200(self, api_client):
        test_client, mock_services = api_client
        mock_services.profile_service.build_runtime_config.return_value = (
            _make_runtime_config()
        )
        mock_profile = MagicMock()
        mock_profile.carrier = "移动"
        mock_services.profile_service.get_active_profile.return_value = mock_profile
        resp = test_client.get("/api/config")
        assert resp.status_code == 200
        data = resp.json()
        assert "username" in data
        assert "browser" in data

    def test_get_config_contains_expected_fields(self, api_client):
        test_client, mock_services = api_client
        mock_services.profile_service.build_runtime_config.return_value = (
            _make_runtime_config()
        )
        mock_profile = MagicMock()
        mock_profile.carrier = "移动"
        mock_services.profile_service.get_active_profile.return_value = mock_profile
        data = test_client.get("/api/config").json()
        assert data["username"] == "testuser"
        assert data["auth_url"] == "http://10.0.0.1"
        assert data["password"] == ""


class TestGetDefaultStealthScript:
    """测试 GET /api/config/default-stealth-script 端点。"""

    def test_returns_script(self, api_client):
        test_client, _ = api_client
        resp = test_client.get("/api/config/default-stealth-script")
        assert resp.status_code == 200
        data = resp.json()
        assert "script" in data
        assert isinstance(data["script"], str)


class TestSaveConfig:
    """测试 PUT /api/config 端点。"""

    @patch("app.api.config.save_global_and_profile")
    def test_save_config_success(self, mock_save, api_client):
        test_client, mock_services = api_client
        mock_save.return_value = SaveResult(success=True, message="配置保存成功")
        mock_services.profile_service.build_runtime_config.return_value = (
            _make_runtime_config()
        )

        # 构建完整 payload（含必填嵌套字段）
        payload = {
            "browser": {"block_proxy": True},
            "monitor": {"check_interval": 60},
            "retry": {"max_retries": 5},
            "pause": {"pause_on_failure": False},
            "logging": {"global_level": "INFO"},
            "app_settings": {"block_proxy": True},
            "username": "newuser",
            "password": "newpass",
            "auth_url": "http://10.0.0.1",
            "isp": "移动",
        }
        resp = test_client.put("/api/config", json=payload)
        assert resp.status_code == 200
        assert resp.json()["success"] is True


class TestSetLogLevel:
    """测试 PUT /api/config/log-level 端点。"""

    @patch("app.utils.logging.LogConfigCenter")
    def test_set_log_level_calls_update_log_level(
        self, mock_log_center_cls, api_client
    ):
        """设置日志级别后应调用 engine.update_log_level()。"""
        test_client, mock_services = api_client

        # 模拟 LogConfigCenter：set_level 后 get_config 返回新级别
        mock_center = MagicMock()
        mock_center.get_config.return_value = {"level": "DEBUG"}
        mock_log_center_cls.get_instance.return_value = mock_center

        resp = test_client.put("/api/config/log-level", json={"level": "DEBUG"})
        assert resp.status_code == 200
        assert resp.json()["success"] is True

        # 验证 engine.update_log_level 被调用（替代裸改 _runtime_config）
        mock_services.engine.update_log_level.assert_called_once_with("DEBUG")

    @patch("app.utils.logging.LogConfigCenter")
    def test_set_log_level_invalid_level_rejected(
        self, mock_log_center_cls, api_client
    ):
        """无效日志级别应返回 422（Pydantic 校验）。"""
        test_client, _ = api_client

        resp = test_client.put("/api/config/log-level", json={"level": "INVALID"})
        assert resp.status_code == 422

    @patch("app.utils.logging.LogConfigCenter")
    def test_set_log_level_updates_profile_service(
        self, mock_log_center_cls, api_client
    ):
        """设置日志级别后应更新 profile_service。"""
        test_client, mock_services = api_client

        mock_center = MagicMock()
        mock_center.get_config.return_value = {"level": "WARNING"}
        mock_log_center_cls.get_instance.return_value = mock_center

        mock_engine = MagicMock()
        mock_engine._runtime_config = RuntimeConfig(
            logging=LoggingSettings(level="INFO")
        )
        mock_services.engine = mock_engine

        resp = test_client.put("/api/config/log-level", json={"level": "WARNING"})
        assert resp.status_code == 200
        mock_services.profile_service.update.assert_called_once()
