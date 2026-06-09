"""src/task_executor.py — 任务执行器综合测试

覆盖 StepConfig, TaskConfig, VariableResolver, StepHandler 子类,
StepExecutorRegistry, TaskValidator, TaskExecutor, TaskManager 等核心类。
"""

from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.tasks.executor import TaskExecutor
from app.tasks.manager import TaskManager, is_valid_task_id, normalize_task_id
from app.tasks.models import (
    StepConfig,
    StepError,
    StepType,
    TaskConfig,
)
from app.tasks.step_handlers import (
    ClickHandler,
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
from app.tasks.validator import TaskValidator
from app.tasks.variable_resolver import VariableResolver

# =====================================================================
# StepConfig
# =====================================================================


class TestStepConfig:
    def test_from_dict_basic(self):
        data = {"id": "s1", "type": "input", "selector": "#user", "value": "admin"}
        step = StepConfig.from_dict(data)
        assert step.id == "s1"
        assert step.type == "input"
        assert step.selector == "#user"
        assert step.value == "admin"

    def test_from_dict_code_to_script(self):
        """code 字段应自动规范化为 script"""
        data = {"id": "s1", "type": "eval", "code": "return 1+1"}
        step = StepConfig.from_dict(data)
        assert step.script == "return 1+1"
        assert not hasattr(step, "code") or "code" not in step.__dataclass_fields__

    def test_from_dict_script_preserved(self):
        """script 字段存在时不应被 code 覆盖"""
        data = {"id": "s1", "type": "eval", "script": "return 2", "code": "return 1"}
        step = StepConfig.from_dict(data)
        assert step.script == "return 2"

    def test_from_dict_frame_non_string_cleared(self):
        """frame 字段非字符串时应被清空"""
        data = {"id": "s1", "type": "click", "selector": "#btn", "frame": True}
        step = StepConfig.from_dict(data)
        assert step.frame is None

    def test_from_dict_frame_string_preserved(self):
        data = {"id": "s1", "type": "click", "selector": "#btn", "frame": "mainFrame"}
        step = StepConfig.from_dict(data)
        assert step.frame == "mainFrame"

    def test_from_dict_extra_fields(self):
        """不在 dataclass 中的字段应收入 extra"""
        data = {"id": "s1", "type": "click", "selector": "#btn", "custom_param": 42}
        step = StepConfig.from_dict(data)
        assert step.extra["custom_param"] == 42

    def test_from_dict_warns_on_typo(self):
        """未知字段应触发 warning 日志（帮助用户发现 typo）"""
        from unittest.mock import patch as _patch

        data = {
            "id": "s1",
            "type": "click",
            "selector": "#btn",
            "selctor": "#wrong",  # typo: selctor → selector
            "unwanted": True,
        }
        with _patch("app.tasks.models.logger") as mock_logger:
            step = StepConfig.from_dict(data)
            mock_logger.warning.assert_called_once()
            args, kwargs = mock_logger.warning.call_args
            # 日志消息应包含所有未知字段名
            msg = args[0].format(*args[1:]) if len(args) > 1 else args[0]
            assert "selctor" in msg
            assert "unwanted" in msg
        # 未知字段仍收入 extra（行为不变）
        assert step.extra["selctor"] == "#wrong"
        assert step.extra["unwanted"] is True

    def test_to_dict_basic(self):
        step = StepConfig(id="s1", type="input", selector="#user", value="admin")
        d = step.to_dict()
        assert d["id"] == "s1"
        assert d["type"] == "input"
        assert d["selector"] == "#user"
        assert d["value"] == "admin"

    def test_to_dict_skips_defaults(self):
        """默认值字段应被跳过"""
        step = StepConfig(id="s1", type="click", selector="#btn")
        d = step.to_dict()
        assert "description" not in d
        assert "timeout" not in d
        assert "clear" not in d

    def test_to_dict_merges_extra(self):
        """extra 字段应合并回顶层"""
        step = StepConfig(id="s1", type="click", selector="#btn", extra={"custom": 1})
        d = step.to_dict()
        assert d["custom"] == 1

    def test_defaults(self):
        step = StepConfig(id="s1", type="input")
        assert step.description == ""
        assert step.timeout is None
        assert step.clear is True
        assert step.wait_until == "networkidle"
        assert step.duration == 1000
        assert step.required is False


# =====================================================================
# TaskConfig
# =====================================================================


class TestTaskConfig:
    def test_from_dict_basic(self):
        data = {
            "name": "测试任务",
            "description": "描述",
            "url": "http://test.com",
            "timeout": 5000,
            "variables": {"USER": "admin"},
            "steps": [{"id": "s1", "type": "click", "selector": "#btn"}],
        }
        config = TaskConfig.from_dict(data)
        assert config.name == "测试任务"
        assert config.url == "http://test.com"
        assert config.timeout == 5000
        assert config.variables == {"USER": "admin"}
        assert len(config.steps) == 1
        assert config.steps[0].id == "s1"

    def test_from_dict_defaults(self):
        config = TaskConfig.from_dict({})
        assert config.name == "未命名任务"
        assert config.url == ""
        assert config.timeout == 30000
        assert config.steps == []
        assert config.step_delay == 0.5

    def test_to_dict_basic(self):
        config = TaskConfig(
            name="test",
            url="http://test.com",
            steps=[StepConfig(id="s1", type="click", selector="#btn")],
        )
        d = config.to_dict()
        assert d["name"] == "test"
        assert d["url"] == "http://test.com"
        assert len(d["steps"]) == 1

    def test_to_dict_skips_empty(self):
        config = TaskConfig(name="test")
        d = config.to_dict()
        assert "variables" not in d
        assert "on_success" not in d
        assert "metadata" not in d

    def test_round_trip(self):
        original = {
            "name": "往返测试",
            "url": "http://test.com",
            "steps": [
                {"id": "s1", "type": "input", "selector": "#user", "value": "admin"},
                {"id": "s2", "type": "click", "selector": "#submit"},
            ],
        }
        config = TaskConfig.from_dict(original)
        serialized = config.to_dict()
        restored = TaskConfig.from_dict(serialized)
        assert restored.name == original["name"]
        assert len(restored.steps) == 2


# =====================================================================
# VariableResolver
# =====================================================================


class TestVariableResolver:
    def _make_config(self, variables=None):
        return TaskConfig(
            name="test",
            url="http://test.com",
            variables=variables or {},
        )

    def test_resolve_no_template(self):
        resolver = VariableResolver(self._make_config(), {})
        assert resolver.resolve("plain text") == "plain text"

    def test_resolve_non_string(self):
        resolver = VariableResolver(self._make_config(), {})
        assert resolver.resolve(42) == 42
        assert resolver.resolve(None) is None

    def test_resolve_env_var(self):
        resolver = VariableResolver(self._make_config(), {"USER": "admin"})
        assert resolver.resolve("{{USER}}") == "admin"

    def test_resolve_task_var(self):
        config = self._make_config(variables={"PASS": "secret"})
        resolver = VariableResolver(config, {})
        assert resolver.resolve("{{PASS}}") == "secret"

    def test_resolve_mixed(self):
        config = self._make_config(variables={"DOMAIN": "test.com"})
        resolver = VariableResolver(config, {"USER": "admin"})
        assert resolver.resolve("http://{{DOMAIN}}/{{USER}}") == "http://test.com/admin"

    def test_resolve_priority_env_over_task(self):
        """环境变量优先级应高于任务变量"""
        config = self._make_config(variables={"X": "task"})
        resolver = VariableResolver(config, {"X": "env"})
        assert resolver.resolve("{{X}}") == "env"

    def test_resolve_priority_runtime_over_env(self):
        """运行时变量优先级应高于环境变量"""
        resolver = VariableResolver(self._make_config(), {"X": "env"})
        resolver.set_runtime_var("X", "runtime")
        assert resolver.resolve("{{X}}") == "runtime"

    def test_resolve_unknown_var(self):
        """未知变量应保留原样"""
        resolver = VariableResolver(self._make_config(), {})
        assert resolver.resolve("{{UNKNOWN}}") == "{{UNKNOWN}}"

    def test_resolve_nested(self):
        config = self._make_config(variables={"A": "{{B}}", "B": "final"})
        resolver = VariableResolver(config, {})
        assert resolver.resolve("{{A}}") == "final"

    def test_resolve_circular_reference(self):
        config = self._make_config(variables={"A": "{{B}}", "B": "{{A}}"})
        resolver = VariableResolver(config, {})
        with pytest.raises(StepError, match="循环引用"):
            resolver.resolve("{{A}}")

    def test_resolve_max_depth(self):
        variables = {}
        for i in range(10):
            variables[f"V{i}"] = f"{{{{V{i + 1}}}}}" if i < 9 else "end"
        config = self._make_config(variables=variables)
        resolver = VariableResolver(config, {})
        with pytest.raises(StepError, match="层级超过限制"):
            resolver.resolve("{{V0}}")

    def test_resolve_caching(self):
        resolver = VariableResolver(self._make_config(), {"X": "cached"})
        r1 = resolver.resolve("{{X}}")
        r2 = resolver.resolve("{{X}}")
        assert r1 == r2 == "cached"

    def test_set_runtime_var_clears_cache(self):
        resolver = VariableResolver(self._make_config(), {"X": "old"})
        resolver.resolve("{{X}}")
        resolver.set_runtime_var("X", "new")
        assert resolver.resolve("{{X}}") == "new"

    def test_resolve_for_js(self):
        resolver = VariableResolver(self._make_config(), {"PASS": "admin'123"})
        result = resolver.resolve_for_js("{{PASS}}")
        # 应返回 JSON 编码的字符串
        assert json.loads(result) == "admin'123"

    def test_resolve_for_js_no_template(self):
        resolver = VariableResolver(self._make_config(), {})
        assert resolver.resolve_for_js("plain") == "plain"

    def test_resolve_for_js_unknown_var(self):
        resolver = VariableResolver(self._make_config(), {})
        result = resolver.resolve_for_js("{{UNKNOWN}}")
        assert result == '""'

    def test_resolve_unknown_var_logs_warning(self):
        """未知变量应触发 warning 日志"""
        resolver = VariableResolver(self._make_config(), {})
        with patch("app.tasks.variable_resolver.logger") as mock_logger:
            resolver.resolve("{{UNKNOWN}}")
            mock_logger.warning.assert_called_once()
            assert "UNKNOWN" in str(mock_logger.warning.call_args)

    def test_resolve_runtime_var_none(self):
        resolver = VariableResolver(self._make_config(), {})
        resolver.set_runtime_var("VAL", None)
        assert resolver.resolve("{{VAL}}") == ""

    def test_resolve_runtime_var_bool(self):
        resolver = VariableResolver(self._make_config(), {})
        resolver.set_runtime_var("FLAG", True)
        assert resolver.resolve("{{FLAG}}") == "true"

    def test_resolve_runtime_var_list(self):
        resolver = VariableResolver(self._make_config(), {})
        resolver.set_runtime_var("ITEMS", [1, 2, 3])
        assert resolver.resolve("{{ITEMS}}") == "[1, 2, 3]"

    def test_resolve_runtime_var_dict(self):
        resolver = VariableResolver(self._make_config(), {})
        resolver.set_runtime_var("OBJ", {"key": "value"})
        assert resolver.resolve("{{OBJ}}") == '{"key": "value"}'

    def test_resolve_runtime_var_string_unchanged(self):
        resolver = VariableResolver(self._make_config(), {})
        resolver.set_runtime_var("STR", "hello")
        assert resolver.resolve("{{STR}}") == "hello"


# =====================================================================
# StepHandler 子类
# =====================================================================


class TestStepHandlerBase:
    """StepHandler 基类方法测试"""

    def test_parse_selectors(self):
        handler = InputHandler()
        result = handler._parse_selectors("#a, #b, #c")
        assert result == ["#a", "#b", "#c"]

    def test_parse_selectors_with_spaces(self):
        handler = InputHandler()
        result = handler._parse_selectors("  #a  ,  #b  ")
        assert result == ["#a", "#b"]

    def test_parse_selectors_empty(self):
        handler = InputHandler()
        result = handler._parse_selectors("")
        assert result == []


class TestInputHandler:
    def test_step_type(self):
        assert InputHandler().step_type == StepType.INPUT

    @pytest.mark.asyncio
    async def test_execute_no_selector(self):
        handler = InputHandler()
        step = StepConfig(id="s1", type="input")
        resolver = VariableResolver(TaskConfig(), {})
        ok, msg = await handler.execute(MagicMock(), step, resolver)
        assert ok is False
        assert "selector" in msg

    @pytest.mark.asyncio
    async def test_execute_success(self):
        handler = InputHandler()
        step = StepConfig(id="s1", type="input", selector="#user", value="admin")
        resolver = VariableResolver(TaskConfig(), {})

        mock_page = MagicMock()
        mock_locator = MagicMock()
        mock_locator.first.wait_for = AsyncMock()
        mock_locator.first.fill = AsyncMock()
        mock_page.locator.return_value = mock_locator

        ok, msg = await handler.execute(mock_page, step, resolver)
        assert ok is True


class TestClickHandler:
    def test_step_type(self):
        assert ClickHandler().step_type == StepType.CLICK

    @pytest.mark.asyncio
    async def test_execute_no_selector(self):
        handler = ClickHandler()
        step = StepConfig(id="s1", type="click")
        resolver = VariableResolver(TaskConfig(), {})
        ok, msg = await handler.execute(MagicMock(), step, resolver)
        assert ok is False
        assert "selector" in msg


class TestSelectHandler:
    def test_step_type(self):
        assert SelectHandler().step_type == StepType.SELECT

    @pytest.mark.asyncio
    async def test_execute_no_selector(self):
        handler = SelectHandler()
        step = StepConfig(id="s1", type="select", value="opt1")
        resolver = VariableResolver(TaskConfig(), {})
        ok, msg = await handler.execute(MagicMock(), step, resolver)
        assert ok is False
        assert "selector" in msg

    @pytest.mark.asyncio
    async def test_execute_empty_value_skips(self):
        handler = SelectHandler()
        step = StepConfig(id="s1", type="select", selector="#sel", value="")
        resolver = VariableResolver(TaskConfig(), {})
        ok, msg = await handler.execute(MagicMock(), step, resolver)
        assert ok is True


class TestWaitHandler:
    def test_step_type(self):
        assert WaitHandler().step_type == StepType.WAIT

    @pytest.mark.asyncio
    async def test_execute_no_selector(self):
        handler = WaitHandler()
        step = StepConfig(id="s1", type="wait")
        resolver = VariableResolver(TaskConfig(), {})
        ok, msg = await handler.execute(MagicMock(), step, resolver)
        assert ok is False

    @pytest.mark.asyncio
    async def test_execute_timeout(self):
        """等待超时应返回中文错误信息"""
        handler = WaitHandler()
        step = StepConfig(id="s1", type="wait", selector="#missing", timeout=100)
        resolver = VariableResolver(TaskConfig(), {})

        mock_page = MagicMock()
        mock_locator = MagicMock()
        mock_locator.first.wait_for = AsyncMock(side_effect=TimeoutError())
        mock_page.locator.return_value = mock_locator

        ok, msg = await handler.execute(mock_page, step, resolver)
        assert ok is False
        assert "超时" in msg


class TestWaitUrlHandler:
    def test_step_type(self):
        assert WaitUrlHandler().step_type == StepType.WAIT_URL

    @pytest.mark.asyncio
    async def test_execute_no_pattern(self):
        handler = WaitUrlHandler()
        step = StepConfig(id="s1", type="wait_url")
        resolver = VariableResolver(TaskConfig(), {})
        ok, msg = await handler.execute(MagicMock(), step, resolver)
        assert ok is False
        assert "pattern" in msg

    @pytest.mark.asyncio
    async def test_execute_invalid_regex(self):
        handler = WaitUrlHandler()
        step = StepConfig(id="s1", type="wait_url", pattern="[invalid")
        resolver = VariableResolver(TaskConfig(), {})
        ok, msg = await handler.execute(MagicMock(), step, resolver)
        assert ok is False
        assert "正则" in msg


class TestEvalHandler:
    def test_step_type(self):
        assert EvalHandler().step_type == StepType.EVAL

    @pytest.mark.asyncio
    async def test_execute_no_script(self):
        handler = EvalHandler()
        step = StepConfig(id="s1", type="eval")
        resolver = VariableResolver(TaskConfig(), {})
        ok, msg = await handler.execute(MagicMock(), step, resolver)
        assert ok is False
        assert "script" in msg

    @pytest.mark.asyncio
    async def test_execute_success(self):
        handler = EvalHandler()
        step = StepConfig(id="s1", type="eval", script="return 1+1")
        resolver = VariableResolver(TaskConfig(), {})

        mock_page = MagicMock()
        mock_page.evaluate = AsyncMock(return_value=2)

        ok, msg = await handler.execute(mock_page, step, resolver)
        assert ok is True

    @pytest.mark.asyncio
    async def test_execute_store_as(self):
        handler = EvalHandler()
        step = StepConfig(id="s1", type="eval", script="return 42", store_as="result")
        resolver = VariableResolver(TaskConfig(), {})

        mock_page = MagicMock()
        mock_page.evaluate = AsyncMock(return_value=42)

        ok, msg = await handler.execute(mock_page, step, resolver)
        assert ok is True
        assert resolver.runtime_vars["result"] == 42

    @pytest.mark.asyncio
    async def test_execute_js_error(self):
        """JS 执行异常应返回明确错误信息"""
        handler = EvalHandler()
        step = StepConfig(id="s1", type="eval", script="throw new Error('test')")
        resolver = VariableResolver(TaskConfig(), {})

        mock_page = MagicMock()
        mock_page.evaluate = AsyncMock(side_effect=Exception("SyntaxError"))

        ok, msg = await handler.execute(mock_page, step, resolver)
        assert ok is False
        assert "JavaScript" in msg


class TestSleepHandler:
    def test_step_type(self):
        assert SleepHandler().step_type == StepType.SLEEP

    @pytest.mark.asyncio
    async def test_execute_default_duration(self):
        handler = SleepHandler()
        step = StepConfig(id="s1", type="sleep")
        resolver = VariableResolver(TaskConfig(), {})

        mock_page = MagicMock()
        mock_page.wait_for_timeout = AsyncMock()

        ok, msg = await handler.execute(mock_page, step, resolver)
        assert ok is True
        mock_page.wait_for_timeout.assert_called_once_with(1000)

    @pytest.mark.asyncio
    async def test_execute_custom_duration(self):
        handler = SleepHandler()
        step = StepConfig(id="s1", type="sleep", duration=2000)
        resolver = VariableResolver(TaskConfig(), {})

        mock_page = MagicMock()
        mock_page.wait_for_timeout = AsyncMock()

        ok, msg = await handler.execute(mock_page, step, resolver)
        assert ok is True
        mock_page.wait_for_timeout.assert_called_once_with(2000)

    @pytest.mark.asyncio
    async def test_execute_max_duration_clamped(self):
        handler = SleepHandler()
        step = StepConfig(id="s1", type="sleep", duration=999999)
        resolver = VariableResolver(TaskConfig(), {})

        mock_page = MagicMock()
        mock_page.wait_for_timeout = AsyncMock()

        ok, msg = await handler.execute(mock_page, step, resolver)
        assert ok is True
        mock_page.wait_for_timeout.assert_called_once_with(handler.MAX_SLEEP_MS)


class TestScreenshotHandler:
    def test_step_type(self):
        assert ScreenshotHandler().step_type == StepType.SCREENSHOT


class TestOcrHandler:
    @pytest.mark.asyncio
    async def test_execute_cleanup_on_target_error(self):
        """target.evaluate 异常时 schedule_cleanup 仍应被调用"""
        handler = OcrHandler()
        step = StepConfig(
            id="s1",
            type="ocr",
            selector="#captcha",
            store_as="code",
            extra={"target_selector": "#captcha_input"},
        )
        resolver = VariableResolver(TaskConfig(), {})

        mock_page = MagicMock()
        mock_element = AsyncMock()
        mock_element.screenshot = AsyncMock(return_value=b"fake_img")

        mock_target = AsyncMock()
        mock_target.fill = AsyncMock(side_effect=Exception("fill failed"))
        mock_target.wait_for = AsyncMock()
        mock_target.evaluate = AsyncMock(side_effect=Exception("evaluate failed"))

        async def mock_find(ctx, sel, timeout):
            if sel == "#captcha":
                return mock_element
            return mock_target

        handler._find_element = mock_find

        with (
            patch.object(handler, "_get_ocr") as mock_get_ocr,
            patch.object(handler, "schedule_cleanup") as mock_cleanup,
        ):
            mock_ocr = MagicMock()
            mock_ocr.classification.return_value = "abc123"
            mock_get_ocr.return_value = mock_ocr

            # force input 异常会从 execute() 冒泡（try/finally 保证清理但不吞异常）
            with pytest.raises(Exception, match="evaluate failed"):
                await handler.execute(mock_page, step, resolver)
            # 关键验证：schedule_cleanup 一定被调用
            mock_cleanup.assert_called_once()


# =====================================================================
# StepExecutorRegistry
# =====================================================================


class TestStepExecutorRegistry:
    def test_all_default_handlers_registered(self):
        registry = StepExecutorRegistry()
        for step_type in StepType:
            assert registry.get(step_type.value) is not None

    def test_custom_js_alias(self):
        registry = StepExecutorRegistry()
        assert registry.get("custom_js") is not None
        assert registry.get("custom_js") is registry.get("eval")

    def test_get_unknown_returns_none(self):
        registry = StepExecutorRegistry()
        assert registry.get("nonexistent") is None

    def test_register_custom_handler(self):
        registry = StepExecutorRegistry()

        class CustomHandler(StepHandler):
            @property
            def step_type(self):
                return "custom_type"

            async def execute(self, page, step, resolver):
                return True, ""

        registry.register(CustomHandler())
        assert registry.get("custom_type") is not None


# =====================================================================
# TaskValidator
# =====================================================================


class TestTaskValidator:
    def test_valid_task(self):
        config = {
            "name": "测试",
            "steps": [{"id": "s1", "type": "click", "selector": "#btn"}],
        }
        ok, errors = TaskValidator.validate(config)
        assert ok is True
        assert errors == []

    def test_missing_name(self):
        config = {"steps": [{"id": "s1", "type": "click", "selector": "#btn"}]}
        ok, errors = TaskValidator.validate(config)
        assert ok is False
        assert any("name" in e for e in errors)

    def test_missing_steps(self):
        config = {"name": "测试"}
        ok, errors = TaskValidator.validate(config)
        assert ok is False
        assert any("steps" in e for e in errors)

    def test_steps_not_list(self):
        config = {"name": "测试", "steps": "not a list"}
        ok, errors = TaskValidator.validate(config)
        assert ok is False

    def test_step_missing_id(self):
        config = {"name": "测试", "steps": [{"type": "click", "selector": "#btn"}]}
        ok, errors = TaskValidator.validate(config)
        assert ok is False
        assert any("id" in e for e in errors)

    def test_step_invalid_id(self):
        config = {
            "name": "测试",
            "steps": [{"id": "123bad", "type": "click", "selector": "#btn"}],
        }
        ok, errors = TaskValidator.validate(config)
        assert ok is False
        assert any("格式" in e for e in errors)

    def test_step_invalid_type(self):
        config = {"name": "测试", "steps": [{"id": "s1", "type": "unknown"}]}
        ok, errors = TaskValidator.validate(config)
        assert ok is False
        assert any("未知" in e for e in errors)

    def test_input_step_missing_selector(self):
        config = {"name": "测试", "steps": [{"id": "s1", "type": "input"}]}
        ok, errors = TaskValidator.validate(config)
        assert ok is False
        assert any("selector" in e for e in errors)

    def test_eval_step_missing_script(self):
        config = {"name": "测试", "steps": [{"id": "s1", "type": "eval"}]}
        ok, errors = TaskValidator.validate(config)
        assert ok is False
        assert any("脚本" in e for e in errors)

    def test_wait_url_missing_pattern(self):
        config = {"name": "测试", "steps": [{"id": "s1", "type": "wait_url"}]}
        ok, errors = TaskValidator.validate(config)
        assert ok is False
        assert any("pattern" in e for e in errors)

    def test_ocr_missing_selector(self):
        config = {"name": "测试", "steps": [{"id": "s1", "type": "ocr"}]}
        ok, errors = TaskValidator.validate(config)
        assert ok is False
        assert any("selector" in e for e in errors)

    def test_custom_js_valid(self):
        config = {
            "name": "测试",
            "steps": [{"id": "s1", "type": "custom_js", "code": "return 1"}],
        }
        ok, errors = TaskValidator.validate(config)
        assert ok is True

    def test_click_select_missing_selector(self):
        config = {"name": "测试", "steps": [{"id": "s1", "type": "click_select"}]}
        ok, errors = TaskValidator.validate(config)
        assert ok is False

    def test_valid_step_ids(self):
        """各种合法 step id 应通过验证"""
        for sid in ["s1", "step_1", "Click", "a"]:
            config = {
                "name": "测试",
                "steps": [{"id": sid, "type": "click", "selector": "#btn"}],
            }
            ok, _ = TaskValidator.validate(config)
            assert ok is True, f"step id '{sid}' 应通过验证"


# =====================================================================
# normalize_task_id / is_valid_task_id
# =====================================================================


class TestTaskIdHelpers:
    def test_normalize_strips(self):
        assert normalize_task_id("  test  ") == "test"

    def test_normalize_non_string(self):
        assert normalize_task_id(None) == ""
        assert normalize_task_id(123) == ""

    def test_valid_ids(self):
        assert is_valid_task_id("default") is True
        assert is_valid_task_id("my_task") is True
        assert is_valid_task_id("Task1") is True

    def test_invalid_ids(self):
        assert is_valid_task_id("") is False
        assert is_valid_task_id("123abc") is False
        assert is_valid_task_id("my-task") is False
        assert is_valid_task_id(None) is False


# =====================================================================
# TaskManager
# =====================================================================


class TestTaskManager:
    def test_list_tasks(self, tmp_path):
        mgr = TaskManager(tmp_path)
        # 创建一个有效任务文件（浏览器任务在 browser/ 子目录）
        task_file = tmp_path / "browser" / "test_task.json"
        task_file.write_text(
            json.dumps({"name": "测试", "steps": []}),
            encoding="utf-8",
        )
        tasks = mgr.list_tasks()
        assert len(tasks) == 1
        assert tasks[0]["id"] == "test_task"

    def test_list_tasks_skips_invalid_ids(self, tmp_path):
        mgr = TaskManager(tmp_path)
        browser_dir = tmp_path / "browser"
        # 含连字符的文件名应被跳过
        (browser_dir / "my-task.json").write_text(
            '{"name":"x","steps":[]}', encoding="utf-8"
        )
        (browser_dir / "valid_task.json").write_text(
            '{"name":"y","steps":[]}', encoding="utf-8"
        )
        tasks = mgr.list_tasks()
        assert len(tasks) == 1
        assert tasks[0]["id"] == "valid_task"

    def test_load_task(self, tmp_path):
        mgr = TaskManager(tmp_path)
        data = {
            "name": "加载测试",
            "url": "http://test.com",
            "steps": [{"id": "s1", "type": "click", "selector": "#btn"}],
        }
        (tmp_path / "browser" / "my_task.json").write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8"
        )
        config = mgr.load_task("my_task")
        assert config is not None
        assert config.name == "加载测试"
        assert config.task_id == "my_task"

    def test_load_task_nonexistent(self, tmp_path):
        mgr = TaskManager(tmp_path)
        assert mgr.load_task("nonexistent") is None

    def test_load_task_invalid_id(self, tmp_path):
        mgr = TaskManager(tmp_path)
        assert mgr.load_task("123bad") is None

    def test_save_task(self, tmp_path):
        mgr = TaskManager(tmp_path)
        data = {
            "name": "保存测试",
            "steps": [{"id": "s1", "type": "click", "selector": "#btn"}],
        }
        ok = mgr.save_task("new_task", data)
        assert ok is True
        assert (tmp_path / "browser" / "new_task.json").exists()

    def test_save_task_invalid(self, tmp_path):
        mgr = TaskManager(tmp_path)
        ok = mgr.save_task("bad_task", {"name": ""})
        assert ok is False

    def test_delete_task(self, tmp_path):
        mgr = TaskManager(tmp_path)
        (tmp_path / "browser" / "to_delete.json").write_text(
            '{"name":"x","steps":[]}', encoding="utf-8"
        )
        ok = mgr.delete_task("to_delete")
        assert ok is True
        assert not (tmp_path / "browser" / "to_delete.json").exists()

    def test_delete_default_returns_false(self, tmp_path):
        mgr = TaskManager(tmp_path)
        assert mgr.delete_task("default") is False

    def test_delete_nonexistent(self, tmp_path):
        """删除不存在的任务：file.unlink(missing_ok=True) 会返回 True"""
        mgr = TaskManager(tmp_path)
        assert mgr.delete_task("nonexistent") is True

    def test_get_active_task_default(self, tmp_path):
        mgr = TaskManager(tmp_path)
        assert mgr.get_active_task() == "default"

    def test_set_active_task(self, tmp_path):
        mgr = TaskManager(tmp_path)
        (tmp_path / "browser" / "my_task.json").write_text(
            '{"name":"x","steps":[]}', encoding="utf-8"
        )
        ok = mgr.set_active_task("my_task")
        assert ok is True
        assert mgr.get_active_task() == "my_task"

    def test_set_active_task_nonexistent(self, tmp_path):
        mgr = TaskManager(tmp_path)
        ok = mgr.set_active_task("nonexistent")
        assert ok is False

    def test_set_active_task_invalid_id(self, tmp_path):
        mgr = TaskManager(tmp_path)
        ok = mgr.set_active_task("123bad")
        assert ok is False

    def test_path_traversal_prevention(self, tmp_path):
        """路径遍历攻击应被阻止"""
        mgr = TaskManager(tmp_path)
        assert mgr.load_task("../etc/passwd") is None
        assert mgr.save_task("../etc/passwd", {"name": "x", "steps": []}) is False
        assert mgr.delete_task("../etc/passwd") is False


