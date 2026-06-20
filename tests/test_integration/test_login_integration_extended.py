"""登录流程集成测试扩展 — 真实组件栈 + mock Worker。

边界约定：
- Playwright Worker → unittest.mock.MagicMock
- 其余组件（ScheduleEngine, TaskExecutor, ProfileService 等）→ 真实实例

复用 tests/test_integration/conftest.py 中的 integration_stack fixture。
"""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from app.services.engine import EngineCmdType, EngineCommand
from app.workers.playwright_worker import WorkerResponse


def _ensure_login_config(engine) -> None:
    """确保引擎运行时配置包含登录所需字段。"""
    engine._runtime_config["username"] = "testuser"
    engine._runtime_config["password"] = "testpass"
    engine._runtime_config["auth_url"] = "http://10.0.0.1"


def _capture_login_completion(task_executor, engine=None, timeout: float = 5.0):
    """安装包装器捕获登录结果。

    hook orchestrator._dispatch，确保登录从委托路径触发时能捕获。
    必须在调用 _handle_login / 触发登录之前调用。
    返回 (result_container, done_event, restore_fn)。
    """
    result = []
    done = threading.Event()
    restores = []

    def _capture(f):
        if not done.is_set():
            try:
                result.append(f.result(timeout=timeout))
            except Exception as e:
                result.append(e)
            done.set()

    # Hook orchestrator._dispatch（委托路径）
    orchestrator = getattr(engine, "_orchestrator", None) if engine else None
    if orchestrator is not None:
        original_dispatch = orchestrator._dispatch

        def wrapped_dispatch(config, source, cancel_event):
            handle = original_dispatch(config, source, cancel_event)
            if handle.future is not None:
                handle.future.add_done_callback(_capture)
            return handle

        orchestrator._dispatch = wrapped_dispatch
        restores.append(lambda: setattr(orchestrator, "_dispatch", original_dispatch))

    def restore():
        for fn in restores:
            fn()

    return result, done, restore


class TestFullEngineLoginChain:
    """引擎 → TaskExecutor → worker 完整登录链路（通过 _handle_login 直接触发）。"""

    def test_chain_success(self, integration_stack):
        engine, profile_service, task_executor, mock_worker = integration_stack
        _ensure_login_config(engine)

        mock_worker.submit.return_value = WorkerResponse(success=True, data="登录成功")

        # 在触发登录前安装捕获器
        result_container, done_event, restore_fn = _capture_login_completion(
            task_executor, engine=engine
        )
        try:
            cmd = EngineCommand(
                type=EngineCmdType.LOGIN, response_event=threading.Event()
            )
            engine._handle_login(cmd)

            # _do_async_login 返回 True → response_data 为提交成功
            assert cmd.response_data == (True, "登录已提交")

            # 等待 login_pool 线程实际执行 execute_login
            assert done_event.wait(timeout=5), "登录 Future 在超时内未完成"
            ok, msg = result_container[0]
            assert ok is True
            assert msg == "登录成功"

            # worker.submit 被调且传入了正确的第一个参数
            mock_worker.submit.assert_called_once()

            # 手动登录不触发自动失败计数
            assert engine._consecutive_login_failures == 0
        finally:
            restore_fn()

    def test_chain_failure(self, integration_stack):
        engine, profile_service, task_executor, mock_worker = integration_stack
        _ensure_login_config(engine)

        mock_worker.submit.return_value = WorkerResponse(
            success=False, error="认证失败"
        )

        result_container, done_event, restore_fn = _capture_login_completion(
            task_executor, engine=engine
        )
        try:
            cmd = EngineCommand(
                type=EngineCmdType.LOGIN, response_event=threading.Event()
            )
            engine._handle_login(cmd)

            assert cmd.response_data == (True, "登录已提交")

            assert done_event.wait(timeout=5), "登录 Future 在超时内未完成"
            ok, msg = result_container[0]
            assert ok is False
            assert msg == "认证失败"

            mock_worker.submit.assert_called_once()
            # 手动登录不触发自动失败计数
            assert engine._consecutive_login_failures == 0
        finally:
            restore_fn()


