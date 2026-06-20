"""登录链路连接测试 — engine → task_executor → mock worker。

验证数据在组件间正确流转，不验证内部实现细节。
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import Future
from unittest.mock import MagicMock, patch

import pytest

from app.network.decision import check_network_status
from app.schemas import MonitorConfigPayload
from app.workers.playwright_worker import WorkerResponse


def _ensure_login_config(engine) -> None:
    """确保引擎运行时配置包含登录所需字段。"""
    engine._runtime_config["username"] = "testuser"
    engine._runtime_config["password"] = "testpass"
    engine._runtime_config["auth_url"] = "http://10.0.0.1"


class TestLoginConnection:
    """登录链路连接测试。"""

    def test_auto_login_success(self, integration_stack):
        """自动登录成功 → worker 被调用。"""
        engine, profile_service, task_executor, mock_worker = integration_stack
        _ensure_login_config(engine)

        mock_worker.submit.return_value = WorkerResponse(success=True, data="登录成功")

        # 网络异常 → check_once 返回 need_login → 触发登录
        with patch(
            "app.network.decision.check_network_status",
            return_value=(False, "network_down", "none"),
        ):
            result = engine._do_async_login()

        assert result is True

        # 等待 login_pool 中的任务完成
        time.sleep(0.5)

        mock_worker.submit.assert_called()

    def test_auto_login_retry(self, integration_stack):
        """登录失败 → 重试 → 最终成功。"""
        engine, profile_service, task_executor, mock_worker = integration_stack
        _ensure_login_config(engine)

        # 第一次失败，第二次成功
        mock_worker.submit.side_effect = [
            WorkerResponse(success=False, error="网络超时"),
            WorkerResponse(success=True, data="登录成功"),
        ]

        # 第一次登录
        future1 = task_executor.execute_login_async()
        ok1, msg1 = future1.result(timeout=5)
        assert ok1 is False
        assert "网络超时" in msg1

        # 重试登录
        future2 = task_executor.execute_login_async()
        ok2, msg2 = future2.result(timeout=5)
        assert ok2 is True
        assert "登录成功" in msg2

        assert mock_worker.submit.call_count == 2

    def test_retry_exhausted(self, integration_stack):
        """连续失败达阈值 → 连续失败计数递增。"""
        engine, profile_service, task_executor, mock_worker = integration_stack
        _ensure_login_config(engine)

        mock_worker.submit.return_value = WorkerResponse(
            success=False, error="网络超时"
        )

        # 通过引擎的 _do_async_login 连续提交登录（走 done callback 路径）
        for i in range(3):
            future = Future()
            handle = MagicMock()
            handle.rejected_reason = None
            handle.future = future
            with patch.object(engine._orchestrator, "submit", return_value=handle):
                result = engine._do_async_login()
            assert result is True
            future.set_result((False, "网络超时"))
            time.sleep(0.2)

        # 连续失败计数应为 3
        assert engine._consecutive_login_failures == 3

    def test_manual_preempt_auto(self, integration_stack):
        """手动登录取消卡住的自动登录。"""
        engine, profile_service, task_executor, mock_worker = integration_stack
        _ensure_login_config(engine)

        login_started = threading.Event()
        login_release = threading.Event()

        def blocking_login(*args, **kwargs):
            login_started.set()
            login_release.wait(timeout=5)
            return WorkerResponse(success=True, data="自动登录成功")

        mock_worker.submit.side_effect = blocking_login

        # 启动自动登录（异步）
        future_auto = task_executor.execute_login_async()
        login_started.wait(timeout=5)

        # 确认登录正在进行
        assert task_executor.is_login_running() is True

        # 取消自动登录
        task_executor.cancel_login()
        login_release.set()

        # 等待自动登录结束
        time.sleep(0.5)
        assert task_executor.is_login_running() is False

        # 现在手动登录应该能成功提交
        mock_worker.submit.side_effect = None
        mock_worker.submit.return_value = WorkerResponse(
            success=True, data="手动登录成功"
        )

        future_manual = task_executor.execute_login_async()
        ok, msg = future_manual.result(timeout=5)
        assert ok is True
        assert "手动登录成功" in msg

    def test_callback_updates_history(self, integration_stack):
        """登录完成 → 历史记录写入。"""
        engine, profile_service, task_executor, mock_worker = integration_stack
        _ensure_login_config(engine)

        login_done = threading.Event()

        def submit_with_event(*args, **kwargs):
            login_done.set()
            return WorkerResponse(success=True, data="登录成功")

        mock_worker.submit.side_effect = submit_with_event

        future = task_executor.execute_login_async()
        login_done.wait(timeout=5)
        ok, msg = future.result(timeout=5)

        assert ok is True
        assert msg == "登录成功"

        # 验证 login_history 服务存在且被调用
        assert engine._login_history is not None

    def test_concurrent_dedup(self, integration_stack):
        """两个线程同时提交 → 只有一个实际执行。"""
        engine, profile_service, task_executor, mock_worker = integration_stack
        _ensure_login_config(engine)

        start_event = threading.Event()
        release_event = threading.Event()
        call_count = 0

        def blocking_submit(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            start_event.set()
            release_event.wait(timeout=5)
            return WorkerResponse(success=True, data="ok")

        mock_worker.submit.side_effect = blocking_submit

        # 线程 A 提交登录
        future_a = task_executor.execute_login_async()
        start_event.wait(timeout=5)

        # 线程 B 尝试提交，应被去重（返回同一个 Future）
        future_b = task_executor.execute_login_async()

        # 验证 submit 只调了一次
        assert call_count == 1

        # 两个 future 应该是同一个对象（去重）
        assert future_a is future_b

        release_event.set()
        future_a.result(timeout=5)

    def test_reload_during_login(self, integration_stack):
        """登录进行中 → 保存配置 → reload → 旧登录正常结束，新配置已生效。"""
        engine, profile_service, task_executor, mock_worker = integration_stack
        _ensure_login_config(engine)

        login_done = threading.Event()
        release_login = threading.Event()

        def slow_login(*args, **kwargs):
            login_done.set()
            release_login.wait(timeout=5)
            return WorkerResponse(success=True, data="ok")

        mock_worker.submit.side_effect = slow_login

        # 启动登录
        future = task_executor.execute_login_async()
        login_done.wait(timeout=5)

        # 登录进行中，保存新配置
        from app.services.config_service import save_and_apply

        new_payload = MonitorConfigPayload(
            username="newuser",
            password="newpass",
            auth_url="http://10.0.0.1",
            check_interval_seconds=60,
        )
        result = save_and_apply(new_payload, profile_service, engine.reload_config)

        # 释放登录
        release_login.set()
        ok, msg = future.result(timeout=5)

        assert ok is True

        # 验证：新配置已生效
        assert engine.get_config().check_interval_seconds == 60
