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

    # 最大追赶窗口：超过此时间不追赶（避免启动时执行过期任务）
    MAX_CATCHUP_MINUTES = 30

    def __init__(self, task_registry, task_executor) -> None:
        self._task_registry = task_registry
        self._task_executor = task_executor
        self._scheduler_running = False
        self._next_schedule_tick = 0.0
        self._last_tick_minute: tuple[int, int] | None = None

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
        self._last_tick_minute = None
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
        """执行一次调度 tick：查询到期任务并提交执行，支持追赶错过的任务。"""
        from datetime import datetime

        try:
            dt_now = datetime.now()
            current_minute = (dt_now.hour, dt_now.minute)
            registry = self._task_registry
            executor = self._task_executor

            if registry and executor:
                # 追赶逻辑：从上次 tick 到当前时间之间的所有分钟
                minutes_to_check = self._get_catchup_minutes(current_minute)
                total_due = 0
                for hour, minute in minutes_to_check:
                    due_tasks = registry.get_due_tasks(hour, minute)
                    for task_id in due_tasks:
                        executor.execute_task_async(task_id)
                    total_due += len(due_tasks)

                if total_due > 0:
                    logger.info("调度周期: 处理 {} 个到期任务（含追赶）", total_due)
                else:
                    logger.debug("调度周期: 无到期任务")

                self._last_tick_minute = current_minute
        finally:
            # 无论是否抛异常，都推进下一次 tick 时间，避免引擎循环每秒重试
            self._next_schedule_tick = (int(time.time() // 60) * 60) + 60

    def _get_catchup_minutes(self, current: tuple[int, int]) -> list[tuple[int, int]]:
        """获取需要追赶的分钟列表。

        从 _last_tick_minute（不含）到 current（含）之间的所有分钟。
        超过 MAX_CATCHUP_MINUTES 的部分不追赶。
        """
        if self._last_tick_minute is None:
            # 首次 tick，只检查当前分钟
            return [current]

        # 计算分钟差
        last_total = self._last_tick_minute[0] * 60 + self._last_tick_minute[1]
        curr_total = current[0] * 60 + current[1]
        diff = curr_total - last_total

        # 处理跨天
        if diff < 0:
            diff += 24 * 60

        # 超过追赶窗口，只检查当前分钟
        if diff > self.MAX_CATCHUP_MINUTES:
            logger.warning(
                "距离上次调度已过去 {} 分钟，超过追赶窗口（{} 分钟），跳过追赶",
                diff, self.MAX_CATCHUP_MINUTES,
            )
            return [current]

        # 生成追赶列表（不含 last_tick_minute，含 current）
        minutes = []
        for i in range(1, diff + 1):
            m = (last_total + i) % (24 * 60)
            minutes.append((m // 60, m % 60))

        return minutes

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
