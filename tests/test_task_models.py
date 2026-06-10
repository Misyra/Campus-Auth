"""任务模型测试 — 覆盖 StepConfig / TaskConfig 的序列化与反序列化。"""

from __future__ import annotations

from app.tasks.models import StepConfig, StepType, TaskConfig

# ── StepConfig.from_dict ──


class TestStepConfigFromDict:
    """StepConfig.from_dict 构建逻辑。"""

    def test_basic_construction(self):
        """基本字段构建。"""
        data = {"id": "s1", "type": "click", "selector": "#btn"}
        step = StepConfig.from_dict(data)
        assert step.id == "s1"
        assert step.type == "click"
        assert step.selector == "#btn"

    def test_code_normalized_to_script(self):
        """code 字段规范化为 script。"""
        data = {"id": "s1", "type": "eval", "code": "return 1+1"}
        step = StepConfig.from_dict(data)
        assert step.script == "return 1+1"
        assert not hasattr(step, "code") or "code" not in step.__dict__

    def test_script_takes_precedence_over_code(self):
        """同时存在 code 和 script 时，script 优先。"""
        data = {"id": "s1", "type": "eval", "code": "old", "script": "new"}
        step = StepConfig.from_dict(data)
        assert step.script == "new"

    def test_frame_non_string_cleared(self):
        """非字符串 frame 值被静默清空。"""
        data = {"id": "s1", "type": "click", "selector": "#btn", "frame": True}
        step = StepConfig.from_dict(data)
        assert step.frame is None

    def test_frame_string_preserved(self):
        """字符串 frame 值保留。"""
        data = {
            "id": "s1",
            "type": "click",
            "selector": "#btn",
            "frame": "iframe[name=main]",
        }
        step = StepConfig.from_dict(data)
        assert step.frame == "iframe[name=main]"

    def test_frame_none_preserved(self):
        """None frame 值保留。"""
        data = {"id": "s1", "type": "click", "selector": "#btn", "frame": None}
        step = StepConfig.from_dict(data)
        assert step.frame is None

    def test_unknown_fields_merged_to_extra(self):
        """未知字段合并到 extra。"""
        data = {
            "id": "s1",
            "type": "click",
            "selector": "#btn",
            "custom_field": "value",
        }
        step = StepConfig.from_dict(data)
        assert step.extra["custom_field"] == "value"

    def test_extra_field_in_data_merged(self):
        """data 中的 extra 字段与未知字段合并。"""
        data = {
            "id": "s1",
            "type": "click",
            "selector": "#btn",
            "extra": {"a": 1},
            "b": 2,
        }
        step = StepConfig.from_dict(data)
        assert step.extra == {"a": 1, "b": 2}

    def test_empty_dict_minimal(self):
        """空字典只填充必填字段。"""
        data = {"id": "s1", "type": "wait"}
        step = StepConfig.from_dict(data)
        assert step.id == "s1"
        assert step.type == "wait"
        assert step.selector is None
        assert step.timeout is None

    def test_all_fields_populated(self):
        """所有字段都能正确填充。"""
        data = {
            "id": "s1",
            "type": "ocr",
            "selector": "#captcha-img",
            "target_selector": "#captcha-input",
            "store_as": "CAPTCHA",
            "old": True,
            "char_range": "0123456789",
            "timeout": 5000,
            "required": True,
        }
        step = StepConfig.from_dict(data)
        assert step.selector == "#captcha-img"
        assert step.target_selector == "#captcha-input"
        assert step.store_as == "CAPTCHA"
        assert step.old is True
        assert step.char_range == "0123456789"
        assert step.timeout == 5000
        assert step.required is True


# ── StepConfig.to_dict ──


class TestStepConfigToDict:
    """StepConfig.to_dict 序列化逻辑。"""

    def test_minimal_output(self):
        """最小输出只包含 id 和 type。"""
        step = StepConfig(id="s1", type="wait")
        d = step.to_dict()
        assert d == {"id": "s1", "type": "wait"}

    def test_non_default_fields_included(self):
        """非默认值字段被包含。"""
        step = StepConfig(id="s1", type="input", selector="#name", value="test")
        d = step.to_dict()
        assert d["selector"] == "#name"
        assert d["value"] == "test"

    def test_default_values_skipped(self):
        """默认值字段被跳过。"""
        step = StepConfig(id="s1", type="input", clear=True)
        d = step.to_dict()
        assert "clear" not in d
        assert "duration" not in d

    def test_none_values_skipped(self):
        """None 值字段被跳过。"""
        step = StepConfig(id="s1", type="click", selector=None, timeout=None)
        d = step.to_dict()
        assert "selector" not in d
        assert "timeout" not in d

    def test_extra_merged_to_top_level(self):
        """extra 字段合并到顶层。"""
        step = StepConfig(id="s1", type="click", extra={"custom": 42})
        d = step.to_dict()
        assert d["custom"] == 42
        assert "extra" not in d

    def test_roundtrip_preserves_data(self):
        """from_dict -> to_dict 往返保持数据一致。"""
        original = {
            "id": "s1",
            "type": "input",
            "selector": "#username",
            "value": "admin",
            "timeout": 5000,
            "extra": {"custom": True},
        }
        step = StepConfig.from_dict(original)
        result = step.to_dict()
        assert result["id"] == "s1"
        assert result["type"] == "input"
        assert result["selector"] == "#username"
        assert result["value"] == "admin"
        assert result["timeout"] == 5000
        assert result["custom"] is True


