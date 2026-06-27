"""配置路由 API 测试 — 覆盖 GET/PUT /api/config 端点。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.schemas import (
    AppSettings,
    BrowserSettings,
    ConfigResponseDTO,
    LoginCredentials,
    LoggingSettings,
    MonitorSettings,
    PauseSettings,
    RetrySettings,
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
        assert "global_level" in data
        assert "source_levels" in data

    def test_set_source_level(self, api_client):
        """测试设置 source 级别"""
        test_client, _ = api_client
        response = test_client.put(
            "/api/config/source-level",
            json={"source": "network", "level": "DEBUG"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True


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
        mock_services.profile_service.build_runtime_config.return_value = _make_runtime_config()
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
        mock_services.profile_service.build_runtime_config.return_value = _make_runtime_config()
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
        mock_services.profile_service.build_runtime_config.return_value = _make_runtime_config()

        # 构建完整 payload（含必填嵌套字段）
        payload = ConfigResponseDTO(
            browser=BrowserSettings(),
            monitor=MonitorSettings(),
            retry=RetrySettings(),
            pause=PauseSettings(),
            logging=LoggingSettings(),
            app_settings=AppSettings(),
            username="newuser",
            password="newpass",
            auth_url="http://10.0.0.1",
            isp="移动",
        ).model_dump()
        resp = test_client.put("/api/config", json=payload)
        assert resp.status_code == 200
        assert resp.json()["success"] is True
