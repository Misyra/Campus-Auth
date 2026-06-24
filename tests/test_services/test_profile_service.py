"""测试 ProfileService 的 load/save 逻辑。"""

from __future__ import annotations

import json
from pathlib import Path

from app.schemas import Profile, ProfilesData
from app.services.profile_service import ProfileService, migrate_v3_to_v4


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
            "config": {"logging": {"level": "DEBUG"}},
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


class TestMigrateV3ToV4:
    """测试 v3 → v4 迁移函数"""

    def test_migrate_v3_to_v4_basic(self):
        """v3 格式正确迁移到 v4"""
        v3_data = {
            "config": {
                "logging": {"level": "DEBUG"},
                "browser": {"headless": True},
                "monitor": {"check_interval_seconds": 300},
            },
            "active_profile": "default",
            "profiles": {"default": {"username": "user1"}},
        }

        result = migrate_v3_to_v4(v3_data)

        # config 应被重命名为 global_config
        assert "config" not in result
        assert "global_config" in result
        assert result["global_config"]["logging"]["level"] == "DEBUG"
        assert result["global_config"]["browser"]["headless"] is True
        assert result["global_config"]["monitor"]["check_interval_seconds"] == 300
        # config_version 应更新为 4
        assert result["config_version"] == 4
        # 其他字段保持不变
        assert result["active_profile"] == "default"
        assert result["profiles"]["default"]["username"] == "user1"

    def test_migrate_v4_no_change(self):
        """v4 格式不做修改"""
        v4_data = {
            "config_version": 4,
            "global_config": {
                "logging": {"level": "INFO"},
            },
            "active_profile": "default",
            "profiles": {"default": {}},
        }

        result = migrate_v3_to_v4(v4_data)

        # 应保持不变
        assert result["config_version"] == 4
        assert "global_config" in result
        assert "config" not in result
        assert result["global_config"]["logging"]["level"] == "INFO"

    def test_migrate_missing_config_field(self):
        """缺少 config 字段时使用空 dict"""
        v3_data = {
            "active_profile": "default",
            "profiles": {"default": {}},
        }

        result = migrate_v3_to_v4(v3_data)

        assert "global_config" in result
        assert result["global_config"] == {}
        assert result["config_version"] == 4

    def test_migrate_strips_credentials(self):
        """credentials 字段被剥离"""
        v3_data = {
            "config": {
                "logging": {"level": "INFO"},
                "credentials": {
                    "username": "admin",
                    "password": "secret123",
                },
            },
            "active_profile": "default",
            "profiles": {"default": {}},
        }

        result = migrate_v3_to_v4(v3_data)

        # credentials 应被移除
        assert "credentials" not in result["global_config"]
        # 其他字段应保留
        assert result["global_config"]["logging"]["level"] == "INFO"

    def test_migrate_strips_active_task(self):
        """active_task 字段被剥离"""
        v3_data = {
            "config": {
                "logging": {"level": "INFO"},
                "active_task": "login",
            },
            "active_profile": "default",
            "profiles": {"default": {}},
        }

        result = migrate_v3_to_v4(v3_data)

        # active_task 应被移除
        assert "active_task" not in result["global_config"]
        assert result["global_config"]["logging"]["level"] == "INFO"

    def test_migrate_strips_custom_variables(self):
        """custom_variables 字段被剥离"""
        v3_data = {
            "config": {
                "logging": {"level": "INFO"},
                "custom_variables": {"key1": "value1"},
            },
            "active_profile": "default",
            "profiles": {"default": {}},
        }

        result = migrate_v3_to_v4(v3_data)

        # custom_variables 保留（属于用户配置）
        assert result["global_config"]["custom_variables"] == {"key1": "value1"}
        assert result["global_config"]["logging"]["level"] == "INFO"

    def test_migrate_strips_all_runtime_fields(self):
        """运行时字段（credentials, active_task）被剥离，custom_variables 保留"""
        v3_data = {
            "config": {
                "logging": {"level": "DEBUG"},
                "credentials": {"username": "admin"},
                "active_task": "monitor",
                "custom_variables": {"env": "production"},
                "browser": {"headless": False},
            },
            "active_profile": "default",
            "profiles": {"default": {}},
        }

        result = migrate_v3_to_v4(v3_data)

        assert "credentials" not in result["global_config"]
        assert "active_task" not in result["global_config"]
        assert result["global_config"]["custom_variables"] == {"env": "production"}
        # 非运行时字段应保留
        assert result["global_config"]["logging"]["level"] == "DEBUG"
        assert result["global_config"]["browser"]["headless"] is False

    def test_migrate_preserves_profiles(self):
        """迁移过程中 profiles 数据完整保留"""
        v3_data = {
            "config": {"logging": {"level": "INFO"}},
            "auto_switch": True,
            "active_profile": "campus",
            "profiles": {
                "default": {"username": "user1", "password": "enc123"},
                "campus": {
                    "username": "user2",
                    "match_ssid": "CampusWiFi",
                    "match_gateway_ip": "192.168.1.1",
                },
            },
        }

        result = migrate_v3_to_v4(v3_data)

        assert result["auto_switch"] is True
        assert result["active_profile"] == "campus"
        assert result["profiles"]["default"]["username"] == "user1"
        assert result["profiles"]["default"]["password"] == "enc123"
        assert result["profiles"]["campus"]["username"] == "user2"
        assert result["profiles"]["campus"]["match_ssid"] == "CampusWiFi"
        assert result["profiles"]["campus"]["match_gateway_ip"] == "192.168.1.1"


