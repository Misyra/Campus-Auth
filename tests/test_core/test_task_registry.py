"""TaskRegistry + TaskHistoryStore 单元测试。"""

from __future__ import annotations

import json
from pathlib import Path

from app.services.task_registry import MAX_HISTORY_SIZE, TaskHistoryStore, TaskRegistry

# ── 辅助函数 ──


def _make_task(
    task_id: str = "test_task",
    name: str = "测试任务",
    enabled: bool = True,
    hour: int = 8,
    minute: int = 30,
    task_type: str = "script",
    target_id: str = "some_script",
) -> dict:
    """构造定时任务配置。"""
    return {
        "name": name,
        "type": task_type,
        "target_id": target_id,
        "enabled": enabled,
        "schedule": {"hour": hour, "minute": minute},
        "timeout": 60,
    }


# ═══════════════════════════════════════════════════════
#  TaskRegistry
# ═══════════════════════════════════════════════════════


class TestRegistryInit:
    """初始化与磁盘加载。"""

    def test_empty_dir(self, tmp_path: Path) -> None:
        """空目录初始化后缓存为空。"""
        reg = TaskRegistry(tmp_path / "tasks")
        assert reg.list_tasks() == []
        assert reg.has_enabled_tasks() is False

    def test_load_existing_tasks(self, tmp_path: Path) -> None:
        """从磁盘加载已有任务。"""
        tasks_dir = tmp_path / "tasks"
        tasks_dir.mkdir()
        (tasks_dir / "aaa.json").write_text(
            json.dumps(
                {"name": "任务A", "enabled": True, "schedule": {"hour": 9, "minute": 0}}
            ),
            encoding="utf-8",
        )
        (tasks_dir / "bbb.json").write_text(
            json.dumps(
                {
                    "name": "任务B",
                    "enabled": False,
                    "schedule": {"hour": 10, "minute": 30},
                }
            ),
            encoding="utf-8",
        )

        reg = TaskRegistry(tasks_dir)
        assert len(reg.list_tasks()) == 2
        task = reg.get_task("aaa")
        assert task is not None
        assert task["id"] == "aaa"
        assert task["name"] == "任务A"

    def test_skips_dotfiles(self, tmp_path: Path) -> None:
        """跳过以点开头的文件。"""
        tasks_dir = tmp_path / "tasks"
        tasks_dir.mkdir()
        (tasks_dir / ".hidden.json").write_text("{}", encoding="utf-8")
        (tasks_dir / "real.json").write_text(
            json.dumps({"name": "真实任务", "enabled": False}),
            encoding="utf-8",
        )

        reg = TaskRegistry(tasks_dir)
        assert len(reg.list_tasks()) == 1

    def test_skips_corrupt_json(self, tmp_path: Path) -> None:
        """跳过损坏的 JSON 文件。"""
        tasks_dir = tmp_path / "tasks"
        tasks_dir.mkdir()
        (tasks_dir / "bad.json").write_text("not json {{{", encoding="utf-8")
        (tasks_dir / "good.json").write_text(
            json.dumps({"name": "好任务", "enabled": False}),
            encoding="utf-8",
        )

        reg = TaskRegistry(tasks_dir)
        assert len(reg.list_tasks()) == 1

    def test_loads_builds_schedule_index(self, tmp_path: Path) -> None:
        """加载时正确构建调度索引。"""
        tasks_dir = tmp_path / "tasks"
        tasks_dir.mkdir()
        (tasks_dir / "t1.json").write_text(
            json.dumps(
                {"name": "T1", "enabled": True, "schedule": {"hour": 8, "minute": 0}}
            ),
            encoding="utf-8",
        )
        (tasks_dir / "t2.json").write_text(
            json.dumps(
                {"name": "T2", "enabled": True, "schedule": {"hour": 8, "minute": 0}}
            ),
            encoding="utf-8",
        )
        (tasks_dir / "t3.json").write_text(
            json.dumps(
                {"name": "T3", "enabled": False, "schedule": {"hour": 8, "minute": 0}}
            ),
            encoding="utf-8",
        )

        reg = TaskRegistry(tasks_dir)
        due = reg.get_due_tasks(8, 0)
        assert "t1" in due
        assert "t2" in due
        assert "t3" not in due  # 禁用的任务不在索引中


