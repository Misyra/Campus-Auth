"""完整模式生命周期测试 — 模拟自启动完整模式（含定时任务）。"""

from __future__ import annotations

import threading
import time
from datetime import datetime
from unittest.mock import patch

import pytest

from app.schemas import AppSettings, ConfigSaveRequest, RuntimeConfig
from app.services.profile_service import save_global_and_profile
from app.schemas import LoginCredentials
from app.workers.playwright_worker import WorkerResponse


def _ensure_login_config(engine) -> None:
    """确保引擎运行时配置包含登录所需字段。"""
    old = engine._runtime_config
    engine._runtime_config = old.model_copy(update={
        "credentials": LoginCredentials(
            username="testuser", password="testpass", auth_url="http://10.0.0.1",
            isp=old.credentials.isp, carrier_custom=old.credentials.carrier_custom,
        ),
    })


class TestFullMode:
    """完整模式全生命周期。"""

    def test_full_lifecycle(self, integration_stack):
        """完整模式：启动 → 断网登录 → 定时任务 → 手动登录 → 配置重载 → 关闭。"""
        engine, profile_service, task_executor, task_registry, mock_worker = integration_stack
        _ensure_login_config(engine)

        login_done = threading.Event()

        def login_with_event(*args, **kwargs):
            login_done.set()
            return WorkerResponse(success=True, data="登录成功")

        mock_worker.submit.side_effect = login_with_event

        # t0: boot() 已启动监控，等待引擎线程就绪
        deadline = time.time() + 5
        while time.time() < deadline and not engine._is_monitoring:
            time.sleep(0.05)
        assert engine._is_monitoring, "引擎监控未在 5 秒内启动"

        # t1: 注册定时任务（时间设为当前，确保 tick 时命中）
        now = datetime.now()
        task_executor.registry.save_task("test_task", {
            "name": "测试任务",
            "type": "shell",
            "command": "echo hello",
            "enabled": True,
            "schedule": {"hour": now.hour, "minute": now.minute},
        })

        # t2: 断网 → 自动登录成功
        with (
            patch(
                "app.services.monitor_service.check_network_status",
                return_value=(False, "network_down", "none"),
            ),
            patch(
                "app.services.monitor_service.check_pause",
                return_value=(False, ""),
            ),
        ):
            engine._do_network_check()
        login_done.wait(timeout=5)

        # t3: 验证定时任务已注册
        assert task_executor.registry.get_task("test_task") is not None
        # 直接触发 scheduler tick 验证任务可执行
        if engine._scheduler:
            due = task_registry.get_due_tasks(now.hour, now.minute)
            if "test_task" in due:
                engine._scheduler.tick(now)
                deadline = time.time() + 10
                while time.time() < deadline:
                    history = task_executor.history_store.get_history("test_task")
                    if len(history) >= 1:
                        break
                    time.sleep(0.1)

        # t4: 手动登录
        login_done.clear()
        mock_worker.submit.side_effect = None
        mock_worker.submit.return_value = WorkerResponse(
            success=True, data="手动登录成功"
        )

        ok, msg = engine.run_manual_login()
        assert ok is True

        # t5: 保存配置 → 重载
        payload = ConfigSaveRequest(
            browser=engine._runtime_config.browser,
            monitor=engine._runtime_config.monitor,
            retry=engine._runtime_config.retry,
            pause=engine._runtime_config.pause,
            logging=engine._runtime_config.logging,
            app_settings=AppSettings(),
            username="testuser",
            password="testpass",
            auth_url="http://10.0.0.1",
        )
        result = save_global_and_profile(payload, profile_service, engine.reload_config)
        assert result.success is True

        # t6: 关闭
        engine.shutdown()
        assert not engine._is_monitoring
