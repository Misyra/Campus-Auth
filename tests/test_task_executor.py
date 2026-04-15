from __future__ import annotations

from pathlib import Path

import pytest

from src.task_executor import (
    TaskConfig,
    TaskExecutor,
    TaskManager,
    is_valid_task_id,
    normalize_task_id,
)


def _build_executor(variables: dict[str, str]) -> TaskExecutor:
    config = TaskConfig(
        {
            "name": "demo",
            "url": "http://example.com",
            "variables": variables,
            "steps": [],
        }
    )
    return TaskExecutor(config=config, env_vars={"CAMPUS_USERNAME": "alice"})


def test_resolve_variable_nested_reference() -> None:
    executor = _build_executor(
        {
            "username": "{{CAMPUS_USERNAME}}",
            "greeting": "hello-{{username}}",
        }
    )

    assert executor._resolve_variable("{{greeting}}") == "hello-alice"


def test_resolve_variable_cycle_raises() -> None:
    executor = _build_executor(
        {
            "a": "{{b}}",
            "b": "{{a}}",
        }
    )

    with pytest.raises(RuntimeError, match="变量循环引用"):
        executor._resolve_variable("{{a}}")


def test_resolve_variable_depth_limit_raises() -> None:
    # Build a long chain a0 -> a1 -> ... -> a10.
    long_chain = {f"a{i}": f"{{{{a{i + 1}}}}}" for i in range(10)}
    long_chain["a10"] = "final"

    executor = _build_executor(long_chain)

    with pytest.raises(RuntimeError, match="展开层级超过限制"):
        executor._resolve_variable("{{a0}}")


def test_task_manager_rejects_invalid_task_id(tmp_path: Path) -> None:
    manager = TaskManager(tmp_path / "tasks")

    assert manager.load_task("../evil") is None
    assert manager.save_task("../evil", {"name": "x", "steps": [{}]}) is False
    assert manager.set_active_task("../evil") is False


def test_task_id_helpers_normalize_and_validate() -> None:
    assert normalize_task_id("  task_01  ") == "task_01"
    assert is_valid_task_id(" task_01 ") is True
    assert is_valid_task_id("task-01") is False