# ── TaskConfig.from_dict ──


class TestTaskConfigFromDict:
    """TaskConfig.from_dict 构建逻辑。"""

    def test_basic_construction(self):
        """基本字段构建。"""
        data = {
            "task_id": "login",
            "name": "登录任务",
            "url": "http://example.com",
            "steps": [{"id": "s1", "type": "click", "selector": "#btn"}],
        }
        config = TaskConfig.from_dict(data)
        assert config.task_id == "login"
        assert config.name == "登录任务"
        assert config.url == "http://example.com"
        assert len(config.steps) == 1
        assert config.steps[0].id == "s1"

    def test_default_values(self):
        """缺失字段使用默认值。"""
        data = {}
        config = TaskConfig.from_dict(data)
        assert config.task_id == ""
        assert config.name == "未命名任务"
        assert config.timeout == 30000
        assert config.variables == {}
        assert config.steps == []
        assert config.reveal_hidden is False
        assert config.step_delay == 0.5

    def test_variables_preserved(self):
        """变量字典被保留。"""
        data = {"variables": {"USERNAME": "admin", "PASSWORD": "123"}}
        config = TaskConfig.from_dict(data)
        assert config.variables == {"USERNAME": "admin", "PASSWORD": "123"}

    def test_metadata_preserved(self):
        """元数据被保留。"""
        data = {"metadata": {"author": "test", "version": 2}}
        config = TaskConfig.from_dict(data)
        assert config.metadata == {"author": "test", "version": 2}

    def test_step_delay_conversion(self):
        """step_delay 正确转换为 float。"""
        data = {"step_delay": 1}
        config = TaskConfig.from_dict(data)
        assert config.step_delay == 1.0
        assert isinstance(config.step_delay, float)


# ── TaskConfig.to_dict ──


class TestTaskConfigToDict:
    """TaskConfig.to_dict 序列化逻辑。"""

    def test_minimal_output(self):
        """最小输出包含必填字段。"""
        config = TaskConfig(task_id="t1", name="test", url="http://example.com")
        d = config.to_dict()
        assert d["task_id"] == "t1"
        assert d["name"] == "test"
        assert d["url"] == "http://example.com"
        assert d["steps"] == []

    def test_empty_optional_fields_skipped(self):
        """空的可选字段被跳过。"""
        config = TaskConfig(task_id="t1", name="test", url="http://example.com")
        d = config.to_dict()
        assert "variables" not in d
        assert "on_success" not in d
        assert "on_failure" not in d
        assert "metadata" not in d
        assert "reveal_hidden" not in d
        assert "step_delay" not in d

    def test_non_default_values_included(self):
        """非默认值的可选字段被包含。"""
        config = TaskConfig(
            task_id="t1",
            name="test",
            url="http://example.com",
            variables={"X": "1"},
            reveal_hidden=True,
            step_delay=1.0,
        )
        d = config.to_dict()
        assert d["variables"] == {"X": "1"}
        assert d["reveal_hidden"] is True
        assert d["step_delay"] == 1.0

    def test_steps_serialized(self):
        """步骤列表被正确序列化。"""
        config = TaskConfig(
            task_id="t1",
            name="test",
            url="http://example.com",
            steps=[StepConfig(id="s1", type="click", selector="#btn")],
        )
        d = config.to_dict()
        assert len(d["steps"]) == 1
        assert d["steps"][0]["id"] == "s1"

    def test_roundtrip_preserves_data(self):
        """from_dict -> to_dict 往返保持数据一致。"""
        original = {
            "task_id": "login",
            "name": "登录",
            "url": "http://example.com",
            "timeout": 60000,
            "variables": {"USER": "admin"},
            "steps": [
                {"id": "s1", "type": "input", "selector": "#user", "value": "{{USER}}"},
                {"id": "s2", "type": "click", "selector": "#submit"},
            ],
            "reveal_hidden": True,
            "step_delay": 1.0,
        }
        config = TaskConfig.from_dict(original)
        result = config.to_dict()
        assert result["task_id"] == "login"
        assert result["name"] == "登录"
        assert result["timeout"] == 60000
        assert result["variables"] == {"USER": "admin"}
        assert len(result["steps"]) == 2
        assert result["reveal_hidden"] is True
        assert result["step_delay"] == 1.0


# ── StepType 枚举 ──


class TestStepType:
    """StepType 枚举值。"""

    def test_all_types_present(self):
        """所有标准步骤类型都存在。"""
        expected = {
            "input",
            "click",
            "select",
            "wait",
            "wait_url",
            "eval",
            "screenshot",
            "sleep",
            "ocr",
            "click_select",
        }
        actual = {t.value for t in StepType}
        assert actual == expected

    def test_enum_value_is_string(self):
        """枚举值是字符串。"""
        assert isinstance(StepType.CLICK, str)
        assert StepType.CLICK == "click"
