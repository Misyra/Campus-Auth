"""env.py 模板替换测试 — 验证单次非递归替换行为。"""

from __future__ import annotations

from app.utils.env import build_login_template_vars


class TestBuildLoginTemplateVars:
    """build_login_template_vars 基础功能测试。"""

    def test_basic_substitution(self):
        """task_url 中的 {{VAR}} 应被正确替换。"""
        result = build_login_template_vars(
            auth_url="http://10.0.0.1/login",
            task_url="http://10.0.0.1/login?redirect={{REDIRECT}}",
            custom_variables={"REDIRECT": "http://example.com"},
        )
        assert result["LOGIN_URL"] == "http://10.0.0.1/login?redirect=http://example.com"

    def test_multiple_vars(self):
        """多个变量应全部被替换。"""
        result = build_login_template_vars(
            auth_url="http://10.0.0.1/login",
            task_url="http://{{HOST}}:{{PORT}}/login",
            custom_variables={"HOST": "10.0.0.1", "PORT": "8080"},
        )
        assert result["LOGIN_URL"] == "http://10.0.0.1:8080/login"

    def test_undefined_var_unchanged(self):
        """未定义的变量应保留原始占位符。"""
        result = build_login_template_vars(
            auth_url="http://10.0.0.1/login",
            task_url="http://10.0.0.1/{{UNDEFINED}}",
        )
        assert result["LOGIN_URL"] == "http://10.0.0.1/{{UNDEFINED}}"

    def test_no_task_url(self):
        """无 task_url 时应使用 auth_url 原值。"""
        result = build_login_template_vars(auth_url="http://10.0.0.1/login")
        assert result["LOGIN_URL"] == "http://10.0.0.1/login"

    def test_empty_task_url(self):
        """空 task_url 应使用 auth_url 原值。"""
        result = build_login_template_vars(
            auth_url="http://10.0.0.1/login",
            task_url="",
        )
        assert result["LOGIN_URL"] == "http://10.0.0.1/login"


class TestNoDoubleReplacement:
    """防止双重替换的核心测试。"""

    def test_no_double_replacement(self):
        """变量值中包含 {{VAR}} 模式时不应被二次替换。

        场景：USERNAME 的值恰好包含 {{PASSWORD}} 占位符，
        替换 USERNAME 后结果中的 {{PASSWORD}} 不应再被展开。
        """
        result = build_login_template_vars(
            auth_url="http://10.0.0.1/login",
            task_url="http://10.0.0.1/{{USERNAME}}/{{PASSWORD}}",
            username="user_{{PASSWORD}}",
            password="secret",
        )
        # 如果发生双重替换，LOGIN_URL 会变成 "http://10.0.0.1/user_secret/secret"
        # 但 {{PASSWORD}} 在 USERNAME 的值中不应被二次展开
        # 由于是单次替换，结果应为 "http://10.0.0.1/user_{{PASSWORD}}/secret"
        assert result["LOGIN_URL"] == "http://10.0.0.1/user_{{PASSWORD}}/secret"

    def test_value_with_literal_braces_not_confused(self):
        """变量值中的花括号不应被误识别为模板变量。"""
        result = build_login_template_vars(
            auth_url="http://10.0.0.1/login",
            task_url="http://10.0.0.1/{{USERNAME}}",
            username="admin{not_var}",
        )
        assert result["LOGIN_URL"] == "http://10.0.0.1/admin{not_var}"

    def test_same_var_referenced_twice(self):
        """同一变量引用两次应两次都被替换。"""
        result = build_login_template_vars(
            auth_url="http://10.0.0.1/login",
            task_url="http://{{HOST}}/{{HOST}}/login",
            custom_variables={"HOST": "10.0.0.1"},
        )
        assert result["LOGIN_URL"] == "http://10.0.0.1/10.0.0.1/login"


