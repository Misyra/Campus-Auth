from __future__ import annotations

from pathlib import Path

import pytest

from src.task_executor import (
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
