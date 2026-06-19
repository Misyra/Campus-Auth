"""登录重试状态机 — 管理重试计数、间隔和决策。"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.utils.logging import get_logger

logger = get_logger("login_retry", source="backend")


@dataclass
class LoginRetryManager:
    """登录重试状态管理器。

    职责：
    - 记录登录成功/失败
    - 判断是否需要重试
    - 计算下次重试延迟

    不负责：
    - 实际执行登录（由 Engine/TaskExecutor 负责）
    - 并发控制（由 TaskExecutor 负责）
    """

    count: int = 0
    last_attempt: float = 0.0
    config: tuple[int, list[int]] | None = None  # (max_retries, intervals)

    def reset(self) -> None:
        """重置重试状态。"""
        self.count = 0
        self.last_attempt = 0.0
        self.config = None

    def configure(self, max_retries: int, intervals: list[int]) -> None:
        """设置重试配置。"""
        self.config = (max_retries, intervals)

    def record_attempt(self, now: float) -> None:
        """记录一次登录尝试。"""
        self.last_attempt = now
        self.count += 1

    def need_retry(self, now: float) -> bool:
        """判断是否需要重试。

        Args:
            now: 当前时间戳

        Returns:
            True 表示应该执行下次重试
        """
        if self.count == 0 or not self.config:
            return False
        max_retries, intervals = self.config
        if self.count >= max_retries:
            return False
        idx = self.count - 1
        if idx >= len(intervals):
            return False
        return now >= self.last_attempt + intervals[idx]

    def next_wakeup(self) -> float | None:
        """返回下次重试的唤醒时间，无重试时返回 None。"""
        if self.count == 0 or not self.config:
            return None
        _, intervals = self.config
        idx = self.count - 1
        if idx >= len(intervals):
            return None
        return self.last_attempt + intervals[idx]