class TestEdgeCases:
    """边界情况测试。"""

    def test_adjacent_vars(self):
        """相邻变量应各自独立替换。"""
        result = build_login_template_vars(
            auth_url="http://10.0.0.1/login",
            task_url="http://{{A}}{{B}}/login",
            custom_variables={"A": "10.0", "B": ".0.1"},
        )
        assert result["LOGIN_URL"] == "http://10.0.0.1/login"

    def test_var_in_middle_of_string(self):
        """字符串中间的变量应被正确替换。"""
        result = build_login_template_vars(
            auth_url="http://10.0.0.1/login",
            task_url="prefix_{{MID}}_suffix",
            custom_variables={"MID": "middle"},
        )
        assert result["LOGIN_URL"] == "prefix_middle_suffix"

    def test_only_template_syntax_recognized(self):
        """只识别 {{VAR}} 语法，不识别 ${VAR} 或单花括号。"""
        result = build_login_template_vars(
            auth_url="http://10.0.0.1/login",
            task_url="http://${HOST}/{{PORT}}",
            custom_variables={"HOST": "evil", "PORT": "80"},
        )
        # ${HOST} 不应被替换
        assert "${HOST}" in result["LOGIN_URL"]
        # {{PORT}} 应被替换
        assert result["LOGIN_URL"] == "http://${HOST}/80"


# ── 内置变量保护 (from test_env_fix) ──


class TestBuiltinVarProtection:
    """自定义变量不应覆盖内置变量（LOGIN_URL、ISP、USERNAME、PASSWORD）"""

    def test_custom_vars_cannot_override_login_url(self):
        """自定义变量不应覆盖 LOGIN_URL"""
        custom = {"LOGIN_URL": "http://evil.com"}
        result = build_login_template_vars(
            auth_url="http://10.0.0.1/login",
            username="user",
            password="pass",
            isp="移动",
            custom_variables=custom,
        )
        assert result["LOGIN_URL"] == "http://10.0.0.1/login"

    def test_custom_vars_cannot_override_isp(self):
        """自定义变量不应覆盖 ISP"""
        custom = {"ISP": "evil_isp"}
        result = build_login_template_vars(
            auth_url="http://10.0.0.1/login",
            username="user",
            password="pass",
            isp="移动",
            custom_variables=custom,
        )
        assert result["ISP"] == "移动"

    def test_custom_vars_cannot_override_username(self):
        """自定义变量不应覆盖 USERNAME"""
        custom = {"USERNAME": "evil_user"}
        result = build_login_template_vars(
            auth_url="http://10.0.0.1/login",
            username="real_user",
            password="pass",
            isp="移动",
            custom_variables=custom,
        )
        assert result["USERNAME"] == "real_user"

    def test_custom_vars_cannot_override_password(self):
        """自定义变量不应覆盖 PASSWORD"""
        custom = {"PASSWORD": "evil_pass"}
        result = build_login_template_vars(
            auth_url="http://10.0.0.1/login",
            username="user",
            password="real_pass",
            isp="移动",
            custom_variables=custom,
        )
        assert result["PASSWORD"] == "real_pass"

    def test_custom_vars_cannot_override_lowercase_builtin(self):
        """小写版本的内置变量名也不应覆盖"""
        custom = {"login_url": "http://evil.com", "isp": "evil"}
        result = build_login_template_vars(
            auth_url="http://10.0.0.1/login",
            username="user",
            password="pass",
            isp="移动",
            custom_variables=custom,
        )
        assert result["LOGIN_URL"] == "http://10.0.0.1/login"
        assert result["ISP"] == "移动"

    def test_non_builtin_custom_vars_allowed(self):
        """非内置变量的自定义变量应正常注入"""
        custom = {"MY_VAR": "hello", "OTHER": "world"}
        result = build_login_template_vars(
            auth_url="http://10.0.0.1/login",
            username="user",
            password="pass",
            custom_variables=custom,
        )
        assert result["MY_VAR"] == "hello"
        assert result["OTHER"] == "world"
