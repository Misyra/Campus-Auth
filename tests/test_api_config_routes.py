"""配置路由 API 测试 — 覆盖 GET/PUT /api/config 端点。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.schemas import (
    MonitorConfigPayload,
    MonitorStatusResponse,
    ProfilesData,
    ProfileSettings,
    SystemSettings,
)


@pytest.fixture
def client(tmp_path):
    """创建隔离的测试客户端。"""
    (tmp_path / "frontend").mkdir(exist_ok=True)
    (tmp_path / "frontend" / "index.html").write_text("<html></html>")
    (tmp_path / "logs").mkdir(exist_ok=True)
    (tmp_path / "temp").mkdir(exist_ok=True)

    with (
        patch("app.constants.PROJECT_ROOT", tmp_path),
        patch("app.constants.FRONTEND_DIR", tmp_path / "frontend"),
        patch("app.constants.LOGS_DIR", tmp_path / "logs"),
        patch("app.constants.TEMP_DIR", tmp_path / "temp"),
    ):
        from app.application import create_app

        mock_services = MagicMock()

        # monitor_service mock
        mock_services.engine.get_config.return_value = MonitorConfigPayload(
            username="testuser", password="••••••••", auth_url="http://10.0.0.1"
        )
        mock_services.engine.get_status.return_value = MonitorStatusResponse(
            monitoring=False,
            network_check_count=0,
            login_attempt_count=0,
            last_check_time=None,
            runtime_seconds=0,
        )
        mock_services.engine.list_logs.return_value = []

        # profile_service mock
        profile_data = ProfilesData(
            system=SystemSettings(username="testuser", password="ENC:test"),
            profiles={"default": ProfileSettings(name="默认方案")},
        )
        mock_services.profile_service.load.return_value = profile_data

        app = create_app()
        app.state.services = mock_services

        test_client = TestClient(app)
        yield test_client, mock_services


class TestGetConfig:
    """测试 GET /api/config 端点。"""

    def test_get_config_returns_200(self, client):
        test_client, _ = client
        resp = test_client.get("/api/config")
        assert resp.status_code == 200
        data = resp.json()
        assert "username" in data
        assert "auth_url" in data

    def test_get_config_contains_expected_fields(self, client):
        test_client, _ = client
        data = test_client.get("/api/config").json()
        assert data["username"] == "testuser"
        assert data["auth_url"] == "http://10.0.0.1"


class TestGetDefaultStealthScript:
    """测试 GET /api/config/default-stealth-script 端点。"""

    def test_returns_script(self, client):
        test_client, _ = client
        resp = test_client.get("/api/config/default-stealth-script")
        assert resp.status_code == 200
        data = resp.json()
        assert "script" in data
        assert isinstance(data["script"], str)


class TestSaveConfig:
    """测试 PUT /api/config 端点。"""

    @patch("app.api.config.save_config_combined")
    def test_save_config_success(self, mock_save, client):
        test_client, mock_services = client
        mock_save.return_value = None

        payload = {
            "username": "newuser",
            "password": "newpass",
            "auth_url": "http://10.0.0.1",
        }
        resp = test_client.put("/api/config", json=payload)
        assert resp.status_code == 200
        assert resp.json()["success"] is True
