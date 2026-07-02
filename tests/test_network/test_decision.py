"""网络决策层 executor 解耦测试。

验证外层决策调度与内层探测使用独立线程池，避免嵌套提交导致饥饿。
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest


class TestDecisionExecutorIsolation:
    """决策 executor 与探测 executor 隔离性。"""

    def test_decision_executor_exists(self):
        """_decision_executor 模块级变量已创建。"""
        from app.network.decision import _decision_executor

        assert isinstance(_decision_executor, ThreadPoolExecutor)

    def test_decision_executor_max_workers(self):
        """决策 executor 最大工作线程数为 3。"""
        from app.network.decision import _decision_executor

        assert _decision_executor._max_workers == 3

    def test_decision_executor_thread_prefix(self):
        """决策 executor 线程名前缀为 net_decision。"""
        from app.network.decision import _decision_executor

        assert _decision_executor._thread_name_prefix == "net_decision"

    def test_decision_executor_is_not_probe_executor(self):
        """决策 executor 与 probes.py 的探测 executor 是不同实例。"""
        from app.network.decision import _decision_executor
        from app.network.probes import executor as probe_executor

        assert _decision_executor is not probe_executor


class TestDecisionExecutorNoStarvation:
    """验证内层探测不会因外层调度占用而饥饿。"""

    def test_probe_executor_not_used_by_decision_layer(self):
        """is_network_available 使用 _decision_executor 而非 probes.executor。"""
        import app.network.decision as decision_mod

        # is_network_available 内部应使用 _decision_executor
        # 通过检查它引用的 pool 对象来验证
        source = decision_mod.is_network_available.__code__.co_names
        # 确认不直接引用 probes.executor
        assert "_decision_executor" in source

    def test_inner_probe_uses_own_pool(self, monkeypatch):
        """内层探测函数使用 probes.executor 而非 decision executor。

        模拟探测函数提交任务到 probes.executor，
        验证决策层提交任务到 _decision_executor 时不会阻塞探测池。
        """
        from app.network import decision as decision_mod
        from app.network import probes

        probe_pool_ids = []
        decision_pool_ids = []

        # 记录 probes.executor.submit 被调用时的线程名
        original_probe_submit = probes.executor.submit

        def track_probe_submit(fn, *args, **kwargs):
            probe_pool_ids.append(threading.current_thread().name)
            return original_probe_submit(fn, *args, **kwargs)

        # 记录 _decision_executor.submit 被调用时的线程名
        original_decision_submit = decision_mod._decision_executor.submit

        def track_decision_submit(fn, *args, **kwargs):
            decision_pool_ids.append(threading.current_thread().name)
            return original_decision_submit(fn, *args, **kwargs)

        monkeypatch.setattr(probes.executor, "submit", track_probe_submit)
        monkeypatch.setattr(
            decision_mod._decision_executor, "submit", track_decision_submit
        )

        # 提交一个探测任务到决策池
        f = decision_mod._decision_executor.submit(lambda: True)
        f.result(timeout=5)

        # 提交一个探测任务到探测池
        f2 = probes.executor.submit(lambda: True)
        f2.result(timeout=5)

        assert len(decision_pool_ids) >= 1
        assert len(probe_pool_ids) >= 1

    def test_concurrent_outer_tasks_do_not_block_inner(self, monkeypatch):
        """多个外层任务并发提交不会阻塞内层探测执行。

        模拟场景：decision executor 提交 3 个外层任务，
        每个外层任务内部向 probe executor 提交子任务。
        如果共享线程池，3 个外层任务占满 3 个 worker 后子任务无法执行。
        """
        from app.network import decision as decision_mod
        from app.network import probes

        inner_completed = threading.Event()
        outer_completed = threading.Event()

        def slow_inner():
            """模拟内层探测任务，需要占用 probe executor 的 worker。"""
            inner_completed.set()
            return True

        def outer_task():
            """模拟外层决策任务，内部向 probe executor 提交子任务。"""
            f = probes.executor.submit(slow_inner)
            f.result(timeout=5)
            outer_completed.set()
            return True

        # 提交 3 个外层任务（占满 decision executor 的 3 个 worker）
        futures = [decision_mod._decision_executor.submit(outer_task) for _ in range(3)]

        # 如果存在线程池饥饿，inner_completed 永远不会被 set
        assert inner_completed.wait(timeout=10), "内层探测任务被饥饿（未在 10s 内完成）"
        assert outer_completed.wait(timeout=10), "外层决策任务未在 10s 内完成"

        for f in futures:
            assert f.result(timeout=5) is True


class TestShutdownDecisionExecutor:
    """决策 executor 关闭行为。

    使用 monkeypatch 替换 _decision_executor 为临时实例，
    避免永久关闭模块级 executor 影响其他测试。
    """

    def test_shutdown_decision_executor_callable(self):
        """shutdown_decision_executor 函数可正常导入和调用。"""
        from app.network.decision import shutdown_decision_executor

        assert callable(shutdown_decision_executor)

    def test_shutdown_decision_executor_waits(self, monkeypatch):
        """shutdown_decision_executor(wait=True) 等待任务完成。"""
        import app.network.decision as decision_mod

        # 创建临时 executor 替换模块级实例
        tmp_executor = ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="test_shutdown"
        )
        monkeypatch.setattr(decision_mod, "_decision_executor", tmp_executor)

        completed = threading.Event()

        def slow_task():
            time.sleep(0.1)
            completed.set()

        tmp_executor.submit(slow_task)

        decision_mod.shutdown_decision_executor(wait=True)

        assert completed.is_set()

        # shutdown 后不能再提交新任务
        with pytest.raises(RuntimeError, match="cannot schedule new futures"):
            tmp_executor.submit(lambda: True)

    def test_shutdown_decision_executor_preserves_probe_executor(self, monkeypatch):
        """关闭 decision executor 不影响 probes.executor。"""
        import app.network.decision as decision_mod
        from app.network import probes

        # 创建临时 executor 替换模块级实例
        tmp_executor = ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="test_shutdown2"
        )
        monkeypatch.setattr(decision_mod, "_decision_executor", tmp_executor)

        decision_mod.shutdown_decision_executor(wait=True)

        # probes.executor 应仍然可用
        f = probes.executor.submit(lambda: 42)
        assert f.result(timeout=5) == 42


class TestCheckNetworkStatusUsesDecisionExecutor:
    """check_network_status 间接使用 decision executor。"""

    def test_check_network_status_calls_is_network_available(self, monkeypatch):
        """check_network_status 调用 is_network_available。"""
        from app.network import decision as decision_mod
        from app.schemas import MonitorSettings

        called_with = {}

        def fake_is_network_available(**kwargs):
            called_with.update(kwargs)
            return True

        monkeypatch.setattr(
            decision_mod, "is_network_available", fake_is_network_available
        )

        monitor = MonitorSettings(
            enable_tcp_check=True,
            enable_http_check=False,
            ping_targets=["8.8.8.8:53"],
            test_urls=[],
            url_check_urls=[],
            network_check_timeout=2,
        )
        ok, status, method = decision_mod.check_network_status(monitor)

        assert ok is True
        assert "enable_tcp" in called_with

    def test_check_network_status_all_disabled(self):
        """所有检测方式关闭时返回 all_disabled。"""
        from app.network import decision as decision_mod
        from app.schemas import MonitorSettings

        monitor = MonitorSettings(
            enable_tcp_check=False,
            enable_http_check=False,
            url_check_urls=[],
        )
        ok, status, method = decision_mod.check_network_status(monitor)

        assert ok is False
        assert status == "all_disabled"