class TestProfileServiceLoadMigration:
    """测试 ProfileService 加载时的自动迁移"""

    def test_load_migrates_v3_config_to_global_config(self, tmp_path: Path):
        """加载 v3 格式 settings.json 时自动迁移到 v4"""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        settings = {
            "auto_switch": True,
            "active_profile": "campus",
            "config": {"logging": {"level": "DEBUG"}},
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

        # 应该正确迁移到 global_config
        assert data.global_config.logging.level == "DEBUG"
        assert data.auto_switch is True
        assert data.active_profile == "campus"
        assert data.profiles["default"].username == "user1"
        assert data.profiles["campus"].username == "user2"
        assert data.profiles["campus"].match_ssid == "CampusWiFi"

    def test_load_migrates_v3_with_credentials_stripped(self, tmp_path: Path):
        """加载 v3 格式时，credentials 被剥离"""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        settings = {
            "config": {
                "logging": {"level": "INFO"},
                "credentials": {
                    "username": "admin",
                    "password": "secret123",
                },
            },
            "active_profile": "default",
            "profiles": {"default": {}},
        }
        (config_dir / "settings.json").write_text(
            json.dumps(settings), encoding="utf-8"
        )

        service = ProfileService(tmp_path)
        data = service.load()

        # credentials 应该被剥离
        assert not hasattr(data.global_config, "credentials")
        assert data.global_config.logging.level == "INFO"

    def test_load_migrates_v3_with_active_task_stripped(self, tmp_path: Path):
        """加载 v3 格式时，active_task 被剥离"""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        settings = {
            "config": {
                "logging": {"level": "INFO"},
                "active_task": "login",
            },
            "active_profile": "default",
            "profiles": {"default": {}},
        }
        (config_dir / "settings.json").write_text(
            json.dumps(settings), encoding="utf-8"
        )

        service = ProfileService(tmp_path)
        data = service.load()

        # active_task 应该被剥离
        assert not hasattr(data.global_config, "active_task")
        assert data.global_config.logging.level == "INFO"

    def test_load_handles_v4_format_directly(self, tmp_path: Path):
        """加载 v4 格式时不做迁移，直接使用"""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        settings = {
            "config_version": 4,
            "global_config": {"logging": {"level": "WARNING"}},
            "active_profile": "default",
            "profiles": {"default": {}},
        }
        (config_dir / "settings.json").write_text(
            json.dumps(settings), encoding="utf-8"
        )

        service = ProfileService(tmp_path)
        data = service.load()

        # 应该直接使用 v4 格式
        assert data.global_config.logging.level == "WARNING"
        assert data.config_version == 4