class TestRegistryGetTask:
    """get_task 测试。"""

    def test_returns_copy(self, tmp_path: Path) -> None:
        """返回副本，修改不影响缓存。"""
        reg = TaskRegistry(tmp_path)
        reg.save_task("abc", _make_task("abc"))

        task = reg.get_task("abc")
        task["name"] = "被篡改"

        assert reg.get_task("abc")["name"] == "测试任务"

    def test_invalid_id(self, tmp_path: Path) -> None:
        """无效 ID 返回 None。"""
        reg = TaskRegistry(tmp_path)
        assert reg.get_task("../escape") is None
        assert reg.get_task("") is None

    def test_nonexistent(self, tmp_path: Path) -> None:
        """不存在的任务返回 None。"""
        reg = TaskRegistry(tmp_path)
        assert reg.get_task("no_such_task") is None


class TestRegistryListTasks:
    """list_tasks 测试。"""

    def test_sorted_by_name(self, tmp_path: Path) -> None:
        reg = TaskRegistry(tmp_path)
        reg.save_task("b_task", _make_task("b_task", name="task_b"))
        reg.save_task("a_task", _make_task("a_task", name="task_a"))

        tasks = reg.list_tasks()
        assert tasks[0]["name"] == "task_a"
        assert tasks[1]["name"] == "task_b"

    def test_returns_copies(self, tmp_path: Path) -> None:
        reg = TaskRegistry(tmp_path)
        reg.save_task("x", _make_task("x"))

        tasks = reg.list_tasks()
        tasks[0]["name"] = "篡改"

        assert reg.get_task("x")["name"] == "测试任务"


class TestRegistrySaveTask:
    """save_task 测试。"""

    def test_create(self, tmp_path: Path) -> None:
        """创建新任务。"""
        reg = TaskRegistry(tmp_path)
        ok, msg = reg.save_task("new_task", _make_task("new_task"))
        assert ok is True
        assert reg.get_task("new_task") is not None

    def test_update(self, tmp_path: Path) -> None:
        """更新已有任务。"""
        reg = TaskRegistry(tmp_path)
        reg.save_task("t1", _make_task("t1", name="原名"))

        reg.save_task("t1", _make_task("t1", name="新名"))
        assert reg.get_task("t1")["name"] == "新名"

    def test_persists_to_disk(self, tmp_path: Path) -> None:
        """任务保存到磁盘。"""
        reg = TaskRegistry(tmp_path)
        reg.save_task("disk_task", _make_task("disk_task"))

        task_file = tmp_path / "disk_task.json"
        assert task_file.exists()
        data = json.loads(task_file.read_text(encoding="utf-8"))
        assert data["name"] == "测试任务"
        assert "id" not in data  # 磁盘不含 id 字段

    def test_invalid_id(self, tmp_path: Path) -> None:
        reg = TaskRegistry(tmp_path)
        ok, msg = reg.save_task("../bad", _make_task())
        assert ok is False

    def test_save_disabled_task_not_in_index(self, tmp_path: Path) -> None:
        """禁用的任务不在调度索引中。"""
        reg = TaskRegistry(tmp_path)
        reg.save_task("d1", _make_task("d1", enabled=False, hour=9, minute=0))

        assert len(reg.get_due_tasks(9, 0)) == 0

    def test_save_enabled_task_in_index(self, tmp_path: Path) -> None:
        """启用的任务在调度索引中。"""
        reg = TaskRegistry(tmp_path)
        reg.save_task("e1", _make_task("e1", enabled=True, hour=14, minute=30))

        assert "e1" in reg.get_due_tasks(14, 30)

    def test_update_changes_index(self, tmp_path: Path) -> None:
        """更新任务时间后索引同步变更。"""
        reg = TaskRegistry(tmp_path)
        reg.save_task("u1", _make_task("u1", hour=10, minute=0))

        assert "u1" in reg.get_due_tasks(10, 0)

        # 改到 15:00
        config = _make_task("u1", hour=15, minute=0)
        reg.save_task("u1", config)

        assert "u1" not in reg.get_due_tasks(10, 0)
        assert "u1" in reg.get_due_tasks(15, 0)


