"""应用生命周期与 API 全量端点 E2E 测试。

验证真实 FastAPI 应用启动后，各 API 端点的状态码与关键字段响应。
所有测试通过 TestClient 调用真实路由，不 mock 服务层。
"""

from __future__ import annotations

import json


def _ensure_probes_active() -> None:
    """清空网络探测关闭标志，避免上一轮 real_app 关闭残留影响。"""
    from app.network.probes import _shutdown_event

    _shutdown_event.clear()


class TestAppLifecycle:
    """应用启动后各 API 端点的真实响应验证。"""

    def test_status_initial_monitoring_false(self, real_app):
        """/api/status 初始 monitoring=False（fixture 不自动启动监控）。"""
        client, _ = real_app
        resp = client.get("/api/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["monitoring"] is False

    def test_monitor_start_stop_toggle(self, real_app, http_portal):
        """启动/停止监控切换 monitoring 标志。"""
        client, _ = real_app
        _ensure_probes_active()
        _, _, base_url = http_portal
        # 配置监控仅启用 URL 检测指向本地门户，避免访问外网或触发登录
        patch_body = {
            "monitor": {
                "enable_tcp_check": False,
                "enable_http_check": False,
                "enable_local_check": False,
                "url_check_urls": [f"{base_url}/success|Success"],
            }
        }
        resp = client.patch("/api/config", json=patch_body)
        assert resp.status_code == 200
        # 启动监控
        resp = client.post("/api/monitor/start")
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        # 验证 monitoring=True
        resp = client.get("/api/status")
        assert resp.json()["monitoring"] is True
        # 停止监控
        resp = client.post("/api/monitor/stop")
        assert resp.status_code == 200
        # 验证 monitoring=False
        resp = client.get("/api/status")
        assert resp.json()["monitoring"] is False

    def test_get_config_flat_fields(self, real_app):
        """GET /api/config 返回扁平字段结构。"""
        client, _ = real_app
        resp = client.get("/api/config")
        assert resp.status_code == 200
        cfg = resp.json()
        # 嵌套配置块
        for key in ("browser", "monitor", "retry", "pause", "logging", "app_settings"):
            assert isinstance(cfg[key], dict), f"{key} 应为字典"
        # 凭据扁平字段
        for key in (
            "username",
            "password",
            "has_password",
            "auth_url",
            "isp",
            "carrier_custom",
            "active_task",
        ):
            assert key in cfg
        assert cfg["username"] == "e2e_user"
        assert cfg["has_password"] is True

    def test_get_logs(self, real_app):
        """GET /api/logs?limit=10 返回日志列表。"""
        client, _ = real_app
        resp = client.get("/api/logs", params={"limit": 10})
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_get_profiles(self, real_app):
        """GET /api/profiles 列出方案。"""
        client, _ = real_app
        resp = client.get("/api/profiles")
        assert resp.status_code == 200
        data = resp.json()
        assert "profiles" in data
        assert "default" in data["profiles"]
        assert data["active_profile"] == "default"

    def test_get_tasks(self, real_app):
        """GET /api/tasks 列出任务。"""
        client, _ = real_app
        resp = client.get("/api/tasks")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_get_scheduled_tasks(self, real_app):
        """GET /api/scheduled-tasks 列出定时任务。"""
        client, _ = real_app
        resp = client.get("/api/scheduled-tasks")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_get_health(self, real_app):
        """GET /api/health 返回系统信息（含版本号 0.0.0-e2e）。"""
        client, _ = real_app
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["version"] == "0.0.0-e2e"
        assert "python_version" in data
        assert "memory" in data

    def test_get_autostart_status(self, real_app):
        """GET /api/autostart/status 返回自启状态。"""
        client, _ = real_app
        resp = client.get("/api/autostart/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "platform" in data
        assert "enabled" in data
        assert "method" in data

    def test_get_browsers(self, real_app):
        """GET /api/browsers 返回浏览器列表。"""
        client, _ = real_app
        resp = client.get("/api/browsers")
        assert resp.status_code == 200
        data = resp.json()
        assert "browsers" in data
        assert isinstance(data["browsers"], list)
        assert "current" in data

    def test_get_login_history(self, real_app):
        """GET /api/login-history 返回登录历史。"""
        client, _ = real_app
        resp = client.get("/api/login-history")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_websocket_logs_connect(self, real_app):
        """WebSocket /ws/logs 能连接并响应 ping。"""
        client, _ = real_app
        with client.websocket_connect("/ws/logs") as ws:
            ws.send_text(json.dumps({"type": "ping"}))
            # 循环接收直到拿到 pong（可能夹带日志广播）
            pong = None
            for _ in range(20):
                msg = ws.receive_text()
                data = json.loads(msg)
                if data.get("type") == "pong":
                    pong = data
                    break
            assert pong is not None, "未收到 pong 响应"
