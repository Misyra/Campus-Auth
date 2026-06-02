"""定时任务功能测试。"""

from __future__ import annotations

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


def test_history(scheduler):
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
    scheduler._add_history(task_id, "success", "执行成功", 1.5)
    scheduler._add_history(task_id, "failure", "执行失败", 0.5)

    # 获取历史
    history = scheduler.get_history(task_id)
    assert len(history) == 2
    assert history[0]["status"] == "failure"  # 最新的在前
    assert history[1]["status"] == "success"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