class TestRegistryDeleteTask:
    """delete_task 测试。"""

    def test_delete_existing(self, tmp_path: Path) -> None:
        reg = TaskRegistry(tmp_path)
        reg.save_task("del_me", _make_task("del_me"))

        ok, msg = reg.delete_task("del_me")
        assert ok is True
        assert reg.get_task("del_me") is None

    def test_delete_nonexistent(self, tmp_path: Path) -> None:
        reg = TaskRegistry(tmp_path)
        ok, msg = reg.delete_task("ghost")
        assert ok is False

    def test_delete_removes_from_index(self, tmp_path: Path) -> None:
        reg = TaskRegistry(tmp_path)
        reg.save_task("idx_del", _make_task("idx_del", hour=12, minute=0))

        assert "idx_del" in reg.get_due_tasks(12, 0)

        reg.delete_task("idx_del")
        assert "idx_del" not in reg.get_due_tasks(12, 0)

    def test_delete_removes_disk_file(self, tmp_path: Path) -> None:
        reg = TaskRegistry(tmp_path)
        reg.save_task("file_del", _make_task("file_del"))

        task_file = tmp_path / "file_del.json"
        assert task_file.exists()

        reg.delete_task("file_del")
        assert not task_file.exists()

    def test_delete_invalid_id(self, tmp_path: Path) -> None:
        reg = TaskRegistry(tmp_path)
        ok, msg = reg.delete_task("../escape")
        assert ok is False


class TestRegistryGetDueTasks:
    """get_due_tasks 测试。"""

    def test_returns_copy(self, tmp_path: Path) -> None:
        """返回副本，修改不影响内部集合。"""
        reg = TaskRegistry(tmp_path)
        reg.save_task("copy_test", _make_task("copy_test", hour=8, minute=0))

        due = reg.get_due_tasks(8, 0)
        due.add("injected")

        assert "injected" not in reg.get_due_tasks(8, 0)

    def test_no_tasks_at_time(self, tmp_path: Path) -> None:
        reg = TaskRegistry(tmp_path)
        assert reg.get_due_tasks(23, 59) == set()

    def test_multiple_tasks_same_time(self, tmp_path: Path) -> None:
        reg = TaskRegistry(tmp_path)
        reg.save_task("a", _make_task("a", hour=9, minute=0))
        reg.save_task("b", _make_task("b", hour=9, minute=0))
        reg.save_task("c", _make_task("c", hour=10, minute=0))

        due = reg.get_due_tasks(9, 0)
        assert "a" in due
        assert "b" in due
        assert "c" not in due


class TestRegistryHasEnabledTasks:
    """has_enabled_tasks 测试。"""

    def test_no_tasks(self, tmp_path: Path) -> None:
        reg = TaskRegistry(tmp_path)
        assert reg.has_enabled_tasks() is False

    def test_all_disabled(self, tmp_path: Path) -> None:
        reg = TaskRegistry(tmp_path)
        reg.save_task("d1", _make_task("d1", enabled=False))
        reg.save_task("d2", _make_task("d2", enabled=False))
        assert reg.has_enabled_tasks() is False

    def test_one_enabled(self, tmp_path: Path) -> None:
        reg = TaskRegistry(tmp_path)
        reg.save_task("d1", _make_task("d1", enabled=False))
        reg.save_task("e1", _make_task("e1", enabled=True))
        assert reg.has_enabled_tasks() is True


class TestRegistryUpdateLastRun:
    """update_last_run 测试。"""

    def test_updates_cache(self, tmp_path: Path) -> None:
        reg = TaskRegistry(tmp_path)
        reg.save_task("lr", _make_task("lr"))

        reg.update_last_run("lr", "success", "2026-01-01T00:00:00")
        task = reg.get_task("lr")
        assert task["last_run"] == "2026-01-01T00:00:00"
        assert task["last_status"] == "success"

    def test_updates_disk(self, tmp_path: Path) -> None:
        reg = TaskRegistry(tmp_path)
        reg.save_task("lr2", _make_task("lr2"))

        reg.update_last_run("lr2", "failure")

        # 重新从磁盘加载验证
        reg2 = TaskRegistry(tmp_path)
        task = reg2.get_task("lr2")
        assert task["last_status"] == "failure"
        assert "last_run" in task

    def test_nonexistent_task(self, tmp_path: Path) -> None:
        """不存在的任务不报错。"""
        reg = TaskRegistry(tmp_path)
        reg.update_last_run("ghost", "success")  # 不应抛异常


