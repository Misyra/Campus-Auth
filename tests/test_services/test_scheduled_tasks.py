"""定时任务功能测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.task_registry import MAX_HISTORY_SIZE, TaskHistoryStore, TaskRegistry


@pytest.fixture
def project_root(tmp_path):
    """创建临时项目目录。"""
    return tmp_path


@pytest.fixture
def scheduler(project_root):
    """创建 Registry + HistoryStore 实例（通过 SimpleNamespace 模拟原 ScheduledTaskService 接口）。"""
    registry = TaskRegistry(project_root / "tasks" / "scheduled")
    history_store = TaskHistoryStore(project_root / "tasks" / "scheduled" / "history")

    def _delete_task(task_id: str):
        success, message = registry.delete_task(task_id)
        if success:
            history_store.delete_history(task_id)
        return success, message

    from types import SimpleNamespace

    return SimpleNamespace(
        _registry=registry,
        _history_store=history_store,
        save_task=registry.save_task,
        get_task=registry.get_task,
        list_tasks=registry.list_tasks,
        delete_task=_delete_task,
        get_history=history_store.get_history,
    )


def test_save_and_get_task(scheduler):
    """测试保存和获取定时任务。"""
    task_id = "test_task"
    config = {
        "name": "测试任务",
        "description": "这是一个测试任务",
        "type": "script",
        "target_id": "test_script",
        "enabled": True,
        "schedule": {"hour": 8, "minute": 30},
        "timeout": 60,
    }

    # 保存任务
    ok, message = scheduler.save_task(task_id, config)
    assert ok is True
    assert "成功" in message

    # 获取任务
    task = scheduler.get_task(task_id)
    assert task is not None
    assert task["id"] == task_id
    assert task["name"] == "测试任务"
    assert task["type"] == "script"
    assert task["target_id"] == "test_script"


def test_list_tasks(scheduler):
    """测试列出定时任务。"""
    # 创建多个任务
    for i in range(3):
        scheduler.save_task(
            f"task_{i}",
            {
                "name": f"任务 {i}",
                "type": "script",
                "target_id": "test_script",
                "enabled": True,
                "schedule": {"hour": i, "minute": 0},
                "timeout": 60,
            },
        )

    tasks = scheduler.list_tasks()
    assert len(tasks) == 3


def test_delete_task(scheduler):
    """测试删除定时任务。"""
    task_id = "to_delete"
    scheduler.save_task(
        task_id,
        {
            "name": "待删除任务",
            "type": "script",
            "target_id": "test_script",
            "enabled": True,
            "schedule": {"hour": 0, "minute": 0},
            "timeout": 60,
        },
    )

    # 确认任务存在
    assert scheduler.get_task(task_id) is not None

    # 删除任务
    ok, message = scheduler.delete_task(task_id)
    assert ok is True

    # 确认任务已删除
    assert scheduler.get_task(task_id) is None


def test_history(scheduler):
    """测试执行历史。"""
    task_id = "history_task"
    scheduler.save_task(
        task_id,
        {
            "name": "历史任务",
            "type": "script",
            "target_id": "test_script",
            "enabled": True,
            "schedule": {"hour": 0, "minute": 0},
            "timeout": 60,
        },
    )

    # 添加历史记录
    scheduler._history_store.add_record(task_id, "success", "执行成功", 1.5)
    scheduler._history_store.add_record(task_id, "failure", "执行失败", 0.5)

    # 获取历史
    history = scheduler.get_history(task_id)
    assert len(history) == 2
    assert history[0]["status"] == "failure"  # 最新的在前
    assert history[1]["status"] == "success"


# =====================================================================
# MAX_HISTORY_SIZE
# =====================================================================


class TestMaxHistorySize:
    def test_is_positive(self):
        assert MAX_HISTORY_SIZE > 0

    def test_is_50(self):
        assert MAX_HISTORY_SIZE == 50


# =====================================================================
# TaskRegistry CRUD 补充
# =====================================================================


class TestScheduleEngineCRUD:
    @pytest.fixture
    def scheduler(self, tmp_path: Path):
        registry = TaskRegistry(tmp_path / "tasks" / "scheduled")
        history_store = TaskHistoryStore(tmp_path / "tasks" / "scheduled" / "history")

        def _delete_task(task_id: str):
            success, message = registry.delete_task(task_id)
            if success:
                history_store.delete_history(task_id)
            return success, message

        from types import SimpleNamespace

        return SimpleNamespace(
            _registry=registry,
            _history_store=history_store,
            save_task=registry.save_task,
            get_task=registry.get_task,
            list_tasks=registry.list_tasks,
            delete_task=_delete_task,
            get_history=history_store.get_history,
        )

    def test_list_tasks_empty(self, scheduler):
        assert scheduler.list_tasks() == []

    def test_list_tasks_sorted_by_name(self, scheduler):
        scheduler.save_task(
            "b_task",
            {
                "name": "Banana",
                "type": "script",
                "target_id": "test_script",
                "schedule": {"hour": 1, "minute": 0},
            },
        )
        scheduler.save_task(
            "a_task",
            {
                "name": "Apple",
                "type": "script",
                "target_id": "test_script",
                "schedule": {"hour": 0, "minute": 0},
            },
        )
        tasks = scheduler.list_tasks()
        assert tasks[0]["name"] == "Apple"
        assert tasks[1]["name"] == "Banana"

    def test_list_tasks_skips_dotfiles(self, scheduler, tmp_path: Path):
        # 创建正常任务
        scheduler.save_task(
            "normal",
            {
                "name": "正常",
                "type": "script",
                "target_id": "test_script",
                "schedule": {"hour": 0, "minute": 0},
            },
        )
        # 创建隐藏文件
        (tmp_path / "tasks" / "scheduled" / ".hidden.json").write_text(
            "{}", encoding="utf-8"
        )
        tasks = scheduler.list_tasks()
        assert len(tasks) == 1
        assert tasks[0]["id"] == "normal"

    def test_list_tasks_skips_malformed_json(self, scheduler, tmp_path: Path):
        scheduler.save_task(
            "good",
            {
                "name": "好的",
                "type": "script",
                "target_id": "test_script",
                "schedule": {"hour": 0, "minute": 0},
            },
        )
        (tmp_path / "tasks" / "scheduled" / "bad.json").write_text(
            "not json", encoding="utf-8"
        )
        tasks = scheduler.list_tasks()
        assert len(tasks) == 1
        assert tasks[0]["id"] == "good"

    def test_get_task_returns_id_field(self, scheduler):
        scheduler.save_task(
            "my_task",
            {
                "name": "测试",
                "type": "script",
                "target_id": "test_script",
                "schedule": {"hour": 0, "minute": 0},
            },
        )
        task = scheduler.get_task("my_task")
        assert task is not None
        assert task["id"] == "my_task"

    def test_get_task_nonexistent(self, scheduler):
        assert scheduler.get_task("nonexistent") is None

    def test_get_task_invalid_id(self, scheduler):
        assert scheduler.get_task("123bad") is None

    def test_get_task_malformed_json(self, scheduler, tmp_path: Path):
        (tmp_path / "tasks" / "scheduled" / "bad.json").write_text(
            "not json", encoding="utf-8"
        )
        assert scheduler.get_task("bad") is None

    def test_delete_task_with_history(self, scheduler, tmp_path: Path):
        scheduler.save_task(
            "del_task",
            {
                "name": "待删",
                "type": "script",
                "target_id": "test_script",
                "schedule": {"hour": 0, "minute": 0},
            },
        )
        scheduler._history_store.add_record("del_task", "success", "ok", 1.0)
        ok, _ = scheduler.delete_task("del_task")
        assert ok is True
        assert scheduler.get_task("del_task") is None
        # 历史文件也应被删除
        history_file = tmp_path / "tasks" / "scheduled" / "history" / "del_task.json"
        assert not history_file.exists()

    def test_delete_task_nonexistent(self, scheduler):
        ok, _ = scheduler.delete_task("nonexistent")
        assert ok is False

    def test_delete_task_invalid_id(self, scheduler):
        ok, _ = scheduler.delete_task("123bad")
        assert ok is False

    def test_save_task_invalid_id(self, scheduler):
        ok, _ = scheduler.save_task("bad id!", {"name": "test"})
        assert ok is False


# =====================================================================
# _add_history / get_history 补充
# =====================================================================


class TestSchedulerHistory:
    @pytest.fixture
    def scheduler(self, tmp_path: Path):
        registry = TaskRegistry(tmp_path / "tasks" / "scheduled")
        history_store = TaskHistoryStore(tmp_path / "tasks" / "scheduled" / "history")

        from types import SimpleNamespace

        return SimpleNamespace(
            _registry=registry,
            _history_store=history_store,
            save_task=registry.save_task,
            get_task=registry.get_task,
            list_tasks=registry.list_tasks,
            delete_task=registry.delete_task,
            get_history=history_store.get_history,
        )

    def test_add_history_creates_file(self, scheduler, tmp_path: Path):
        scheduler._history_store.add_record("test", "success", "ok", 1.0)
        history_file = tmp_path / "tasks" / "scheduled" / "history" / "test.json"
        assert history_file.exists()

    def test_add_history_max_size(self, scheduler):
        for i in range(MAX_HISTORY_SIZE + 10):
            scheduler._history_store.add_record("test", "success", f"run {i}", 1.0)
        history = scheduler.get_history("test")
        assert len(history) == MAX_HISTORY_SIZE
        # 最新的在前
        assert history[0]["message"] == f"run {MAX_HISTORY_SIZE + 9}"

    def test_add_history_truncates_message(self, scheduler):
        long_msg = "x" * 1000
        scheduler._history_store.add_record("test", "success", long_msg, 1.0)
        history = scheduler.get_history("test")
        assert len(history[0]["message"]) == 500

    def test_add_history_invalid_id(self, scheduler):
        # 不应抛异常
        scheduler._history_store.add_record("123bad", "success", "ok", 1.0)

    def test_get_history_empty(self, scheduler):
        assert scheduler.get_history("nonexistent") == []

    def test_get_history_invalid_id(self, scheduler):
        assert scheduler.get_history("123bad") == []

    def test_get_history_malformed_json(self, scheduler, tmp_path: Path):
        history_dir = tmp_path / "tasks" / "scheduled" / "history"
        history_dir.mkdir(parents=True, exist_ok=True)
        (history_dir / "bad.json").write_text("not json", encoding="utf-8")
        assert scheduler.get_history("bad") == []

    def test_get_history_returns_runs_list(self, scheduler):
        scheduler._history_store.add_record("test", "success", "ok", 1.0)
        scheduler._history_store.add_record("test", "failure", "err", 0.5)
        history = scheduler.get_history("test")
        assert len(history) == 2
        assert history[0]["status"] == "failure"
        assert history[1]["status"] == "success"
        for entry in history:
            assert "timestamp" in entry
            assert "duration" in entry
