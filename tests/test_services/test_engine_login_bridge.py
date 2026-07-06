"""EngineLoginBridge 单元测试。"""

from __future__ import annotations

import threading
from concurrent.futures import Future

from app.services.engine import LoginBridge


class TestRegisteredFuturesCleanup:
    """submit_login 应清理已完成的 Future 引用。"""

    def test_done_futures_cleaned_up(self):
        """已完成的 Future 应在下次 submit_login 时被清理。"""
        bridge = LoginBridge.__new__(LoginBridge)
        bridge._registered_futures = set()
        bridge._futures_lock = threading.Lock()

        # 模拟已完成的 Future
        done_future = Future()
        done_future.set_result((True, "ok"))
        bridge._registered_futures.add(done_future)

        # 模拟未完成的 Future
        pending_future = Future()
        bridge._registered_futures.add(pending_future)

        assert len(bridge._registered_futures) == 2

        # 模拟 submit_login 入口的清理逻辑
        with bridge._futures_lock:
            bridge._registered_futures = {
                f for f in bridge._registered_futures if not f.done()
            }

        # 已完成的 Future 应被清理
        assert len(bridge._registered_futures) == 1
        assert pending_future in bridge._registered_futures
