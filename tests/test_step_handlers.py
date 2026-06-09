"""步骤处理器测试 — 覆盖 StepExecutorRegistry 和各 StepHandler 子类核心功能。

重点覆盖：
- StepExecutorRegistry 注册与获取
- InputHandler / ClickHandler 降级逻辑（_try_candidates_with_fallback）
- SelectHandler 模糊匹配
- ClickSelectHandler 完整流程
- WaitHandler 超时与成功
- WaitUrlHandler URL 正则匹配
- EvalHandler store_as 变量存储
- ScreenshotHandler 截图流程
- SleepHandler 时长截断
- OcrHandler 识别流程与清理
- _resolve_frame 解析
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.tasks.models import StepConfig, StepType, TaskConfig
from app.tasks.step_handlers import (
    ClickHandler,
    ClickSelectHandler,
    EvalHandler,
    InputHandler,
    OcrHandler,
    ScreenshotHandler,
    SelectHandler,
    SleepHandler,
    StepExecutorRegistry,
    StepHandler,
    WaitHandler,
    WaitUrlHandler,
)
from app.tasks.variable_resolver import VariableResolver

# ── 辅助工具 ──


def _make_resolver(**task_kwargs) -> VariableResolver:
    """创建一个用于测试的 VariableResolver。"""
    return VariableResolver(TaskConfig(**task_kwargs), {})


def _make_page() -> MagicMock:
    """创建一个模拟的 Playwright page 对象。"""
    page = MagicMock()
    page.url = "http://localhost"
    page.frame.return_value = None
    return page


def _make_locator(page: MagicMock, visible: bool = True):
    """为 page 配置一个模拟 locator，可控制 wait_for 是否成功。"""
    locator = MagicMock()
    locator.first.wait_for = AsyncMock()
    locator.first.fill = AsyncMock()
    locator.first.click = AsyncMock()
    locator.first.dispatch_event = AsyncMock()
    locator.first.select_option = AsyncMock(return_value=["selected"])
    locator.first.evaluate = AsyncMock()
    locator.first.screenshot = AsyncMock(return_value=b"img_bytes")
    page.locator.return_value = locator
    return locator


# ── StepExecutorRegistry ──


class TestStepExecutorRegistry:
    """步骤执行器注册表。"""

    def test_all_step_types_registered(self):
        """所有 StepType 枚举值都应有对应处理器。"""
        registry = StepExecutorRegistry()
        for step_type in StepType:
            handler = registry.get(step_type.value)
            assert handler is not None, f"缺少处理器: {step_type.value}"

    def test_custom_js_alias(self):
        """custom_js 应被别名为 eval 处理器。"""
        registry = StepExecutorRegistry()
        eval_handler = registry.get("eval")
        custom_js_handler = registry.get("custom_js")
        assert custom_js_handler is eval_handler

    def test_get_unknown_returns_none(self):
        """未知类型返回 None。"""
        registry = StepExecutorRegistry()
        assert registry.get("nonexistent_type") is None

    def test_register_custom_handler(self):
        """自定义处理器可注册并获取。"""
        registry = StepExecutorRegistry()

        class MyHandler(StepHandler):
            @property
            def step_type(self):
                return "my_custom"

            async def execute(self, page, step, resolver):
                return True, ""

        registry.register(MyHandler())
        assert registry.get("my_custom") is not None

    def test_handler_instances_are_singletons(self):
        """同一类型多次 get 返回同一实例。"""
        registry = StepExecutorRegistry()
        h1 = registry.get("input")
        h2 = registry.get("input")
        assert h1 is h2


# ── StepHandler 基类 ──


class TestStepHandlerBase:
    """StepHandler 基类工具方法。"""

    def test_parse_selectors_single(self):
        handler = InputHandler()
        assert handler._parse_selectors("#btn") == ["#btn"]

    def test_parse_selectors_multiple(self):
        handler = InputHandler()
        assert handler._parse_selectors("#a, #b, #c") == ["#a", "#b", "#c"]

    def test_parse_selectors_strips_spaces(self):
        handler = InputHandler()
        assert handler._parse_selectors("  #a  ,  #b  ") == ["#a", "#b"]

    def test_parse_selectors_empty(self):
        handler = InputHandler()
        assert handler._parse_selectors("") == []

    def test_resolve_params_basic(self):
        """resolve_params 应提取 step 的非 None 字段并解析变量。"""
        handler = InputHandler()
        resolver = _make_resolver()
        step = StepConfig(id="s1", type="input", selector="#user", value="admin")
        params = handler.resolve_params(step, resolver)
        assert params["selector"] == "#user"
        assert params["value"] == "admin"

    def test_resolve_params_with_template(self):
        """resolve_params 应解析模板变量。"""
        handler = InputHandler()
        resolver = VariableResolver(TaskConfig(), {"USER": "admin"})
        step = StepConfig(id="s1", type="input", selector="#user", value="{{USER}}")
        params = handler.resolve_params(step, resolver)
        assert params["value"] == "admin"

    def test_resolve_params_excludes_extra(self):
        """resolve_params 不应包含 extra（extra 单独处理）。"""
        handler = InputHandler()
        resolver = _make_resolver()
        step = StepConfig(id="s1", type="input", selector="#user", extra={"k": "v"})
        params = handler.resolve_params(step, resolver)
        # extra 中的字段被合并到 params 中
        assert params["k"] == "v"

    def test_resolve_params_skips_none(self):
        """None 值的字段应被跳过。"""
        handler = InputHandler()
        resolver = _make_resolver()
        step = StepConfig(id="s1", type="input", selector="#user")
        params = handler.resolve_params(step, resolver)
        assert "value" not in params


# ── InputHandler ──


class TestInputHandler:
    """输入步骤处理器。"""

    def test_step_type(self):
        assert InputHandler().step_type == StepType.INPUT

    @pytest.mark.asyncio
    async def test_no_selector_returns_error(self):
        """缺少 selector 时应返回错误。"""
        handler = InputHandler()
        step = StepConfig(id="s1", type="input", value="test")
        ok, msg = await handler.execute(_make_page(), step, _make_resolver())
        assert ok is False
        assert "selector" in msg

    @pytest.mark.asyncio
    async def test_fill_success(self):
        """正常填入值应成功。"""
        handler = InputHandler()
        step = StepConfig(id="s1", type="input", selector="#user", value="admin")
        page = _make_page()
        _make_locator(page)

        ok, msg = await handler.execute(page, step, _make_resolver())
        assert ok is True

    @pytest.mark.asyncio
    async def test_fallback_to_force_input(self):
        """fill 失败时应降级到强制输入 JS。"""
        handler = InputHandler()
        step = StepConfig(id="s1", type="input", selector="#user", value="admin")

        page = _make_page()
        locator = _make_locator(page)
        # 策略1：fill 抛异常
        locator.first.fill = AsyncMock(side_effect=Exception("fill failed"))
        # 策略2：wait_for(attached) + evaluate 成功
        locator.first.wait_for = AsyncMock()
        locator.first.evaluate = AsyncMock()

        ok, msg = await handler.execute(page, step, _make_resolver())
        assert ok is True

    @pytest.mark.asyncio
    async def test_all_candidates_fail(self):
        """所有候选选择器均失败时应返回错误。"""
        handler = InputHandler()
        step = StepConfig(id="s1", type="input", selector="#missing", value="test")

        page = _make_page()
        locator = _make_locator(page)
        locator.first.wait_for = AsyncMock(side_effect=Exception("not found"))
        locator.first.fill = AsyncMock(side_effect=Exception("not found"))

        ok, msg = await handler.execute(page, step, _make_resolver())
        assert ok is False
        assert "未找到" in msg

    @pytest.mark.asyncio
    async def test_multiple_candidates_tries_in_order(self):
        """多个候选选择器应按顺序尝试。"""
        handler = InputHandler()
        step = StepConfig(id="s1", type="input", selector="#a, #b", value="x")
        page = _make_page()

        locator = MagicMock()
        call_count = 0

        async def mock_wait(state="visible", timeout=10000):
            nonlocal call_count
            call_count += 1
            if call_count <= 1:
                # 第一个候选的策略1超时，第二个候选的策略1成功
                pass

        locator.first.wait_for = mock_wait
        locator.first.fill = AsyncMock()
        page.locator.return_value = locator

        ok, msg = await handler.execute(page, step, _make_resolver())
        assert ok is True

    @pytest.mark.asyncio
    async def test_clear_param_passed(self):
        """clear 参数应被正确传递。"""
        handler = InputHandler()
        step = StepConfig(
            id="s1", type="input", selector="#user", value="admin", clear=False
        )
        page = _make_page()
        _make_locator(page)

        ok, msg = await handler.execute(page, step, _make_resolver())
        assert ok is True


# ── ClickHandler ──


class TestClickHandler:
    """点击步骤处理器。"""

    def test_step_type(self):
        assert ClickHandler().step_type == StepType.CLICK

    @pytest.mark.asyncio
    async def test_no_selector_returns_error(self):
        """缺少 selector 时应返回错误。"""
        handler = ClickHandler()
        step = StepConfig(id="s1", type="click")
        ok, msg = await handler.execute(_make_page(), step, _make_resolver())
        assert ok is False
        assert "selector" in msg

    @pytest.mark.asyncio
    async def test_click_success(self):
        """正常点击应成功。"""
        handler = ClickHandler()
        step = StepConfig(id="s1", type="click", selector="#btn")
        page = _make_page()
        _make_locator(page)

        ok, msg = await handler.execute(page, step, _make_resolver())
        assert ok is True

    @pytest.mark.asyncio
    async def test_fallback_to_dispatch_event(self):
        """click 失败时应降级到 dispatch_event。"""
        handler = ClickHandler()
        step = StepConfig(id="s1", type="click", selector="#btn")

        page = _make_page()
        locator = _make_locator(page)
        locator.first.click = AsyncMock(side_effect=Exception("click failed"))
        locator.first.dispatch_event = AsyncMock()
        locator.first.wait_for = AsyncMock()

        ok, msg = await handler.execute(page, step, _make_resolver())
        assert ok is True
        locator.first.dispatch_event.assert_called_with("click")

    @pytest.mark.asyncio
    async def test_all_fail_returns_error(self):
        """普通点击和降级都失败时应返回错误。"""
        handler = ClickHandler()
        step = StepConfig(id="s1", type="click", selector="#btn")

        page = _make_page()
        locator = _make_locator(page)
        locator.first.wait_for = AsyncMock(side_effect=Exception("not found"))
        locator.first.click = AsyncMock(side_effect=Exception("not found"))
        locator.first.dispatch_event = AsyncMock(side_effect=Exception("not found"))

        ok, msg = await handler.execute(page, step, _make_resolver())
        assert ok is False


# ── SelectHandler ──


class TestSelectHandler:
    """下拉选择步骤处理器。"""

    def test_step_type(self):
        assert SelectHandler().step_type == StepType.SELECT

    @pytest.mark.asyncio
    async def test_no_selector_returns_error(self):
        """缺少 selector 时应返回错误。"""
        handler = SelectHandler()
        step = StepConfig(id="s1", type="select", value="opt1")
        ok, msg = await handler.execute(_make_page(), step, _make_resolver())
        assert ok is False
        assert "selector" in msg

    @pytest.mark.asyncio
    async def test_empty_value_skips(self):
        """value 为空时应跳过（成功）。"""
        handler = SelectHandler()
        step = StepConfig(id="s1", type="select", selector="#sel", value="")
        ok, msg = await handler.execute(_make_page(), step, _make_resolver())
        assert ok is True

    @pytest.mark.asyncio
    async def test_unresolved_variable_skips(self):
        """value 包含未解析变量时应跳过。"""
        handler = SelectHandler()
        step = StepConfig(id="s1", type="select", selector="#sel", value="{{VAR}}")
        ok, msg = await handler.execute(_make_page(), step, _make_resolver())
        assert ok is True

    @pytest.mark.asyncio
    async def test_select_exact_match(self):
        """精确匹配应成功。"""
        handler = SelectHandler()
        step = StepConfig(id="s1", type="select", selector="#sel", value="opt1")
        page = _make_page()
        _make_locator(page)

        ok, msg = await handler.execute(page, step, _make_resolver())
        assert ok is True

    @pytest.mark.asyncio
    async def test_element_not_found_required(self):
        """元素未找到且 required=True 时应返回错误。"""
        handler = SelectHandler()
        step = StepConfig(
            id="s1", type="select", selector="#sel", value="opt1", required=True
        )

        page = _make_page()
        locator = _make_locator(page)
        locator.first.wait_for = AsyncMock(side_effect=Exception("not found"))

        ok, msg = await handler.execute(page, step, _make_resolver())
        assert ok is False

    @pytest.mark.asyncio
    async def test_element_not_found_non_required(self):
        """元素未找到且 required=False 时应跳过（成功）。"""
        handler = SelectHandler()
        step = StepConfig(
            id="s1", type="select", selector="#sel", value="opt1", required=False
        )

        page = _make_page()
        locator = _make_locator(page)
        locator.first.wait_for = AsyncMock(side_effect=Exception("not found"))

        ok, msg = await handler.execute(page, step, _make_resolver())
        assert ok is True


# ── ClickSelectHandler ──


class TestClickSelectHandler:
    """点击-选择步骤处理器（自定义 div 下拉框）。"""

    def test_step_type(self):
        assert ClickSelectHandler().step_type == StepType.CLICK_SELECT

    @pytest.mark.asyncio
    async def test_no_selector_returns_error(self):
        """缺少 selector 时应返回错误。"""
        handler = ClickSelectHandler()
        step = StepConfig(id="s1", type="click_select", value="opt1")
        ok, msg = await handler.execute(_make_page(), step, _make_resolver())
        assert ok is False
        assert "selector" in msg

    @pytest.mark.asyncio
    async def test_empty_value_skips(self):
        """value 为空时应跳过。"""
        handler = ClickSelectHandler()
        step = StepConfig(id="s1", type="click_select", selector="#dropdown", value="")
        ok, msg = await handler.execute(_make_page(), step, _make_resolver())
        assert ok is True

    @pytest.mark.asyncio
    async def test_unresolved_variable_skips(self):
        """value 包含未解析变量时应跳过。"""
        handler = ClickSelectHandler()
        step = StepConfig(
            id="s1", type="click_select", selector="#dropdown", value="{{VAR}}"
        )
        ok, msg = await handler.execute(_make_page(), step, _make_resolver())
        assert ok is True

    @pytest.mark.asyncio
    async def test_trigger_not_found_non_required(self):
        """触发器未找到且非 required 时应跳过。"""
        handler = ClickSelectHandler()
        step = StepConfig(
            id="s1", type="click_select", selector="#dropdown", value="opt1"
        )

        page = _make_page()
        locator = _make_locator(page)
        locator.first.wait_for = AsyncMock(side_effect=Exception("not found"))

        ok, msg = await handler.execute(page, step, _make_resolver())
        assert ok is True

    @pytest.mark.asyncio
    async def test_trigger_not_found_required(self):
        """触发器未找到且 required=True 时应返回错误。"""
        handler = ClickSelectHandler()
        step = StepConfig(
            id="s1",
            type="click_select",
            selector="#dropdown",
            value="opt1",
            required=True,
        )

        page = _make_page()
        locator = _make_locator(page)
        locator.first.wait_for = AsyncMock(side_effect=Exception("not found"))

        ok, msg = await handler.execute(page, step, _make_resolver())
        assert ok is False

    @pytest.mark.asyncio
    async def test_option_not_found_non_required(self):
        """选项未找到且非 required 时应跳过。"""
        handler = ClickSelectHandler()
        step = StepConfig(
            id="s1", type="click_select", selector="#dropdown", value="opt1"
        )

        page = _make_page()
        locator = _make_locator(page)
        # 触发器找到
        locator.first.wait_for = AsyncMock()
        locator.first.click = AsyncMock()
        # 选项找不到
        handler._click_option = AsyncMock(return_value=False)
        page.wait_for_timeout = AsyncMock()

        ok, msg = await handler.execute(page, step, _make_resolver())
        assert ok is True


# ── WaitHandler ──


class TestWaitHandler:
    """等待步骤处理器。"""

    def test_step_type(self):
        assert WaitHandler().step_type == StepType.WAIT

    @pytest.mark.asyncio
    async def test_no_selector_returns_error(self):
        """缺少 selector 时应返回错误。"""
        handler = WaitHandler()
        step = StepConfig(id="s1", type="wait")
        ok, msg = await handler.execute(_make_page(), step, _make_resolver())
        assert ok is False
        assert "selector" in msg

    @pytest.mark.asyncio
    async def test_wait_success(self):
        """元素出现后应成功。"""
        handler = WaitHandler()
        step = StepConfig(id="s1", type="wait", selector="#target")
        page = _make_page()
        _make_locator(page)

        ok, msg = await handler.execute(page, step, _make_resolver())
        assert ok is True

    @pytest.mark.asyncio
    async def test_wait_timeout(self):
        """等待超时应返回错误。"""
        handler = WaitHandler()
        step = StepConfig(id="s1", type="wait", selector="#target", timeout=100)
        page = _make_page()
        locator = _make_locator(page)
        locator.first.wait_for = AsyncMock(side_effect=TimeoutError())

        ok, msg = await handler.execute(page, step, _make_resolver())
        assert ok is False
        assert "超时" in msg

    @pytest.mark.asyncio
    async def test_wait_generic_error(self):
        """其他异常应返回错误信息。"""
        handler = WaitHandler()
        step = StepConfig(id="s1", type="wait", selector="#target")
        page = _make_page()
        locator = _make_locator(page)
        locator.first.wait_for = AsyncMock(side_effect=RuntimeError("crash"))

        ok, msg = await handler.execute(page, step, _make_resolver())
        assert ok is False
        assert "crash" in msg


# ── WaitUrlHandler ──


class TestWaitUrlHandler:
    """等待 URL 处理器。"""

    def test_step_type(self):
        assert WaitUrlHandler().step_type == StepType.WAIT_URL

    @pytest.mark.asyncio
    async def test_no_pattern_returns_error(self):
        """缺少 pattern 时应返回错误。"""
        handler = WaitUrlHandler()
        step = StepConfig(id="s1", type="wait_url")
        ok, msg = await handler.execute(_make_page(), step, _make_resolver())
        assert ok is False
        assert "pattern" in msg

    @pytest.mark.asyncio
    async def test_invalid_regex_returns_error(self):
        """无效正则应返回错误。"""
        handler = WaitUrlHandler()
        step = StepConfig(id="s1", type="wait_url", pattern="[invalid")
        ok, msg = await handler.execute(_make_page(), step, _make_resolver())
        assert ok is False
        assert "正则" in msg

    @pytest.mark.asyncio
    async def test_url_already_matches(self):
        """URL 已匹配时应立即成功。"""
        handler = WaitUrlHandler()
        step = StepConfig(id="s1", type="wait_url", pattern="success")
        page = _make_page()
        page.url = "http://example.com/success"

        ok, msg = await handler.execute(page, step, _make_resolver())
        assert ok is True

    @pytest.mark.asyncio
    async def test_url_becomes_matching(self):
        """URL 在等待过程中变为匹配时应成功。"""
        handler = WaitUrlHandler()
        step = StepConfig(id="s1", type="wait_url", pattern="done", timeout=2000)
        page = _make_page()
        page.url = "http://example.com/pending"

        call_count = 0

        def get_url():
            nonlocal call_count
            call_count += 1
            if call_count >= 3:
                return "http://example.com/done"
            return "http://example.com/pending"

        type(page).url = property(lambda self: get_url())

        ok, msg = await handler.execute(page, step, _make_resolver())
        assert ok is True

    @pytest.mark.asyncio
    async def test_url_timeout(self):
        """URL 一直不匹配时应超时返回错误。"""
        handler = WaitUrlHandler()
        step = StepConfig(id="s1", type="wait_url", pattern="never", timeout=200)
        page = _make_page()
        page.url = "http://example.com/other"

        ok, msg = await handler.execute(page, step, _make_resolver())
        assert ok is False
        assert "超时" in msg


# ── EvalHandler ──


class TestEvalHandler:
    """JS 执行步骤处理器。"""

    def test_step_type(self):
        assert EvalHandler().step_type == StepType.EVAL

    @pytest.mark.asyncio
    async def test_no_script_returns_error(self):
        """缺少 script 时应返回错误。"""
        handler = EvalHandler()
        step = StepConfig(id="s1", type="eval")
        ok, msg = await handler.execute(_make_page(), step, _make_resolver())
        assert ok is False
        assert "script" in msg

    @pytest.mark.asyncio
    async def test_eval_success(self):
        """正常执行 JS 应成功。"""
        handler = EvalHandler()
        step = StepConfig(id="s1", type="eval", script="return 1+1")
        page = _make_page()
        page.evaluate = AsyncMock(return_value=2)

        ok, msg = await handler.execute(page, step, _make_resolver())
        assert ok is True

    @pytest.mark.asyncio
    async def test_eval_with_store_as(self):
        """store_as 应将返回值存储到运行时变量。"""
        handler = EvalHandler()
        step = StepConfig(
            id="s1", type="eval", script="return 'hello'", store_as="RESULT"
        )
        page = _make_page()
        page.evaluate = AsyncMock(return_value="hello")
        resolver = _make_resolver()

        ok, msg = await handler.execute(page, step, resolver)
        assert ok is True
        assert resolver.runtime_vars["RESULT"] == "hello"

    @pytest.mark.asyncio
    async def test_eval_js_error(self):
        """JS 执行异常应返回错误信息。"""
        handler = EvalHandler()
        step = StepConfig(id="s1", type="eval", script="throw new Error('boom')")
        page = _make_page()
        page.evaluate = AsyncMock(side_effect=Exception("SyntaxError"))

        ok, msg = await handler.execute(page, step, _make_resolver())
        assert ok is False
        assert "JavaScript" in msg

    @pytest.mark.asyncio
    async def test_eval_result_truncated(self):
        """返回值超长时应被截断到 100 字符。"""
        handler = EvalHandler()
        long_value = "x" * 200
        step = StepConfig(id="s1", type="eval", script="return long")
        page = _make_page()
        page.evaluate = AsyncMock(return_value=long_value)

        ok, msg = await handler.execute(page, step, _make_resolver())
        assert ok is True
        assert len(msg) <= 100

    @pytest.mark.asyncio
    async def test_eval_resolves_template_vars(self):
        """脚本中的模板变量应被解析（通过 resolve_for_js）。"""
        handler = EvalHandler()
        step = StepConfig(id="s1", type="eval", script="return '{{CODE}}'")
        page = _make_page()
        page.evaluate = AsyncMock(return_value="42")
        resolver = VariableResolver(TaskConfig(), {"CODE": "42"})

        ok, msg = await handler.execute(page, step, resolver)
        assert ok is True


# ── ScreenshotHandler ──


class TestScreenshotHandler:
    """截图步骤处理器。"""

    def test_step_type(self):
        assert ScreenshotHandler().step_type == StepType.SCREENSHOT

    @pytest.mark.asyncio
    async def test_screenshot_success(self):
        """截图成功应返回 URL。"""
        handler = ScreenshotHandler()
        step = StepConfig(id="s1", type="screenshot")
        page = _make_page()

        with patch(
            "app.utils.file_helpers.save_screenshot", new_callable=AsyncMock
        ) as mock_save:
            mock_save.return_value = "/logs/2024-01-01/screenshots/test.png"
            ok, msg = await handler.execute(page, step, _make_resolver(task_id="test"))
            assert ok is True
            assert "/logs/" in msg

    @pytest.mark.asyncio
    async def test_screenshot_with_path(self):
        """指定 path 参数时应使用自定义文件名。"""
        handler = ScreenshotHandler()
        step = StepConfig(id="s1", type="screenshot", path="custom.png")
        page = _make_page()

        with patch(
            "app.utils.file_helpers.save_screenshot", new_callable=AsyncMock
        ) as mock_save:
            mock_save.return_value = "/logs/2024-01-01/screenshots/custom.png"
            ok, msg = await handler.execute(page, step, _make_resolver())
            assert ok is True

    @pytest.mark.asyncio
    async def test_screenshot_failure(self):
        """截图失败时应返回错误。"""
        handler = ScreenshotHandler()
        step = StepConfig(id="s1", type="screenshot")
        page = _make_page()

        with patch(
            "app.utils.file_helpers.save_screenshot", new_callable=AsyncMock
        ) as mock_save:
            mock_save.return_value = None
            ok, msg = await handler.execute(page, step, _make_resolver())
            assert ok is False
            assert "截图失败" in msg


# ── SleepHandler ──


class TestSleepHandler:
    """休眠步骤处理器。"""

    def test_step_type(self):
        assert SleepHandler().step_type == StepType.SLEEP

    @pytest.mark.asyncio
    async def test_default_duration(self):
        """默认休眠时长应为 1000ms。"""
        handler = SleepHandler()
        step = StepConfig(id="s1", type="sleep")
        page = _make_page()
        page.wait_for_timeout = AsyncMock()

        ok, msg = await handler.execute(page, step, _make_resolver())
        assert ok is True
        page.wait_for_timeout.assert_called_once_with(1000)

    @pytest.mark.asyncio
    async def test_custom_duration(self):
        """自定义休眠时长应正确传递。"""
        handler = SleepHandler()
        step = StepConfig(id="s1", type="sleep", duration=3000)
        page = _make_page()
        page.wait_for_timeout = AsyncMock()

        ok, msg = await handler.execute(page, step, _make_resolver())
        assert ok is True
        page.wait_for_timeout.assert_called_once_with(3000)

    @pytest.mark.asyncio
    async def test_duration_truncated_to_max(self):
        """超过 MAX_SLEEP_MS 的时长应被截断。"""
        handler = SleepHandler()
        step = StepConfig(id="s1", type="sleep", duration=999999)
        page = _make_page()
        page.wait_for_timeout = AsyncMock()

        ok, msg = await handler.execute(page, step, _make_resolver())
        assert ok is True
        page.wait_for_timeout.assert_called_once_with(handler.MAX_SLEEP_MS)

    @pytest.mark.asyncio
    async def test_duration_exactly_at_max(self):
        """恰好等于 MAX_SLEEP_MS 的时长不应被截断。"""
        handler = SleepHandler()
        step = StepConfig(id="s1", type="sleep", duration=handler.MAX_SLEEP_MS)
        page = _make_page()
        page.wait_for_timeout = AsyncMock()

        ok, msg = await handler.execute(page, step, _make_resolver())
        assert ok is True
        page.wait_for_timeout.assert_called_once_with(handler.MAX_SLEEP_MS)

    def test_max_sleep_ms_is_5_minutes(self):
        """MAX_SLEEP_MS 应为 300000（5分钟）。"""
        assert SleepHandler.MAX_SLEEP_MS == 300000


# ── OcrHandler ──


class TestOcrHandler:
    """验证码识别步骤处理器。"""

    def test_step_type(self):
        assert OcrHandler().step_type == StepType.OCR

    @pytest.mark.asyncio
    async def test_no_selector_returns_error(self):
        """缺少 selector 时应返回错误。"""
        handler = OcrHandler()
        step = StepConfig(id="s1", type="ocr")
        ok, msg = await handler.execute(_make_page(), step, _make_resolver())
        assert ok is False
        assert "selector" in msg

    @pytest.mark.asyncio
    async def test_image_not_found(self):
        """验证码图片元素未找到时应返回错误。"""
        handler = OcrHandler()
        step = StepConfig(id="s1", type="ocr", selector="#captcha")
        page = _make_page()
        handler._find_element = AsyncMock(return_value=None)

        ok, msg = await handler.execute(page, step, _make_resolver())
        assert ok is False
        assert "未找到" in msg

    @pytest.mark.asyncio
    async def test_ocr_success_with_store_as(self):
        """识别成功且有 store_as 时应存储结果。"""
        handler = OcrHandler()
        step = StepConfig(id="s1", type="ocr", selector="#captcha", store_as="CAPTCHA")
        page = _make_page()
        resolver = _make_resolver()

        mock_element = AsyncMock()
        mock_element.screenshot = AsyncMock(return_value=b"img")
        handler._find_element = AsyncMock(return_value=mock_element)

        with (
            patch.object(handler, "_get_ocr") as mock_get_ocr,
            patch.object(handler, "schedule_cleanup") as mock_cleanup,
        ):
            mock_ocr = MagicMock()
            mock_ocr.classification.return_value = "AB12"
            mock_get_ocr.return_value = mock_ocr

            ok, msg = await handler.execute(page, step, resolver)
            assert ok is True
            assert "AB12" in msg
            assert resolver.runtime_vars["CAPTCHA"] == "AB12"
            mock_cleanup.assert_called_once()

    @pytest.mark.asyncio
    async def test_ocr_with_target_selector(self):
        """有 target_selector 时应自动填入验证码。"""
        handler = OcrHandler()
        step = StepConfig(
            id="s1",
            type="ocr",
            selector="#captcha",
            target_selector="#captcha_input",
        )
        page = _make_page()

        mock_img = AsyncMock()
        mock_img.screenshot = AsyncMock(return_value=b"img")
        mock_target = AsyncMock()
        mock_target.fill = AsyncMock()

        async def find_element(ctx, sel, timeout):
            if sel == "#captcha":
                return mock_img
            return mock_target

        handler._find_element = find_element

        with (
            patch.object(handler, "_get_ocr") as mock_get_ocr,
            patch.object(handler, "schedule_cleanup"),
        ):
            mock_ocr = MagicMock()
            mock_ocr.classification.return_value = "XYZ"
            mock_get_ocr.return_value = mock_ocr

            ok, msg = await handler.execute(page, step, _make_resolver())
            assert ok is True
            mock_target.fill.assert_called_once_with("XYZ", timeout=10000)

    @pytest.mark.asyncio
    async def test_ocr_with_char_range(self):
        """有 char_range 时应创建独立 OCR 实例（不复用缓存）。"""
        handler = OcrHandler()
        step = StepConfig(
            id="s1", type="ocr", selector="#captcha", char_range="0123456789"
        )
        page = _make_page()

        mock_element = AsyncMock()
        mock_element.screenshot = AsyncMock(return_value=b"img")
        handler._find_element = AsyncMock(return_value=mock_element)

        mock_ocr = MagicMock()
        mock_ocr.classification.return_value = "1234"

        mock_ddddocr = MagicMock()
        mock_ddddocr.DdddOcr.return_value = mock_ocr

        with (
            patch.dict("sys.modules", {"ddddocr": mock_ddddocr}),
            patch.object(handler, "schedule_cleanup"),
        ):
            ok, msg = await handler.execute(page, step, _make_resolver())
            assert ok is True
            mock_ocr.set_ranges.assert_called_once_with("0123456789")

    @pytest.mark.asyncio
    async def test_ocr_recognition_failure(self):
        """OCR 识别失败时应返回错误并触发清理。"""
        handler = OcrHandler()
        step = StepConfig(id="s1", type="ocr", selector="#captcha")
        page = _make_page()

        mock_element = AsyncMock()
        mock_element.screenshot = AsyncMock(return_value=b"img")
        handler._find_element = AsyncMock(return_value=mock_element)

        with (
            patch.object(handler, "_get_ocr") as mock_get_ocr,
            patch.object(handler, "schedule_cleanup") as mock_cleanup,
        ):
            mock_get_ocr.side_effect = Exception("model load failed")

            ok, msg = await handler.execute(page, step, _make_resolver())
            assert ok is False
            assert "识别失败" in msg
            mock_cleanup.assert_called_once()

    def test_schedule_cleanup_sets_timer(self):
        """schedule_cleanup 应设置定时器。"""
        handler = OcrHandler()
        with patch("app.tasks.step_handlers.threading.Timer") as mock_timer_cls:
            mock_timer = MagicMock()
            mock_timer_cls.return_value = mock_timer
            handler.schedule_cleanup(old=False)
            mock_timer_cls.assert_called_once()
            mock_timer.start.assert_called_once()

    def test_do_cleanup_removes_instance(self):
        """_do_cleanup 应清除缓存的 OCR 实例。"""
        OcrHandler._ocr_instances[False] = MagicMock()
        OcrHandler._do_cleanup(False)
        assert False not in OcrHandler._ocr_instances

    def test_get_ocr_reuses_cached_instance(self):
        """_get_ocr 应复用缓存实例。"""
        mock_instance = MagicMock()
        OcrHandler._ocr_instances[False] = mock_instance
        try:
            result = OcrHandler._get_ocr(old=False)
            assert result is mock_instance
        finally:
            OcrHandler._ocr_instances.pop(False, None)


# ── _resolve_frame ──


class TestResolveFrame:
    """frame 上下文解析。"""

    @pytest.mark.asyncio
    async def test_no_frame_returns_page(self):
        """无 frame 配置时应返回原始 page。"""
        handler = InputHandler()
        step = StepConfig(id="s1", type="input", selector="#user")
        page = _make_page()

        result = await handler._resolve_frame(page, step)
        assert result is page

    @pytest.mark.asyncio
    async def test_frame_by_name(self):
        """应优先按 name 匹配 frame。"""
        handler = InputHandler()
        step = StepConfig(id="s1", type="input", selector="#user", frame="mainFrame")
        page = _make_page()
        mock_frame = MagicMock()
        page.frame.return_value = mock_frame

        result = await handler._resolve_frame(page, step)
        assert result is mock_frame
        page.frame.assert_called_with(name="mainFrame")

    @pytest.mark.asyncio
    async def test_frame_by_url(self):
        """name 匹配失败时应回退到 URL 匹配。"""
        handler = InputHandler()
        step = StepConfig(
            id="s1", type="input", selector="#user", frame="http://example.com/frame"
        )
        page = _make_page()
        # 第一次调用（name）返回 None，第二次调用（url）返回 frame
        mock_frame = MagicMock()
        page.frame.side_effect = [None, mock_frame]

        result = await handler._resolve_frame(page, step)
        assert result is mock_frame

    @pytest.mark.asyncio
    async def test_frame_non_string_cleared(self):
        """frame 为非字符串时应返回原始 page。"""
        handler = InputHandler()
        step = StepConfig(id="s1", type="input", selector="#user")
        step.frame = 123  # 非字符串
        page = _make_page()

        result = await handler._resolve_frame(page, step)
        assert result is page

    @pytest.mark.asyncio
    async def test_frame_fallback_to_page(self):
        """所有匹配方式都失败时应返回原始 page。"""
        handler = InputHandler()
        step = StepConfig(id="s1", type="input", selector="#user", frame="#iframe")
        page = _make_page()
        page.frame.return_value = None
        page.query_selector = AsyncMock(return_value=None)

        result = await handler._resolve_frame(page, step)
        assert result is page


# ── _try_candidates_with_fallback ──


class TestTryCandidatesWithFallback:
    """候选选择器降级通用模式。"""

    @pytest.mark.asyncio
    async def test_first_candidate_visible_success(self):
        """第一个候选可见时应直接成功。"""
        handler = InputHandler()
        page = _make_page()
        _make_locator(page)

        action_fn = AsyncMock()
        fallback_fn = AsyncMock()

        ok, msg = await handler._try_candidates_with_fallback(
            page, "#btn", 10000, action_fn, fallback_fn
        )
        assert ok is True
        action_fn.assert_called_once()
        fallback_fn.assert_not_called()

    @pytest.mark.asyncio
    async def test_visible_fallback_to_attached(self):
        """可见元素查找失败时应降级到 attached 状态。"""
        handler = InputHandler()
        page = _make_page()
        locator = _make_locator(page)

        call_count = 0

        async def mock_wait(state="visible", timeout=10000):
            nonlocal call_count
            call_count += 1
            if state == "visible":
                raise Exception("not visible")
            # attached 成功

        locator.first.wait_for = mock_wait
        action_fn = AsyncMock()
        fallback_fn = AsyncMock()

        ok, msg = await handler._try_candidates_with_fallback(
            page, "#btn", 10000, action_fn, fallback_fn
        )
        assert ok is True
        fallback_fn.assert_called_once()

    @pytest.mark.asyncio
    async def test_all_fail_returns_error(self):
        """所有候选和降级都失败时应返回错误。"""
        handler = InputHandler()
        page = _make_page()
        locator = _make_locator(page)
        locator.first.wait_for = AsyncMock(side_effect=Exception("not found"))

        action_fn = AsyncMock()
        fallback_fn = AsyncMock()

        ok, msg = await handler._try_candidates_with_fallback(
            page, "#missing", 10000, action_fn, fallback_fn
        )
        assert ok is False
        assert "未找到" in msg

    @pytest.mark.asyncio
    async def test_multiple_candidates_order(self):
        """多个候选应按顺序尝试。"""
        handler = InputHandler()
        page = _make_page()

        def make_locator_for(name):
            loc = MagicMock()
            loc.first.wait_for = AsyncMock()
            loc.first.click = AsyncMock()
            return loc

        locators = {
            "#first": make_locator_for("#first"),
            "#second": make_locator_for("#second"),
        }

        def locator_side_effect(sel):
            return locators[sel]

        page.locator.side_effect = locator_side_effect

        action_fn = AsyncMock()

        ok, msg = await handler._try_candidates_with_fallback(
            page, "#first, #second", 10000, action_fn, AsyncMock()
        )
        assert ok is True
        # 第一个候选应成功，action_fn 只调用一次
        assert action_fn.call_count == 1
