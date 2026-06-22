"""CompositeCancelEvent — 组合多个取消事件的惰性扫描实现。"""

from __future__ import annotations

import threading


class CompositeCancelEvent(threading.Event):
    """组合多个 cancel_event：任一源被 set，则 is_set() 返回 True。

    继承 threading.Event，is_set() 被覆盖为惰性扫描模式。
    消费者无需感知组合机制——仍调用 event.is_set()。

    用于 LoginOrchestrator 的 cancel 联动：当去重复用旧 handle 时，
    将新调用方的 cancel_event 添加为源，实现"任一取消 → 整体取消"。
    """

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

    def clear(self) -> None:
        """重置（仅清除自身标志，保留源列表）。"""
        super().clear()

    def clear_sources(self) -> None:
        """清除所有源（用于 handle 销毁时释放引用）。"""
        with self._lock:
            self._sources.clear()
