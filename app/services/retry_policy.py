"""重试策略框架 — 定义重试行为的抽象基类与具体策略。"""

from __future__ import annotations

import math
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

    def __init__(self, max_retries: int = 3, interval: int = 5) -> None:
        self.max_retries = max(1, min(max_retries, 10))
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
    """监控重试策略 — 用于引擎长期网络监控，自带退避管理。

    关键行为：仅在网络从断开恢复到连通时重置退避状态，
    而非每次网络检测都重置。

    Args:
        max_retries: 最大重试次数
        interval: 基础重试间隔秒数
        backoff_after_cycles: 经过多少个循环周期后开始指数退避
    """

    # 退避上限：30 分钟
    _MAX_BACKOFF: float = 1800.0

    def __init__(
        self,
        max_retries: int = 10,
        interval: int = 30,
        backoff_after_cycles: int = 3,
    ) -> None:
        self.max_retries = max(1, max_retries)
        self.interval = max(1, interval)
        self.backoff_after_cycles = max(1, backoff_after_cycles)

        # 内部状态
        self._attempt: int = 0
        self._prev_network_ok: bool | None = None  # None = 未知
        self._consecutive_failures: int = 0

    # -- 公开 API -------------------------------------------------------

    def attempts(self) -> Iterator[int]:
        """产生 1..max_retries 的重试序号。"""
        yield from range(1, self.max_retries + 1)

    def delay_before(self, attempt: int) -> float:
        """返回第 attempt 次重试前的延迟。

        在 backoff_after_cycles 之前返回固定 interval；
        之后按指数退避计算，上限 1800 秒。
        """
        if attempt <= 1:
            return 0.0
        if attempt <= self.backoff_after_cycles:
            return float(self.interval)
        exponent = attempt - self.backoff_after_cycles
        delay = self.interval * math.pow(2, exponent)
        return min(delay, self._MAX_BACKOFF)

    def on_network_check(self, need_login: bool) -> bool:
        """处理一次网络检测结果。

        仅在网络从 "需要登录"（断开）恢复到 "不需要登录"（连通）时
        重置退避状态。

        Args:
            need_login: True 表示当前网络断开/需要认证

        Returns:
            True 表示检测到 down->up 恢复转换（调用方可据此重置重试计数）
        """
        current_ok = not need_login
        transitioned = False

        if self._prev_network_ok is False and current_ok is True:
            # down -> up 转换：重置退避状态
            self._consecutive_failures = 0
            self._attempt = 0
            transitioned = True
        elif need_login:
            self._consecutive_failures += 1

        self._prev_network_ok = current_ok
        return transitioned

    def on_login_done(self, success: bool) -> float | None:
        """处理登录完成事件。

        Args:
            success: 登录是否成功

        Returns:
            成功时返回 0.0，失败时返回下次重试的延迟秒数，
            超过 max_retries 时返回 None
        """
        if success:
            self._attempt = 0
            self._consecutive_failures = 0
            return 0.0

        self._attempt += 1
        if self._attempt >= self.max_retries:
            return None
        return self.delay_before(self._attempt)
