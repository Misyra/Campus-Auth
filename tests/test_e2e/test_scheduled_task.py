"""定时任务调度 E2E 测试 — 真实调度器在分钟边界触发任务。

验证 SchedulerService + TaskRegistry + TaskExecutor 的完整调度链路：
- 创建定时脚本任务，设置 schedule 为最近的分钟边界
- 调度器在分钟边界自动触发任务执行
- 执行历史记录正确写入
- 修改 schedule 后新参数即时生效
- 禁用任务后不再触发

调度器最小粒度为分钟级（schedule 索引按 (hour, minute) 构建），
测试需等待真实分钟边界，标记为 slow。
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta

import pytest

# ── 辅助函数 ──


def _save_script(client, task_id: str, content: str = 'print("scheduled_task_fired")'):
    """保存一个 py 脚本任务作为定时任务的执行目标。"""
    payload = {
        "type": "py",
        "name": f"E2E 定时目标 {task_id}",
        "description": "定时任务执行目标",
        "content": content,
    }
    resp = client.put(f"/api/scripts/{task_id}", json=payload)
    assert resp.status_code == 200, f"保存脚本失败: {resp.text}"


def _create_scheduled_task(
    client, task_id: str, target_id: str, hour: int, minute: int, enabled: bool = True
) -> str:
    """创建定时任务，返回服务器生成的实际 task_id。

    API 生成 task_<uuid> 格式的 ID，不使用客户端提供的 ID。
    通过任务名称从列表中查找实际 ID。
    """
    task_name = f"E2E 定时任务 {task_id}"
    payload = {
        "name": task_name,
        "description": "E2E 调度测试",
        "type": "script",
        "target_id": target_id,
        "enabled": enabled,
        "schedule": {"hour": hour, "minute": minute},
        "timeout": 30,
    }
    resp = client.post("/api/scheduled-tasks", json=payload)
    assert resp.status_code == 200, f"创建定时任务失败: {resp.text}"
    # API 生成 task_<uuid> ID，需从列表中查找实际 ID
    tasks = client.get("/api/scheduled-tasks").json()
    task = next(t for t in tasks if t["name"] == task_name)
    return task["id"]


def _get_history(client, task_id: str):
    """获取定时任务执行历史。"""
    resp = client.get(f"/api/scheduled-tasks/{task_id}/history")
    assert resp.status_code == 200, f"获取历史失败: {resp.text}"
    return resp.json()


def _compute_target_minute(offset_seconds: int = 5):
    """计算目标分钟边界。

    返回 (target_datetime, schedule_hour, schedule_minute)。
    保证目标时间至少在 offset_seconds 秒之后，避免竞争条件。
    """
    now = datetime.now()
    # 下一个分钟边界
    next_minute = (now + timedelta(minutes=1)).replace(second=0, microsecond=0)
    # 如果距离下一个边界太近（< offset_seconds），用再下一个
    if (next_minute - now).total_seconds() < offset_seconds:
        next_minute = next_minute + timedelta(minutes=1)
    return next_minute, next_minute.hour, next_minute.minute


def _wait_until(target: datetime, extra_seconds: int = 10, max_wait: int = 80):
    """等待直到 target + extra_seconds，最长 max_wait 秒。"""
    deadline = target + timedelta(seconds=extra_seconds)
    now = datetime.now()
    wait_seconds = (deadline - now).total_seconds()
    if wait_seconds > max_wait:
        wait_seconds = max_wait
    if wait_seconds > 0:
        time.sleep(wait_seconds)


# ── 测试类 ──


@pytest.mark.slow
class TestScheduledTaskScheduling:
    """定时任务真实调度测试 — 等待真实分钟边界触发。"""

    def test_scheduled_task_fires_at_minute_boundary(self, real_app):
        """创建定时任务，等待调度器在分钟边界触发执行。"""
        client, app = real_app

        # 1. 创建脚本任务作为执行目标
        _save_script(client, "e2e_sched_target")

        # 2. 计算目标分钟并创建定时任务
        target_dt, hour, minute = _compute_target_minute()
        actual_task_id = _create_scheduled_task(
            client, "e2e_sched_task", "e2e_sched_target", hour, minute
        )

        # 3. 等待调度器触发
        _wait_until(target_dt, extra_seconds=10)

        # 4. 验证历史记录中有执行记录
        history = _get_history(client, actual_task_id)
        assert len(history) >= 1, f"定时任务未触发，历史记录为空 (target={target_dt})"
        assert history[0]["status"] in ("success", "failure")

    def test_disabled_task_does_not_fire(self, real_app):
        """禁用的定时任务不会被调度器触发。"""
        client, _ = real_app

        _save_script(client, "e2e_disabled_target")

        target_dt, hour, minute = _compute_target_minute()
        # 创建时 enabled=False
        actual_task_id = _create_scheduled_task(
            client, "e2e_disabled_task", "e2e_disabled_target", hour, minute, enabled=False
        )

        # 等待边界过去
        _wait_until(target_dt, extra_seconds=5)

        # 禁用任务不应有执行历史
        history = _get_history(client, actual_task_id)
        assert len(history) == 0, f"禁用任务不应触发，但有历史记录: {history}"

    def test_toggle_task_changes_enabled_state(self, real_app):
        """切换定时任务的启用/禁用状态。"""
        client, _ = real_app

        _save_script(client, "e2e_toggle_target")

        # 创建已启用的任务
        target_dt, hour, minute = _compute_target_minute(offset_seconds=120)
        actual_task_id = _create_scheduled_task(
            client, "e2e_toggle_task", "e2e_toggle_target", hour, minute, enabled=True
        )

        # 禁用任务
        resp = client.post(f"/api/scheduled-tasks/{actual_task_id}/toggle")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

        # 验证已禁用
        tasks = client.get("/api/scheduled-tasks").json()
        task = next(t for t in tasks if t["id"] == actual_task_id)
        assert task["enabled"] is False

        # 再次启用
        resp = client.post(f"/api/scheduled-tasks/{actual_task_id}/toggle")
        assert resp.status_code == 200
        tasks = client.get("/api/scheduled-tasks").json()
        task = next(t for t in tasks if t["id"] == actual_task_id)
        assert task["enabled"] is True

    def test_update_schedule_changes_next_fire(self, real_app):
        """修改定时任务的 schedule 参数后新参数即时生效。"""
        client, _ = real_app

        _save_script(client, "e2e_update_target")

        # 用一个远的 schedule 创建任务（确保不会立即触发）
        actual_task_id = _create_scheduled_task(
            client, "e2e_update_task", "e2e_update_target", hour=3, minute=0
        )

        # 验证初始 schedule
        tasks = client.get("/api/scheduled-tasks").json()
        task = next(t for t in tasks if t["id"] == actual_task_id)
        assert task["schedule"]["hour"] == 3
        assert task["schedule"]["minute"] == 0

        # 计算目标分钟并更新 schedule
        target_dt, new_hour, new_minute = _compute_target_minute()
        update_payload = {
            "schedule": {"hour": new_hour, "minute": new_minute},
        }
        resp = client.put(f"/api/scheduled-tasks/{actual_task_id}", json=update_payload)
        assert resp.status_code == 200
        assert resp.json()["success"] is True

        # 验证 schedule 已更新
        tasks = client.get("/api/scheduled-tasks").json()
        task = next(t for t in tasks if t["id"] == actual_task_id)
        assert task["schedule"]["hour"] == new_hour
        assert task["schedule"]["minute"] == new_minute

        # 等待触发
        _wait_until(target_dt, extra_seconds=10)

        # 验证任务在新 schedule 时间触发
        history = _get_history(client, actual_task_id)
        assert len(history) >= 1, (
            f"修改 schedule 后任务未触发 (target={target_dt}, "
            f"schedule={new_hour}:{new_minute:02d})"
        )

    def test_delete_task_removes_history(self, real_app):
        """删除定时任务后历史记录也被清除。"""
        client, _ = real_app

        _save_script(client, "e2e_delete_target")

        target_dt, hour, minute = _compute_target_minute()
        actual_task_id = _create_scheduled_task(
            client, "e2e_delete_task", "e2e_delete_target", hour, minute
        )

        # 等待触发
        _wait_until(target_dt, extra_seconds=10)

        # 确保有历史
        history = _get_history(client, actual_task_id)
        assert len(history) >= 1

        # 删除任务
        resp = client.delete(f"/api/scheduled-tasks/{actual_task_id}")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

        # 任务列表中不再存在
        tasks = client.get("/api/scheduled-tasks").json()
        assert not any(t["id"] == actual_task_id for t in tasks)

        # 历史也被清除（404 因为任务不存在）
        resp = client.get(f"/api/scheduled-tasks/{actual_task_id}/history")
        assert resp.status_code == 404
