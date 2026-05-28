"""backend/main.py — API 路由综合测试

使用 FastAPI TestClient 测试各 API 端点。
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient


# =====================================================================
# 辅助：创建测试客户端
# =====================================================================


@pytest.fixture
def client(tmp_path):
    """创建隔离的测试客户端"""
    # 设置临时项目根目录
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps({
            "system": {
                "username": "testuser",
                "password": "ENC:test",
                "auth_url": "http://10.0.0.1",
            },
            "profiles": {
                "default": {"name": "默认方案"},
            },
        }),
        encoding="utf-8",
    )
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    (tasks_dir / "default.json").write_text(
        json.dumps({
            "name": "默认任务",
            "steps": [{"id": "s1", "type": "click", "selector": "#btn"}],
        }),
        encoding="utf-8",
    )

    with patch("backend.main.PROJECT_ROOT", tmp_path), \
         patch("backend.main.FRONTEND_DIR", tmp_path / "frontend"), \
         patch("backend.main.LOGS_DIR", tmp_path / "logs"):
        # 创建前端目录
        (tmp_path / "frontend").mkdir(exist_ok=True)
        (tmp_path / "frontend" / "index.html").write_text("<html></html>")

        from backend.main import app
        from backend import main as main_module

        # 重新初始化服务
        main_module.profile_service = MagicMock()
        main_module.service = MagicMock()

        # 模拟 get_config 返回
        from backend.schemas import MonitorConfigPayload
        main_module.service.get_config.return_value = MonitorConfigPayload(
            username="testuser",
            password="••••••••",
            auth_url="http://10.0.0.1",
        )

        # 模拟 get_status 返回
        from backend.schemas import MonitorStatusResponse
        main_module.service.get_status.return_value = MonitorStatusResponse(
            monitoring=False,
            network_check_count=0,
            login_attempt_count=0,
            last_check_time=None,
            runtime_seconds=0,
        )

        # 模拟 list_logs 返回
        main_module.service.list_logs.return_value = []

        # 模拟 start/stop_monitoring 返回
        main_module.service.start_monitoring.return_value = (True, "监控已启动")
        main_module.service.stop_monitoring.return_value = (True, "监控已停止")
        main_module.service.login_in_progress = False
        main_module.service.run_manual_login.return_value = (True, "手动登录成功")

        test_client = TestClient(app)
        yield test_client


# =====================================================================
# 健康检查
# =====================================================================


class TestHealthEndpoint:
    def test_health(self, client):
        response = client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "version" in data


# =====================================================================
# 初始化状态
# =====================================================================


class TestInitStatusEndpoint:
    def test_init_status(self, client):
        response = client.get("/api/init-status")
        assert response.status_code == 200
        data = response.json()
        assert "initialized" in data
        assert "password_decryption_failed" in data


# =====================================================================
# 配置
# =====================================================================


class TestConfigEndpoint:
    def test_get_config(self, client):
        response = client.get("/api/config")
        assert response.status_code == 200
        data = response.json()
        assert "username" in data
        assert "auth_url" in data

    def test_save_config(self, client):
        response = client.put(
            "/api/config",
            json={
                "username": "newuser",
                "password": "newpass",
                "auth_url": "http://10.0.0.1",
                "check_interval_seconds": 300,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True


# =====================================================================
# 状态
# =====================================================================


class TestStatusEndpoint:
    def test_get_status(self, client):
        response = client.get("/api/status")
        assert response.status_code == 200
        data = response.json()
        assert "monitoring" in data
        assert "network_check_count" in data


# =====================================================================
# 日志
# =====================================================================


class TestLogsEndpoint:
    def test_get_logs(self, client):
        response = client.get("/api/logs")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_get_logs_with_limit(self, client):
        response = client.get("/api/logs?limit=10")
        assert response.status_code == 200


# =====================================================================
# 监控控制
# =====================================================================


class TestMonitorEndpoints:
    def test_start_monitoring(self, client):
        response = client.post("/api/monitor/start")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    def test_stop_monitoring(self, client):
        response = client.post("/api/monitor/stop")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True


# =====================================================================
# 登录
# =====================================================================


class TestLoginEndpoint:
    def test_manual_login(self, client):
        response = client.post("/api/actions/login")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True


# =====================================================================
# 版本比较（_compare_versions）
# =====================================================================


class TestCompareVersions:
    def test_equal(self):
        from backend.main import _compare_versions
        assert _compare_versions("1.0.0", "1.0.0") == 0

    def test_greater(self):
        from backend.main import _compare_versions
        assert _compare_versions("1.1.0", "1.0.0") == 1

    def test_less(self):
        from backend.main import _compare_versions
        assert _compare_versions("1.0.0", "1.1.0") == -1

    def test_different_lengths(self):
        from backend.main import _compare_versions
        assert _compare_versions("1.0.0.1", "1.0.0") == 1
        assert _compare_versions("1.0", "1.0.0") == -1

    def test_invalid_input(self):
        from backend.main import _compare_versions
        assert _compare_versions("invalid", "1.0.0") == 0
        assert _compare_versions("1.0.0", "invalid") == 0

    def test_major_version_diff(self):
        from backend.main import _compare_versions
        assert _compare_versions("2.0.0", "1.9.9") == 1
