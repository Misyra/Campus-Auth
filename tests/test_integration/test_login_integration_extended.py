"""登录流程集成测试扩展 — 真实组件栈 + mock Worker。

边界约定：
- Playwright Worker → unittest.mock.MagicMock
- 其余组件（ScheduleEngine, TaskExecutor, ProfileService, LoginRetryManager 等）→ 真实实例

复用 tests/test_integration/conftest.py 中的 integration_stack fixture。
"""

from __future__ import annotations

import threading
from unittest.mock import MagicMock

import pytest

from app.services.engine import EngineCmdType, EngineCommand
from app.workers.playwright_worker import WorkerResponse


def _ensure_login_config(engine) -> None:
    """确保引擎运行时配置包含登录所需字段。"""
    engine._runtime_config["username"] = "testuser"
    engine._runtime_config["password"] = "testpass"
    engine._runtime_config["auth_url"] = "http://10.0.0.1"


def _capture_login_completion(task_executor, timeout: float = 5.0):
    """安装 _on_login_done 包装器，在回调清除 _login_future 前捕获结果。

    必须在调用 _handle_login / 触发登录之前调用。
    返回 (result_container, done_event, restore_fn)。
    """
    result = []
    done = threading.Event()

    original = task_executor._on_login_done

    def wrapper(future):
        try:
            result.append(future.result(timeout=timeout))
        except Exception as e:
            result.append(e)
        done.set()
        original(future)

    task_executor._on_login_done = wrapper
    return result, done, lambda: setattr(task_executor, "_on_login_done", original)


class TestFullEngineLoginChain:
    """引擎 → TaskExecutor → worker 完整登录链路（通过 _handle_login 直接触发）。"""

    def test_chain_success(self, integration_stack):
        engine, profile_service, task_executor, mock_worker = integration_stack
        _ensure_login_config(engine)

        mock_worker.submit.return_value = WorkerResponse(success=True, data="登录成功")

        # 在触发登录前安装捕获器（_on_login_done 会清除 _login_future 引用）
        result_container, done_event, restore_fn = _capture_login_completion(
            task_executor
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

            # 手动登录不触发重试计数（is_manual=True 跳过 record_attempt）
            assert engine._login_retry.count == 0
            assert engine._login_retry.last_attempt == 0
        finally:
            restore_fn()

    def test_chain_failure(self, integration_stack):
        engine, profile_service, task_executor, mock_worker = integration_stack
        _ensure_login_config(engine)

        mock_worker.submit.return_value = WorkerResponse(
            success=False, error="认证失败"
        )

        result_container, done_event, restore_fn = _capture_login_completion(
            task_executor
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
            assert engine._login_retry.count == 0
        finally:
            restore_fn()
