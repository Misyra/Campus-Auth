from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from backend.profile_service import ProfileService, _normalize_isp_to_carrier
from backend.schemas import ProfileSettings, ProfilesData


class TestNormalizeIsp:

    def test_empty(self):
        assert _normalize_isp_to_carrier("") == ("无", "")

    def test_builtin(self):
        assert _normalize_isp_to_carrier("移动") == ("移动", "")

    def test_custom(self):
        assert _normalize_isp_to_carrier("校园网") == ("自定义", "校园网")


class TestProfileService:

    def _make_service(self, tmp_path: Path) -> ProfileService:
        return ProfileService(tmp_path)

    def test_load_empty(self, tmp_path):
        svc = self._make_service(tmp_path)
        data = svc.load()
        assert isinstance(data, ProfilesData)
        assert data.active_profile == "default"

    def test_save_and_load(self, tmp_path):
        svc = self._make_service(tmp_path)
        data = ProfilesData(
            active_profile="default",
            profiles={"default": ProfileSettings(name="Test")},
        )
        svc.save(data)
        loaded = svc.load()
        assert loaded.profiles["default"].name == "Test"

    def test_get_active_profile(self, tmp_path):
        svc = self._make_service(tmp_path)
        data = ProfilesData(
            active_profile="default",
            profiles={"default": ProfileSettings(name="Active", username="user1")},
        )
        svc.save(data)
        profile = svc.get_active_profile()
        assert profile.username == "user1"

    def test_set_active_profile_not_found(self, tmp_path):
        svc = self._make_service(tmp_path)
        ok, msg = svc.set_active_profile("nonexistent")
        assert ok is False
        assert "不存在" in msg

    def test_set_active_profile_success(self, tmp_path):
        svc = self._make_service(tmp_path)
        data = ProfilesData(
            active_profile="default",
            profiles={
                "default": ProfileSettings(name="Default"),
                "other": ProfileSettings(name="Other"),
            },
        )
        svc.save(data)
        ok, msg = svc.set_active_profile("other")
        assert ok is True
        loaded = svc.load()
        assert loaded.active_profile == "other"

    def test_delete_default_profile(self, tmp_path):
        svc = self._make_service(tmp_path)
        ok, msg = svc.delete_profile("default")
        assert ok is False
        assert "不能删除" in msg

    def test_delete_profile(self, tmp_path):
        svc = self._make_service(tmp_path)
        data = ProfilesData(
            active_profile="default",
            profiles={
                "default": ProfileSettings(name="Default"),
                "temp": ProfileSettings(name="Temp"),
            },
        )
        svc.save(data)
        ok, msg = svc.delete_profile("temp")
        assert ok is True
        loaded = svc.load()
        assert "temp" not in loaded.profiles

    def test_save_profile_encrypts_password(self, tmp_path):
        svc = self._make_service(tmp_path)
        settings = ProfileSettings(name="Test", username="user", password="plain")
        ok, msg = svc.save_profile("test", settings)
        assert ok is True
        loaded = svc.load()
        assert loaded.profiles["test"].password.startswith("ENC:")

    def test_save_profile_preserves_masked_password(self, tmp_path):
        svc = self._make_service(tmp_path)
        existing = ProfileSettings(name="Test", username="user", password="ENC:existing")
        svc.save_profile("test", existing)
        settings = ProfileSettings(name="Test", username="user", password="••••••")
        ok, msg = svc.save_profile("test", settings)
        assert ok is True
        loaded = svc.load()
        assert loaded.profiles["test"].password == "ENC:existing"

    def test_detect_matching_profile_no_match(self, tmp_path):
        svc = self._make_service(tmp_path)
        data = ProfilesData(
            active_profile="default",
            profiles={"default": ProfileSettings(name="Default", match_gateway_ip="10.0.0.1")},
        )
        svc.save(data)
        with patch("backend.profile_service.detect_gateway_ip", return_value="192.168.1.1"):
            with patch("backend.profile_service.detect_wifi_ssid", return_value=None):
                result = svc.detect_matching_profile()
                assert result is None

    def test_detect_matching_profile_gateway(self, tmp_path):
        svc = self._make_service(tmp_path)
        data = ProfilesData(
            active_profile="default",
            profiles={"default": ProfileSettings(name="Default", match_gateway_ip="192.168.1.1")},
        )
        svc.save(data)
        with patch("backend.profile_service.detect_gateway_ip", return_value="192.168.1.1"):
            with patch("backend.profile_service.detect_wifi_ssid", return_value=None):
                result = svc.detect_matching_profile()
                assert result == "default"

    def test_set_auto_switch(self, tmp_path):
        svc = self._make_service(tmp_path)
        svc.set_auto_switch(True)
        data = svc.load()
        assert data.auto_switch is True

    def test_invalidate_cache(self, tmp_path):
        svc = self._make_service(tmp_path)
        svc.load()
        svc.invalidate_cache()
        assert svc._data is None
