"""任务验证器测试 — 覆盖 TaskValidator。"""

from __future__ import annotations

from app.tasks.validator import TaskValidator

# ── validate ──


class TestValidate:
    """任务配置验证。"""

    def test_valid_config(self):
        """有效配置。"""
        config = {
            "name": "测试任务",
            "steps": [
                {"id": "s1", "type": "click", "selector": "#btn"},
            ],
        }
        ok, errors = TaskValidator.validate(config)
        assert ok is True
        assert errors == []

    def test_missing_name(self):
        """缺少 name。"""
        config = {"steps": [{"id": "s1", "type": "click", "selector": "#btn"}]}
        ok, errors = TaskValidator.validate(config)
        assert ok is False
        assert any("name" in e for e in errors)

    def test_missing_steps(self):
        """缺少 steps。"""
        config = {"name": "test"}
        ok, errors = TaskValidator.validate(config)
        assert ok is False
        assert any("steps" in e for e in errors)

    def test_steps_not_list(self):
        """steps 不是数组。"""
        config = {"name": "test", "steps": "not a list"}
        ok, errors = TaskValidator.validate(config)
        assert ok is False
        assert any("数组" in e for e in errors)

    def test_empty_steps(self):
        """空 steps 数组是合法的（任务可以没有步骤）。"""
        config = {"name": "test", "steps": []}
        ok, errors = TaskValidator.validate(config)
        assert ok is True
        assert errors == []

    def test_multiple_errors(self):
        """多个错误。"""
        config = {}
        ok, errors = TaskValidator.validate(config)
        assert ok is False
        assert len(errors) >= 2


# ── _validate_step ──


class TestValidateStep:
    """步骤验证。"""

    def test_valid_step(self):
        """有效步骤。"""
        step = {"id": "s1", "type": "click", "selector": "#btn"}
        errors = TaskValidator._validate_step(step, 0)
        assert errors == []

    def test_missing_id(self):
        """缺少 id。"""
        step = {"type": "click", "selector": "#btn"}
        errors = TaskValidator._validate_step(step, 0)
        assert any("id" in e for e in errors)

    def test_missing_type(self):
        """缺少 type。"""
        step = {"id": "s1", "selector": "#btn"}
        errors = TaskValidator._validate_step(step, 0)
        assert any("type" in e for e in errors)

    def test_invalid_step_id(self):
        """无效步骤 ID。"""
        step = {"id": "123", "type": "click", "selector": "#btn"}
        errors = TaskValidator._validate_step(step, 0)
        assert any("格式无效" in e for e in errors)

    def test_invalid_step_type(self):
        """无效步骤类型。"""
        step = {"id": "s1", "type": "invalid"}
        errors = TaskValidator._validate_step(step, 0)
        assert any("未知" in e for e in errors)

    def test_click_requires_selector(self):
        """click 需要 selector。"""
        step = {"id": "s1", "type": "click"}
        errors = TaskValidator._validate_step(step, 0)
        assert any("selector" in e for e in errors)

    def test_input_requires_selector(self):
        """input 需要 selector。"""
        step = {"id": "s1", "type": "input"}
        errors = TaskValidator._validate_step(step, 0)
        assert any("selector" in e for e in errors)

    def test_select_requires_selector(self):
        """select 需要 selector。"""
        step = {"id": "s1", "type": "select"}
        errors = TaskValidator._validate_step(step, 0)
        assert any("selector" in e for e in errors)

    def test_wait_url_requires_pattern(self):
        """wait_url 需要 pattern。"""
        step = {"id": "s1", "type": "wait_url"}
        errors = TaskValidator._validate_step(step, 0)
        assert any("pattern" in e for e in errors)

    def test_eval_requires_script(self):
        """eval 需要 script。"""
        step = {"id": "s1", "type": "eval"}
        errors = TaskValidator._validate_step(step, 0)
        assert any("脚本" in e for e in errors)

    def test_eval_with_code_accepted(self):
        """eval 接受 code（兼容）。"""
        step = {"id": "s1", "type": "eval", "code": "return 1"}
        errors = TaskValidator._validate_step(step, 0)
        assert errors == []

    def test_ocr_requires_selector(self):
        """ocr 需要 selector。"""
        step = {"id": "s1", "type": "ocr"}
        errors = TaskValidator._validate_step(step, 0)
        assert any("selector" in e for e in errors)

    def test_custom_js_accepted(self):
        """custom_js 类型被接受。"""
        step = {"id": "s1", "type": "custom_js", "code": "return 1"}
        errors = TaskValidator._validate_step(step, 0)
        assert errors == []

    def test_step_index_in_error(self):
        """错误消息包含步骤索引。"""
        step = {"id": "s1", "type": "invalid"}
        errors = TaskValidator._validate_step(step, 5)
        assert any("steps[5]" in e for e in errors)

    def test_wait_no_selector_required(self):
        """wait 不需要 selector。"""
        step = {"id": "s1", "type": "wait", "selector": "#el"}
        errors = TaskValidator._validate_step(step, 0)
        assert errors == []

    def test_sleep_no_extra_fields(self):
        """sleep 不需要额外字段。"""
        step = {"id": "s1", "type": "sleep", "duration": 1000}
        errors = TaskValidator._validate_step(step, 0)
        assert errors == []

    def test_screenshot_no_extra_fields(self):
        """screenshot 不需要额外字段。"""
        step = {"id": "s1", "type": "screenshot"}
        errors = TaskValidator._validate_step(step, 0)
        assert errors == []

    def test_timeout_negative_rejected(self):
        """负数 timeout 触发错误。"""
        step = {"id": "s1", "type": "click", "selector": "#btn", "timeout": -1}
        errors = TaskValidator._validate_step(step, 0)
        assert any("timeout" in e for e in errors)

    def test_timeout_zero_rejected(self):
        """零 timeout 触发错误。"""
        step = {"id": "s1", "type": "click", "selector": "#btn", "timeout": 0}
        errors = TaskValidator._validate_step(step, 0)
        assert any("timeout" in e for e in errors)

    def test_timeout_non_numeric_rejected(self):
        """非数值 timeout 触发错误。"""
        step = {"id": "s1", "type": "click", "selector": "#btn", "timeout": "abc"}
        errors = TaskValidator._validate_step(step, 0)
        assert any("timeout" in e for e in errors)

    def test_timeout_float_accepted(self):
        """浮点数 timeout 被接受。"""
        step = {"id": "s1", "type": "click", "selector": "#btn", "timeout": 5.0}
        errors = TaskValidator._validate_step(step, 0)
        assert errors == []


class TestValidateDuplicateIds:
    """步骤重复 ID 检测。"""

    def test_duplicate_ids_reported(self):
        """重复步骤 ID 触发错误。"""
        config = {
            "name": "test",
            "steps": [
                {"id": "s1", "type": "click", "selector": "#a"},
                {"id": "s1", "type": "click", "selector": "#b"},
            ],
        }
        ok, errors = TaskValidator.validate(config)
        assert ok is False
        assert any("重复" in e for e in errors)

    def test_unique_ids_valid(self):
        """唯一步骤 ID 通过验证。"""
        config = {
            "name": "test",
            "steps": [
                {"id": "s1", "type": "click", "selector": "#a"},
                {"id": "s2", "type": "click", "selector": "#b"},
            ],
        }
        ok, errors = TaskValidator.validate(config)
        assert ok is True
