"""完整模式生命周期测试 — 模拟自启动完整模式（含定时任务）。"""

from __future__ import annotations

import threading
import time
from datetime import datetime
from unittest.mock import patch

import pytest

from app.schemas import MonitorConfigPayload
from app.services.config_service import save_and_apply
from app.workers.playwright_worker import WorkerResponse


def _ensure_login_config(engine) -> None:
    """确保引擎运行时配置包含登录所需字段。"""
    engine._runtime_config["username"] = "testuser"
    engine._runtime_config["password"] = "testpass"
    engine._runtime_config["auth_url"] = "http://10.0.0.1"


class TestFullMode:
    """完整模式全生命周期。"""

    def test_full_lifecycle(self, full_stack):
        """完整模式：启动 → 断网登录 → 定时任务 → 手动登录 → 配置重载 → 关闭。"""
        engine, profile_service, task_executor, task_registry, mock_worker = full_stack
        _ensure_login_config(engine)

        login_done = threading.Event()

        def login_with_event(*args, **kwargs):
            login_done.set()
            return WorkerResponse(success=True, data="登录成功")

        mock_worker.submit.side_effect = login_with_event

        # t0: 启动监控 + 调度器
        result = engine.start_monitoring()
        assert result[0] is True
        # 等待引擎线程处理 START 命令
        time.sleep(0.5)
        assert engine._is_monitoring
        engine.start_scheduler()
        assert engine.scheduler_running

        # t1: 注册定时任务（时间设为当前，确保 tick 时命中）
        now = datetime.now()
        task_executor.save_task("test_task", {
            "name": "测试任务",
            "type": "shell",
            "command": "echo hello",
            "enabled": True,
            "schedule": {"hour": now.hour, "minute": now.minute},
        })

        # t2: 断网 → 自动登录成功
        with patch(
            "app.services.monitor_service.check_network_status",
            return_value=(False, "network_down", "none"),
        ):
            engine._do_network_check()
        login_done.wait(timeout=5)

        # t3: 触发定时任务 tick
        # 直接调用 get_due_tasks 验证任务在调度索引中
        due = task_registry.get_due_tasks(now.hour, now.minute)
        if "test_task" in due:
            engine._run_schedule_tick()
            # 等待异步任务完成（execute_task_async 提交到线程池）
            time.sleep(2)
            history = task_executor.get_history("test_task")
            assert len(history) >= 1
        else:
            # 分钟边界导致任务不在当前 tick 中，验证任务已注册
            assert task_executor.get_task("test_task") is not None

        # t4: 手动登录
        login_done.clear()
        mock_worker.submit.side_effect = None
        mock_worker.submit.return_value = WorkerResponse(
            success=True, data="手动登录成功"
        )

        ok, msg = engine.run_manual_login()
        assert ok is True

        # t5: 保存配置 → 重载
        new_payload = MonitorConfigPayload(
            username="testuser",
            password="",
            auth_url="http://10.0.0.1",
            check_interval_seconds=120,
        )
        result = save_and_apply(new_payload, profile_service, engine.reload_config)
        assert result.success is True
        assert engine.get_config().check_interval_seconds == 120

        # t6: 关闭
        engine.shutdown()
        assert not engine._is_monitoring