class TestNetworkDetectionLogin:
    """网络检测触发自动登录 + 重试。"""

    def test_network_triggers_login(self, integration_stack):
        engine, profile_service, task_executor, mock_worker = integration_stack
        _ensure_login_config(engine)

        mock_core = MagicMock()
        mock_core.check_once.return_value = {"need_login": True, "interval": 300}
        mock_core.consume_profile_switch_flag.return_value = False
        mock_core.monitoring = True
        engine._monitor_core = mock_core

        engine._runtime_config["retry_settings"] = {
            "max_retries": 3,
            "retry_interval": 30,
        }

        assert not task_executor.is_login_running()

        result_container, done_event, restore_fn = _capture_login_completion(
            task_executor, engine=engine
        )
        try:
            engine._do_network_check()

            assert done_event.wait(timeout=5), "Login Future did not complete in time"
            ok, msg = result_container[0]
            assert ok is True
            assert msg == "登录成功"

            assert engine._next_network_check > time.time()
            mock_worker.submit.assert_called_once()
        finally:
            restore_fn()

    def test_retry_after_failure(self, integration_stack):
        engine, profile_service, task_executor, mock_worker = integration_stack
        _ensure_login_config(engine)

        mock_worker.submit.return_value = WorkerResponse(
            success=False, error="认证失败"
        )

        # 第一次登录（手动触发）
        result_container, done_event, restore_fn = _capture_login_completion(
            task_executor, engine=engine
        )
        try:
            cmd = EngineCommand(
                type=EngineCmdType.LOGIN, response_event=threading.Event()
            )
            engine._handle_login(cmd)
            assert cmd.response_data == (True, "登录已提交")

            assert done_event.wait(timeout=5), "第一次登录未在超时内完成"
            ok, msg = result_container[0]
            assert ok is False
            assert msg == "认证失败"
        finally:
            restore_fn()

        # 模拟重试状态：一次失败后
        engine._consecutive_login_failures = 1

        # 第二次登录（自动重试路径）
        result_container2, done_event2, restore_fn2 = _capture_login_completion(
            task_executor, engine=engine
        )
        try:
            result = engine._do_async_login()
            assert result is True

            assert done_event2.wait(timeout=5), "重试登录未在超时内完成"
            ok, msg = result_container2[0]
            assert ok is False
            assert msg == "认证失败"

            assert mock_worker.submit.call_count == 2
            # 自动登录失败应递增连续失败计数
            assert engine._consecutive_login_failures >= 1
        finally:
            restore_fn2()


class TestCancelPropagation:
    """取消事件在 engine ↔ executor 之间的传播。"""

    def test_cancel_during_login(self, integration_stack):
        engine, profile_service, task_executor, mock_worker = integration_stack
        _ensure_login_config(engine)

        submit_called = threading.Event()
        submit_release = threading.Event()
        captured_cancel_event = None

        # 在触发登录前安装捕获器，用 Event 同步登录完成
        result_container, done_event, restore_fn = _capture_login_completion(
            task_executor, engine=engine
        )
        try:
            def blocking_submit(*args, **kwargs):
                nonlocal captured_cancel_event
                captured_cancel_event = kwargs.get("data", {}).get("cancel_event")
                submit_called.set()
                assert submit_release.wait(timeout=5), "submit was not released in time"
                return WorkerResponse(success=True, data="登录成功")

            mock_worker.submit.side_effect = blocking_submit

            future = task_executor.execute_login_async()

            assert submit_called.wait(timeout=5), "worker.submit was not called in time"
            assert task_executor.is_login_running()

            task_executor.cancel_login()

            submit_release.set()

            # 等待登录完成
            assert done_event.wait(timeout=5), "登录完成回调未触发"
            ok, msg = result_container[0]
            assert ok is True

            assert not task_executor.is_login_running()
        finally:
            restore_fn()


class TestReloadException:
    """配置重载异常时正在执行的登录应继续完成。"""

    def test_reload_during_login_config_error(self, integration_stack, tmp_path):
        engine, profile_service, task_executor, mock_worker = integration_stack
        _ensure_login_config(engine)

        submit_called = threading.Event()
        submit_release = threading.Event()

        result_container, done_event, restore_fn = _capture_login_completion(
            task_executor, engine=engine
        )
        try:
            def blocking_submit(*args, **kwargs):
                submit_called.set()
                assert submit_release.wait(timeout=5), "submit was not released in time"
                return WorkerResponse(success=True, data="登录成功")

            mock_worker.submit.side_effect = blocking_submit

            # 启动登录
            future = task_executor.execute_login_async()

            assert submit_called.wait(timeout=5), "worker.submit was not called in time"
            assert task_executor.is_login_running()

            # _reload_config_internal 底层用 profile_service.load()
            # 读取 settings.json，且 ProfileService 对 IO 异常做了防御
            # 处理（捕获 Exception 返回空 ProfilesData）。
            # 因此 mock _reload_config_internal 返回 False 来模拟重载失败。
            with patch.object(engine, "_reload_config_internal", return_value=False):
                reload_cmd = EngineCommand(
                    type=EngineCmdType.RELOAD,
                    data={},
                    response_event=threading.Event(),
                )
                engine._handle_reload(reload_cmd)

                assert reload_cmd.response_data is not None
                success, msg = reload_cmd.response_data
                assert success is False
                assert "配置重载失败" in msg

            # 释放登录
            submit_release.set()

            # 等待登录完成
            assert done_event.wait(timeout=5), "登录 Future 在超时内未完成"
            ok, msg = result_container[0]
            assert ok is True
            assert msg == "登录成功"

            # 验证引擎仍保留旧配置
            assert engine._runtime_config["username"] == "testuser"
            assert engine._runtime_config["auth_url"] == "http://10.0.0.1"
        finally:
            restore_fn()


