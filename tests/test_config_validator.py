"""src/utils/config.py 测试"""
from __future__ import annotations

from src.utils.config import ConfigValidator


class TestValidateGuiConfig:
    def test_valid_config(self):
        """完整有效配置应通过验证"""
        ok, msg = ConfigValidator.validate_gui_config(
            username="testuser",
            password="testpass",
            check_interval="5",
        )
        assert ok is True
        assert msg == ""

    def test_empty_username(self):
        """空用户名应返回失败"""
        ok, msg = ConfigValidator.validate_gui_config(
            username="", password="pass", check_interval="5"
        )
        assert ok is False
        assert "账号" in msg

    def test_masked_password_accepted(self):
        """掩码密码应被接受（用户未修改密码）"""
        ok, msg = ConfigValidator.validate_gui_config(
            username="testuser",
            password="••••••••",
            check_interval="5",
        )
        assert ok is True

    def test_empty_password_without_mask(self):
        """无掩码的空密码应返回失败"""
        ok, msg = ConfigValidator.validate_gui_config(
            username="testuser", password="", check_interval="5"
        )
        assert ok is False
        assert "密码" in msg

    def test_invalid_interval(self):
        """非数字间隔应返回失败"""
        ok, msg = ConfigValidator.validate_gui_config(
            username="testuser", password="testpass", check_interval="abc"
        )
        assert ok is False
        assert "间隔" in msg

    def test_interval_too_large(self):
        """超过 1440 的间隔应返回失败"""
        ok, msg = ConfigValidator.validate_gui_config(
            username="testuser", password="testpass", check_interval="2000"
        )
        assert ok is False


class TestValidateEnvConfig:
    def test_valid_config(self):
        """有效环境配置应返回 True"""
        ok, msg = ConfigValidator.validate_env_config({
            "username": "testuser",
            "password": "testpass",
            "auth_url": "http://10.0.0.1",
        })
        assert ok is True

    def test_missing_username(self):
        """缺少用户名应返回 False"""
        ok, msg = ConfigValidator.validate_env_config({
            "username": "",
            "password": "pass",
            "auth_url": "http://10.0.0.1",
        })
        assert ok is False

    def test_missing_auth_url(self):
        """缺少认证地址应返回 False"""
        ok, msg = ConfigValidator.validate_env_config({
            "username": "user",
            "password": "pass",
            "auth_url": "",
        })
        assert ok is False
