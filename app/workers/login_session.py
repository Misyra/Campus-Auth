"""登录会话 — 管理浏览器生命周期和单次会话内的重试循环。

职责边界：
- 浏览器生命周期：async with BrowserContextManager 包住整个重试循环
- 重试循环：for attempt in range(max_retries)
- 失败分类决策：根据 AttemptOutcome.should_retry 决定是否重试
- 取消响应：cancel_event.is_set() 与 interruptible_sleep

不负责（交给 LoginAttempt）：
- 具体登录步骤（goto/fill/submit/parse）
- 任务加载与分支（Script/Browser）
- dialog 监听、登录成功等待
"""

from __future__ import annotations

import threading
from typing import Any

from app.utils.browser import BrowserContextManager
from app.utils.concurrent import interruptible_sleep
from app.utils.logging import get_logger
from app.workers.login_attempt import LoginAttempt
from app.workers.login_models import (
    AttemptOutcome,
    AttemptOutcomeType,
    LoginRetryPolicy,
)

logger = get_logger("login_session", source="backend")


class LoginSession:
    """登录会话 — 管理浏览器生命周期和重试循环。"""

    def __init__(
        self,
        config: dict[str, Any],
        cancel_event: threading.Event,
        retry_policy: LoginRetryPolicy | None = None,
    ) -> None:
        """初始化登录会话。

        Args:
            config: Worker 配置字典（由 runtime_config_to_worker_dict 生成）。
            cancel_event: 取消事件，set 后中断会话。
            retry_policy: 会话级重试策略。None 时从 config["retry_settings"] 构造。
        """
        self._config = config
        self._cancel_event = cancel_event
        self._retry_policy = retry_policy or self._build_default_policy(config)
        self._logger = logger

    @staticmethod
    def _build_default_policy(config: dict[str, Any]) -> LoginRetryPolicy:
        """从 worker config dict 的 retry_settings 构造默认策略。"""
        retry_dict = config.get("retry_settings") or {}
        max_retries = int(retry_dict.get("max_retries", 3))
        interval = float(retry_dict.get("retry_interval", 5))
        return LoginRetryPolicy(max_retries=max_retries, interval_seconds=interval)

    async def run(self) -> AttemptOutcome:
        """执行登录会话，含重试循环。

        浏览器生命周期由 async with BrowserContextManager 管理：
        - 进入：创建/复用浏览器（worker.ensure_browser）
        - 退出：关闭浏览器（worker._close_browser）

        所有 return 路径都在 async with 块内，Python 语义保证
        __aexit__ 必执行 → 浏览器在任何终态下都关闭。

        Returns:
            AttemptOutcome：SUCCESS / INVALID_CREDENTIAL / CANCELLED / EXHAUSTED。
            程序异常（TypeError 等）不捕获，向上传播让 Worker 处理。
        """
        async with BrowserContextManager(self._config, self._cancel_event) as browser:
            attempt = LoginAttempt(self._config, self._cancel_event, browser=browser)

            for i in range(self._retry_policy.max_retries):
                # 1. 取消检查
                if self._cancel_event.is_set():
                    return AttemptOutcome(AttemptOutcomeType.CANCELLED, "登录已取消")

                # 2. 执行单次尝试
                self._logger.info(
                    "登录尝试 {}/{}", i + 1, self._retry_policy.max_retries
                )
                outcome = await attempt.execute()

                # 3. 终态（成功/不可重试/取消）直接返回
                if not outcome.should_retry:
                    return outcome

                # 4. 可重试：仅在还有下次尝试时等待
                if i + 1 < self._retry_policy.max_retries:
                    delay = self._retry_policy.next_delay(i)
                    self._logger.info("等待 {:.1f}s 后重试", delay)
                    if not await interruptible_sleep(delay, self._cancel_event):
                        return AttemptOutcome(
                            AttemptOutcomeType.CANCELLED, "登录已取消"
                        )

            # 5. 重试耗尽（仍在 async with 内，return 触发 __aexit__ 关闭浏览器）
            self._logger.warning("重试 {} 次后仍失败", self._retry_policy.max_retries)
            return AttemptOutcome(
                AttemptOutcomeType.EXHAUSTED,
                f"重试 {self._retry_policy.max_retries} 次后仍失败",
            )
