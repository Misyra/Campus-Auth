"""轻量模式生命周期测试 — 模拟自启动轻量模式的完整流程。"""

from __future__ import annotations

import threading
import time
from unittest.mock import patch

import pytest

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


class TestLightweightMode:
    """轻量模式全生命周期。"""

    def test_full_lifecycle(self, integration_stack):
        """轻量模式：启动 → 断网登录 → 成功 → 再次断网 → 重试 → 手动登录 → 停止。"""
        engine, profile_service, task_executor, _, mock_worker = integration_stack
        _ensure_login_config(engine)

        login_count = [0]
        login_done = threading.Event()

        def counting_login(*args, **kwargs):
            login_count[0] += 1
            login_done.set()
            return WorkerResponse(success=True, data="登录成功")

        mock_worker.submit.side_effect = counting_login

        # t0: boot() 已启动监控，等待引擎线程就绪
        deadline = time.time() + 5
        while time.time() < deadline and not engine._is_monitoring:
            time.sleep(0.05)
        assert engine._is_monitoring, "引擎监控未在 5 秒内启动"

        # t1: 断网 → 自动登录成功
        config = engine.get_runtime_config()
        handle1 = task_executor._login_orchestrator.submit(source="auto", config=config)
        future1 = handle1.future
        ok1, msg1 = future1.result(timeout=5)
        assert ok1 is True
        assert login_count[0] >= 1

        # t2: 再次断网 → 自动登录
        login_done.clear()
        handle2 = task_executor._login_orchestrator.submit(source="auto", config=config)
        future2 = handle2.future
        ok2, msg2 = future2.result(timeout=5)
        assert ok2 is True
        assert login_count[0] >= 2

        # t3: 手动登录
        login_done.clear()
        mock_worker.submit.side_effect = None
        mock_worker.submit.return_value = WorkerResponse(success=True, data="手动登录成功")

        ok, msg = engine.run_manual_login()
        assert ok is True

        # t4: 停止监控
        engine.stop_monitoring()
        deadline = time.time() + 5
        while time.time() < deadline and engine._is_monitoring:
            time.sleep(0.05)
        assert not engine._is_monitoring
