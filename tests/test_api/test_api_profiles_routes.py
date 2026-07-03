"""方案路由 API 测试 — 覆盖方案 CRUD、活动方案、网络检测、自动切换端点。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

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

    def test_delete_last_profile_stops_monitoring(self, api_client):
        """删除最后一个方案后应停止监控。"""
        test_client, mock_services = api_client
        mock_services.profile_service.delete_profile.return_value = (True, "删除成功")
        # 模拟所有方案已删除（active_profile 为 None）
        mock_data = MagicMock()
        mock_data.active_profile = None
        mock_services.profile_service.load.return_value = mock_data

        resp = test_client.delete("/api/profiles/default")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "所有方案已删除，监控已停止" in data["message"]
        mock_services.engine.stop_monitoring.assert_called_once()
        mock_services.engine.apply_profile.assert_not_called()

    def test_delete_profile_applies_new_active(self, api_client):
        """删除方案后仍有剩余方案时应切换到新的活动方案。"""
        test_client, mock_services = api_client
        mock_services.profile_service.delete_profile.return_value = (True, "删除成功")
        # 模拟还有剩余方案
        remaining_data = ProfilesData(
            profiles={"backup": Profile(name="备用方案", username="u", password="ENC:p")},
            active_profile="backup",
        )
        mock_services.profile_service.load.return_value = remaining_data

        resp = test_client.delete("/api/profiles/default")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        mock_services.engine.apply_profile.assert_called_once_with("backup")
        mock_services.engine.stop_monitoring.assert_not_called()


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
        resp = test_client.post("/api/profiles/auto-switch", json={"enabled": True})
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_auto_switch_disable(self, api_client):
        test_client, mock_services = api_client
        mock_services.profile_service.set_auto_switch.return_value = None
        resp = test_client.post("/api/profiles/auto-switch", json={"enabled": False})
        assert resp.status_code == 200
        assert resp.json()["success"] is True


# ── save_profile 参数验证 ──


class TestSaveProfileApplyId:
    """验证 save_profile 路由传递 profile_id 而非 payload.name 给 apply_profile。"""

    def test_apply_profile_uses_id_not_name(self):
        from app.api.profiles import save_profile
        from app.schemas import Profile

        mock_profile_svc = MagicMock()
        mock_monitor_svc = MagicMock()

        mock_profile_svc.save_profile.return_value = (True, "OK")
        mock_data = MagicMock()
        mock_data.active_profile = "my_profile_id"
        mock_profile_svc.load.return_value = mock_data

        payload = Profile(name="完全不同的展示名")
        save_profile(
            profile_id="my_profile_id",
            payload=payload,
            profile_svc=mock_profile_svc,
            monitor_svc=mock_monitor_svc,
        )

        mock_monitor_svc.apply_profile.assert_called_once_with("my_profile_id")
