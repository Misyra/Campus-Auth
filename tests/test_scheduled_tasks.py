"""定时任务功能测试。"""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from backend.scheduler_service import SchedulerService


@pytest.fixture
def project_root(tmp_path):
    """创建临时项目目录。"""
    return tmp_path


@pytest.fixture
def scheduler(project_root):
    """创建调度器实例。"""
    return SchedulerService(project_root)


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
        scheduler.save_task(f"task_{i}", {
            "name": f"任务 {i}",
            "type": "shell",
            "command": f"echo {i}",
            "enabled": True,
            "shell_path": "",
            "schedule": {"hour": i, "minute": 0},
            "timeout": 60,
        })

    tasks = scheduler.list_tasks()
    assert len(tasks) == 3


def test_delete_task(scheduler):
    """测试删除定时任务。"""
    task_id = "to_delete"
    scheduler.save_task(task_id, {
        "name": "待删除任务",
        "type": "shell",
        "command": "echo delete me",
        "enabled": True,
        "shell_path": "",
        "schedule": {"hour": 0, "minute": 0},
        "timeout": 60,
    })

    # 确认任务存在
    assert scheduler.get_task(task_id) is not None

    # 删除任务
    ok, message = scheduler.delete_task(task_id)
    assert ok is True

    # 确认任务已删除
    assert scheduler.get_task(task_id) is None


@pytest.mark.asyncio
async def test_history(scheduler):
    """测试执行历史。"""
    task_id = "history_task"
    scheduler.save_task(task_id, {
        "name": "历史任务",
        "type": "shell",
        "command": "echo history",
        "enabled": True,
        "shell_path": "",
        "schedule": {"hour": 0, "minute": 0},
        "timeout": 60,
    })

    # 添加历史记录
    await scheduler._add_history(task_id, "success", "执行成功", 1.5)
    await scheduler._add_history(task_id, "failure", "执行失败", 0.5)

    # 获取历史
    history = scheduler.get_history(task_id)
    assert len(history) == 2
    assert history[0]["status"] == "failure"  # 最新的在前
    assert history[1]["status"] == "success"


class TestExecuteShellUsesPolicy:
    """测试 _execute_shell 使用 ShellCommandPolicy 进行安全校验。"""

    @pytest.mark.asyncio
    async def test_execute_shell_uses_policy(self, scheduler):
        """_execute_shell 应通过 ShellCommandPolicy 验证路径并钳制超时。"""
        from unittest.mock import AsyncMock
        # 直接 mock 缓存的 _shell_policy 实例
        mock_policy = MagicMock()
        mock_policy.run = AsyncMock(return_value=(0, "hello", ""))
        scheduler._shell_policy = mock_policy

        success, message = await scheduler._execute_shell("echo hello", 60, "cmd.exe")

        # 验证 run 被调用
        mock_policy.run.assert_called_once()
        assert success is True

    @pytest.mark.asyncio
    async def test_execute_shell_rejects_unknown_path(self, scheduler):
        """_execute_shell 应拒绝不在白名单中的 shell 路径。"""
        fake_shells = [{"name": "cmd", "path": "cmd.exe", "description": "Windows 命令提示符"}]

        with patch("backend.scheduler_service.detect_available_shells", return_value=fake_shells):
            success, message = await scheduler._execute_shell(
                "echo hello", 60, "/malicious/shell",
            )
            assert success is False
            assert "白名单" in message

    @pytest.mark.asyncio
    async def test_execute_shell_timeout_clamped(self, scheduler):
        """_execute_shell 的超时应通过 ShellCommandPolicy 被 clamp 到 [1, 300]。"""
        from unittest.mock import AsyncMock
        # 直接 mock 缓存的 _shell_policy 实例
        mock_policy = MagicMock()
        mock_policy.run = AsyncMock(return_value=(0, "ok", ""))
        scheduler._shell_policy = mock_policy

        # 传入超大超时值 999
        success, message = await scheduler._execute_shell("echo test", 999, "cmd.exe")

        # 验证执行成功
        assert success is True
        # 验证 run 被调用
        mock_policy.run.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
