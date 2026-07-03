"""CompositeCancelEvent 测试。"""

from __future__ import annotations

import threading
import time

import pytest

from app.utils.cancel_token import CompositeCancelEvent


class TestCompositeCancelEvent:
    """CompositeCancelEvent 单元测试。"""

    def test_initial_state_not_set(self) -> None:
        """新建的 CompositeCancelEvent 应处于未 set 状态。"""
        cce = CompositeCancelEvent()
        assert not cce.is_set()

    def test_set_directly(self) -> None:
        """直接 set() 后 is_set() 应返回 True。"""
        cce = CompositeCancelEvent()
        cce.set()
        assert cce.is_set()

    def test_add_source_already_set_immediate_propagation(self) -> None:
        """添加已 set 的源，应立即将自身 set。"""
        cce = CompositeCancelEvent()
        source = threading.Event()
        source.set()

        cce.add_source(source)

        assert cce.is_set()

    def test_add_source_then_set_later(self) -> None:
        """添加未 set 的源，源 set 后 is_set() 应通过惰性扫描返回 True。"""
        cce = CompositeCancelEvent()
        source = threading.Event()

        cce.add_source(source)
        assert not cce.is_set()

        source.set()

        assert cce.is_set()

    def test_multiple_sources_any_set_triggers(self) -> None:
        """多个源中任意一个 set 即触发。"""
        cce = CompositeCancelEvent()
        src1 = threading.Event()
        src2 = threading.Event()
        src3 = threading.Event()

        cce.add_source(src1)
        cce.add_source(src2)
        cce.add_source(src3)

        assert not cce.is_set()

        src2.set()

        assert cce.is_set()

    def test_add_source_dedup(self) -> None:
        """同一源重复添加不应导致列表膨胀。"""
        cce = CompositeCancelEvent()
        source = threading.Event()

        cce.add_source(source)
        cce.add_source(source)
        cce.add_source(source)

        assert len(cce._sources) == 1

    def test_clear_resets_self_and_sources(self) -> None:
        """clear() 清除自身标志并复位所有源事件。"""
        cce = CompositeCancelEvent()
        source = threading.Event()
        source.set()

        cce.add_source(source)
        assert cce.is_set()

        # clear 同时复位自身和源
        cce.clear()
        assert not cce.is_set()
        # 源列表仍保留（仅复位，不清除引用）
        assert len(cce._sources) == 1
        assert not source.is_set()

    def test_is_set_caches_result(self) -> None:
        """is_set() 发现源 set 后会缓存结果（后续不再扫描）。"""
        cce = CompositeCancelEvent()
        source = threading.Event()
        source.set()

        cce.add_source(source)

        # 第一次调用触发惰性扫描，super().set() 被调用
        assert cce.is_set()

        # 移除源列表后，is_set() 仍应返回 True（已被缓存）
        with cce._lock:
            cce._sources.clear()
        assert cce.is_set()

    def test_thread_safety_concurrent_add_and_is_set(self) -> None:
        """并发 add_source + is_set 不应抛异常。"""
        cce = CompositeCancelEvent()
        errors: list[Exception] = []

        def add_sources() -> None:
            try:
                for i in range(100):
                    evt = threading.Event()
                    cce.add_source(evt)
                    if i % 2 == 0:
                        evt.set()
            except Exception as e:
                errors.append(e)

        def check_is_set() -> None:
            try:
                for _ in range(100):
                    cce.is_set()
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=add_sources),
            threading.Thread(target=check_is_set),
            threading.Thread(target=add_sources),
            threading.Thread(target=check_is_set),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert not errors, f"并发执行出错: {errors}"
        assert cce.is_set()  # 有偶数 i 的源被 set 了

    def test_clear_then_source_set_propagates_again(self) -> None:
        """clear() 后，新 set 的源仍可重新传播。"""
        cce = CompositeCancelEvent()
        src1 = threading.Event()
        src2 = threading.Event()

        cce.add_source(src1)
        src1.set()
        assert cce.is_set()

        # 也 clear 源，使惰性扫描不会立即命中
        src1.clear()
        cce.clear()
        assert not cce.is_set()

        # 新源 set 应能再次传播
        cce.add_source(src2)
        src2.set()
        assert cce.is_set()

    def test_clear_resets_all_sources(self) -> None:
        """clear() 应同时复位自身标志和所有源事件。"""
        cce = CompositeCancelEvent()
        src = threading.Event()
        cce.add_source(src)
        src.set()
        assert cce.is_set()
        cce.clear()
        assert not cce.is_set()

    def test_no_sources_is_set_false(self) -> None:
        """无任何源时，clear 后 is_set() 应为 False。"""
        cce = CompositeCancelEvent()
        cce.set()
        cce.clear()
        assert not cce.is_set()

    def test_no_deadlock_wait_concurrent_with_is_set(self) -> None:
        """wait() 和 is_set() 并发调用不应死锁。

        死锁场景：is_set() 持有 _lock → 调用 super().set() 获取 _cond；
        wait() 持有 _cond → 调用 is_set() 获取 _lock。
        修复后 super().set() 在锁外调用，锁顺序不再颠倒。
        """
        cce = CompositeCancelEvent()
        source = threading.Event()
        cce.add_source(source)
        # 先 set 源，使 wait() 能立即返回，避免阻塞干扰死锁检测
        source.set()
        errors: list[Exception] = []

        def run_wait() -> None:
            try:
                for _ in range(100):
                    cce.wait(timeout=0.5)
            except Exception as e:
                errors.append(e)

        def run_is_set() -> None:
            try:
                for _ in range(100):
                    cce.is_set()
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=run_wait),
            threading.Thread(target=run_is_set),
            threading.Thread(target=run_wait),
            threading.Thread(target=run_is_set),
        ]

        for t in threads:
            t.start()
        # 超时 10 秒即判定死锁
        for t in threads:
            t.join(timeout=10)
            if t.is_alive():
                pytest.fail("死锁检测：线程未在 10 秒内完成，疑似死锁")

        assert not errors, f"并发执行出错: {errors}"
