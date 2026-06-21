from app.services.config_migration import migrate_v2_to_v3


class TestMigrateV2ToV3:
    """v2 → v3 迁移测试。"""

    def test_basic_migration(self):
        """v2 格式迁移到 v3，凭证从 global_settings 合并到 default profile。"""
        v2 = {
            "auto_switch": False,
            "active_profile": "default",
            "global_settings": {
                "headless": True,
                "browser_timeout": 8,
                "check_interval_seconds": 300,
                "username": "admin",
                "password": "ENC:abc",
                "auth_url": "http://10.0.0.1/login",
                "carrier": "移动",
                "carrier_custom": "",
                "active_task": "",
                "backend_log_level": "INFO",
                "max_retries": 3,
                "retry_interval": 5,
                "pause_enabled": True,
                "pause_start_hour": 0,
                "pause_end_hour": 6,
            },
            "profiles": {
                "default": {
                    "name": "默认方案",
                    "username": "admin",
                    "password": "ENC:abc",
                    "auth_url": "http://10.0.0.1/login",
                },
            },
        }
        result = migrate_v2_to_v3(v2)

        assert result["config_version"] == 3
        assert "global_settings" not in result
        assert "config" in result
        assert result["config"]["browser"]["headless"] is True
        assert result["config"]["monitor"]["check_interval_seconds"] == 300
        assert result["config"]["retry"]["max_retries"] == 3
        # 凭证在 profile 中
        assert result["profiles"]["default"]["username"] == "admin"
        assert result["profiles"]["default"]["password"] == "ENC:abc"

    def test_migration_profile_credential_fallback(self):
        """profile 留空的凭证字段从 global_settings 继承。"""
        v2 = {
            "auto_switch": False,
            "active_profile": "default",
            "global_settings": {
                "username": "global_user",
                "password": "ENC:global",
                "auth_url": "http://global.url",
                "carrier": "联通",
            },
            "profiles": {
                "default": {
                    "name": "默认方案",
                    "username": "",
                    "password": "",
                    "auth_url": "",
                    "carrier": "无",
                },
            },
        }
        result = migrate_v2_to_v3(v2)
        default = result["profiles"]["default"]
        assert default["username"] == "global_user"
        assert default["password"] == "ENC:global"
        assert default["auth_url"] == "http://global.url"
        assert default["carrier"] == "联通"

    def test_migration_creates_default_profile_if_missing(self):
        """没有 default profile 时自动创建。"""
        v2 = {
            "auto_switch": False,
            "active_profile": "default",
            "global_settings": {
                "username": "admin",
                "password": "ENC:abc",
                "auth_url": "http://10.0.0.1/login",
            },
            "profiles": {},
        }
        result = migrate_v2_to_v3(v2)
        assert "default" in result["profiles"]
        assert result["profiles"]["default"]["username"] == "admin"

    def test_migration_preserves_multiple_profiles(self):
        """多个 profile 的凭证各自保留。"""
        v2 = {
            "auto_switch": True,
            "active_profile": "dorm",
            "global_settings": {
                "username": "global",
                "password": "ENC:g",
                "auth_url": "http://global",
            },
            "profiles": {
                "default": {
                    "name": "默认",
                    "username": "default_user",
                    "password": "ENC:d",
                    "auth_url": "http://default",
                },
                "dorm": {
                    "name": "宿舍",
                    "username": "dorm_user",
                    "password": "ENC:dm",
                    "auth_url": "http://dorm",
                    "match_gateway_ip": "10.0.0.1",
                },
            },
        }
        result = migrate_v2_to_v3(v2)
        assert result["active_profile"] == "dorm"
        assert result["profiles"]["dorm"]["username"] == "dorm_user"
        assert result["profiles"]["dorm"]["match_gateway_ip"] == "10.0.0.1"

    def test_migration_v3_passthrough(self):
        """已经是 v3 格式的数据直接返回。"""
        v3 = {"config_version": 3, "config": {}, "profiles": {}}
        result = migrate_v2_to_v3(v3)
        assert result is v3
