"""登录历史路由 API 测试 — 覆盖查询、清空登录记录端点。"""

from __future__ import annotations


class TestGetLoginHistory:
    """测试 GET /api/login-history 端点。"""

    def test_get_login_history_returns_200(self, api_client):
        test_client, mock_services = api_client
        mock_services.login_history_service.list_recent.return_value = []
        resp = test_client.get("/api/login-history")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_get_login_history_with_limit(self, api_client):
        test_client, mock_services = api_client
        mock_services.login_history_service.list_recent.return_value = []
        resp = test_client.get("/api/login-history?limit=10")
        assert resp.status_code == 200


class TestClearLoginHistory:
    """测试 DELETE /api/login-history 端点。"""

    def test_clear_login_history_success(self, api_client):
        test_client, mock_services = api_client
        mock_services.login_history_service.clear.return_value = 5
        resp = test_client.delete("/api/login-history")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "5" in data["message"]

    def test_clear_login_history_empty(self, api_client):
        test_client, mock_services = api_client
        mock_services.login_history_service.clear.return_value = 0
        resp = test_client.delete("/api/login-history")
        assert resp.status_code == 200
        assert resp.json()["success"] is True
