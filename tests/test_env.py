"""登录模板变量测试 — 覆盖 build_login_template_vars。"""

from __future__ import annotations

from app.utils.env import build_login_template_vars

# ── build_login_template_vars ──


class TestBuildLoginTemplateVars:
    """登录模板变量构建。"""

    def test_basic_vars(self):
        """基本变量构建。"""
        config = {
            "auth_url": "http://example.com/login",
            "username": "admin",
            "password": "pass123",
            "isp": "移动",
        }
        result = build_login_template_vars(config)
        assert result["LOGIN_URL"] == "http://example.com/login"
        assert result["USERNAME"] == "admin"
        assert result["PASSWORD"] == "pass123"
        assert result["ISP"] == "移动"

    def test_empty_config(self):
        """空配置。"""
        result = build_login_template_vars({})
        assert result == {}

    def test_custom_variables(self):
        """自定义变量。"""
        config = {"auth_url": "http://example.com"}
        custom = {"MY_VAR": "value", "OTHER": "test"}
        result = build_login_template_vars(config, custom_variables=custom)
        assert result["MY_VAR"] == "value"
        assert result["OTHER"] == "test"

    def test_denylist_variable_skipped(self):
        """保留变量名被跳过。"""
        config = {"auth_url": "http://example.com"}
        custom = {"PATH": "/usr/bin", "HOME": "/root"}
        result = build_login_template_vars(config, custom_variables=custom)
        assert "PATH" not in result
        assert "HOME" not in result

    def test_denylist_case_insensitive(self):
        """保留变量名大小写不敏感。"""
        config = {"auth_url": "http://example.com"}
        custom = {"path": "/usr/bin", "Home": "/root"}
        result = build_login_template_vars(config, custom_variables=custom)
        assert "path" not in result
        assert "Home" not in result

    def test_task_url_resolved(self):
        """task_url 中的变量被解析。"""
        config = {
            "auth_url": "http://example.com/login",
            "username": "admin",
        }
        result = build_login_template_vars(config, task_url="http://{{USERNAME}}:{{LOGIN_URL}}")
        assert result["LOGIN_URL"] == "http://admin:http://example.com/login"

    def test_task_url_overrides_login_url(self):
        """task_url 覆盖 LOGIN_URL。"""
        config = {"auth_url": "http://original.com"}
        result = build_login_template_vars(config, task_url="http://custom.com")
        assert result["LOGIN_URL"] == "http://custom.com"

    def test_empty_custom_variables(self):
        """空自定义变量。"""
        config = {"auth_url": "http://example.com"}
        result = build_login_template_vars(config, custom_variables={})
        assert result["LOGIN_URL"] == "http://example.com"

    def test_none_custom_variables(self):
        """None 自定义变量。"""
        config = {"auth_url": "http://example.com"}
        result = build_login_template_vars(config, custom_variables=None)
        assert result["LOGIN_URL"] == "http://example.com"

    def test_non_dict_custom_variables_ignored(self):
        """非字典自定义变量被忽略。"""
        config = {"auth_url": "http://example.com"}
        result = build_login_template_vars(config, custom_variables="not a dict")
        assert result["LOGIN_URL"] == "http://example.com"

    def test_missing_isp(self):
        """缺少 ISP。"""
        config = {"auth_url": "http://example.com", "username": "admin"}
        result = build_login_template_vars(config)
        assert "ISP" not in result

    def test_empty_isp(self):
        """空 ISP。"""
        config = {"auth_url": "http://example.com", "isp": ""}
        result = build_login_template_vars(config)
        assert "ISP" not in result
