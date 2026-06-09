"""任务服务逻辑测试 — 覆盖纯逻辑函数。"""

from __future__ import annotations

from app.services.task import _DANGEROUS_STEP_TYPES, _check_dangerous_steps

# ── _check_dangerous_steps ──


class TestCheckDangerousSteps:
    """危险步骤检查。"""

    def test_no_steps(self):
        """无步骤。"""
        result = _check_dangerous_steps({})
        assert result == []

    def test_safe_steps(self):
        """安全步骤。"""
        task_data = {
            "steps": [
                {"id": "s1", "type": "click", "selector": "#btn"},
                {"id": "s2", "type": "input", "selector": "#input", "value": "test"},
            ]
        }
        result = _check_dangerous_steps(task_data)
        assert result == []

    def test_eval_step(self):
        """eval 步骤被检测。"""
        task_data = {
            "steps": [
                {"id": "s1", "type": "eval", "script": "return 1"},
            ]
        }
        result = _check_dangerous_steps(task_data)
        assert len(result) == 1
        assert result[0]["step_type"] == "eval"
        assert result[0]["step_index"] == 1

    def test_custom_js_step(self):
        """custom_js 步骤被检测。"""
        task_data = {
            "steps": [
                {"id": "s1", "type": "custom_js", "code": "alert(1)"},
            ]
        }
        result = _check_dangerous_steps(task_data)
        assert len(result) == 1
        assert result[0]["step_type"] == "custom_js"

    def test_code_field_extracted(self):
        """code 字段被提取。"""
        task_data = {
            "steps": [
                {"id": "s1", "type": "eval", "code": "return 1+1"},
            ]
        }
        result = _check_dangerous_steps(task_data)
        assert result[0]["code"] == "return 1+1"

    def test_script_field_extracted(self):
        """script 字段被提取。"""
        task_data = {
            "steps": [
                {"id": "s1", "type": "eval", "script": "return 2+2"},
            ]
        }
        result = _check_dangerous_steps(task_data)
        assert result[0]["code"] == "return 2+2"

    def test_extra_code_extracted(self):
        """extra.code 被提取。"""
        task_data = {
            "steps": [
                {"id": "s1", "type": "eval", "extra": {"code": "return 3+3"}},
            ]
        }
        result = _check_dangerous_steps(task_data)
        assert result[0]["code"] == "return 3+3"

    def test_multiple_dangerous_steps(self):
        """多个危险步骤。"""
        task_data = {
            "steps": [
                {"id": "s1", "type": "eval", "script": "return 1"},
                {"id": "s2", "type": "click", "selector": "#btn"},
                {"id": "s3", "type": "custom_js", "code": "alert(1)"},
            ]
        }
        result = _check_dangerous_steps(task_data)
        assert len(result) == 2
        assert result[0]["step_index"] == 1
        assert result[1]["step_index"] == 3

    def test_description_fallback(self):
        """描述回退到 id。"""
        task_data = {
            "steps": [
                {"id": "s1", "type": "eval", "script": "return 1"},
            ]
        }
        result = _check_dangerous_steps(task_data)
        assert result[0]["description"] == "s1"

    def test_description_from_step(self):
        """描述从 description 字段获取。"""
        task_data = {
            "steps": [
                {"id": "s1", "type": "eval", "description": "自定义描述", "script": "return 1"},
            ]
        }
        result = _check_dangerous_steps(task_data)
        assert result[0]["description"] == "自定义描述"

    def test_non_dict_step_skipped(self):
        """非字典步骤被跳过。"""
        task_data = {
            "steps": ["not a dict", 123, None]
        }
        result = _check_dangerous_steps(task_data)
        assert result == []

    def test_long_code_truncated(self):
        """长代码被截断。"""
        long_code = "x" * 3000
        task_data = {
            "steps": [
                {"id": "s1", "type": "eval", "script": long_code},
            ]
        }
        result = _check_dangerous_steps(task_data)
        assert len(result[0]["code"]) == 2000


# ── _DANGEROUS_STEP_TYPES ──


class TestDangerousStepTypes:
    """危险步骤类型常量。"""

    def test_contains_eval(self):
        """包含 eval。"""
        assert "eval" in _DANGEROUS_STEP_TYPES

    def test_contains_custom_js(self):
        """包含 custom_js。"""
        assert "custom_js" in _DANGEROUS_STEP_TYPES

    def test_not_contains_click(self):
        """不包含 click。"""
        assert "click" not in _DANGEROUS_STEP_TYPES
