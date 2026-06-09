"""变量解析器测试 — 覆盖 VariableResolver 的核心逻辑。"""

from __future__ import annotations

import pytest

from app.tasks.models import StepError, TaskConfig
from app.tasks.variable_resolver import VariableResolver

# ── fixtures ──


def _make_config(url="http://example.com", variables=None, steps=None):
    """创建测试用 TaskConfig。"""
    return TaskConfig(
        name="test",
        url=url,
        description="test task",
        variables=variables or {},
        steps=steps or [],
    )


# ── 基础解析 ──


class TestBasicResolve:
    """基础变量解析。"""

    def test_no_template_returns_original(self):
        """无模板标记的字符串原样返回。"""
        resolver = VariableResolver(_make_config(), {})
        assert resolver.resolve("hello") == "hello"
        assert resolver.resolve("") == ""

    def test_non_string_passthrough(self):
        """非字符串类型原样返回。"""
        resolver = VariableResolver(_make_config(), {})
        assert resolver.resolve(42) == 42
        assert resolver.resolve(None) is None
        assert resolver.resolve(True) is True

    def test_template_vars_resolution(self):
        """模板变量解析。"""
        resolver = VariableResolver(
            _make_config(), {"USERNAME": "admin", "PASSWORD": "123"}
        )
        assert resolver.resolve("{{USERNAME}}") == "admin"
        assert resolver.resolve("{{PASSWORD}}") == "123"

    def test_mixed_template_and_text(self):
        """模板和文本混合。"""
        resolver = VariableResolver(_make_config(), {"HOST": "example.com"})
        assert resolver.resolve("http://{{HOST}}/login") == "http://example.com/login"

    def test_multiple_vars_in_one_string(self):
        """一个字符串中多个变量。"""
        resolver = VariableResolver(_make_config(), {"A": "hello", "B": "world"})
        assert resolver.resolve("{{A}} {{B}}") == "hello world"


# ── 优先级 ──


class TestVariablePriority:
    """变量查找优先级：runtime > template > task variables。"""

    def test_runtime_overrides_template(self):
        """运行时变量优先于模板变量。"""
        resolver = VariableResolver(_make_config(), {"X": "template"})
        resolver.set_runtime_var("X", "runtime")
        assert resolver.resolve("{{X}}") == "runtime"

    def test_template_overrides_task_vars(self):
        """模板变量优先于任务变量。"""
        config = _make_config(variables={"X": "task_var"})
        resolver = VariableResolver(config, {"X": "template"})
        assert resolver.resolve("{{X}}") == "template"

    def test_task_vars_fallback(self):
        """任务变量作为兜底。"""
        config = _make_config(variables={"X": "task_var"})
        resolver = VariableResolver(config, {})
        assert resolver.resolve("{{X}}") == "task_var"

    def test_unresolved_var_preserved(self):
        """未解析的变量保留原样。"""
        resolver = VariableResolver(_make_config(), {})
        assert resolver.resolve("{{UNKNOWN}}") == "{{UNKNOWN}}"


# ── 递归解析 ──


class TestRecursiveResolve:
    """变量嵌套和循环引用。"""

    def test_nested_variable_resolution(self):
        """嵌套变量解析。"""
        config = _make_config(variables={"INNER": "value", "OUTER": "{{INNER}}"})
        resolver = VariableResolver(config, {})
        assert resolver.resolve("{{OUTER}}") == "value"

    def test_circular_reference_raises(self):
        """循环引用应抛出异常。"""
        config = _make_config(variables={"A": "{{B}}", "B": "{{A}}"})
        resolver = VariableResolver(config, {})
        with pytest.raises(StepError, match="循环引用"):
            resolver.resolve("{{A}}")

    def test_max_depth_raises(self):
        """超过最大展开层级应抛出异常。"""
        # 构造深度为 MAX_DEPTH+1 的嵌套链
        variables = {}
        for i in range(VariableResolver.MAX_DEPTH + 2):
            variables[f"VAR{i}"] = f"{{{{VAR{i + 1}}}}}"
        config = _make_config(variables=variables)
        resolver = VariableResolver(config, {})
        with pytest.raises(StepError, match="层级超过限制"):
            resolver.resolve("{{VAR0}}")


# ── 缓存 ──


class TestCaching:
    """解析结果缓存。"""

    def test_cache_hit(self):
        """相同输入返回缓存结果。"""
        resolver = VariableResolver(_make_config(), {"X": "cached"})
        r1 = resolver.resolve("{{X}}")
        r2 = resolver.resolve("{{X}}")
        assert r1 == r2 == "cached"

    def test_cache_cleared_on_set_runtime_var(self):
        """设置运行时变量后缓存清空。"""
        resolver = VariableResolver(_make_config(), {"X": "old"})
        resolver.resolve("{{X}}")
        resolver.set_runtime_var("X", "new")
        assert resolver.resolve("{{X}}") == "new"


# ── resolve_for_js ──


class TestResolveForJs:
    """JavaScript 安全编码。"""

    def test_basic_js_resolve(self):
        """基本 JS 解析。"""
        resolver = VariableResolver(_make_config(), {"PASS": "hello"})
        result = resolver.resolve_for_js("{{PASS}}")
        assert result == '"hello"'

    def test_special_chars_escaped(self):
        """特殊字符转义。"""
        resolver = VariableResolver(_make_config(), {"PASS": "a'b\"c"})
        result = resolver.resolve_for_js("{{PASS}}")
        # json.dumps 会转义引号
        assert '"' in result
        assert "a'b" in result

    def test_unresolved_var_empty_string(self):
        """未解析变量在 JS 中返回空字符串。"""
        resolver = VariableResolver(_make_config(), {})
        result = resolver.resolve_for_js("{{MISSING}}")
        assert result == '""'

    def test_non_template_passthrough(self):
        """无模板标记原样返回。"""
        resolver = VariableResolver(_make_config(), {})
        assert resolver.resolve_for_js("plain text") == "plain text"

    def test_non_string_passthrough(self):
        """非字符串原样返回。"""
        resolver = VariableResolver(_make_config(), {})
        assert resolver.resolve_for_js(42) == 42
