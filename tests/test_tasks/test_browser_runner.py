"""BrowserTaskRunner 单元测试。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.tasks.browser_runner import BrowserTaskRunner
from app.tasks.models import JsCheck, TaskConfig


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
    async def test_failure_checks_hit_returns_failure(self, runner_factory):
        """failure_checks 命中 → (False, '命中失败信号: ...')。"""
        cfg = TaskConfig(name="t")
        cfg.failure_checks.append(JsCheck(expr="true", message="密码错误", timeout=100))
        runner = runner_factory(cfg)
        page = MagicMock()
        page.wait_for_function = AsyncMock()
        ok, reason = await runner._check_success(page)
        assert ok is False
        assert "命中失败信号" in reason
        assert "密码错误" in reason

    @pytest.mark.asyncio
    async def test_failure_checks_miss_continue(self, runner_factory):
        """failure_checks 未命中 → 继续后续判定。"""
        cfg = TaskConfig(name="t")
        cfg.failure_checks.append(JsCheck(expr="false", timeout=100))
        runner = runner_factory(cfg)
        page = MagicMock()
        page.wait_for_function = AsyncMock(side_effect=Exception("timeout"))
        ok, reason = await runner._check_success(page)
        assert ok is True
        assert "步骤执行完成" in reason

    @pytest.mark.asyncio
    async def test_asserted_takes_priority_over_success_checks(self, runner_factory):
        """_asserted=True 优先于 success_checks。"""
        cfg = TaskConfig(name="t")
        cfg.success_checks.append(JsCheck(expr="false", timeout=100))
        runner = runner_factory(cfg)
        runner._asserted = True
        page = MagicMock()
        ok, reason = await runner._check_success(page)
        assert ok is True
        assert "断言文本已命中" in reason

    @pytest.mark.asyncio
    async def test_failure_checks_takes_priority_over_asserted(self, runner_factory):
        """failure_checks 优先于 _asserted。"""
        cfg = TaskConfig(name="t")
        cfg.failure_checks.append(JsCheck(expr="true", message="失败", timeout=100))
        runner = runner_factory(cfg)
        runner._asserted = True
        page = MagicMock()
        page.wait_for_function = AsyncMock()
        ok, reason = await runner._check_success(page)
        assert ok is False
        assert "命中失败信号" in reason

    @pytest.mark.asyncio
    async def test_success_checks_hit_returns_success(self, runner_factory):
        """success_checks 命中 → (True, '命中成功信号: ...')。"""
        cfg = TaskConfig(name="t")
        cfg.success_checks.append(JsCheck(expr="true", message="已登录", timeout=100))
        runner = runner_factory(cfg)
        page = MagicMock()
        page.wait_for_function = AsyncMock()
        ok, reason = await runner._check_success(page)
        assert ok is True
        assert "命中成功信号" in reason
        assert "已登录" in reason

    @pytest.mark.asyncio
    async def test_success_checks_miss_fallback(self, runner_factory):
        """success_checks 未命中 → 兜底信任步骤。"""
        cfg = TaskConfig(name="t")
        cfg.success_checks.append(JsCheck(expr="false", timeout=100))
        runner = runner_factory(cfg)
        page = MagicMock()
        page.wait_for_function = AsyncMock(side_effect=Exception("timeout"))
        ok, reason = await runner._check_success(page)
        assert ok is True
        assert "步骤执行完成" in reason

    @pytest.mark.asyncio
    async def test_evaluate_js_checks_exception_does_not_block(self, runner_factory):
        """评估异常视为未命中，不阻断流程。"""
        cfg = TaskConfig(name="t")
        cfg.failure_checks.append(JsCheck(expr="throw new Error('x')", timeout=100))
        runner = runner_factory(cfg)
        page = MagicMock()
        page.wait_for_function = AsyncMock(side_effect=Exception("js error"))
        ok, reason = await runner._check_success(page)
        assert ok is True
        assert "步骤执行完成" in reason

    @pytest.mark.asyncio
    async def test_failure_uses_expr_prefix_when_no_message(self, runner_factory):
        """failure_checks 命中但无 message → 使用 expr 前 40 字符。"""
        cfg = TaskConfig(name="t")
        cfg.failure_checks.append(JsCheck(expr="document.body.innerText.includes('x')", timeout=100))
        runner = runner_factory(cfg)
        page = MagicMock()
        page.wait_for_function = AsyncMock()
        ok, reason = await runner._check_success(page)
        assert ok is False
        assert "document.body.innerText.includes('x')" in reason