# =====================================================================
# TaskExecutor（使用 mock page）
# =====================================================================


class TestTaskExecutor:
    @pytest.mark.asyncio
    async def test_execute_step_at_out_of_range(self):
        config = TaskConfig(
            name="test",
            steps=[StepConfig(id="s1", type="click", selector="#btn")],
        )
        executor = TaskExecutor(config)
        mock_page = MagicMock()
        result = await executor.execute_step_at(mock_page, -1)
        assert result["success"] is False
        assert "超出范围" in result["message"]

        result = await executor.execute_step_at(mock_page, 10)
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_execute_all_steps_success(self):
        """所有步骤成功时应返回成功"""
        config = TaskConfig(
            name="test",
            steps=[
                StepConfig(id="s1", type="eval", script="return true"),
            ],
        )
        executor = TaskExecutor(config)

        mock_page = MagicMock()
        mock_page.evaluate = AsyncMock(return_value=True)
        mock_page.goto = AsyncMock()
        mock_page.wait_for_selector = AsyncMock()
        mock_page.frames = [MagicMock()]

        ok, msg = await executor.execute(mock_page)
        assert ok is True

    @pytest.mark.asyncio
    async def test_execute_step_failure_stops(self):
        """步骤失败时应停止执行"""
        config = TaskConfig(
            name="test",
            steps=[
                StepConfig(id="s1", type="eval", script="return true"),
                StepConfig(id="s2", type="eval", script=""),
            ],
        )
        executor = TaskExecutor(config)

        mock_page = MagicMock()
        mock_page.evaluate = AsyncMock(return_value=True)
        mock_page.goto = AsyncMock()
        mock_page.wait_for_selector = AsyncMock()
        mock_page.frames = [MagicMock()]
        mock_page.screenshot = AsyncMock()
        mock_page.url = "http://test.com"

        ok, msg = await executor.execute(mock_page)
        assert ok is False

    def test_registry_initialized(self):
        config = TaskConfig(name="test")
        executor = TaskExecutor(config)
        assert executor.registry is not None
        assert isinstance(executor.registry, StepExecutorRegistry)

    def test_resolver_initialized(self):
        config = TaskConfig(name="test", variables={"X": "1"})
        executor = TaskExecutor(config, template_vars={"Y": "2"})
        assert executor.resolver is not None
        assert executor.resolver.resolve("{{X}}") == "1"
        assert executor.resolver.resolve("{{Y}}") == "2"

    @pytest.mark.asyncio
    async def test_execute_step_timeout_truncation(self):
        """步骤超时应被截断到任务剩余时间"""
        config = TaskConfig(
            name="test",
            timeout=5000,
            steps=[StepConfig(id="s1", type="eval", script="return 1", timeout=10000)],
        )
        executor = TaskExecutor(config)
        mock_page = MagicMock()
        mock_page.evaluate = AsyncMock(return_value=1)

        step = config.steps[0]
        assert step.timeout == 10000
        # deadline = 5.0s, perf_counter = 4.5s → 剩余 500ms
        task_deadline = time.perf_counter() + 0.5
        success, _ = await executor._execute_step(mock_page, step, task_deadline)
        assert success is True
        # 执行后恢复原值
        assert step.timeout == 10000

    @pytest.mark.asyncio
    async def test_execute_step_sleep_duration_truncation(self):
        """sleep 步骤时长应被截断到任务剩余时间"""
        config = TaskConfig(
            name="test",
            timeout=5000,
            steps=[StepConfig(id="s1", type="sleep", duration=300000)],
        )
        executor = TaskExecutor(config)
        mock_page = MagicMock()
        mock_page.wait_for_timeout = AsyncMock()

        step = config.steps[0]
        task_deadline = time.perf_counter() + 1.0
        success, _ = await executor._execute_step(mock_page, step, task_deadline)
        assert success is True
        # 验证 wait_for_timeout 被调用的时长不超过剩余时间（约 1000ms）
        call_args = mock_page.wait_for_timeout.call_args[0][0]
        assert call_args <= 1100  # 允许少量误差
        # 验证 duration 恢复原值
        assert step.duration == 300000
