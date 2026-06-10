"""监控路由 API 测试 — 覆盖监控启停、状态查询、日志、网络测试、纯净模式端点。"""

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
        mock_services.engine.start_monitoring.return_value = (
            True,
            "监控已启动",
        )
        mock_services.engine.stop_monitoring.return_value = (
            True,
            "监控已停止",
        )
        mock_services.engine.run_manual_login.return_value = (
            True,
            "手动登录成功",
        )
        mock_services.engine.test_network.return_value = (True, "网络正常")
        mock_services.engine.pure_mode = False
        mock_services.engine.toggle_pure_mode.return_value = True

        app = create_app()
        app.state.services = mock_services

        test_client = TestClient(app)
        yield test_client, mock_services


class TestGetStatus:
    """测试 GET /api/status 端点。"""

    def test_get_status_returns_200(self, client):
        test_client, _ = client
        resp = test_client.get("/api/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "monitoring" in data
        assert "network_check_count" in data
        assert "login_attempt_count" in data

    def test_get_status_default_values(self, client):
        test_client, _ = client
        data = test_client.get("/api/status").json()
        assert data["monitoring"] is False
        assert data["network_check_count"] == 0


class TestGetLogs:
    """测试 GET /api/logs 端点。"""

    def test_get_logs_returns_200(self, client):
        test_client, _ = client
        resp = test_client.get("/api/logs")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_get_logs_with_limit(self, client):
        test_client, _ = client
        resp = test_client.get("/api/logs?limit=50")
        assert resp.status_code == 200


class TestStartMonitoring:
    """测试 POST /api/monitor/start 端点。"""

    def test_start_monitoring_success(self, client):
        test_client, _ = client
        resp = test_client.post("/api/monitor/start")
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert resp.json()["message"] == "监控已启动"


class TestStopMonitoring:
    """测试 POST /api/monitor/stop 端点。"""

    def test_stop_monitoring_success(self, client):
        test_client, _ = client
        resp = test_client.post("/api/monitor/stop")
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert resp.json()["message"] == "监控已停止"


class TestManualLogin:
    """测试 POST /api/actions/login 端点。"""

    def test_manual_login_success(self, client):
        test_client, _ = client
        resp = test_client.post("/api/actions/login")
        assert resp.status_code == 200
        assert resp.json()["success"] is True


class TestTestNetwork:
    """测试 POST /api/actions/test-network 端点。"""

    def test_test_network_success(self, client):
        test_client, _ = client
        resp = test_client.post("/api/actions/test-network")
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert resp.json()["message"] == "网络正常"


class TestPureMode:
    """测试 GET/POST /api/pure-mode 端点。"""

    def test_get_pure_mode(self, client):
        test_client, _ = client
        resp = test_client.get("/api/pure-mode")
        assert resp.status_code == 200
        assert "enabled" in resp.json()
        assert resp.json()["enabled"] is False

    def test_toggle_pure_mode(self, client):
        test_client, _ = client
        resp = test_client.post("/api/pure-mode")
        assert resp.status_code == 200
        assert "enabled" in resp.json()