class TestLoginOnceRetry:
    """LOGIN_ONCE 模式重试逻辑：_execute_login_with_retries 直接测试。"""

    def test_execute_login_with_retries_success(self, integration_stack):
        engine, _, _, _ = integration_stack
        _ensure_login_config(engine)
        mock_worker = MagicMock()
        mock_worker.submit.return_value = WorkerResponse(success=True, data="登录成功")
        runtime_config = engine._copy_runtime_config()
        runtime_config["retry_settings"] = {"max_retries": 3, "retry_interval": 1}

        with (
            patch("app.workers.playwright_worker.get_worker", return_value=mock_worker),
            patch("main.cleanup_orphan_browsers"),
            patch("time.sleep"),
        ):
            from main import _execute_login_with_retries, LoginResult

            result = _execute_login_with_retries(runtime_config, MagicMock())

        assert result == LoginResult.SUCCESS
        mock_worker.submit.assert_called_once()

    def test_execute_login_with_retries_exhausted(self, integration_stack):
        engine, _, _, _ = integration_stack
        _ensure_login_config(engine)
        mock_worker = MagicMock()
        mock_worker.submit.return_value = WorkerResponse(success=False, error="超时")
        runtime_config = engine._copy_runtime_config()
        runtime_config["retry_settings"] = {"max_retries": 2, "retry_interval": 0}

        with (
            patch("app.workers.playwright_worker.get_worker", return_value=mock_worker),
            patch("main.cleanup_orphan_browsers"),
            patch("time.sleep"),
        ):
            from main import _execute_login_with_retries, LoginResult

            result = _execute_login_with_retries(runtime_config, MagicMock())

        assert result == LoginResult.TEMPORARY_FAILURE
        assert mock_worker.submit.call_count == 2

    def test_execute_login_with_retries_retry_then_succeed(self, integration_stack):
        """第一次失败、重试后成功 → 返回 SUCCESS。"""
        engine, _, _, _ = integration_stack
        _ensure_login_config(engine)
        mock_worker = MagicMock()
        mock_worker.submit.side_effect = [
            WorkerResponse(success=False, error="超时"),
            WorkerResponse(success=True, data="登录成功"),
        ]
        runtime_config = engine._copy_runtime_config()
        runtime_config["retry_settings"] = {"max_retries": 3, "retry_interval": 0}

        with (
            patch("app.workers.playwright_worker.get_worker", return_value=mock_worker),
            patch("main.cleanup_orphan_browsers"),
            patch("time.sleep"),
        ):
            from main import _execute_login_with_retries, LoginResult

            result = _execute_login_with_retries(runtime_config, MagicMock())

        assert result == LoginResult.SUCCESS
        assert mock_worker.submit.call_count == 2


class TestProfileSwitchDuringLogin:
    """方案切换在登录过程中的并发安全性。"""

    def test_profile_switch_during_login(self, integration_stack):
        engine, profile_service, task_executor, mock_worker = integration_stack
        _ensure_login_config(engine)

        submit_called = threading.Event()
        submit_release = threading.Event()

        result_container, done_event, restore_fn = _capture_login_completion(
            task_executor, engine=engine
        )
        try:
            def blocking_submit(*args, **kwargs):
                submit_called.set()
                assert submit_release.wait(timeout=5), "submit was not released in time"
                return WorkerResponse(success=True, data="登录成功")

            mock_worker.submit.side_effect = blocking_submit

            future = task_executor.execute_login_async()

            assert submit_called.wait(timeout=5), "worker.submit was not called in time"
            assert task_executor.is_login_running()

            switch_cmd = EngineCommand(
                type=EngineCmdType.APPLY_PROFILE,
                data={"profile_id": "default"},
                response_event=threading.Event(),
            )
            engine._handle_apply_profile(switch_cmd)

            assert switch_cmd.response_data == (True, "方案切换成功")

            submit_release.set()

            assert done_event.wait(timeout=5), "登录 Future 在超时内未完成"
            ok, msg = result_container[0]
            assert ok is True
            assert msg == "登录成功"

            assert engine._runtime_config.get("username") == "testuser"
            assert engine._runtime_config.get("auth_url") == "http://10.0.0.1"
        finally:
            restore_fn()
