from __future__ import annotations

from pathlib import Path

import pytest

from src.task_executor import (
    ConditionConfig,
    StepConfig,
    TaskConfig,
    TaskExecutor,
    TaskManager,
    TaskValidator,
    is_valid_task_id,
    normalize_task_id,
)


def _build_executor(variables: dict[str, str]) -> TaskExecutor:
    """构建测试执行器"""
    config = TaskConfig(
        name="demo",
        url="http://example.com",
        variables=variables,
        steps=[],
    )
    return TaskExecutor(config=config, env_vars={"USERNAME": "alice"})


def test_resolve_variable_nested_reference() -> None:
    """测试嵌套变量解析"""
    executor = _build_executor(
        {
            "username": "{{USERNAME}}",
            "greeting": "hello-{{username}}",
        }
    )

    assert executor.resolver.resolve("{{greeting}}") == "hello-alice"


def test_resolve_variable_cycle_raises() -> None:
    """测试变量循环引用检测"""
    executor = _build_executor(
        {
            "a": "{{b}}",
            "b": "{{a}}",
        }
    )

    with pytest.raises(Exception, match="循环引用"):
        executor.resolver.resolve("{{a}}")


def test_resolve_variable_depth_limit_raises() -> None:
    """测试变量展开深度限制"""
    long_chain = {f"a{i}": f"{{{{a{i + 1}}}}}" for i in range(17)}
    long_chain["a17"] = "final"

    executor = _build_executor(long_chain)

    with pytest.raises(Exception, match="层级超过限制"):
        executor.resolver.resolve("{{a0}}")


def test_task_manager_rejects_invalid_task_id(tmp_path: Path) -> None:
    """测试任务管理器拒绝无效任务ID"""
    manager = TaskManager(tmp_path / "tasks")

    assert manager.load_task("../evil") is None
    assert manager.save_task("../evil", {"name": "x", "steps": []}) is False
    assert manager.set_active_task("../evil") is False


def test_task_id_helpers_normalize_and_validate() -> None:
    """测试任务ID辅助函数"""
    assert normalize_task_id("  task_01  ") == "task_01"
    assert is_valid_task_id(" task_01 ") is True
    assert is_valid_task_id("task-01") is False
    assert is_valid_task_id("01task") is False  # 必须以字母开头


def test_task_validator_valid_task() -> None:
    """测试验证器通过有效任务"""
    valid_task = {
        "name": "测试任务",
        "steps": [
            {"id": "step1", "type": "navigate", "url": "http://example.com"}
        ],
    }
    is_valid, errors = TaskValidator.validate(valid_task)
    assert is_valid is True
    assert len(errors) == 0


def test_task_validator_missing_name() -> None:
    """测试验证器检测缺少名称"""
    invalid_task = {
        "steps": [{"id": "step1", "type": "navigate", "url": "http://example.com"}]
    }
    is_valid, errors = TaskValidator.validate(invalid_task)
    assert is_valid is False
    assert any("name" in e for e in errors)


def test_task_validator_missing_steps() -> None:
    """测试验证器检测缺少步骤"""
    invalid_task = {"name": "测试任务"}
    is_valid, errors = TaskValidator.validate(invalid_task)
    assert is_valid is False
    assert any("steps" in e for e in errors)


def test_task_validator_invalid_step_type() -> None:
    """测试验证器检测无效步骤类型"""
    invalid_task = {
        "name": "测试任务",
        "steps": [{"id": "step1", "type": "invalid_type"}],
    }
    is_valid, errors = TaskValidator.validate(invalid_task)
    assert is_valid is False
    assert any("invalid_type" in e for e in errors)


def test_task_validator_missing_step_fields() -> None:
    """测试验证器检测缺少步骤字段"""
    invalid_task = {
        "name": "测试任务",
        "steps": [{"type": "navigate"}],  # 缺少 id
    }
    is_valid, errors = TaskValidator.validate(invalid_task)
    assert is_valid is False
    assert any("id" in e.lower() for e in errors)


def test_task_validator_navigate_missing_url() -> None:
    """测试验证器检测 navigate 缺少 url"""
    invalid_task = {
        "name": "测试任务",
        "steps": [{"id": "step1", "type": "navigate"}],
    }
    is_valid, errors = TaskValidator.validate(invalid_task)
    assert is_valid is False
    assert any("url" in e for e in errors)


