"""调试路由 API 测试 — 覆盖调试会话的启动、单步执行、全部执行、停止、状态查询端点。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

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

        # debug_manager（方法均为 async）
        mock_services.debug_manager.get_status.return_value = {
            "running": False,
            "task_id": None,
            "current_step": 0,
            "total_steps": 0,
            "steps": [],
            "results": [],
            "screenshot_url": None,
        }
        mock_services.debug_manager.start = AsyncMock(
            return_value={"running": True, "message": "调试已启动"}
        )
        mock_services.debug_manager.next_step = AsyncMock(
            return_value={"running": False}
        )
        mock_services.debug_manager.run_all = AsyncMock(
            return_value={"running": False}
        )
        mock_services.debug_manager.stop = AsyncMock(
            return_value={"running": False, "message": "调试会话已关闭"}
        )

        app = create_app()
        app.state.services = mock_services

        test_client = TestClient(app)
        yield test_client, mock_services


class TestDebugStart:
    """测试 POST /api/debug/start 端点。"""

    def test_debug_start_returns_200(self, client):
        test_client, _ = client
        resp = test_client.post("/api/debug/start")
        assert resp.status_code == 200
        assert resp.json()["running"] is True


class TestDebugNext:
    """测试 POST /api/debug/next 端点。"""

    def test_debug_next_returns_200(self, client):
        test_client, _ = client
        resp = test_client.post("/api/debug/next")
        assert resp.status_code == 200
        assert "running" in resp.json()


class TestDebugRunAll:
    """测试 POST /api/debug/run-all 端点。"""

    def test_debug_run_all_returns_200(self, client):
        test_client, _ = client
        resp = test_client.post("/api/debug/run-all")
        assert resp.status_code == 200
        assert "running" in resp.json()


class TestDebugStop:
    """测试 POST /api/debug/stop 端点。"""

    def test_debug_stop_returns_200(self, client):
        test_client, _ = client
        resp = test_client.post("/api/debug/stop")
        assert resp.status_code == 200
        assert resp.json()["running"] is False


class TestDebugStatus:
    """测试 GET /api/debug/status 端点。"""

    def test_debug_status_returns_200(self, client):
        test_client, _ = client
        resp = test_client.get("/api/debug/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "running" in data
        assert "current_step" in data
        assert "total_steps" in data

    def test_debug_status_default_values(self, client):
        test_client, _ = client
        data = test_client.get("/api/debug/status").json()
        assert data["running"] is False
        assert data["task_id"] is None
