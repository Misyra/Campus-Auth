"""调试路由 API 测试 — 覆盖调试会话的启动、单步执行、全部执行、停止、状态查询端点。"""

from __future__ import annotations

from unittest.mock import AsyncMock


class TestDebugStart:
    """测试 POST /api/debug/start 端点。"""

    def test_debug_start_returns_200(self, api_client):
        test_client, mock_services = api_client
        mock_services.debug_manager.start = AsyncMock(
            return_value={"running": True, "message": "调试已启动"}
        )
        resp = test_client.post("/api/debug/start")
        assert resp.status_code == 200
        assert resp.json()["running"] is True


class TestDebugNext:
    """测试 POST /api/debug/next 端点。"""

    def test_debug_next_returns_200(self, api_client):
        test_client, mock_services = api_client
        mock_services.debug_manager.next_step = AsyncMock(
            return_value={"running": False}
        )
        resp = test_client.post("/api/debug/next")
        assert resp.status_code == 200
        assert "running" in resp.json()


class TestDebugRunAll:
    """测试 POST /api/debug/run-all 端点。"""

    def test_debug_run_all_returns_200(self, api_client):
        test_client, mock_services = api_client
        mock_services.debug_manager.run_all = AsyncMock(
            return_value={"running": False}
        )
        resp = test_client.post("/api/debug/run-all")
        assert resp.status_code == 200
        assert "running" in resp.json()


class TestDebugStop:
    """测试 POST /api/debug/stop 端点。"""

    def test_debug_stop_returns_200(self, api_client):
        test_client, mock_services = api_client
        mock_services.debug_manager.stop = AsyncMock(
            return_value={"running": False, "message": "调试会话已关闭"}
        )
        resp = test_client.post("/api/debug/stop")
        assert resp.status_code == 200
        assert resp.json()["running"] is False
