"""登录会话数据模型 — AttemptOutcome 系列。

与 app/schemas.py::LoginResult(StrEnum) 区分：
- LoginResult：进程级登录退出码（SUCCESS / TEMPORARY_FAILURE / CONFIG_ERROR）
- AttemptOutcome：单次登录尝试结果（含重试分类与终态）
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class AttemptOutcomeType(StrEnum):
    """单次登录尝试的结果分类。"""

    SUCCESS = "success"              # 登录成功
    RETRYABLE = "retryable"          # 网络/临时错误，可重试
    INVALID_CREDENTIAL = "invalid"   # 账号密码错误，不可重试
    CANCELLED = "cancelled"          # 用户取消
    EXHAUSTED = "exhausted"          # 重试次数耗尽（终态，不应再重试）


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
