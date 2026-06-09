"""配置验证工具测试 — 覆盖 ConfigValidator。"""

from __future__ import annotations

from app.utils.config import ConfigValidator

# ── validate_gui_config ──


class TestValidateGuiConfig:
    """GUI 配置验证。"""

    def test_valid_config(self):
        """有效配置。"""
        ok, msg = ConfigValidator.validate_gui_config("admin", "password123", "5")
        assert ok is True
        assert msg == ""

    def test_empty_username(self):
        """空用户名。"""
        ok, msg = ConfigValidator.validate_gui_config("", "password", "5")
        assert ok is False
        assert "账号不能为空" in msg

    def test_empty_password(self):
        """空密码。"""
        ok, msg = ConfigValidator.validate_gui_config("admin", "", "5")
        assert ok is False
        assert "密码不能为空" in msg

    def test_masked_password_accepted(self):
        """掩码密码被接受。"""
        ok, msg = ConfigValidator.validate_gui_config("admin", "••••••••", "5")
        assert ok is True

    def test_short_username(self):
        """用户名过短。"""
        ok, msg = ConfigValidator.validate_gui_config("a", "password", "5")
        assert ok is False
        assert "账号长度不能少于2位" in msg

    def test_short_password(self):
        """密码过短。"""
        ok, msg = ConfigValidator.validate_gui_config("admin", "a", "5")
        assert ok is False
        assert "密码长度不能少于2位" in msg

    def test_masked_password_skip_length_check(self):
        """掩码密码跳过长度检查。"""
        ok, msg = ConfigValidator.validate_gui_config("admin", "•", "5")
        assert ok is True

    def test_invalid_interval_not_number(self):
        """检测间隔非数字。"""
        ok, msg = ConfigValidator.validate_gui_config("admin", "password", "abc")
        assert ok is False
        assert "检测间隔必须是正整数" in msg

    def test_interval_zero(self):
        """检测间隔为 0。"""
        ok, msg = ConfigValidator.validate_gui_config("admin", "password", "0")
        assert ok is False
        assert "检测间隔必须大于0" in msg

    def test_interval_negative(self):
        """检测间隔为负数。"""
        ok, msg = ConfigValidator.validate_gui_config("admin", "password", "-1")
        assert ok is False
        assert "检测间隔必须大于0" in msg

    def test_interval_too_large(self):
        """检测间隔超过 24 小时。"""
        ok, msg = ConfigValidator.validate_gui_config("admin", "password", "86401")
        assert ok is False
        assert "不能超过86400秒" in msg

    def test_interval_max_valid(self):
        """检测间隔最大有效值 86400。"""
        ok, msg = ConfigValidator.validate_gui_config("admin", "password", "86400")
        assert ok is True

    def test_whitespace_trimmed(self):
        """首尾空格被去除。"""
        ok, msg = ConfigValidator.validate_gui_config(
            "  admin  ", "  password  ", "  5  "
        )
        assert ok is True


# ── validate_env_config ──


class TestValidateEnvConfig:
    """环境配置验证。"""

    def test_valid_config(self):
        """有效配置。"""
        config = {
            "username": "admin",
            "password": "password",
            "auth_url": "http://example.com/login",
        }
        ok, msg = ConfigValidator.validate_env_config(config)
        assert ok is True

    def test_missing_username(self):
        """缺少用户名。"""
        config = {"password": "password", "auth_url": "http://example.com"}
        ok, msg = ConfigValidator.validate_env_config(config)
        assert ok is False
        assert "缺少用户名或密码" in msg

    def test_missing_password(self):
        """缺少密码。"""
        config = {"username": "admin", "auth_url": "http://example.com"}
        ok, msg = ConfigValidator.validate_env_config(config)
        assert ok is False
        assert "缺少用户名或密码" in msg

    def test_missing_auth_url(self):
        """缺少认证地址。"""
        config = {"username": "admin", "password": "password"}
        ok, msg = ConfigValidator.validate_env_config(config)
        assert ok is False
        assert "缺少认证地址" in msg

    def test_invalid_auth_url(self):
        """无效认证地址。"""
        config = {
            "username": "admin",
            "password": "password",
            "auth_url": "ftp://example.com",
        }
        ok, msg = ConfigValidator.validate_env_config(config)
        assert ok is False
        assert "http://" in msg

    def test_https_url_accepted(self):
        """HTTPS 地址被接受。"""
        config = {
            "username": "admin",
            "password": "password",
            "auth_url": "https://example.com/login",
        }
        ok, msg = ConfigValidator.validate_env_config(config)
        assert ok is True

    def test_empty_config(self):
        """空配置。"""
        ok, msg = ConfigValidator.validate_env_config({})
        assert ok is False

    def test_empty_username(self):
        """空用户名字符串。"""
        config = {
            "username": "",
            "password": "password",
            "auth_url": "http://example.com",
        }
        ok, msg = ConfigValidator.validate_env_config(config)
        assert ok is False
