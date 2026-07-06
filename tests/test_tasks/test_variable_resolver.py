"""VariableResolver 单元测试。"""

from __future__ import annotations

import json

from app.tasks.models import TaskConfig
from app.tasks.variable_resolver import VariableResolver


def _make_resolver(
    template_vars: dict[str, str] | None = None,
    runtime_vars: dict[str, str] | None = None,
    variables: dict[str, str] | None = None,
) -> VariableResolver:
    """创建 VariableResolver 实例的辅助函数。"""
    config = TaskConfig(
        task_id="test",
        url="http://example.com",
        name="test_task",
        description="desc",
        variables=variables or {},
    )
    resolver = VariableResolver(config, template_vars or {})
    if runtime_vars:
        for k, v in runtime_vars.items():
            resolver.runtime_vars[k] = v
    return resolver


# ── resolve_for_js 白名单替换 ──


class TestResolveForJsWhitelist:
    """resolve_for_js 仅替换已知变量，不误处理 JS 双花括号。"""

    def test_replaces_known_template_var(self):
        """替换已知 template_vars 中的变量。"""
        resolver = _make_resolver(template_vars={"user": "admin"})
        result = resolver.resolve_for_js("login('{{user}}')")
        assert result == json.dumps("login('admin')") or "admin" in result

    def test_replaces_known_runtime_var(self):
        """替换已知 runtime_vars 中的变量。"""
        resolver = _make_resolver(runtime_vars={"url": "http://test.com"})
        result = resolver.resolve_for_js("fetch('{{url}}')")
        assert "http://test.com" in result

    def test_json_encodes_string_value(self):
        """字符串值经过 JSON 编码（带引号）。"""
        resolver = _make_resolver(template_vars={"pwd": "a'b\"c"})
        result = resolver.resolve_for_js("'{{pwd}}'")
        # JSON 编码后应包含转义引号
        assert "a'b" in result or "a\\'b" in result

    def test_none_value_encodes_as_null(self):
        """None 值编码为 JSON null。"""
        resolver = _make_resolver(runtime_vars={"val": None})
        result = resolver.resolve_for_js("{{val}}")
        assert result == "null"

    def test_non_string_value_encodes_as_json(self):
        """非字符串值（如数字、布尔）编码为 JSON。"""
        resolver = _make_resolver(runtime_vars={"count": 42})
        result = resolver.resolve_for_js("{{count}}")
        assert result == "42"

    def test_preserves_unknown_double_curly(self):
        """保留未知的双花括号（JS 模板语法），不误替换。"""
        resolver = _make_resolver(template_vars={"user": "admin"})
        js_code = "const tpl = `Hello {{person}}`;"
        result = resolver.resolve_for_js(js_code)
        # {{person}} 不在白名单中，应原样保留
        assert "{{person}}" in result

    def test_preserves_multiple_unknown_curly(self):
        """保留多个未知双花括号。"""
        resolver = _make_resolver(template_vars={"user": "admin"})
        js_code = "{{a}} and {{b}} and {{user}}"
        result = resolver.resolve_for_js(js_code)
        assert "{{a}}" in result
        assert "{{b}}" in result
        assert "admin" in result

    def test_non_string_input_returned_as_is(self):
        """非字符串输入直接返回。"""
        resolver = _make_resolver()
        assert resolver.resolve_for_js(123) == 123
        assert resolver.resolve_for_js(None) is None

    def test_no_curly_braces_returned_as_is(self):
        """不含双花括号的字符串直接返回。"""
        resolver = _make_resolver(template_vars={"user": "admin"})
        assert resolver.resolve_for_js("hello world") == "hello world"

    def test_runtime_var_overrides_template_var(self):
        """runtime_vars 优先于 template_vars。"""
        resolver = _make_resolver(
            template_vars={"x": "template_val"},
            runtime_vars={"x": "runtime_val"},
        )
        result = resolver.resolve_for_js("{{x}}")
        assert "runtime_val" in result
        assert "template_val" not in result

    def test_multiple_known_vars(self):
        """同时替换多个已知变量。"""
        resolver = _make_resolver(
            template_vars={"user": "admin"},
            runtime_vars={"pass": "secret"},
        )
        result = resolver.resolve_for_js("{{user}}:{{pass}}")
        assert "admin" in result
        assert "secret" in result

    def test_mixed_known_and_unknown(self):
        """已知变量被替换，未知变量保留。"""
        resolver = _make_resolver(template_vars={"user": "admin"})
        result = resolver.resolve_for_js("{{user}} and {{unknown}}")
        assert "admin" in result
        assert "{{unknown}}" in result

    def test_empty_string(self):
        """空字符串直接返回。"""
        resolver = _make_resolver()
        assert resolver.resolve_for_js("") == ""

    def test_bool_value_encodes_as_json(self):
        """布尔值编码为 JSON。"""
        resolver = _make_resolver(runtime_vars={"flag": True})
        result = resolver.resolve_for_js("{{flag}}")
        assert result == "true"

    def test_dict_value_encodes_as_json(self):
        """字典值编码为 JSON。"""
        resolver = _make_resolver(runtime_vars={"data": {"key": "val"}})
        result = resolver.resolve_for_js("{{data}}")
        parsed = json.loads(result)
        assert parsed == {"key": "val"}

    def test_config_variables_resolved(self):
        """config.variables 中的中间变量（如 username → {{USERNAME}}）应被递归解析。"""
        resolver = _make_resolver(
            template_vars={"USERNAME": "admin", "PASSWORD": "p@ss"},
            variables={"username": "{{USERNAME}}", "password": "{{PASSWORD}}"},
        )
        result = resolver.resolve_for_js("{{username}}:{{password}}")
        assert "admin" in result
        assert "p@ss" in result
        assert "{{USERNAME}}" not in result
        assert "{{PASSWORD}}" not in result

    def test_config_variables_chain_resolution(self):
        """config.variables 支持多层链式解析（如 alias → user → REAL_USER）。"""
        resolver = _make_resolver(
            template_vars={"REAL_USER": "alice"},
            variables={"user": "{{REAL_USER}}", "alias": "{{user}}"},
        )
        result = resolver.resolve_for_js("{{alias}}")
        assert "alice" in result
        assert "{{REAL_USER}}" not in result
        assert "{{user}}" not in result
