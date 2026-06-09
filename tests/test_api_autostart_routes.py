"""自动启动路由 API 测试 — 覆盖 Shell 列表查询、自启动状态/启用/禁用端点。"""

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

        # autostart_service
        mock_services.autostart_service.status.return_value = {
            "platform": "windows",
            "enabled": False,
            "method": "",
            "location": "",
        }
        mock_services.autostart_service.enable.return_value = (True, "自启动已启用")
        mock_services.autostart_service.disable.return_value = (True, "自启动已禁用")

        app.state.services = mock_services

        test_client = TestClient(app)
        yield test_client, mock_services


class TestListShells:
    """测试 GET /api/shells 端点。"""

    @patch("app.api.autostart.get_default_shell", return_value="/bin/bash")
    @patch("app.api.autostart.detect_available_shells")
    def test_list_shells_returns_200(self, mock_detect, mock_default, client):
        test_client, _ = client
        mock_detect.return_value = [
            {"name": "bash", "path": "/bin/bash", "description": "Bourne Again Shell"}
        ]
        resp = test_client.get("/api/shells")
        assert resp.status_code == 200
        data = resp.json()
        assert "shells" in data
        assert "default" in data
        assert isinstance(data["shells"], list)


class TestAutostartStatus:
    """测试 GET /api/autostart/status 端点。"""

    def test_autostart_status_returns_200(self, client):
        test_client, _ = client
        resp = test_client.get("/api/autostart/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "platform" in data
        assert "enabled" in data
        assert "method" in data
        assert "location" in data

    def test_autostart_status_default_disabled(self, client):
        test_client, _ = client
        data = test_client.get("/api/autostart/status").json()
        assert data["enabled"] is False


class TestEnableAutostart:
    """测试 POST /api/autostart/enable 端点。"""

    def test_enable_autostart_success(self, client):
        test_client, _ = client
        resp = test_client.post("/api/autostart/enable")
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert resp.json()["message"] == "自启动已启用"


class TestDisableAutostart:
    """测试 POST /api/autostart/disable 端点。"""

    def test_disable_autostart_success(self, client):
        test_client, _ = client
        resp = test_client.post("/api/autostart/disable")
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert resp.json()["message"] == "自启动已禁用"
