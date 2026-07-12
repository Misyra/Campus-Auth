"""TaskExecutor 测试 — 聚焦 TaskRegistry / TaskHistoryStore 基础构造。"""

from __future__ import annotations

from app.services.task_registry import TaskHistoryStore, TaskRegistry


def test_history_store_initialized_at_construct(tmp_path):
    """TaskRegistry 和 TaskHistoryStore 应可独立创建。"""
    registry = TaskRegistry(tmp_path / "tasks" / "scheduled")
    history_store = TaskHistoryStore(tmp_path / "tasks" / "scheduled" / "history")
    assert hasattr(registry, "list_tasks")
    assert hasattr(history_store, "add_record")
