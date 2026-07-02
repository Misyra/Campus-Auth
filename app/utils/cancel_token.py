"""CompositeCancelEvent — 组合多个取消事件的惰性扫描实现。"""

from __future__ import annotations

import threading
import time


class CompositeCancelEvent(threading.Event):
    """组合多个 cancel_event：任一源被 set，则 is_set() 返回 True。

    继承 threading.Event，is_set() 和 wait() 均被覆盖为惰性扫描模式。
    消费者无需感知组合机制——仍调用 event.is_set() / event.wait()。

    用于 LoginOrchestrator 的 cancel 联动：当去重复用旧 handle 时，
    将新调用方的 cancel_event 添加为源，实现"任一取消 → 整体取消"。
    """

    # 扫描间隔（秒），wait() 轮询源事件的频率
    _POLL_INTERVAL = 0.1

    def __init__(self) -> None:
        super().__init__()
        self._sources: list[threading.Event] = []
        self._lock = threading.Lock()

    def add_source(self, event: threading.Event) -> None:
        """添加一个取消源。若该源已 set，立即 set 自身。"""
        with self._lock:
            if event not in self._sources:
                self._sources.append(event)
                if event.is_set():
                    super().set()

    def is_set(self) -> bool:
        """惰性扫描：每次调用时检查所有源。"""
        if super().is_set():
            return True
        with self._lock:
            for src in self._sources:
                if src.is_set():
                    super().set()
                    return True
        return False

    def wait(self, timeout: float | None = None) -> bool:
        """等待任一源事件被 set 或超时。

        覆写父类 wait()，使其感知源事件。
        父类 wait() 直接读 _flag，不调用 is_set()，无法感知源事件。
        """
        if self.is_set():
            return True
        if timeout is None:
            # 无限等待：定期轮询源事件
            while not self.is_set():
                super().wait(self._POLL_INTERVAL)
            return True
        else:
            # 带超时：定期轮询直到超时
            end_time = time.monotonic() + timeout
            while not self.is_set():
                remaining = end_time - time.monotonic()
                if remaining <= 0:
                    return False
                super().wait(min(self._POLL_INTERVAL, remaining))
            return True

    def clear(self) -> None:
        """重置自身标志并清除所有源。"""
        super().clear()
        with self._lock:
            for src in self._sources:
                src.clear()

    def clear_sources(self) -> None:
        """清除所有源（用于 handle 销毁时释放引用）。"""
        with self._lock:
            self._sources.clear()
