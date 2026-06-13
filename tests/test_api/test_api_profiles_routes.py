"""方案路由 API 测试 — 覆盖方案 CRUD、活动方案、网络检测、自动切换端点。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.schemas import (
    MonitorConfigPayload,
    MonitorStatusResponse,
    ProfilesData,
    ProfileSettings,
    SystemSettings,
)


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
        profile_data = ProfilesData(
            system=SystemSettings(username="testuser", password="ENC:test"),
            profiles={"default": ProfileSettings(name="默认方案")},
        )
        mock_services.profile_service.load.return_value = profile_data
        mock_services.profile_service.get_active_profile.return_value = ProfileSettings(
            name="默认方案"
        )
        mock_services.profile_service.save_profile.return_value = (True, "保存成功")
        mock_services.profile_service.delete_profile.return_value = (True, "删除成功")
        mock_services.profile_service.set_active_profile.return_value = (
            True,
            "切换成功",
        )
        mock_services.profile_service.detect_matching_profile.return_value = None
        mock_services.profile_service.set_auto_switch.return_value = None

        app = create_app()
        app.state.services = mock_services

        test_client = TestClient(app)
        yield test_client, mock_services


class TestListProfiles:
    """测试 GET /api/profiles 端点。"""

    def test_list_profiles_returns_200(self, client):
        test_client, _ = client
        resp = test_client.get("/api/profiles")
        assert resp.status_code == 200
        data = resp.json()
        assert "profiles" in data
        assert "active_profile" in data
        assert "auto_switch" in data

    def test_list_profiles_content(self, client):
        test_client, _ = client
        data = test_client.get("/api/profiles").json()
        assert "default" in data["profiles"]
        assert data["profiles"]["default"]["name"] == "默认方案"


class TestGetProfile:
    """测试 GET /api/profiles/{profile_id} 端点。"""

    def test_get_profile_found(self, client):
        test_client, _ = client
        resp = test_client.get("/api/profiles/default")
        assert resp.status_code == 200
        data = resp.json()
        assert data["profile_id"] == "default"
        assert "settings" in data

    def test_get_profile_not_found(self, client):
        test_client, _ = client
        resp = test_client.get("/api/profiles/nonexistent")
        assert resp.status_code == 404


class TestSaveProfile:
    """测试 PUT /api/profiles/{profile_id} 端点。"""

    def test_save_profile_success(self, client):
        test_client, _ = client
        resp = test_client.put(
            "/api/profiles/default",
            json={"name": "更新方案", "network_targets": "8.8.8.8:53"},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True


class TestDeleteProfile:
    """测试 DELETE /api/profiles/{profile_id} 端点。"""

    def test_delete_profile_success(self, client):
        test_client, _ = client
        resp = test_client.delete("/api/profiles/default")
        assert resp.status_code == 200
        assert resp.json()["success"] is True


class TestSetActiveProfile:
    """测试 POST /api/profiles/active/{profile_id} 端点。"""

    def test_set_active_profile_success(self, client):
        test_client, _ = client
        resp = test_client.post("/api/profiles/active/default")
        assert resp.status_code == 200
        assert resp.json()["success"] is True


class TestDetectNetwork:
    """测试 POST /api/profiles/detect 端点。"""

    @patch("app.network.detect.detect_wifi_ssid", return_value=None)
    @patch("app.network.detect.detect_gateway_ip", return_value="10.0.0.1")
    def test_detect_network_returns_200(self, mock_gateway, mock_ssid, client):
        test_client, _ = client
        resp = test_client.post("/api/profiles/detect")
        assert resp.status_code == 200
        data = resp.json()
        assert "gateway_ip" in data
        assert "ssid" in data
        assert "matched_profile_id" in data


class TestAutoSwitch:
    """测试 POST /api/profiles/auto-switch 端点。"""

    def test_auto_switch_enable(self, client):
        test_client, _ = client
        resp = test_client.post("/api/profiles/auto-switch?enabled=true")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_auto_switch_disable(self, client):
        test_client, _ = client
        resp = test_client.post("/api/profiles/auto-switch?enabled=false")
        assert resp.status_code == 200
        assert resp.json()["success"] is True
