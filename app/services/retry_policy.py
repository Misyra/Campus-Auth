"""重试策略框架 — MonitoredPolicy 用于引擎长期网络监控。

本模块替代了原先的 ``LoginRetryManager``，作为登录编排重构的一部分，
将重试策略从管理器中解耦为独立的策略类。
"""

from __future__ import annotations

import threading
from typing import Iterator


class MonitoredPolicy:
    """监控重试策略 — 固定延迟表，用于引擎长期网络监控。

    Args:
        max_retries: 最大重试次数（默认 5）
    """

    # 固定延迟表：每次登录失败后的等待秒数
    # 索引 = attempt - 1（第 1 次失败 → _DELAYS[0]，第 2 次 → _DELAYS[1]，依此类推）
    _DELAYS: list[float] = [5.0, 10.0, 20.0, 60.0, 100.0]

    def __init__(self, max_retries: int = 5) -> None:
        self.max_retries = max(1, max_retries)
        self._attempt: int = 0
        self._prev_network_ok: bool | None = None
        self._lock = threading.Lock()

    @property
    def retries_exhausted(self) -> bool:
        """是否已用尽重试次数。"""
        return self._attempt >= self.max_retries

    def reset(self) -> None:
        """重置重试计数。"""
        with self._lock:
            self._attempt = 0

    def attempts(self) -> Iterator[int]:
        yield from range(1, self.max_retries + 1)

    def delay_before(self, attempt: int) -> float:
        """返回第 attempt 次登录失败后的延迟（查表）。"""
        idx = min(attempt - 1, len(self._DELAYS) - 1)
        return self._DELAYS[idx]

    def on_network_check(self, need_login: bool) -> bool:
        """网络检测结果回调。仅在 down→up 转换时重置。线程安全。"""
        with self._lock:
            current_ok = not need_login
            transitioned = False
            if self._prev_network_ok is False and current_ok is True:
                self._attempt = 0
                transitioned = True
            self._prev_network_ok = current_ok
            return transitioned

    def on_login_done(self, success: bool) -> float | None:
        """登录完成回调。返回下次重试前的延迟秒数（None=停止重试）。线程安全。"""
        with self._lock:
            if success:
                self._attempt = 0
                return None
            self._attempt += 1
            if self._attempt > self.max_retries:
                return None
            return self.delay_before(self._attempt)
