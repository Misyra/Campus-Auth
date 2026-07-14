"""BrowserTaskService 测试 — 通用浏览器自动化服务。"""

import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from unittest.mock import MagicMock

import pytest

from app.services.browser_task_service import (
    BrowserTaskHandle,
    BrowserTaskService,
)


def _make_mock_executor():
    """创建使用真实线程池的 mock executor，用于测试。

    使用后台线程执行任务，确保 submit 返回时任务仍在运行（与真实 executor 行为一致）。
    """
    real_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="test-bt")
    mock = MagicMock()
    mock.submit.side_effect = real_pool.submit
    mock.shutdown.side_effect = real_pool.shutdown
    return mock


def _make_mock_worker():
    """创建立即返回成功的 mock worker。"""
    worker = MagicMock()
    result = MagicMock()
    result.success = True
    result.data = "浏览器任务执行成功"
    result.error = None
    worker.submit.return_value = result
    return worker


def _make_slow_worker(delay: float = 0.1):
    """创建延迟返回的 mock worker，避免 done_callback 死锁。"""
    worker = MagicMock()
    result = MagicMock()
    result.success = True
    result.data = "浏览器任务执行成功"
    result.error = None

    def slow_submit(*args, **kwargs):
        time.sleep(delay)
        return result

    worker.submit.side_effect = slow_submit
    return worker


@pytest.fixture
def service():
    """创建使用慢速 worker 的服务，避免 done_callback 死锁。"""
    worker = _make_slow_worker()
    return BrowserTaskService(
        worker_getter=lambda: worker,
        executor=_make_mock_executor(),
    )


# ── 基础 ──


def test_browser_task_service_can_be_instantiated():
    """BrowserTaskService 可用 worker_getter + executor 构造。"""
    svc = BrowserTaskService(
        worker_getter=MagicMock(),
        executor=MagicMock(),
    )
    assert svc is not None


def test_submit_task_returns_handle():
    """submit_task 返回 BrowserTaskHandle，rejected_reason 为 None。"""
    svc = BrowserTaskService(
        worker_getter=lambda: _make_mock_worker(),
        executor=_make_mock_executor(),
    )
    handle = svc.submit_task(
        task_config={"active_task": "test_task"}, cancel_event=None
    )
    assert isinstance(handle, BrowserTaskHandle)
    assert handle.rejected_reason is None
    handle.result(timeout=5)


# ── submit_task ──


class TestSubmitTask:
    def test_submit_task_runs_and_completes(self, service):
        """submit_task 后 is_running() 为 True，future 完成后 is_running() 为 False。"""
        handle = service.submit_task(task_config={"active_task": "test"})
        # 慢速 worker (0.1s) 应使 is_running 为 True
        assert service.is_running() is True
        # 等待完成
        handle.result(timeout=5)
        # 等待 done_callback 清理 slot
        time.sleep(0.05)
        assert service.is_running() is False

    def test_concurrent_submit_deduplicates(self, service):
        """并发 submit_task 同一任务时命中去重，返回同一 handle。"""
        call_count = [0]
        dispatch_barrier = threading.Barrier(2, timeout=5)
        slow_future = Future()

        def slow_dispatch(task_config, cancel_event, timeout=None):
            call_count[0] += 1
            # 同步：确保两个线程都已就绪
            dispatch_barrier.wait()
            time.sleep(0.15)
            return BrowserTaskHandle(
                future=slow_future,
                cancel_event=cancel_event,
            )

        service._dispatch = slow_dispatch

        results = []

        def first_submit():
            results.append(service.submit_task(task_config={"active_task": "t"}))

        def second_submit():
            dispatch_barrier.wait()
            time.sleep(0.02)
            results.append(service.submit_task(task_config={"active_task": "t"}))

        t1 = threading.Thread(target=first_submit)
        t2 = threading.Thread(target=second_submit)
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)

        assert len(results) == 2
        # 第二个 submit 应复用第一个的 handle（去重）
        assert results[0] is results[1]
        # _dispatch 只应被调用一次
        assert call_count[0] == 1

    def test_cancel_running_triggers_cancel_event(self, service):
        """cancel_running() 后 cancel_event.is_set() 为 True。"""
        handle = service.submit_task(task_config={"active_task": "test"})
        service.cancel_running()
        assert handle.cancel_event.is_set()
        handle.result(timeout=5)

    def test_rejected_when_executor_full(self):
        """executor 满时返回 rejected_reason 非 None 的 handle。"""
        mock_executor = MagicMock()
        mock_executor.submit.side_effect = RuntimeError("queue full")

        svc = BrowserTaskService(
            worker_getter=lambda: _make_mock_worker(),
            executor=mock_executor,
        )
        handle = svc.submit_task(task_config={"active_task": "test"})
        assert handle.rejected_reason is not None
        assert handle.future is None

    def test_result_on_rejected_handle(self):
        """rejected handle 的 result() 返回 (False, rejected_reason)。"""
        handle = BrowserTaskHandle(
            future=None,
            cancel_event=threading.Event(),
            rejected_reason="任务队列已满，请稍后重试",
        )
        success, msg = handle.result()
        assert success is False
        assert msg == "任务队列已满，请稍后重试"


# ── dispatch 异常清理 ──


class TestDispatchException:
    def test_dispatch_exception_clears_sentinel(self):
        """如果 _dispatch 抛异常，slot 应被清除，不卡在 dispatching 占位状态。"""
        svc = BrowserTaskService(
            worker_getter=lambda: _make_mock_worker(),
            executor=_make_mock_executor(),
        )
        svc._dispatch = MagicMock(side_effect=RuntimeError("pool full"))

        with pytest.raises(RuntimeError):
            svc.submit_task(task_config={"active_task": "test"})

        # slot 应为 None（不再是 dispatching 占位状态）
        assert svc._slot is None


# ── bind_proxy 注入 ──


def test_bind_proxy_injected_into_task_config():
    """set_bind_proxy 设置后，submit_task 应将 bind_proxy 注入 task_config。

    场景：启用网卡绑定代理的用户，定时浏览器任务需走绑定 NIC，而非默认路由。
    与 LoginOrchestrator._dispatch 调用 runtime_config_to_worker_dict(config, bind_proxy=...) 对齐。
    """
    captured: dict = {}

    def fake_dispatch(task_config, cancel_event, timeout=None):
        captured["task_config"] = task_config
        return BrowserTaskHandle(
            future=None,
            cancel_event=cancel_event,
            rejected_reason="__test__",
        )

    svc = BrowserTaskService(
        worker_getter=lambda: _make_mock_worker(),
        executor=_make_mock_executor(),
    )
    svc._dispatch = fake_dispatch
    svc.set_bind_proxy("http://192.168.1.10:8080")

    original_config = {"active_task": "checkin", "browser_settings": {"headless": True}}
    svc.submit_task(task_config=original_config)

    # 验证 bind_proxy 已注入 browser_settings
    bs = captured["task_config"]["browser_settings"]
    assert bs["bind_proxy"] == "http://192.168.1.10:8080"
    # 原有字段保留
    assert bs["headless"] is True
    # 调用方原 dict 不应被修改（不可变注入）
    assert "bind_proxy" not in original_config["browser_settings"]
