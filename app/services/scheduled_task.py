"""ScheduledTaskService — 向后兼容的委托层。

内部调用 TaskRegistry + TaskExecutor + TaskHistoryStore，
保持所有公共方法签名不变。

调度状态由 ScheduleEngine 管理，此类不再维护调度器线程。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.utils.logging import get_logger

scheduled_task_logger = get_logger("scheduled_task", source="backend")


class ScheduledTaskService:
    """向后兼容的委托层 — 内部调用 TaskRegistry / TaskExecutor / TaskHistoryStore。"""

    def __init__(
        self,
        project_root: Path,
        task_manager=None,
        registry=None,
        executor=None,
        history_store=None,
    ):
        # 依赖注入：优先使用传入的组件，否则自动创建
        self._project_root = project_root
        self._task_manager = task_manager

        tasks_dir = project_root / "tasks" / "scheduled"
        history_dir = tasks_dir / "history"

        if registry is not None:
            self._registry = registry
        else:
            from app.services.task_registry import TaskRegistry

            self._registry = TaskRegistry(tasks_dir)

        if history_store is not None:
            self._history_store = history_store
        else:
            from app.services.task_registry import TaskHistoryStore

            self._history_store = TaskHistoryStore(history_dir)

        if executor is not None:
            self._executor = executor

        # 调度器状态（已迁移至 Engine，保留字段以兼容外部访问）
        self._scheduler_running = False

    @property
    def scheduler_running(self) -> bool:
        """调度器是否正在运行（已迁移至 Engine，始终返回 False）。"""
        return False

    # ── CRUD（委托给 TaskRegistry）──

    def has_enabled_tasks(self) -> bool:
        """检查是否存在启用的定时任务。"""
        return self._registry.has_enabled_tasks()

    def list_tasks(self) -> list[dict[str, Any]]:
        """列出所有定时任务。"""
        return self._registry.list_tasks()

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        """获取定时任务详情。"""
        return self._registry.get_task(task_id)

    def save_task(self, task_id: str, config: dict[str, Any]) -> tuple[bool, str]:
        """保存定时任务。"""
        return self._registry.save_task(task_id, config)

    def delete_task(self, task_id: str) -> tuple[bool, str]:
        """删除定时任务。"""
        ok, msg = self._registry.delete_task(task_id)
        if ok:
            # 同时删除历史记录
            self._history_store.delete_history(task_id)
        return ok, msg

    # ── 历史（委托给 TaskHistoryStore）──

    def get_history(self, task_id: str) -> list[dict[str, Any]]:
        """获取任务执行历史。"""
        return self._history_store.get_history(task_id)

    def _add_history_sync(
        self, task_id: str, status: str, message: str, duration: float
    ) -> None:
        """添加执行历史记录。"""
        self._history_store.add_record(task_id, status, message, duration)

    # ── 执行（委托给 TaskExecutor）──

    def execute_task(self, task_id: str) -> tuple[bool, str]:
        """执行定时任务。"""
        return self._executor.execute_task(task_id)

    # ── 调度器生命周期（已迁移至 Engine，保留空操作以兼容）──

    def start_scheduler(self) -> None:
        """启动定时任务调度（已迁移至 Engine，空操作）。"""
        scheduled_task_logger.debug(
            "start_scheduler 调用已忽略（调度状态由 Engine 管理）"
        )

    def stop_scheduler(self) -> None:
        """停止调度器（已迁移至 Engine，空操作）。"""
        scheduled_task_logger.debug(
            "stop_scheduler 调用已忽略（调度状态由 Engine 管理）"
        )

    def check_and_execute(self) -> None:
        """检查并执行到期的定时任务（已迁移至 Engine，空操作）。"""
        pass