def test_task_validator_input_missing_selector() -> None:
    """测试验证器检测 input 缺少 selector"""
    invalid_task = {
        "name": "测试任务",
        "steps": [{"id": "step1", "type": "input", "value": "test"}],
    }
    is_valid, errors = TaskValidator.validate(invalid_task)
    assert is_valid is False
    assert any("selector" in e for e in errors)


def test_task_config_from_dict() -> None:
    """测试从字典创建任务配置"""
    data = {
        "name": "测试任务",
        "description": "测试描述",
        "version": "1.0.0",
        "url": "http://example.com",
        "timeout": 15000,
        "variables": {"key": "value"},
        "steps": [
            {"id": "s1", "type": "navigate", "url": "{{url}}"}
        ],
        "success_conditions": [
            {"type": "variable", "variable": "result", "value": True}
        ],
        "on_success": {"message": "成功"},
        "on_failure": {"message": "失败", "screenshot": True},
    }
    config = TaskConfig.from_dict(data)
    assert config.name == "测试任务"
    assert config.description == "测试描述"
    assert config.version == "1.0.0"
    assert config.timeout == 15000
    assert len(config.steps) == 1
    assert len(config.success_conditions) == 1


def test_step_config_to_dict_strips_nulls() -> None:
    """测试 to_dict 跳过默认值和 None"""
    step = StepConfig(id="s1", type="navigate", url="http://example.com")
    d = step.to_dict()
    assert d == {"id": "s1", "type": "navigate", "url": "http://example.com"}
    # 不应包含 description, timeout, selector 等默认值
    assert "description" not in d
    assert "timeout" not in d
    assert "selector" not in d
    assert "extra" not in d


def test_step_config_to_dict_includes_non_defaults() -> None:
    """测试 to_dict 包含非默认值"""
    step = StepConfig(
        id="s1", type="input", selector="#user", value="test", clear=False, timeout=3000
    )
    d = step.to_dict()
    assert d["selector"] == "#user"
    assert d["value"] == "test"
    assert d["clear"] is False
    assert d["timeout"] == 3000
    # clear=True 是默认值，clear=False 应该出现


def test_step_config_to_dict_merges_extra() -> None:
    """测试 to_dict 将 extra 合并回顶层"""
    step = StepConfig(id="s1", type="click", selector="#btn", extra={"custom": 42})
    d = step.to_dict()
    assert d["custom"] == 42
    assert "extra" not in d


def test_step_config_from_dict_normalizes_code_to_script() -> None:
    """测试 from_dict 将 code 规范化为 script"""
    step = StepConfig.from_dict({
        "id": "s1", "type": "eval", "code": "return 1+1"
    })
    assert step.script == "return 1+1"
    # code 不应留在 extra 中
    assert "code" not in step.extra


def test_step_config_from_dict_script_takes_precedence() -> None:
    """测试 from_dict 中 script 优先于 code"""
    step = StepConfig.from_dict({
        "id": "s1", "type": "eval", "script": "return 1", "code": "return 2"
    })
    assert step.script == "return 1"


def test_condition_config_to_dict() -> None:
    """测试 ConditionConfig.to_dict 跳过 None"""
    cond = ConditionConfig(type="variable", variable="x", value=True)
    d = cond.to_dict()
    assert d == {"type": "variable", "variable": "x", "value": True}
    assert "pattern" not in d
    assert "selector" not in d
    assert "script" not in d


def test_task_config_to_dict_compact() -> None:
    """测试 TaskConfig.to_dict 输出紧凑"""
    config = TaskConfig(
        name="test",
        url="http://example.com",
        steps=[StepConfig(id="s1", type="navigate", url="http://example.com")],
    )
    d = config.to_dict()
    assert "variables" not in d  # 空 dict 不包含
    assert "success_conditions" not in d
    assert "on_success" not in d
    assert "on_failure" not in d
    assert "metadata" not in d
    assert len(d["steps"]) == 1
    assert d["steps"][0]["id"] == "s1"


def test_task_manager_list_tasks_source_default(tmp_path: Path) -> None:
    """测试 list_tasks 对无 source 字段的任务默认为 api"""
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    (tasks_dir / "test.json").write_text(
        '{"name": "test", "steps": [{"id": "s1", "type": "navigate", "url": "http://x"}]}',
        encoding="utf-8",
    )
    manager = TaskManager(tasks_dir)
    tasks = manager.list_tasks()
    assert len(tasks) == 1
    assert tasks[0]["source"] == "api"
