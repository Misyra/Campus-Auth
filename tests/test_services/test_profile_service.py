"""测试 ProfileService 的 load/save 逻辑。"""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from app.schemas import GlobalConfig, Profile, ProfilesData
from app.services.profile_service import ProfileService, reset_profile_service_singleton


@pytest.fixture(autouse=True)
def _reset_singleton():
    """每个测试前重置单例，避免缓存污染。"""
    reset_profile_service_singleton()
    yield
    reset_profile_service_singleton()


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

    def test_load_returns_cached_instance_when_unchanged(self, tmp_path: Path):
        """mtime 未变时 load 返回缓存引用（同一对象）"""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        settings = {"active_profile": "default", "profiles": {"default": {}}}
        (config_dir / "settings.json").write_text(
            json.dumps(settings), encoding="utf-8"
        )

        service = ProfileService(tmp_path)
        data1 = service.load()
        data2 = service.load()

        # 缓存命中，同一引用
        assert data1 is data2
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


class TestProfileServiceCache:
    """测试 mtime 缓存行为"""

    def test_load_caches_result(self, tmp_path):
        """第二次 load() 应命中缓存，不读盘。"""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        settings = {"active_profile": "default", "profiles": {"default": {}}}
        (config_dir / "settings.json").write_text(
            json.dumps(settings), encoding="utf-8"
        )

        ps = ProfileService(tmp_path)
        # 第一次 load：读盘
        data1 = ps.load()
        # mock read_text 验证第二次不读盘
        with patch.object(Path, "read_text") as mock_read:
            mock_read.side_effect = AssertionError("应命中缓存，不应读盘")
            data2 = ps.load()
        assert data2 is data1  # 同一引用（缓存）

    def test_mtime_change_invalidates_cache(self, tmp_path):
        """文件 mtime 变化时缓存失效，重新读盘。"""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        settings = {"active_profile": "default", "profiles": {"default": {}}}
        (config_dir / "settings.json").write_text(
            json.dumps(settings), encoding="utf-8"
        )

        ps = ProfileService(tmp_path)
        data1 = ps.load()
        # 模拟外部修改文件（touch 更新 mtime）
        settings_path = config_dir / "settings.json"
        time.sleep(0.1)
        settings_path.touch()
        data2 = ps.load()
        assert data2 is not data1  # 缓存失效，新对象

    def test_update_refreshes_cache(self, tmp_path):
        """update() 写盘后缓存应刷新。"""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        settings = {"active_profile": "default", "profiles": {"default": {}}}
        (config_dir / "settings.json").write_text(
            json.dumps(settings), encoding="utf-8"
        )

        ps = ProfileService(tmp_path)
        ps.load()
        ps.update(lambda d: d)  # 无修改但触发 save
        # 下一次 load 应从缓存返回最新数据
        with patch.object(Path, "read_text") as mock_read:
            mock_read.side_effect = AssertionError("update 后应命中缓存")
            ps.load()


class TestFrozenModels:
    def test_global_config_frozen(self):
        """GlobalConfig 应为 frozen。"""
        from pydantic import ValidationError

        cfg = GlobalConfig()
        with pytest.raises(ValidationError):
            cfg.browser = GlobalConfig().browser  # setattr 应抛错

    def test_profiles_data_frozen(self):
        """ProfilesData 应为 frozen。"""
        from pydantic import ValidationError

        data = ProfilesData()
        with pytest.raises(ValidationError):
            data.active_profile = "test"

    def test_profile_frozen(self):
        """Profile 应为 frozen。"""
        from pydantic import ValidationError

        p = Profile()
        with pytest.raises(ValidationError):
            p.name = "test"
