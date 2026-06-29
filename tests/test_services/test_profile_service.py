"""测试 ProfileService 的 load/save 逻辑。"""

from __future__ import annotations

import json
from pathlib import Path

from app.schemas import Profile, ProfilesData
from app.services.profile_service import ProfileService


class TestProfileServiceLoad:
    """测试 load 方法"""

    def test_load_returns_default_when_file_missing(self, tmp_path: Path):
        """文件不存在时返回默认 ProfilesData"""
        service = ProfileService(tmp_path)
        data = service.load()

        assert isinstance(data, ProfilesData)
        assert data.active_profile == "default"
        assert "default" in data.profiles

    def test_load_reads_settings_json(self, tmp_path: Path):
        """从 settings.json 正确读取数据"""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        settings = {
            "auto_switch": True,
            "active_profile": "campus",
            "global_config": {"logging": {"level": "DEBUG"}},
            "profiles": {
                "default": {"username": "user1"},
                "campus": {"username": "user2", "match_ssid": "CampusWiFi"},
            },
        }
        (config_dir / "settings.json").write_text(
            json.dumps(settings), encoding="utf-8"
        )

        service = ProfileService(tmp_path)
        data = service.load()

        assert data.auto_switch is True
        assert data.active_profile == "campus"
        assert data.global_config.logging.level == "DEBUG"
        assert data.profiles["default"].username == "user1"
        assert data.profiles["campus"].username == "user2"
        assert data.profiles["campus"].match_ssid == "CampusWiFi"

    def test_load_handles_corrupt_file(self, tmp_path: Path):
        """损坏文件被备份，返回默认数据"""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "settings.json").write_text("not valid json{{{", encoding="utf-8")

        service = ProfileService(tmp_path)
        data = service.load()

        assert isinstance(data, ProfilesData)
        # 损坏文件应被备份
        corrupt_files = list(config_dir.glob("settings.corrupt.*.json"))
        assert len(corrupt_files) == 1

    def test_load_returns_new_instance_each_time(self, tmp_path: Path):
        """每次 load 返回新实例（无缓存），数据一致"""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        settings = {"active_profile": "default", "profiles": {"default": {}}}
        (config_dir / "settings.json").write_text(
            json.dumps(settings), encoding="utf-8"
        )

        service = ProfileService(tmp_path)
        data1 = service.load()
        data2 = service.load()

        # 每次返回新实例，不是同一个对象
        assert data1 is not data2
        assert data1.profiles is not data2.profiles
        assert data1.active_profile == data2.active_profile


class TestProfileServiceSave:
    """测试 save 方法"""

    def test_save_creates_settings_json(self, tmp_path: Path):
        """save 创建 settings.json 文件"""
        service = ProfileService(tmp_path)
        data = ProfilesData(
            auto_switch=True,
            active_profile="campus",
            profiles={
                "default": Profile(username="user1"),
                "campus": Profile(username="user2"),
            },
        )
        service.save(data)

        settings_path = tmp_path / "config" / "settings.json"
        assert settings_path.exists()

        saved = json.loads(settings_path.read_text(encoding="utf-8"))
        assert saved["auto_switch"] is True
        assert saved["active_profile"] == "campus"
        assert "default" in saved["profiles"]
        assert "campus" in saved["profiles"]
        assert saved["profiles"]["default"]["username"] == "user1"
        assert saved["profiles"]["campus"]["username"] == "user2"

    def test_save_then_load_roundtrip(self, tmp_path: Path):
        """保存后加载，数据一致"""
        service = ProfileService(tmp_path)
        original = ProfilesData(
            auto_switch=True,
            active_profile="test",
            profiles={
                "default": Profile(username="user1", password="encrypted"),
                "test": Profile(
                    username="user2",
                    match_ssid="TestSSID",
                    match_gateway_ip="192.168.1.1",
                ),
            },
        )
        service.save(original)

        # 清除缓存后重新加载
        service2 = ProfileService(tmp_path)
        loaded = service2.load()

        assert loaded.auto_switch == original.auto_switch
        assert loaded.active_profile == original.active_profile
        assert loaded.profiles["default"].username == "user1"
        assert loaded.profiles["default"].password == "encrypted"
        assert loaded.profiles["test"].username == "user2"
        assert loaded.profiles["test"].match_ssid == "TestSSID"
        assert loaded.profiles["test"].match_gateway_ip == "192.168.1.1"

    def test_save_does_not_create_profiles_directory(self, tmp_path: Path):
        """save 不再创建 profiles 子目录"""
        service = ProfileService(tmp_path)
        data = ProfilesData()
        service.save(data)

        profiles_dir = tmp_path / "config" / "profiles"
        assert not profiles_dir.exists()
