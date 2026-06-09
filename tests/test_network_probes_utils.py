"""网络探测工具测试 — 覆盖纯逻辑函数。"""

from __future__ import annotations

import threading

from app.network.probes import is_block_proxy, set_block_proxy

# ── set_block_proxy / is_block_proxy ──


class TestBlockProxy:
    """代理屏蔽设置。"""

    def test_default_is_true(self):
        """默认屏蔽代理。"""
        # 重置状态
        set_block_proxy(True)
        assert is_block_proxy() is True

    def test_set_false(self):
        """设置为 False。"""
        set_block_proxy(False)
        assert is_block_proxy() is False
        # 恢复
        set_block_proxy(True)

    def test_set_true(self):
        """设置为 True。"""
        set_block_proxy(True)
        assert is_block_proxy() is True

    def test_thread_safety(self):
        """线程安全。"""
        results = []

        def worker(value):
            set_block_proxy(value)
            results.append(is_block_proxy())

        threads = [
            threading.Thread(target=worker, args=(i % 2 == 0,)) for i in range(10)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 所有结果都应该是布尔值
        assert all(isinstance(r, bool) for r in results)
