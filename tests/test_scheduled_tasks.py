"""定时任务功能测试。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.services.engine import MAX_HISTORY_SIZE, ScheduleEngine
from app.utils.shell_utils import get_default_shell


@pytest.fixture
def project_root(tmp_path):
    """创建临时项目目录。"""
    return tmp_path


@pytest.fixture
def scheduler(project_root):
    """创建调度器实例。"""
    return ScheduleEngine(project_root)


def test_save_and_get_task(scheduler):
    """测试保存和获取定时任务。"""
    task_id = "test_task"
    config = {
        "name": "测试任务",
        "description": "这是一个测试任务",
        "type": "shell",
        "command": "echo hello",
        "enabled": True,
        "shell_path": "",
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
    assert task["type"] == "shell"
    assert task["command"] == "echo hello"


def test_list_tasks(scheduler):
    """测试列出定时任务。"""
    # 创建多个任务
    for i in range(3):
        scheduler.save_task(
            f"task_{i}",
            {
                "name": f"任务 {i}",
                "type": "shell",
                "command": f"echo {i}",
                "enabled": True,
                "shell_path": "",
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
            "type": "shell",
            "command": "echo delete me",
            "enabled": True,
            "shell_path": "",
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
            "type": "shell",
            "command": "echo history",
            "enabled": True,
            "shell_path": "",
            "schedule": {"hour": 0, "minute": 0},
            "timeout": 60,
        },
    )

    # 添加历史记录
    scheduler._add_history_sync(task_id, "success", "执行成功", 1.5)
    scheduler._add_history_sync(task_id, "failure", "执行失败", 0.5)

    # 获取历史
    history = scheduler.get_history(task_id)
    assert len(history) == 2
    assert history[0]["status"] == "failure"  # 最新的在前
    assert history[1]["status"] == "success"


class TestExecuteShellUsesPolicy:
    """测试 _execute_shell_sync 使用 ShellCommandPolicy 进行安全校验。"""

    def test_execute_shell_uses_policy(self, scheduler):
        """_execute_shell_sync 应通过 ShellCommandPolicy 验证路径并钳制超时。"""
        # 直接 mock 缓存的 _shell_policy 实例
        mock_policy = MagicMock()
        mock_policy.run_sync = MagicMock(return_value=(0, "hello", ""))
        scheduler._shell_policy = mock_policy

        success, message = scheduler._execute_shell_sync("echo hello", 60, "cmd.exe")

        # 验证 run_sync 被调用
        mock_policy.run_sync.assert_called_once()
        assert success is True

    def test_execute_shell_rejects_unknown_path(self, scheduler):
        """_execute_shell_sync 应拒绝不在白名单中的 shell 路径。"""
        fake_shells = [
            {"name": "cmd", "path": "cmd.exe", "description": "Windows 命令提示符"}
        ]

        with patch(
            "app.services.engine.detect_available_shells", return_value=fake_shells
        ):
            success, message = scheduler._execute_shell_sync(
                "echo hello",
                60,
                "/malicious/shell",
            )
            assert success is False
            assert "白名单" in message

    def test_execute_shell_timeout_clamped(self, scheduler):
        """_execute_shell_sync 的超时应通过 ShellCommandPolicy 被 clamp 到 [1, 300]。"""
        # 直接 mock 缓存的 _shell_policy 实例
        mock_policy = MagicMock()
        mock_policy.run_sync = MagicMock(return_value=(0, "ok", ""))
        scheduler._shell_policy = mock_policy

        # 传入超大超时值 999
        success, message = scheduler._execute_shell_sync("echo test", 999, "cmd.exe")

        # 验证执行成功
        assert success is True
        # 验证 run_sync 被调用
        mock_policy.run_sync.assert_called_once()


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
# ScheduleEngine._validate_task_id
# =====================================================================


class TestValidateTaskId:
    def test_valid_ids(self):
        assert ScheduleEngine._validate_task_id("my_task") is True
        assert ScheduleEngine._validate_task_id("task123") is True
        assert ScheduleEngine._validate_task_id("A") is True

    def test_invalid_ids(self):
        assert ScheduleEngine._validate_task_id("") is False
        assert ScheduleEngine._validate_task_id("123bad") is False
        assert ScheduleEngine._validate_task_id("my-task") is False
        assert ScheduleEngine._validate_task_id("my task") is False


# =====================================================================
# ScheduleEngine CRUD 补充
# =====================================================================


class TestScheduleEngineCRUD:
    @pytest.fixture
    def scheduler(self, tmp_path: Path) -> ScheduleEngine:
        return ScheduleEngine(tmp_path)

    def test_list_tasks_empty(self, scheduler: ScheduleEngine):
        assert scheduler.list_tasks() == []

    def test_list_tasks_sorted_by_name(self, scheduler: ScheduleEngine):
        scheduler.save_task(
            "b_task",
            {
                "name": "Banana",
                "type": "shell",
                "command": "echo b",
                "schedule": {"hour": 1, "minute": 0},
            },
        )
        scheduler.save_task(
            "a_task",
            {
                "name": "Apple",
                "type": "shell",
                "command": "echo a",
                "schedule": {"hour": 0, "minute": 0},
            },
        )
        tasks = scheduler.list_tasks()
        assert tasks[0]["name"] == "Apple"
        assert tasks[1]["name"] == "Banana"

    def test_list_tasks_skips_dotfiles(
        self, scheduler: ScheduleEngine, tmp_path: Path
    ):
        # 创建正常任务
        scheduler.save_task(
            "normal",
            {
                "name": "正常",
                "type": "shell",
                "command": "echo ok",
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

    def test_list_tasks_skips_malformed_json(
        self, scheduler: ScheduleEngine, tmp_path: Path
    ):
        scheduler.save_task(
            "good",
            {
                "name": "好的",
                "type": "shell",
                "command": "echo ok",
                "schedule": {"hour": 0, "minute": 0},
            },
        )
        (tmp_path / "tasks" / "scheduled" / "bad.json").write_text(
            "not json", encoding="utf-8"
        )
        tasks = scheduler.list_tasks()
        assert len(tasks) == 1
        assert tasks[0]["id"] == "good"

    def test_get_task_returns_id_field(self, scheduler: ScheduleEngine):
        scheduler.save_task(
            "my_task",
            {
                "name": "测试",
                "type": "shell",
                "command": "echo ok",
                "schedule": {"hour": 0, "minute": 0},
            },
        )
        task = scheduler.get_task("my_task")
        assert task is not None
        assert task["id"] == "my_task"

    def test_get_task_nonexistent(self, scheduler: ScheduleEngine):
        assert scheduler.get_task("nonexistent") is None

    def test_get_task_invalid_id(self, scheduler: ScheduleEngine):
        assert scheduler.get_task("123bad") is None

    def test_get_task_malformed_json(self, scheduler: ScheduleEngine, tmp_path: Path):
        (tmp_path / "tasks" / "scheduled" / "bad.json").write_text(
            "not json", encoding="utf-8"
        )
        assert scheduler.get_task("bad") is None

    def test_delete_task_with_history(
        self, scheduler: ScheduleEngine, tmp_path: Path
    ):
        scheduler.save_task(
            "del_task",
            {
                "name": "待删",
                "type": "shell",
                "command": "echo del",
                "schedule": {"hour": 0, "minute": 0},
            },
        )
        scheduler._add_history_sync("del_task", "success", "ok", 1.0)
        ok, _ = scheduler.delete_task("del_task")
        assert ok is True
        assert scheduler.get_task("del_task") is None
        # 历史文件也应被删除
        history_file = tmp_path / "tasks" / "scheduled" / "history" / "del_task.json"
        assert not history_file.exists()

    def test_delete_task_nonexistent(self, scheduler: ScheduleEngine):
        ok, _ = scheduler.delete_task("nonexistent")
        assert ok is False

    def test_delete_task_invalid_id(self, scheduler: ScheduleEngine):
        ok, _ = scheduler.delete_task("123bad")
        assert ok is False

    def test_save_task_invalid_id(self, scheduler: ScheduleEngine):
        ok, _ = scheduler.save_task("123bad", {"name": "test"})
        assert ok is False


# =====================================================================
# _add_history / get_history 补充
# =====================================================================


class TestSchedulerHistory:
    @pytest.fixture
    def scheduler(self, tmp_path: Path) -> ScheduleEngine:
        return ScheduleEngine(tmp_path)

    def test_add_history_creates_file(
        self, scheduler: ScheduleEngine, tmp_path: Path
    ):
        scheduler._add_history_sync("test", "success", "ok", 1.0)
        history_file = tmp_path / "tasks" / "scheduled" / "history" / "test.json"
        assert history_file.exists()

    def test_add_history_max_size(self, scheduler: ScheduleEngine):
        for i in range(MAX_HISTORY_SIZE + 10):
            scheduler._add_history_sync("test", "success", f"run {i}", 1.0)
        history = scheduler.get_history("test")
        assert len(history) == MAX_HISTORY_SIZE
        # 最新的在前
        assert history[0]["message"] == f"run {MAX_HISTORY_SIZE + 9}"

    def test_add_history_truncates_message(self, scheduler: ScheduleEngine):
        long_msg = "x" * 1000
        scheduler._add_history_sync("test", "success", long_msg, 1.0)
        history = scheduler.get_history("test")
        assert len(history[0]["message"]) == 500

    def test_add_history_invalid_id(self, scheduler: ScheduleEngine):
        # 不应抛异常
        scheduler._add_history_sync("123bad", "success", "ok", 1.0)

    def test_get_history_empty(self, scheduler: ScheduleEngine):
        assert scheduler.get_history("nonexistent") == []

    def test_get_history_invalid_id(self, scheduler: ScheduleEngine):
        assert scheduler.get_history("123bad") == []

    def test_get_history_malformed_json(
        self, scheduler: ScheduleEngine, tmp_path: Path
    ):
        history_dir = tmp_path / "tasks" / "scheduled" / "history"
        history_dir.mkdir(parents=True, exist_ok=True)
        (history_dir / "bad.json").write_text("not json", encoding="utf-8")
        assert scheduler.get_history("bad") == []

    def test_get_history_returns_runs_list(self, scheduler: ScheduleEngine):
        scheduler._add_history_sync("test", "success", "ok", 1.0)
        scheduler._add_history_sync("test", "failure", "err", 0.5)
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
    def test_start_sets_running(self, tmp_path: Path):
        scheduler = ScheduleEngine(tmp_path)
        scheduler.start_scheduler()
        assert scheduler._scheduler_running is True
        scheduler.stop_scheduler()

    def test_stop_clears_running(self, tmp_path: Path):
        scheduler = ScheduleEngine(tmp_path)
        scheduler.start_scheduler()
        scheduler.stop_scheduler()
        assert scheduler._scheduler_running is False

    def test_double_start_no_error(self, tmp_path: Path):
        scheduler = ScheduleEngine(tmp_path)
        scheduler.start_scheduler()
        scheduler.start_scheduler()  # 不应抛异常
        scheduler.stop_scheduler()

    def test_stop_when_not_running(self, tmp_path: Path):
        scheduler = ScheduleEngine(tmp_path)
        scheduler.stop_scheduler()  # 不应抛异常
