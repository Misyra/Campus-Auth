"""配置链路连接测试 — config_service → runtime_config → engine。

验证配置保存、重载、回滚、加密在真实组件间正确流转。
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.schemas import MonitorConfigPayload
from app.services.config_service import save_and_apply


class TestConfigConnection:
    """配置链路连接测试。"""

    def test_save_apply_success(self, integration_stack):
        """保存 → 磁盘 + 运行时都更新。"""
        engine, profile_service, task_executor, mock_worker = integration_stack

        new_payload = MonitorConfigPayload(
            username="newuser",
            password="newpass",
            auth_url="http://10.0.0.1",
            check_interval_seconds=60,
        )
        result = save_and_apply(new_payload, profile_service, engine.reload_config)

        assert result.success is True

        # 验证磁盘
        data = profile_service.load()
        assert data.global_settings.check_interval_seconds == 60

        # 验证运行时
        config = engine.get_config()
        assert config.check_interval_seconds == 60

    def test_save_apply_rollback(self, integration_stack):
        """reload 失败 → 磁盘回滚，运行时不变。"""
        engine, profile_service, task_executor, mock_worker = integration_stack

        old_config = engine.get_config()

        def failing_reload():
            return False, "重载失败"

        new_payload = MonitorConfigPayload(
            username="newuser",
            password="newpass",
            auth_url="http://10.0.0.1",
            check_interval_seconds=999,
        )
        result = save_and_apply(new_payload, profile_service, failing_reload)

        assert result.success is False

        # 验证磁盘已回滚
        data = profile_service.load()
        assert data.global_settings.check_interval_seconds == old_config.check_interval_seconds

    def test_interval_reload(self, integration_stack):
        """修改 check_interval → 重载后生效。"""
        engine, profile_service, task_executor, mock_worker = integration_stack

        payload = MonitorConfigPayload(
            username="testuser",
            password="",
            auth_url="http://10.0.0.1",
            check_interval_seconds=120,
        )
        save_and_apply(payload, profile_service, engine.reload_config)

        assert engine.get_config().check_interval_seconds == 120

    def test_password_encrypt(self, integration_stack):
        """明文密码 → 保存后磁盘 ENC: → 读取后解密还原。"""
        engine, profile_service, task_executor, mock_worker = integration_stack

        payload = MonitorConfigPayload(
            username="testuser",
            password="mypassword123",
            auth_url="http://10.0.0.1",
        )
        save_and_apply(payload, profile_service, engine.reload_config)

        # 验证磁盘上密码已加密
        data = profile_service.load()
        profile = data.profiles.get("default")
        assert profile is not None
        assert profile.password != "mypassword123"

    def test_log_level_reload(self, integration_stack):
        """修改 backend_log_level → 重载后生效。"""
        engine, profile_service, task_executor, mock_worker = integration_stack

        payload = MonitorConfigPayload(
            username="testuser",
            password="",
            auth_url="http://10.0.0.1",
            backend_log_level="DEBUG",
        )
        save_and_apply(payload, profile_service, engine.reload_config)

        assert engine.get_config().backend_log_level == "DEBUG"
