"""SchedulerService — 定时任务调度器（从 ScheduleEngine 提取）。

职责：管理定时任务调度状态（running / next_tick）、执行 tick、
根据任务列表自动启停调度器。

依赖：task_registry（查询到期任务）、task_executor（异步执行任务）。
"""

from __future__ import annotations

import time

from app.utils.logging import get_logger

logger = get_logger("scheduler", source="backend")


class SchedulerService:
    """定时任务调度器。"""

    def __init__(self, task_registry, task_executor) -> None:
        self._task_registry = task_registry
        self._task_executor = task_executor
        self._scheduler_running = False
        self._next_schedule_tick = 0.0

    # ── 属性 ──

    @property
    def running(self) -> bool:
        """调度器是否正在运行。"""
        return self._scheduler_running

    @property
    def next_tick_time(self) -> float:
        """下次调度 tick 的时间戳。"""
        return self._next_schedule_tick

    # ── 生命周期 ──

    def start(self) -> None:
        """启动调度器。幂等：已启动时不做操作。"""
        if self._scheduler_running:
            return
        self._scheduler_running = True
        self._next_schedule_tick = (int(time.time() // 60) * 60) + 60
        logger.info("定时任务调度器已启动")

    def stop(self) -> None:
        """停止调度器。"""
        self._scheduler_running = False
        logger.info("定时任务调度器已停止")

    # ── 调度 ──

    def should_tick(self, now: float) -> bool:
        """是否应执行一次调度 tick。"""
        return self._scheduler_running and now >= self._next_schedule_tick

    def tick(self, now: float) -> None:
        """执行一次调度 tick：查询到期任务并提交执行。"""
        from datetime import datetime

        try:
            dt_now = datetime.now()
            registry = self._task_registry
            executor = self._task_executor
            if registry and executor:
                due_tasks = registry.get_due_tasks(dt_now.hour, dt_now.minute)
                for task_id in due_tasks:
                    executor.execute_task_async(task_id)
                logger.debug("调度 tick: 处理 {} 个到期任务", len(due_tasks))
        finally:
            # 无论是否抛异常，都推进下一次 tick 时间，避免引擎循环每秒重试
            self._next_schedule_tick = (int(time.time() // 60) * 60) + 60

    # ── 状态同步 ──

    def sync_state(self) -> None:
        """根据是否有启用任务自动启停调度器。"""
        has_tasks = self.has_enabled_tasks()
        if has_tasks and not self._scheduler_running:
            self.start()
        elif not has_tasks and self._scheduler_running:
            self.stop()

    def has_enabled_tasks(self) -> bool:
        """检查是否存在启用的定时任务。"""
        return self._task_executor.registry.has_enabled_tasks() if self._task_executor else False
