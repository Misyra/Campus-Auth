"""重试策略框架 — 定义重试行为的抽象基类与具体策略。

本模块替代了原先的 ``LoginRetryManager``，作为登录编排重构的一部分，
将重试策略从管理器中解耦为独立的策略类。
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from typing import Iterator


class RetryPolicy(ABC):
    """重试策略抽象基类。"""

    @abstractmethod
    def attempts(self) -> Iterator[int]:
        """产生重试序号（从 1 开始）。"""
        ...

    @abstractmethod
    def delay_before(self, attempt: int) -> float:
        """返回第 attempt 次重试前应等待的秒数。"""
        ...


class ImmediatePolicy(RetryPolicy):
    """立即重试策略 — 固定间隔，无指数退避。

    用于 login_once 路径的快速重试。

    Args:
        max_retries: 最大重试次数，限制在 1-10 范围内，默认 3
        interval: 重试间隔秒数，最小值为 1，默认 5
    """

    # max_retries 的上限
    _MAX_RETRIES: int = 10

    def __init__(self, max_retries: int = 3, interval: int = 5) -> None:
        self.max_retries = max(1, min(max_retries, self._MAX_RETRIES))
        self.interval = max(1, interval)

    def attempts(self) -> Iterator[int]:
        """产生 1..max_retries 的重试序号。"""
        yield from range(1, self.max_retries + 1)

    def delay_before(self, attempt: int) -> float:
        """第一次重试无延迟，后续返回固定间隔。"""
        if attempt <= 1:
            return 0.0
        return float(self.interval)


class MonitoredPolicy(RetryPolicy):
    """监控重试策略 — 固定延迟表，用于引擎长期网络监控。

    Args:
        max_retries: 最大重试次数（默认 5）
    """

    # 固定延迟表：attempt → delay_seconds
    _DELAYS: list[float] = [0.0, 0.0, 30.0, 60.0, 120.0]

    def __init__(self, max_retries: int = 5) -> None:
        self.max_retries = max(1, max_retries)
        self._attempt: int = 0
        self._prev_network_ok: bool | None = None
        self._lock = threading.Lock()

    @property
    def retries_exhausted(self) -> bool:
        """是否已用尽重试次数。"""
        return self._attempt >= self.max_retries

    def attempts(self) -> Iterator[int]:
        yield from range(1, self.max_retries + 1)

    def delay_before(self, attempt: int) -> float:
        """返回第 attempt 次重试前的延迟（查表）。"""
        if attempt <= 1:
            return 0.0
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
        """登录完成回调。返回下次检测前的延迟秒数（None=停止）。线程安全。"""
        with self._lock:
            if success:
                self._attempt = 0
                return None
            self._attempt += 1
            if self._attempt >= self.max_retries:
                return None
            return self.delay_before(self._attempt)
