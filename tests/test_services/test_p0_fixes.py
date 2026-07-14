"""P0 修复验证测试。

测试两个关键修复：
1. 浏览器定时任务正确注入 task_id
2. 定时任务调度器追赶机制
"""

from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from app.schemas import RuntimeConfig
from app.services.scheduler_service import SchedulerService
from app.services.task_executor import TaskExecutor
from app.services.task_registry import TaskHistoryStore, TaskRegistry

# =====================================================================
# P0-1: 浏览器定时任务 task_id 注入
# =====================================================================


class TestBrowserTaskIdInjection:
    """验证 _execute_browser 将 task_id 注入到 RuntimeConfig.active_task。"""

    @pytest.fixture
    def setup(self, tmp_path):
        """创建测试所需的 registry、executor 和模拟任务。"""
        tasks_dir = tmp_path / "tasks" / "scheduled"
        tasks_dir.mkdir(parents=True)

        # 创建一个浏览器类型定时任务
        task_config = {
            "name": "测试浏览器任务",
            "type": "browser",
            "enabled": True,
            "schedule": {"hour": 12, "minute": 0},
        }
        (tasks_dir / "test_browser_task.json").write_text(
            json.dumps(task_config), encoding="utf-8"
        )

        registry = TaskRegistry(tasks_dir)
        history_store = TaskHistoryStore(tasks_dir / "history")

        mock_browser_svc = MagicMock()
        mock_handle = MagicMock()
        mock_handle.rejected_reason = None
        mock_handle.result.return_value = (True, "成功")
        mock_browser_svc.submit_task.return_value = mock_handle

        mock_task_manager = MagicMock()
        mock_task_manager.get_task_detail.return_value = {"type": "browser"}

        executor = TaskExecutor(
            registry=registry,
            history_store=history_store,
            worker_getter=lambda: None,
            get_runtime_config=lambda: RuntimeConfig(),
            login_orchestrator=MagicMock(),
            task_manager=mock_task_manager,
            browser_task_service=mock_browser_svc,
        )

        return executor, mock_browser_svc, mock_task_manager

    def test_browser_task_injects_task_id(self, setup):
        """浏览器定时任务应将 task_id 注入到 worker_config.active_task。"""
        executor, mock_browser_svc, mock_task_manager = setup

        # 模拟全局配置的 active_task 是 "default"
        mock_config = RuntimeConfig()
        executor._get_runtime_config = lambda: mock_config

        # 执行浏览器定时任务
        executor._execute_browser("test_browser_task", timeout=60)

        # 验证 submit_task 被调用
        assert mock_browser_svc.submit_task.called

        # 获取提交的 task_config（worker dict）
        call_kwargs = mock_browser_svc.submit_task.call_args.kwargs
        task_config = call_kwargs["task_config"]

        assert task_config["active_task"] == "test_browser_task"

    def test_browser_task_no_inject_when_same(self, setup):
        """当 task_id 与 config.active_task 相同时，task_config 仍应携带正确的 active_task。"""
        executor, mock_browser_svc, mock_task_manager = setup

        # 模拟全局配置的 active_task 已经是目标任务
        mock_config = RuntimeConfig(active_task="test_browser_task")
        executor._get_runtime_config = lambda: mock_config

        executor._execute_browser("test_browser_task", timeout=60)

        # 获取提交的 task_config（worker dict）
        call_kwargs = mock_browser_svc.submit_task.call_args.kwargs
        task_config = call_kwargs["task_config"]

        # active_task 应保持为目标任务
        assert task_config["active_task"] == "test_browser_task"

    def test_browser_task_nonexistent_returns_failure(self, setup):
        """不存在的任务应返回失败。"""
        executor, mock_browser_svc, mock_task_manager = setup
        mock_task_manager.get_task_detail.return_value = None

        success, msg = executor._execute_browser("nonexistent_task", timeout=60)
        assert success is False
        assert "不存在" in msg

    def test_non_browser_task_returns_failure(self, setup):
        """非浏览器类型任务应返回失败。"""
        executor, mock_browser_svc, mock_task_manager = setup
        mock_task_manager.get_task_detail.return_value = {"type": "script"}

        success, msg = executor._execute_browser("test_script_task", timeout=60)
        assert success is False
        assert "不存在" in msg


# =====================================================================
# P0-2: 定时任务调度器追赶机制
# =====================================================================


