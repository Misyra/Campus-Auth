from __future__ import annotations

from app.schemas import ProfileSettings, ProfilesData, SystemSettings


class TestMigrateConfig:
    def test_migrate_credentials_to_default_profile(self):
        """测试迁移凭证到 default profile"""
        from app.services.runtime_config import migrate_config_if_needed

        # 创建旧格式的数据（模拟有 system 字段的情况）
        system = SystemSettings()
        system.username = "testuser"
        system.password = "testpass"
        system.auth_url = "http://example.com"
        system.carrier = "移动"

        data = ProfilesData()
        # 模拟旧格式：使用 object.__setattr__ 绕过 Pydantic 限制
        object.__setattr__(data, 'system', system)

        # 执行迁移
        result = migrate_config_if_needed(data)

        # 验证迁移结果
        assert result.profiles["default"].username == "testuser"
        assert result.profiles["default"].password == "testpass"
        assert result.profiles["default"].auth_url == "http://example.com"
        assert result.profiles["default"].carrier == "移动"

        # 验证 system 中的凭证已清空
        assert result.system.username == ""
        assert result.system.password == ""
        assert result.system.auth_url == ""
        assert result.system.carrier == "无"

    def test_no_migration_if_no_credentials(self):
        """测试没有凭证时不执行迁移"""
        from app.services.runtime_config import migrate_config_if_needed

        system = SystemSettings()
        data = ProfilesData()
        # 模拟旧格式：使用 object.__setattr__ 绕过 Pydantic 限制
        object.__setattr__(data, 'system', system)

        result = migrate_config_if_needed(data)

        # 验证没有变化
        assert result.profiles["default"].username == ""

    def test_migration_preserves_existing_profile(self):
        """测试迁移保留现有 profile 配置"""
        from app.services.runtime_config import migrate_config_if_needed

        system = SystemSettings()
        system.username = "global_user"
        system.password = "global_pass"

        existing_profile = ProfileSettings(
            username="profile_user",
            password="profile_pass",
        )

        data = ProfilesData(profiles={"default": existing_profile})
        # 模拟旧格式：使用 object.__setattr__ 绕过 Pydantic 限制
        object.__setattr__(data, 'system', system)

        result = migrate_config_if_needed(data)

        # 验证保留了现有的 profile 配置
        assert result.profiles["default"].username == "profile_user"
        assert result.profiles["default"].password == "profile_pass"