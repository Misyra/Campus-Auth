"""浏览器 API 端点测试。"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.schemas import MonitorConfigPayload, MonitorStatusResponse


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

        # monitor_service
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

        # profile_service
        mock_profile = MagicMock()
        mock_profile_data = MagicMock()
        mock_profile_data.global_settings.browser_channel = "playwright"
        mock_profile.load.return_value = mock_profile_data
        mock_services.profile_service = mock_profile

        app = create_app()
        app.state.services = mock_services

        test_client = TestClient(app)
        yield test_client, mock_services


def test_get_browsers_returns_200(client):
    """GET /api/browsers 应返回 200。"""
    test_client, _ = client
    response = test_client.get("/api/browsers")
    assert response.status_code == 200


def test_get_browsers_structure(client):
    """响应应包含 browsers 列表和 current 字段。"""
    test_client, _ = client
    response = test_client.get("/api/browsers")
    data = response.json()
    assert "browsers" in data
    assert "current" in data
    assert isinstance(data["browsers"], list)


def test_get_browsers_contains_all_channels(client):
    """browsers 列表应包含所有 5 种选项。"""
    test_client, _ = client
    response = test_client.get("/api/browsers")
    data = response.json()
    channels = [b["channel"] for b in data["browsers"]]
    assert "playwright" in channels
    assert "msedge" in channels
    assert "chrome" in channels
    assert "firefox" in channels
    assert "custom" in channels
    assert len(channels) == 5


def test_get_browsers_current_field(client):
    """current 字段应返回当前配置的 browser_channel。"""
    test_client, _ = client
    response = test_client.get("/api/browsers")
    data = response.json()
    assert data["current"] in ["playwright", "msedge", "chrome", "firefox", "custom"]


def test_get_browsers_item_structure(client):
    """每个浏览器项应包含必要字段。"""
    test_client, _ = client
    response = test_client.get("/api/browsers")
    data = response.json()
    for b in data["browsers"]:
        assert "channel" in b
        assert "name" in b
        assert "icon" in b
        assert "installed" in b
        assert "needs_download" in b
        assert "description" in b