class TestSchedulerCatchup:
    """验证 SchedulerService 的追赶机制。"""

    @pytest.fixture
    def scheduler(self):
        """创建测试用的调度器。"""
        mock_registry = MagicMock()
        mock_executor = MagicMock()
        scheduler = SchedulerService(mock_registry, mock_executor)
        return scheduler, mock_registry, mock_executor

    def test_first_tick_only_checks_current_minute(self, scheduler):
        """首次 tick 应只检查当前分钟。"""
        scheduler_obj, mock_registry, _ = scheduler
        scheduler_obj.start()

        mock_registry.get_due_tasks.return_value = set()

        scheduler_obj.tick(0)

        # 应该只调用一次 get_due_tasks
        assert mock_registry.get_due_tasks.call_count == 1

    def test_catchup_after_gap(self, scheduler):
        """间隔一段时间后，应追赶中间错过的分钟。"""
        scheduler_obj, mock_registry, mock_executor = scheduler
        scheduler_obj.start()

        # 手动设置 _last_tick_minute 为 12:30（模拟上次 tick 的时间）
        scheduler_obj._last_tick_minute = (12, 30)

        # 模拟当前时间 12:33（错过了 12:31, 12:32）
        with patch("datetime.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 7, 4, 12, 33)
            mock_registry.get_due_tasks.return_value = set()

            scheduler_obj.tick(0)

            # 应该调用 3 次：12:31, 12:32, 12:33（追赶 + 当前分钟）
            assert mock_registry.get_due_tasks.call_count == 3

            # 验证调用顺序
            calls = mock_registry.get_due_tasks.call_args_list
            assert calls[0][0] == (12, 31)
            assert calls[1][0] == (12, 32)
            assert calls[2][0] == (12, 33)

    def test_catchup_skips_when_too_long(self, scheduler):
        """超过追赶窗口时，应跳过追赶。"""
        scheduler_obj, mock_registry, mock_executor = scheduler
        scheduler_obj.start()

        # 设置上次 tick 为 31 分钟前
        scheduler_obj._last_tick_minute = (12, 0)

        # 模拟当前时间 12:31（超过 MAX_CATCHUP_MINUTES=30）
        with patch("datetime.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 7, 4, 12, 31)
            mock_registry.get_due_tasks.return_value = set()

            scheduler_obj.tick(0)

            # 应该只调用 1 次（当前分钟），不追赶
            assert mock_registry.get_due_tasks.call_count == 1

    def test_catchup_handles_midnight(self, scheduler):
        """跨天时应正确处理追赶。"""
        scheduler_obj, mock_registry, mock_executor = scheduler
        scheduler_obj.start()

        # 设置上次 tick 为 23:58
        scheduler_obj._last_tick_minute = (23, 58)

        # 模拟当前时间 00:01（跨天，追赶 23:59, 0:00, 0:01）
        with patch("datetime.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 7, 5, 0, 1)
            mock_registry.get_due_tasks.return_value = set()

            scheduler_obj.tick(0)

            # 应该调用 3 次：23:59, 0:00, 0:01
            assert mock_registry.get_due_tasks.call_count == 3

            calls = mock_registry.get_due_tasks.call_args_list
            assert calls[0][0] == (23, 59)
            assert calls[1][0] == (0, 0)
            assert calls[2][0] == (0, 1)

    def test_catchup_executes_due_tasks(self, scheduler):
        """追赶期间发现的到期任务应被提交执行。"""
        scheduler_obj, mock_registry, mock_executor = scheduler
        scheduler_obj.start()

        scheduler_obj._last_tick_minute = (12, 0)

        # 模拟 12:01 有一个任务到期
        with patch("datetime.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 7, 4, 12, 2)

            def get_due_tasks(hour, minute):
                if (hour, minute) == (12, 1):
                    return {"task_123"}
                return set()

            mock_registry.get_due_tasks.side_effect = get_due_tasks

            scheduler_obj.tick(0)

            # task_123 应该被提交执行
            mock_executor.execute_task_async.assert_called_once_with("task_123")

    def test_start_resets_last_tick_minute(self, scheduler):
        """启动调度器应重置 _last_tick_minute。"""
        scheduler_obj, _, _ = scheduler

        scheduler_obj._last_tick_minute = (12, 30)
        scheduler_obj.start()

        assert scheduler_obj._last_tick_minute is None

    def test_get_catchup_minutes_returns_current_when_no_history(self, scheduler):
        """无历史记录时，应只返回当前分钟。"""
        scheduler_obj, _, _ = scheduler
        scheduler_obj._last_tick_minute = None

        result = scheduler_obj._get_catchup_minutes((12, 30))
        assert result == [(12, 30)]

    def test_get_catchup_minutes_returns_correct_range(self, scheduler):
        """应返回正确的追赶分钟范围。"""
        scheduler_obj, _, _ = scheduler
        scheduler_obj._last_tick_minute = (12, 28)

        result = scheduler_obj._get_catchup_minutes((12, 30))
        assert result == [(12, 29), (12, 30)]

    def test_get_catchup_minutes_handles_midnight(self, scheduler):
        """跨天时应正确生成追赶列表。"""
        scheduler_obj, _, _ = scheduler
        scheduler_obj._last_tick_minute = (23, 59)

        result = scheduler_obj._get_catchup_minutes((0, 1))
        assert result == [(0, 0), (0, 1)]