# ═══════════════════════════════════════════════════════
#  TaskHistoryStore
# ═══════════════════════════════════════════════════════


class TestHistoryAddAndGet:
    """add_record 和 get_history 测试。"""

    def test_add_and_get(self, tmp_path: Path) -> None:
        store = TaskHistoryStore(tmp_path)
        store.add_record("task1", "success", "执行成功", 1.5)

        history = store.get_history("task1")
        assert len(history) == 1
        assert history[0]["status"] == "success"
        assert history[0]["message"] == "执行成功"
        assert history[0]["duration"] == 1.5
        assert "timestamp" in history[0]

    def test_newest_first(self, tmp_path: Path) -> None:
        store = TaskHistoryStore(tmp_path)
        store.add_record("task1", "success", "第一次", 1.0)
        store.add_record("task1", "failure", "第二次", 2.0)

        history = store.get_history("task1")
        assert len(history) == 2
        assert history[0]["message"] == "第二次"
        assert history[1]["message"] == "第一次"

    def test_message_truncation(self, tmp_path: Path) -> None:
        store = TaskHistoryStore(tmp_path)
        long_msg = "x" * 1000
        store.add_record("task1", "success", long_msg, 1.0)

        history = store.get_history("task1")
        assert len(history[0]["message"]) == 500

    def test_empty_history(self, tmp_path: Path) -> None:
        store = TaskHistoryStore(tmp_path)
        assert store.get_history("no_such_task") == []

    def test_invalid_id(self, tmp_path: Path) -> None:
        store = TaskHistoryStore(tmp_path)
        assert store.get_history("../escape") == []

    def test_persists_to_disk(self, tmp_path: Path) -> None:
        store = TaskHistoryStore(tmp_path)
        store.add_record("persist", "success", "持久化测试", 0.5)

        history_file = tmp_path / "persist.json"
        assert history_file.exists()
        data = json.loads(history_file.read_text(encoding="utf-8"))
        assert len(data["runs"]) == 1


class TestHistoryMaxSize:
    """MAX_HISTORY_SIZE 裁剪测试。"""

    def test_exceeds_max(self, tmp_path: Path) -> None:
        store = TaskHistoryStore(tmp_path)
        for i in range(MAX_HISTORY_SIZE + 10):
            store.add_record("big", "success", f"第{i}次", float(i))

        history = store.get_history("big")
        assert len(history) == MAX_HISTORY_SIZE
        # 最新的在前
        assert history[0]["message"] == f"第{MAX_HISTORY_SIZE + 9}次"

    def test_exact_max(self, tmp_path: Path) -> None:
        store = TaskHistoryStore(tmp_path)
        for i in range(MAX_HISTORY_SIZE):
            store.add_record("exact", "success", f"#{i}", float(i))

        history = store.get_history("exact")
        assert len(history) == MAX_HISTORY_SIZE


class TestHistoryDelete:
    """delete_history 测试。"""

    def test_delete_existing(self, tmp_path: Path) -> None:
        store = TaskHistoryStore(tmp_path)
        store.add_record("to_del", "success", "将被删除", 1.0)

        store.delete_history("to_del")
        assert store.get_history("to_del") == []

    def test_delete_nonexistent(self, tmp_path: Path) -> None:
        """删除不存在的历史记录不报错。"""
        store = TaskHistoryStore(tmp_path)
        store.delete_history("ghost")  # 不应抛异常

    def test_invalid_id(self, tmp_path: Path) -> None:
        """无效 ID 不报错。"""
        store = TaskHistoryStore(tmp_path)
        store.delete_history("../escape")  # 不应抛异常
