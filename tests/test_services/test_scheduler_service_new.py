"""SchedulerService 单元测试 — 从 ScheduleEngine 提取的调度逻辑。"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from app.services.scheduler_service import SchedulerService


class TestSchedulerServiceLifecycle:
    """start / stop / running 状态管理。"""

    def test_initial_state(self):
        svc = SchedulerService(task_registry=MagicMock(), task_executor=MagicMock())
        assert svc.running is False
        assert svc.next_tick_time == 0.0

    def test_start_sets_running(self):
        svc = SchedulerService(task_registry=MagicMock(), task_executor=MagicMock())
        svc.start()
        assert svc.running is True
        # next_tick_time 应为下一个整分钟
        expected = (int(time.time() // 60) * 60) + 60
        assert abs(svc.next_tick_time - expected) <= 1

    def test_start_idempotent(self):
        svc = SchedulerService(task_registry=MagicMock(), task_executor=MagicMock())
        svc.start()
        tick1 = svc.next_tick_time
        svc.start()  # 再次调用不应重置
        assert svc.next_tick_time == tick1

    def test_stop_clears_running(self):
        svc = SchedulerService(task_registry=MagicMock(), task_executor=MagicMock())
        svc.start()
        svc.stop()
        assert svc.running is False


class TestSchedulerServiceTick:
    """should_tick / tick 调度逻辑。"""

    def test_should_tick_false_when_not_running(self):
        svc = SchedulerService(task_registry=MagicMock(), task_executor=MagicMock())
        assert svc.should_tick(time.time()) is False

    def test_should_tick_true_when_due(self):
        svc = SchedulerService(task_registry=MagicMock(), task_executor=MagicMock())
        svc.start()
        # 将 next_tick_time 设为过去时间
        svc._next_schedule_tick = time.time() - 10
        assert svc.should_tick(time.time()) is True

    def test_should_tick_false_when_not_due(self):
        svc = SchedulerService(task_registry=MagicMock(), task_executor=MagicMock())
        svc.start()
        svc._next_schedule_tick = time.time() + 60
        assert svc.should_tick(time.time()) is False

    def test_tick_advances_next_tick(self):
        registry = MagicMock()
        registry.get_due_tasks.return_value = []
        executor = MagicMock()
        svc = SchedulerService(task_registry=registry, task_executor=executor)
        svc.start()
        svc._next_schedule_tick = time.time() - 10  # 已到期
        old_tick = svc._next_schedule_tick
        svc.tick(time.time())
        # tick 后 next_tick_time 应推进到下一个整分钟
        assert svc.next_tick_time > old_tick

    def test_tick_dispatches_due_tasks(self):
        registry = MagicMock()
        registry.get_due_tasks.return_value = ["task_a", "task_b"]
        executor = MagicMock()
        svc = SchedulerService(task_registry=registry, task_executor=executor)
        svc.start()
        svc._next_schedule_tick = time.time() - 10
        svc.tick(time.time())
        assert executor.execute_task_async.call_count == 2


class TestSchedulerServiceSyncState:
    """sync_state — 根据任务启停调度器。"""

    def test_sync_state_starts_when_tasks_exist(self):
        executor = MagicMock()
        executor.has_enabled_tasks.return_value = True
        svc = SchedulerService(task_registry=MagicMock(), task_executor=executor)
        svc.sync_state()
        assert svc.running is True

    def test_sync_state_stops_when_no_tasks(self):
        executor = MagicMock()
        executor.has_enabled_tasks.return_value = False
        svc = SchedulerService(task_registry=MagicMock(), task_executor=executor)
        svc.start()
        svc.sync_state()
        assert svc.running is False

    def test_has_enabled_tasks_delegates(self):
        executor = MagicMock()
        executor.has_enabled_tasks.return_value = True
        svc = SchedulerService(task_registry=MagicMock(), task_executor=executor)
        assert svc.has_enabled_tasks() is True
        executor.has_enabled_tasks.assert_called_once()

    def test_has_enabled_tasks_no_executor(self):
        svc = SchedulerService(task_registry=MagicMock(), task_executor=None)
        assert svc.has_enabled_tasks() is False
