"""SchedulerService 扩展测试 — get_default_shell / _validate_task_id / list_tasks / get_task / delete_task / get_history / _add_history

补充 test_scheduler_service.py 和 test_scheduled_tasks.py 中未覆盖的部分。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.services.scheduler import SchedulerService, get_default_shell, MAX_HISTORY_SIZE


# =====================================================================
# get_default_shell
# =====================================================================


class TestGetDefaultShell:
    def test_returns_nonempty_string(self):
        shell = get_default_shell()
        assert isinstance(shell, str)
        assert len(shell) > 0


# =====================================================================
# MAX_HISTORY_SIZE
# =====================================================================


class TestMaxHistorySize:
    def test_is_positive(self):
        assert MAX_HISTORY_SIZE > 0

    def test_is_50(self):
        assert MAX_HISTORY_SIZE == 50


# =====================================================================
# SchedulerService._validate_task_id
# =====================================================================


class TestValidateTaskId:
    def test_valid_ids(self):
        assert SchedulerService._validate_task_id("my_task") is True
        assert SchedulerService._validate_task_id("task123") is True
        assert SchedulerService._validate_task_id("A") is True

    def test_invalid_ids(self):
        assert SchedulerService._validate_task_id("") is False
        assert SchedulerService._validate_task_id("123bad") is False
        assert SchedulerService._validate_task_id("my-task") is False
        assert SchedulerService._validate_task_id("my task") is False


# =====================================================================
# SchedulerService CRUD 补充
# =====================================================================


class TestSchedulerServiceCRUD:
    @pytest.fixture
    def scheduler(self, tmp_path: Path) -> SchedulerService:
        return SchedulerService(tmp_path)

    def test_list_tasks_empty(self, scheduler: SchedulerService):
        assert scheduler.list_tasks() == []

    def test_list_tasks_sorted_by_name(self, scheduler: SchedulerService):
        scheduler.save_task("b_task", {"name": "Banana", "type": "shell", "command": "echo b", "schedule": {"hour": 1, "minute": 0}})
        scheduler.save_task("a_task", {"name": "Apple", "type": "shell", "command": "echo a", "schedule": {"hour": 0, "minute": 0}})
        tasks = scheduler.list_tasks()
        assert tasks[0]["name"] == "Apple"
        assert tasks[1]["name"] == "Banana"

    def test_list_tasks_skips_dotfiles(self, scheduler: SchedulerService, tmp_path: Path):
        # 创建正常任务
        scheduler.save_task("normal", {"name": "正常", "type": "shell", "command": "echo ok", "schedule": {"hour": 0, "minute": 0}})
        # 创建隐藏文件
        (tmp_path / "tasks" / "scheduled" / ".hidden.json").write_text("{}", encoding="utf-8")
        tasks = scheduler.list_tasks()
        assert len(tasks) == 1
        assert tasks[0]["id"] == "normal"

    def test_list_tasks_skips_malformed_json(self, scheduler: SchedulerService, tmp_path: Path):
        scheduler.save_task("good", {"name": "好的", "type": "shell", "command": "echo ok", "schedule": {"hour": 0, "minute": 0}})
        (tmp_path / "tasks" / "scheduled" / "bad.json").write_text("not json", encoding="utf-8")
        tasks = scheduler.list_tasks()
        assert len(tasks) == 1
        assert tasks[0]["id"] == "good"

    def test_get_task_returns_id_field(self, scheduler: SchedulerService):
        scheduler.save_task("my_task", {"name": "测试", "type": "shell", "command": "echo ok", "schedule": {"hour": 0, "minute": 0}})
        task = scheduler.get_task("my_task")
        assert task is not None
        assert task["id"] == "my_task"

    def test_get_task_nonexistent(self, scheduler: SchedulerService):
        assert scheduler.get_task("nonexistent") is None

    def test_get_task_invalid_id(self, scheduler: SchedulerService):
        assert scheduler.get_task("123bad") is None

    def test_get_task_malformed_json(self, scheduler: SchedulerService, tmp_path: Path):
        (tmp_path / "tasks" / "scheduled" / "bad.json").write_text("not json", encoding="utf-8")
        assert scheduler.get_task("bad") is None

    @pytest.mark.asyncio
    async def test_delete_task_with_history(self, scheduler: SchedulerService, tmp_path: Path):
        scheduler.save_task("del_task", {"name": "待删", "type": "shell", "command": "echo del", "schedule": {"hour": 0, "minute": 0}})
        await scheduler._add_history("del_task", "success", "ok", 1.0)
        ok, _ = scheduler.delete_task("del_task")
        assert ok is True
        assert scheduler.get_task("del_task") is None
        # 历史文件也应被删除
        history_file = tmp_path / "tasks" / "scheduled" / "history" / "del_task.json"
        assert not history_file.exists()

    def test_delete_task_nonexistent(self, scheduler: SchedulerService):
        ok, _ = scheduler.delete_task("nonexistent")
        assert ok is False

    def test_delete_task_invalid_id(self, scheduler: SchedulerService):
        ok, _ = scheduler.delete_task("123bad")
        assert ok is False

    def test_save_task_invalid_id(self, scheduler: SchedulerService):
        ok, _ = scheduler.save_task("123bad", {"name": "test"})
        assert ok is False


# =====================================================================
# _add_history / get_history 补充
# =====================================================================


class TestSchedulerHistory:
    @pytest.fixture
    def scheduler(self, tmp_path: Path) -> SchedulerService:
        return SchedulerService(tmp_path)

    @pytest.mark.asyncio
    async def test_add_history_creates_file(self, scheduler: SchedulerService, tmp_path: Path):
        await scheduler._add_history("test", "success", "ok", 1.0)
        history_file = tmp_path / "tasks" / "scheduled" / "history" / "test.json"
        assert history_file.exists()

    @pytest.mark.asyncio
    async def test_add_history_max_size(self, scheduler: SchedulerService):
        for i in range(MAX_HISTORY_SIZE + 10):
            await scheduler._add_history("test", "success", f"run {i}", 1.0)
        history = scheduler.get_history("test")
        assert len(history) == MAX_HISTORY_SIZE
        # 最新的在前
        assert history[0]["message"] == f"run {MAX_HISTORY_SIZE + 9}"

    @pytest.mark.asyncio
    async def test_add_history_truncates_message(self, scheduler: SchedulerService):
        long_msg = "x" * 1000
        await scheduler._add_history("test", "success", long_msg, 1.0)
        history = scheduler.get_history("test")
        assert len(history[0]["message"]) == 500

    @pytest.mark.asyncio
    async def test_add_history_invalid_id(self, scheduler: SchedulerService):
        # 不应抛异常
        await scheduler._add_history("123bad", "success", "ok", 1.0)

    def test_get_history_empty(self, scheduler: SchedulerService):
        assert scheduler.get_history("nonexistent") == []

    def test_get_history_invalid_id(self, scheduler: SchedulerService):
        assert scheduler.get_history("123bad") == []

    def test_get_history_malformed_json(self, scheduler: SchedulerService, tmp_path: Path):
        history_dir = tmp_path / "tasks" / "scheduled" / "history"
        history_dir.mkdir(parents=True, exist_ok=True)
        (history_dir / "bad.json").write_text("not json", encoding="utf-8")
        assert scheduler.get_history("bad") == []

    @pytest.mark.asyncio
    async def test_get_history_returns_runs_list(self, scheduler: SchedulerService):
        await scheduler._add_history("test", "success", "ok", 1.0)
        await scheduler._add_history("test", "failure", "err", 0.5)
        history = scheduler.get_history("test")
        assert len(history) == 2
        assert history[0]["status"] == "failure"
        assert history[1]["status"] == "success"
        for entry in history:
            assert "timestamp" in entry
            assert "duration" in entry


# =====================================================================
# start / stop
# =====================================================================


class TestSchedulerStartStop:
    @pytest.mark.asyncio
    async def test_start_sets_running(self, tmp_path: Path):
        scheduler = SchedulerService(tmp_path)
        scheduler.start()
        assert scheduler._running is True
        scheduler.stop()

    @pytest.mark.asyncio
    async def test_stop_clears_running(self, tmp_path: Path):
        scheduler = SchedulerService(tmp_path)
        scheduler.start()
        scheduler.stop()
        assert scheduler._running is False

    @pytest.mark.asyncio
    async def test_double_start_no_error(self, tmp_path: Path):
        scheduler = SchedulerService(tmp_path)
        scheduler.start()
        scheduler.start()  # 不应抛异常
        scheduler.stop()

    def test_stop_when_not_running(self, tmp_path: Path):
        scheduler = SchedulerService(tmp_path)
        scheduler.stop()  # 不应抛异常
