"""BrowserTaskRunner 单元测试。"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.tasks.browser_runner import BrowserTaskRunner
from app.tasks.models import TaskConfig


@pytest.fixture
def runner_factory():
    """构造 BrowserTaskRunner 的工厂。"""

    def _make(config: TaskConfig | None = None):
        cfg = config or TaskConfig(name="test", task_id="t1")
        return BrowserTaskRunner(cfg, cancel_event=MagicMock())

    return _make


class TestCheckSuccess:
    """_check_success 行为测试。"""

    @pytest.mark.asyncio
    async def test_returns_tuple(self, runner_factory):
        """_check_success 返回 tuple[bool, str]。"""
        runner = runner_factory()
        page = MagicMock()
        ok, reason = await runner._check_success(page)
        assert ok is True
        assert isinstance(reason, str)

    @pytest.mark.asyncio
    async def test_no_monitor_config_attr(self, runner_factory):
        """BrowserTaskRunner 实例不再有 monitor_config 属性。"""
        runner = runner_factory()
        assert not hasattr(runner, "monitor_config")

    @pytest.mark.asyncio
    async def test_no_network_detection_check_method(self, runner_factory):
        """BrowserTaskRunner 不再有 _network_detection_check 方法。"""
        runner = runner_factory()
        assert not hasattr(runner, "_network_detection_check")

    @pytest.mark.asyncio
    async def test_no_js_check_methods(self, runner_factory):
        """BrowserTaskRunner 不再有 _poll_js_expression / _evaluate_js_checks 方法。"""
        runner = runner_factory()
        assert not hasattr(runner, "_poll_js_expression")
        assert not hasattr(runner, "_evaluate_js_checks")


class TestCheckSuccessDefault:
    """未声明 success_condition 的兜底行为。"""

    @pytest.mark.asyncio
    async def test_no_condition_returns_success(self, runner_factory):
        """未声明 success_condition → 默认成功。"""
        runner = runner_factory(TaskConfig(name="t"))
        page = MagicMock()
        ok, reason = await runner._check_success(page)
        assert ok is True
        assert "步骤执行完成" in reason

    @pytest.mark.asyncio
    async def test_no_condition_but_asserted(self, runner_factory):
        """未声明 success_condition 但 _asserted=True → 返回断言文本命中。"""
        runner = runner_factory(TaskConfig(name="t"))
        runner._asserted = True
        page = MagicMock()
        ok, reason = await runner._check_success(page)
        assert ok is True
        assert "断言文本已命中" in reason


class TestCheckSuccessCondition:
    """声明了 success_condition 的判定行为。"""

    @pytest.mark.asyncio
    async def test_truthy_bool_returns_success(self, runner_factory):
        """变量值为 True → 成功。"""
        cfg = TaskConfig(name="t", success_condition="flag")
        runner = runner_factory(cfg)
        runner.resolver.runtime_vars["flag"] = True
        page = MagicMock()
        ok, reason = await runner._check_success(page)
        assert ok is True
        assert "成功条件命中" in reason
        assert "flag=True" in reason

    @pytest.mark.asyncio
    async def test_falsy_bool_returns_failure(self, runner_factory):
        """变量值为 False → 失败（按重试策略重试）。"""
        cfg = TaskConfig(name="t", success_condition="flag")
        runner = runner_factory(cfg)
        runner.resolver.runtime_vars["flag"] = False
        page = MagicMock()
        ok, reason = await runner._check_success(page)
        assert ok is False
        assert "成功条件未命中" in reason
        assert "flag=False" in reason

    @pytest.mark.asyncio
    async def test_var_not_set_returns_failure(self, runner_factory):
        """变量未设置 → 失败，提示检查 store_as。"""
        cfg = TaskConfig(name="t", success_condition="missing")
        runner = runner_factory(cfg)
        page = MagicMock()
        ok, reason = await runner._check_success(page)
        assert ok is False
        assert "变量未设置" in reason
        assert "missing" in reason

    @pytest.mark.asyncio
    async def test_truthy_string_returns_success(self, runner_factory):
        """非空非 'false' 字符串 → 成功。"""
        cfg = TaskConfig(name="t", success_condition="flag")
        runner = runner_factory(cfg)
        runner.resolver.runtime_vars["flag"] = "ok"
        page = MagicMock()
        ok, _ = await runner._check_success(page)
        assert ok is True

    @pytest.mark.asyncio
    async def test_falsy_string_returns_failure(self, runner_factory):
        """'false' / '0' / '' 字符串 → 失败。"""
        for val in ("false", "0", "", "no", "off", "FALSE", "  "):
            cfg = TaskConfig(name="t", success_condition="flag")
            runner = runner_factory(cfg)
            runner.resolver.runtime_vars["flag"] = val
            page = MagicMock()
            ok, _ = await runner._check_success(page)
            assert ok is False, f"value={val!r} 应判定为失败"

    @pytest.mark.asyncio
    async def test_non_zero_number_returns_success(self, runner_factory):
        """非零数字 → 成功。"""
        cfg = TaskConfig(name="t", success_condition="flag")
        runner = runner_factory(cfg)
        runner.resolver.runtime_vars["flag"] = 42
        page = MagicMock()
        ok, _ = await runner._check_success(page)
        assert ok is True

    @pytest.mark.asyncio
    async def test_zero_number_returns_failure(self, runner_factory):
        """零 → 失败。"""
        cfg = TaskConfig(name="t", success_condition="flag")
        runner = runner_factory(cfg)
        runner.resolver.runtime_vars["flag"] = 0
        page = MagicMock()
        ok, _ = await runner._check_success(page)
        assert ok is False

    @pytest.mark.asyncio
    async def test_none_value_returns_failure(self, runner_factory):
        """None → 失败。"""
        cfg = TaskConfig(name="t", success_condition="flag")
        runner = runner_factory(cfg)
        # runtime_vars 中存在该键但值为 None
        runner.resolver.runtime_vars["flag"] = None
        page = MagicMock()
        ok, _ = await runner._check_success(page)
        assert ok is False

    @pytest.mark.asyncio
    async def test_whitespace_only_condition_treated_as_empty(self, runner_factory):
        """success_condition 仅含空白 → 视为未声明，走兜底。"""
        cfg = TaskConfig(name="t", success_condition="   ")
        runner = runner_factory(cfg)
        page = MagicMock()
        ok, reason = await runner._check_success(page)
        assert ok is True
        assert "步骤执行完成" in reason


class TestIsTruthy:
    """_is_truthy 静态方法测试。"""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (True, True),
            (False, False),
            (None, False),
            ("true", True),
            ("True", True),
            ("TRUE", True),
            ("false", False),
            ("False", False),
            ("FALSE", False),
            ("0", False),
            ("1", True),
            ("", False),
            ("  ", False),
            ("ok", True),
            ("no", False),
            ("off", False),
            ("on", True),
            (0, False),
            (1, True),
            (-1, True),
            (0.0, False),
            (0.1, True),
            ([], False),
            ([1], True),
            ({}, False),
            ({"k": 1}, True),
        ],
    )
    def test_truthy_judgement(self, value, expected):
        assert BrowserTaskRunner._is_truthy(value) is expected
