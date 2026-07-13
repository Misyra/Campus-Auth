"""监控路由 API 测试 — 覆盖监控启停、状态查询、日志、网络测试、纯净模式端点。"""

from __future__ import annotations

from app.schemas import MonitorStatusResponse


class TestGetStatus:
    """测试 GET /api/status 端点。"""

    def test_get_status_returns_200(self, api_client):
        test_client, mock_services = api_client
        mock_services.engine.get_status.return_value = MonitorStatusResponse(
            monitoring=False,
            network_check_count=0,
            login_attempt_count=0,
            last_check_time=None,
            runtime_seconds=0,
        )
        resp = test_client.get("/api/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "monitoring" in data
        assert "network_check_count" in data
        assert "login_attempt_count" in data

    def test_get_status_default_values(self, api_client):
        test_client, mock_services = api_client
        mock_services.engine.get_status.return_value = MonitorStatusResponse(
            monitoring=False,
            network_check_count=0,
            login_attempt_count=0,
            last_check_time=None,
            runtime_seconds=0,
        )
        data = test_client.get("/api/status").json()
        assert data["monitoring"] is False
        assert data["network_check_count"] == 0


class TestGetLogs:
    """测试 GET /api/logs 端点。"""

    def test_get_logs_returns_200(self, api_client):
        test_client, mock_services = api_client
        mock_services.engine.list_logs.return_value = []
        resp = test_client.get("/api/logs")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_get_logs_with_limit(self, api_client):
        test_client, mock_services = api_client
        mock_services.engine.list_logs.return_value = []
        resp = test_client.get("/api/logs?limit=50")
        assert resp.status_code == 200


class TestStartMonitoring:
    """测试 POST /api/monitor/start 端点。"""

    def test_start_monitoring_success(self, api_client):
        test_client, mock_services = api_client
        mock_services.engine.start_monitoring.return_value = (True, "监控已启动")
        resp = test_client.post("/api/monitor/start")
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert resp.json()["message"] == "监控已启动"


class TestStopMonitoring:
    """测试 POST /api/monitor/stop 端点。"""

    def test_stop_monitoring_success(self, api_client):
        test_client, mock_services = api_client
        mock_services.engine.stop_monitoring.return_value = (True, "监控已停止")
        resp = test_client.post("/api/monitor/stop")
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert resp.json()["message"] == "监控已停止"


class TestManualLogin:
    """测试 POST /api/actions/login 端点。"""

    def test_manual_login_success(self, api_client):
        test_client, mock_services = api_client
        mock_services.engine.run_manual_login.return_value = (True, "登录成功")
        resp = test_client.post("/api/actions/login")
        assert resp.status_code == 200
        assert resp.json()["success"] is True


class TestCancelLogin:
    """测试 POST /api/actions/cancel-login 端点。"""

    def test_cancel_login_success(self, api_client):
        test_client, mock_services = api_client
        mock_services.engine.cancel_login.return_value = (True, "已取消登录")
        resp = test_client.post("/api/actions/cancel-login")
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert resp.json()["message"] == "已取消登录"

    def test_cancel_login_no_pending(self, api_client):
        test_client, mock_services = api_client
        mock_services.engine.cancel_login.return_value = (False, "没有待取消的登录")
        resp = test_client.post("/api/actions/cancel-login")
        assert resp.status_code == 200
        assert resp.json()["success"] is False
        assert resp.json()["message"] == "没有待取消的登录"


class TestTestNetwork:
    """测试 POST /api/actions/test-network 端点。"""

    def test_test_network_success(self, api_client):
        test_client, mock_services = api_client
        mock_services.engine.test_network.return_value = (True, "网络正常")
        resp = test_client.post("/api/actions/test-network")
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert resp.json()["message"] == "网络正常"


class TestPureMode:
    """测试 GET/POST /api/pure-mode 端点。"""

    def test_get_pure_mode(self, api_client):
        """GET /api/pure-mode 应从 config_service.pure_mode 读取（Task 3.4）。"""
        test_client, mock_services = api_client
        mock_services.config_service.pure_mode = False
        resp = test_client.get("/api/pure-mode")
        assert resp.status_code == 200
        assert "enabled" in resp.json()
        assert resp.json()["enabled"] is False

    def test_toggle_pure_mode(self, api_client):
        """POST /api/pure-mode 应调用 config_service.toggle_pure_mode（Task 3.4）。"""
        test_client, mock_services = api_client
        mock_services.config_service.toggle_pure_mode.return_value = True
        resp = test_client.post("/api/pure-mode")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["enabled"] is True
        # 验证 config_service 被调用而非 engine
        mock_services.config_service.toggle_pure_mode.assert_called_once()
        mock_services.engine.toggle_pure_mode.assert_not_called()


class TestNetworkInterfacesAPI:
    """测试 GET /api/network/interfaces 端点。"""

    def test_get_interfaces_returns_list(self, api_client):
        from unittest.mock import patch

        from app.network.interfaces import InterfaceInfo

        test_client, _mock_services = api_client
        fake_interfaces = [
            InterfaceInfo(
                name="以太网", ip="192.168.1.5", gateway="192.168.1.1", is_up=True
            ),
        ]
        with patch("app.network.interfaces.InterfaceManager") as MockMgr:
            MockMgr.return_value.list_interfaces.return_value = fake_interfaces
            resp = test_client.get("/api/network/interfaces")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["id"] == "以太网"
        assert data[0]["name"] == "以太网"
        assert data[0]["ip"] == "192.168.1.5"
        assert data[0]["gateway"] == "192.168.1.1"
        assert data[0]["is_up"] is True

    def test_get_interfaces_empty(self, api_client):
        from unittest.mock import patch

        test_client, _mock_services = api_client
        with patch("app.network.interfaces.InterfaceManager") as MockMgr:
            MockMgr.return_value.list_interfaces.return_value = []
            resp = test_client.get("/api/network/interfaces")

        assert resp.status_code == 200
        assert resp.json() == []

    def test_get_interfaces_multiple(self, api_client):
        from unittest.mock import patch

        from app.network.interfaces import InterfaceInfo

        test_client, _mock_services = api_client
        fake_interfaces = [
            InterfaceInfo(
                name="以太网", ip="192.168.1.5", gateway="192.168.1.1", is_up=True
            ),
            InterfaceInfo(name="WLAN", ip="10.0.0.2", gateway="10.0.0.1", is_up=False),
        ]
        with patch("app.network.interfaces.InterfaceManager") as MockMgr:
            MockMgr.return_value.list_interfaces.return_value = fake_interfaces
            resp = test_client.get("/api/network/interfaces")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[1]["id"] == "WLAN"
        assert data[1]["is_up"] is False
