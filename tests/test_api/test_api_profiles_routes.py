"""方案路由 API 测试 — 覆盖方案 CRUD、活动方案、网络检测、自动切换端点。"""

from __future__ import annotations

from unittest.mock import patch

from app.schemas import (
    Profile,
    ProfilesData,
)


class TestListProfiles:
    """测试 GET /api/profiles 端点。"""

    def test_list_profiles_returns_200(self, api_client):
        test_client, mock_services = api_client
        profile_data = ProfilesData(
            profiles={"default": Profile(name="默认方案", username="testuser", password="ENC:test")},
        )
        mock_services.profile_service.load.return_value = profile_data
        resp = test_client.get("/api/profiles")
        assert resp.status_code == 200
        data = resp.json()
        assert "profiles" in data
        assert "active_profile" in data
        assert "auto_switch" in data

    def test_list_profiles_content(self, api_client):
        test_client, mock_services = api_client
        profile_data = ProfilesData(
            profiles={"default": Profile(name="默认方案", username="testuser", password="ENC:test")},
        )
        mock_services.profile_service.load.return_value = profile_data
        data = test_client.get("/api/profiles").json()
        assert "default" in data["profiles"]
        assert data["profiles"]["default"]["name"] == "默认方案"


class TestGetProfile:
    """测试 GET /api/profiles/{profile_id} 端点。"""

    def test_get_profile_found(self, api_client):
        test_client, mock_services = api_client
        profile_data = ProfilesData(
            profiles={"default": Profile(name="默认方案", username="testuser", password="ENC:test")},
        )
        mock_services.profile_service.load.return_value = profile_data
        resp = test_client.get("/api/profiles/default")
        assert resp.status_code == 200
        data = resp.json()
        assert data["profile_id"] == "default"
        assert "settings" in data

    def test_get_profile_not_found(self, api_client):
        test_client, mock_services = api_client
        profile_data = ProfilesData(
            profiles={"default": Profile(name="默认方案", username="testuser", password="ENC:test")},
        )
        mock_services.profile_service.load.return_value = profile_data
        resp = test_client.get("/api/profiles/nonexistent")
        assert resp.status_code == 404


class TestSaveProfile:
    """测试 PUT /api/profiles/{profile_id} 端点。"""

    def test_save_profile_success(self, api_client):
        test_client, mock_services = api_client
        mock_services.profile_service.save_profile.return_value = (True, "保存成功")
        resp = test_client.put(
            "/api/profiles/default",
            json={"name": "更新方案", "network_targets": "8.8.8.8:53"},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True


class TestDeleteProfile:
    """测试 DELETE /api/profiles/{profile_id} 端点。"""

    def test_delete_profile_success(self, api_client):
        test_client, mock_services = api_client
        mock_services.profile_service.delete_profile.return_value = (True, "删除成功")
        resp = test_client.delete("/api/profiles/default")
        assert resp.status_code == 200
        assert resp.json()["success"] is True


class TestSetActiveProfile:
    """测试 POST /api/profiles/active/{profile_id} 端点。"""

    def test_set_active_profile_success(self, api_client):
        test_client, mock_services = api_client
        mock_services.engine.apply_profile.return_value = (True, "切换成功")
        resp = test_client.post("/api/profiles/active/default")
        assert resp.status_code == 200
        assert resp.json()["success"] is True


class TestDetectNetwork:
    """测试 POST /api/profiles/detect 端点。"""

    @patch("app.network.detect.detect_wifi_ssid", return_value=None)
    @patch("app.network.detect.detect_gateway_ip", return_value="10.0.0.1")
    def test_detect_network_returns_200(self, mock_gateway, mock_ssid, api_client):
        test_client, mock_services = api_client
        mock_services.profile_service.detect_matching_profile.return_value = None
        resp = test_client.post("/api/profiles/detect")
        assert resp.status_code == 200
        data = resp.json()
        assert "gateway_ip" in data
        assert "ssid" in data
        assert "matched_profile_id" in data


class TestAutoSwitch:
    """测试 POST /api/profiles/auto-switch 端点。"""

    def test_auto_switch_enable(self, api_client):
        test_client, mock_services = api_client
        mock_services.profile_service.set_auto_switch.return_value = None
        resp = test_client.post("/api/profiles/auto-switch?enabled=true")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_auto_switch_disable(self, api_client):
        test_client, mock_services = api_client
        mock_services.profile_service.set_auto_switch.return_value = None
        resp = test_client.post("/api/profiles/auto-switch?enabled=false")
        assert resp.status_code == 200
        assert resp.json()["success"] is True
