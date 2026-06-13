"""测试 env.py 自定义变量覆盖内置变量的保护行为"""

from __future__ import annotations

from app.utils.env import build_login_template_vars


class TestBuiltinVarProtection:
    """自定义变量不应覆盖内置变量（LOGIN_URL、ISP、USERNAME、PASSWORD）"""

    def test_custom_vars_cannot_override_login_url(self):
        """自定义变量不应覆盖 LOGIN_URL"""
        config = {
            "auth_url": "http://10.0.0.1/login",
            "username": "user",
            "password": "pass",
            "isp": "移动",
        }
        custom = {"LOGIN_URL": "http://evil.com"}
        result = build_login_template_vars(config, custom_variables=custom)
        assert result["LOGIN_URL"] == "http://10.0.0.1/login"

    def test_custom_vars_cannot_override_isp(self):
        """自定义变量不应覆盖 ISP"""
        config = {
            "auth_url": "http://10.0.0.1/login",
            "username": "user",
            "password": "pass",
            "isp": "移动",
        }
        custom = {"ISP": "evil_isp"}
        result = build_login_template_vars(config, custom_variables=custom)
        assert result["ISP"] == "移动"

    def test_custom_vars_cannot_override_username(self):
        """自定义变量不应覆盖 USERNAME"""
        config = {
            "auth_url": "http://10.0.0.1/login",
            "username": "real_user",
            "password": "pass",
            "isp": "移动",
        }
        custom = {"USERNAME": "evil_user"}
        result = build_login_template_vars(config, custom_variables=custom)
        assert result["USERNAME"] == "real_user"

    def test_custom_vars_cannot_override_password(self):
        """自定义变量不应覆盖 PASSWORD"""
        config = {
            "auth_url": "http://10.0.0.1/login",
            "username": "user",
            "password": "real_pass",
            "isp": "移动",
        }
        custom = {"PASSWORD": "evil_pass"}
        result = build_login_template_vars(config, custom_variables=custom)
        assert result["PASSWORD"] == "real_pass"

    def test_custom_vars_cannot_override_lowercase_builtin(self):
        """小写版本的内置变量名也不应覆盖"""
        config = {
            "auth_url": "http://10.0.0.1/login",
            "username": "user",
            "password": "pass",
            "isp": "移动",
        }
        custom = {"login_url": "http://evil.com", "isp": "evil"}
        result = build_login_template_vars(config, custom_variables=custom)
        assert result["LOGIN_URL"] == "http://10.0.0.1/login"
        assert result["ISP"] == "移动"

    def test_non_builtin_custom_vars_allowed(self):
        """非内置变量的自定义变量应正常注入"""
        config = {
            "auth_url": "http://10.0.0.1/login",
            "username": "user",
            "password": "pass",
        }
        custom = {"MY_VAR": "hello", "OTHER": "world"}
        result = build_login_template_vars(config, custom_variables=custom)
        assert result["MY_VAR"] == "hello"
        assert result["OTHER"] == "world"
