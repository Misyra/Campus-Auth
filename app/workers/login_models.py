"""登录会话数据模型 — AttemptOutcome / LoginRetryPolicy。

与 app/schemas.py::LoginResult(StrEnum) 区分：
- LoginResult：进程级登录退出码（SUCCESS / TEMPORARY_FAILURE / CONFIG_ERROR）
- AttemptOutcome：单次登录尝试结果（含重试分类与终态）
- LoginRetryPolicy：单次会话内的重试策略
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.schemas import RetrySettings


class AttemptOutcomeType(StrEnum):
    """单次登录尝试的结果分类。"""

    SUCCESS = "success"  # 登录成功
    RETRYABLE = "retryable"  # 网络/临时错误，可重试
    INVALID_CREDENTIAL = "invalid"  # 账号密码错误，不可重试
    CANCELLED = "cancelled"  # 用户取消
    EXHAUSTED = "exhausted"  # 重试次数耗尽（终态，不应再重试）


@dataclass(frozen=True, slots=True)
class AttemptOutcome:
    """单次登录尝试的结果。

    frozen=True 保证结果在传递过程中不被篡改；
    slots=True 减少内存开销并阻止动态属性新增。
    """

    type: AttemptOutcomeType
    message: str = ""

    @property
    def should_retry(self) -> bool:
        """是否应该重试。

        EXHAUSTED / CANCELLED / SUCCESS / INVALID_CREDENTIAL 均为终态，
        只有 RETRYABLE 返回 True。
        """
        return self.type == AttemptOutcomeType.RETRYABLE


@dataclass
class LoginRetryPolicy:
    """单次登录会话内的重试策略。

    固定间隔重试，无状态机。
    边界约束与 login_runner 既有约束一致：max_retries ∈ [1, 10]。
    """

    max_retries: int
    interval_seconds: float

    def __post_init__(self) -> None:
        # 与 login_runner 既有约束保持一致：[1, 10]
        self.max_retries = max(1, min(self.max_retries, 10))
        self.interval_seconds = max(1.0, float(self.interval_seconds))

    @classmethod
    def from_runtime_config(cls, retry_settings: RetrySettings) -> LoginRetryPolicy:
        """从 RuntimeConfig.retry 构造。单一来源。

        RetrySettings.max_retries 允许 0（Field ge=0），但 LoginRetryPolicy
        至少 1 次尝试，__post_init__ 会裁剪。
        """
        return cls(
            max_retries=retry_settings.max_retries,
            interval_seconds=float(retry_settings.retry_interval),
        )

    def next_delay(self, attempt_index: int) -> float | None:
        """返回第 attempt_index 次重试前的延迟（秒），None 表示不再重试。

        attempt_index 从 0 开始（第 0 次重试 = 第 1 次失败后）。
        """
        if attempt_index >= self.max_retries:
            return None
        return self.interval_seconds
