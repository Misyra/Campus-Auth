"""debug_session 线程安全测试 — 验证 _next_debug_gen 使用锁保护。"""

from __future__ import annotations

import inspect
import threading

from app.services.debug_session import _next_debug_gen


class TestNextDebugGenThreadSafety:
    """_next_debug_gen 线程安全。"""

    def test_function_uses_lock(self):
        """_next_debug_gen 应使用 threading.Lock 保护全局状态。"""
        source = inspect.getsource(_next_debug_gen)
        assert "lock" in source.lower(), (
            "_next_debug_gen 未使用锁保护，请添加 threading.Lock"
        )

    def test_concurrent_calls_return_unique_values(self):
        """多线程并发调用 _next_debug_gen 应返回不重复的值。"""
        results: list[int] = []
        errors: list[Exception] = []
        num_threads = 20
        calls_per_thread = 50

        barrier = threading.Barrier(num_threads)

        def worker():
            try:
                barrier.wait()
                for _ in range(calls_per_thread):
                    val = _next_debug_gen()
                    results.append(val)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"并发调用产生异常: {errors}"
        expected_count = num_threads * calls_per_thread
        assert len(results) == expected_count
        assert len(set(results)) == expected_count, (
            f"存在重复值，说明线程不安全: "
            f"总数={expected_count}, 去重后={len(set(results))}"
        )

    def test_values_are_strictly_consecutive(self):
        """并发返回值应严格连续无间隔。"""
        results: list[int] = []
        lock = threading.Lock()
        num_threads = 10
        calls_per_thread = 20

        barrier = threading.Barrier(num_threads)

        def worker():
            barrier.wait()
            for _ in range(calls_per_thread):
                val = _next_debug_gen()
                with lock:
                    results.append(val)

        threads = [threading.Thread(target=worker) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == num_threads * calls_per_thread
        sorted_values = sorted(results)
        for i in range(1, len(sorted_values)):
            assert sorted_values[i] == sorted_values[i - 1] + 1, (
                f"值不连续: {sorted_values[i-1]} -> {sorted_values[i]}"
            )
