"""TaskFacade — 定时任务 API 入口。"""

from __future__ import annotations

from typing import Any


class TaskFacade:
    """定时任务 API 入口 — 包装 Registry + Executor + HistoryStore。"""

    def __init__(self, registry, executor, history_store):
        self._registry = registry
        self._executor = executor
        self._history_store = history_store

    def list_tasks(self) -> list[dict]:
        return self._registry.list_tasks()

    def get_task(self, task_id: str) -> dict | None:
        return self._registry.get_task(task_id)

    def save_task(self, task_id: str, config: dict) -> tuple[bool, str]:
        return self._registry.save_task(task_id, config)

    def delete_task(self, task_id: str) -> tuple[bool, str]:
        success, message = self._registry.delete_task(task_id)
        if success:
            self._history_store.delete_history(task_id)
        return success, message

    def get_history(self, task_id: str) -> list[dict]:
        return self._history_store.get_history(task_id)

    def execute_task(self, task_id: str) -> None:
        self._executor.execute_task_async(task_id)

    def has_enabled_tasks(self) -> bool:
        return self._registry.has_enabled_tasks()
