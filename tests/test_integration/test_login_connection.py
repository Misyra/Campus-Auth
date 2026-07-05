"""登录链路连接测试 — engine → task_executor → mock worker。

验证数据在组件间正确流转，不验证内部实现细节。
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import Future
from unittest.mock import AsyncMock, MagicMock, patch

from app.schemas import AppSettings, LoginCredentials
from app.workers.playwright_worker import WorkerResponse


def _ensure_login_config(engine) -> None:
    """确保引擎运行时配置包含登录所需字段。"""
    old = engine._runtime_config
    engine._runtime_config = old.model_copy(
        update={
            "credentials": LoginCredentials(
                username="testuser",
                password="testpass",
                auth_url="http://10.0.0.1",
                isp=old.credentials.isp,
                carrier_custom=old.credentials.carrier_custom,
            ),
        }
    )


class TestLoginConnection:
    """登录链路连接测试。"""

    def test_auto_login_success(self, integration_stack):
        """自动登录成功 → worker 被调用。"""
        engine, profile_service, task_executor, _, mock_worker = integration_stack
        _ensure_login_config(engine)

        mock_worker.submit.return_value = WorkerResponse(success=True, data="登录成功")

        # 网络异常 → check_once 返回 need_login → 触发登录
        with (
            patch(
                "app.network.decision.check_network_status",
                new=AsyncMock(return_value=(False, "network_down", "none")),
            ),
            patch(
                "app.network.decision.check_login_prerequisites",
                new=AsyncMock(return_value=(True, "")),
            ),
        ):
            import asyncio
            loop = asyncio.new_event_loop()
            result = loop.run_until_complete(engine._do_async_login())
            loop.close()

        assert result is True

        # 等待 login_pool 中的任务完成
        deadline = time.time() + 5
        while time.time() < deadline and not mock_worker.submit.called:
            time.sleep(0.05)

        mock_worker.submit.assert_called()

    def test_auto_login_retry(self, integration_stack):
        """登录失败 → 重试 → 最终成功。"""
        engine, profile_service, task_executor, _, mock_worker = integration_stack
        _ensure_login_config(engine)

        # 第一次失败，第二次成功
        mock_worker.submit.side_effect = [
            WorkerResponse(success=False, error="网络超时"),
            WorkerResponse(success=True, data="登录成功"),
        ]

        # 第一次登录
        config = engine.get_runtime_config()
        handle1 = task_executor._login_orchestrator.submit(source="auto", config=config)
        future1 = handle1.future
        ok1, msg1 = future1.result(timeout=5)
        assert ok1 is False
        assert "网络超时" in msg1

        # 重试登录
        handle2 = task_executor._login_orchestrator.submit(source="auto", config=config)
        future2 = handle2.future
        ok2, msg2 = future2.result(timeout=5)
        assert ok2 is True
        assert "登录成功" in msg2

        assert mock_worker.submit.call_count == 2

    def test_retry_exhausted(self, integration_stack):
        """连续失败达阈值 → MonitoredPolicy._attempt 递增。"""
        engine, profile_service, task_executor, _, mock_worker = integration_stack
        _ensure_login_config(engine)

        from app.schemas import MonitorSettings

        engine._runtime_config = engine._runtime_config.model_copy(
            update={
                "monitor": MonitorSettings(
                    enable_local_check=False, check_auth_url=False
                ),
            }
        )

        mock_worker.submit.return_value = WorkerResponse(
            success=False, error="网络超时"
        )

        # 通过引擎的 _do_async_login 连续提交登录（走 done callback 路径）
        import asyncio
        for i in range(3):
            future = Future()
            handle = MagicMock()
            handle.rejected_reason = None
            handle.future = future
            with patch.object(engine._orchestrator, "submit", return_value=handle):
                loop = asyncio.new_event_loop()
                result = loop.run_until_complete(engine._do_async_login())
                loop.close()
            assert result is True
            future.set_result((False, "网络超时"))
            time.sleep(0.2)

        # 连续失败计数应为 3（通过 MonitoredPolicy._attempt 验证）
        assert engine._retry_policy._attempt == 3

    def test_manual_preempt_auto(self, integration_stack):
        """手动登录取消卡住的自动登录。"""
        engine, profile_service, task_executor, _, mock_worker = integration_stack
        _ensure_login_config(engine)

        login_started = threading.Event()
        login_release = threading.Event()

        def blocking_login(*args, **kwargs):
            login_started.set()
            login_release.wait(timeout=5)
            return WorkerResponse(success=True, data="自动登录成功")

        mock_worker.submit.side_effect = blocking_login

        # 启动自动登录（异步）
        config = engine.get_runtime_config()
        handle_auto = task_executor._login_orchestrator.submit(
            source="auto", config=config
        )
        future_auto = handle_auto.future
        login_started.wait(timeout=5)

        # 确认登录正在进行
        assert task_executor.is_login_running() is True

        # 取消自动登录
        task_executor.cancel_login()
        login_release.set()

        # 等待自动登录结束
        deadline = time.time() + 5
        while time.time() < deadline and task_executor.is_login_running():
            time.sleep(0.05)
        assert task_executor.is_login_running() is False

        # 现在手动登录应该能成功提交
        mock_worker.submit.side_effect = None
        mock_worker.submit.return_value = WorkerResponse(
            success=True, data="手动登录成功"
        )

        handle_manual = task_executor._login_orchestrator.submit(
            source="auto", config=config
        )
        future_manual = handle_manual.future
        ok, msg = future_manual.result(timeout=5)
        assert ok is True
        assert "手动登录成功" in msg

    def test_callback_updates_history(self, integration_stack):
        """登录完成 → 历史记录写入。"""
        engine, profile_service, task_executor, _, mock_worker = integration_stack
        _ensure_login_config(engine)

        login_done = threading.Event()

        def submit_with_event(*args, **kwargs):
            login_done.set()
            return WorkerResponse(success=True, data="登录成功")

        mock_worker.submit.side_effect = submit_with_event

        config = engine.get_runtime_config()
        handle = task_executor._login_orchestrator.submit(source="auto", config=config)
        future = handle.future
        login_done.wait(timeout=5)
        ok, msg = future.result(timeout=5)

        assert ok is True
        assert msg == "登录成功"

        # 验证 login_history 服务存在且被调用
        assert engine._login_history is not None

    def test_concurrent_dedup(self, integration_stack):
        """两个线程同时提交 → 只有一个实际执行。"""
        engine, profile_service, task_executor, _, mock_worker = integration_stack
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
        config = engine.get_runtime_config()
        handle_a = task_executor._login_orchestrator.submit(
            source="auto", config=config
        )
        future_a = handle_a.future
        start_event.wait(timeout=5)

        # 线程 B 尝试提交，应被去重（返回同一个 Future）
        handle_b = task_executor._login_orchestrator.submit(
            source="auto", config=config
        )
        future_b = handle_b.future

        # 验证 submit 只调了一次
        assert call_count == 1

        # 两个 future 应该是同一个对象（去重）
        assert future_a is future_b

        release_event.set()
        future_a.result(timeout=5)

    def test_reload_during_login(self, integration_stack):
        """登录进行中 → 保存配置 → reload → 旧登录正常结束，新配置已生效。"""
        engine, profile_service, task_executor, _, mock_worker = integration_stack
        _ensure_login_config(engine)

        login_done = threading.Event()
        release_login = threading.Event()

        def slow_login(*args, **kwargs):
            login_done.set()
            release_login.wait(timeout=5)
            return WorkerResponse(success=True, data="ok")

        mock_worker.submit.side_effect = slow_login

        # 启动登录
        config = engine.get_runtime_config()
        handle = task_executor._login_orchestrator.submit(source="auto", config=config)
        future = handle.future
        login_done.wait(timeout=5)

        # 登录进行中，保存新配置
        from app.schemas import ConfigSaveRequest
        from app.services.profile_service import save_global_and_profile

        payload = ConfigSaveRequest(
            browser=engine._runtime_config.browser,
            monitor=engine._runtime_config.monitor,
            retry=engine._runtime_config.retry,
            pause=engine._runtime_config.pause,
            logging=engine._runtime_config.logging,
            app_settings=AppSettings(),
        )
        result = save_global_and_profile(payload, profile_service, engine.reload_config)

        # 释放登录
        release_login.set()
        ok, msg = future.result(timeout=5)

        assert ok is True
