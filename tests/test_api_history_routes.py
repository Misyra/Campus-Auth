"""登录历史路由 API 测试 — 覆盖查询、清空登录记录端点。"""

from __future__ import annotations

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
        from app.application import app

        mock_services = MagicMock()

        # monitor_service
        mock_services.monitor_service.get_config.return_value = MonitorConfigPayload(
            username="testuser", password="••••••••", auth_url="http://10.0.0.1"
        )
        mock_services.monitor_service.get_status.return_value = MonitorStatusResponse(
            monitoring=False,
            network_check_count=0,
            login_attempt_count=0,
            last_check_time=None,
            runtime_seconds=0,
        )
        mock_services.monitor_service.list_logs.return_value = []

        # login_history_service
        mock_services.login_history_service.list_recent.return_value = []
        mock_services.login_history_service.clear.return_value = 0

        app.state.services = mock_services

        test_client = TestClient(app)
        yield test_client, mock_services


class TestGetLoginHistory:
    """测试 GET /api/login-history 端点。"""

    def test_get_login_history_returns_200(self, client):
        test_client, _ = client
        resp = test_client.get("/api/login-history")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_get_login_history_with_limit(self, client):
        test_client, _ = client
        resp = test_client.get("/api/login-history?limit=10")
        assert resp.status_code == 200


class TestClearLoginHistory:
    """测试 DELETE /api/login-history 端点。"""

    def test_clear_login_history_success(self, client):
        test_client, mock_services = client
        mock_services.login_history_service.clear.return_value = 5
        resp = test_client.delete("/api/login-history")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "5" in data["message"]

    def test_clear_login_history_empty(self, client):
        test_client, mock_services = client
        mock_services.login_history_service.clear.return_value = 0
        resp = test_client.delete("/api/login-history")
        assert resp.status_code == 200
        assert resp.json()["success"] is True
