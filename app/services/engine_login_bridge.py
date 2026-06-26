"""LoginBridge — 登录提交委托，从 ScheduleEngine 提取。"""

from __future__ import annotations

import threading
import time
from concurrent.futures import CancelledError, Future
from typing import TYPE_CHECKING, Callable

from app.schemas import RuntimeConfig
from app.utils.logging import get_logger

if TYPE_CHECKING:
    from app.services.login_orchestrator import LoginOrchestrator
    from app.services.retry_policy import MonitoredPolicy

logger = get_logger("login_bridge", source="backend")


class LoginBridge:
    """登录提交与回调管理，从 ScheduleEngine._do_async_login 提取。"""

    def __init__(
        self,
        get_orchestrator: Callable[[], LoginOrchestrator | None],
        get_runtime_config: Callable[[], RuntimeConfig],
        retry_policy: MonitoredPolicy,
        status_update_callback: Callable[[], None],
        record_log: Callable[..., None],
        wakeup_event: threading.Event,
        get_monitor_check_interval: Callable[[], int],
    ) -> None:
        self._get_orchestrator = get_orchestrator
        self._get_runtime_config = get_runtime_config
        self._retry_policy = retry_policy
        self._status_update_callback = status_update_callback
        self._record_log = record_log
        self._wakeup_event = wakeup_event
        self._get_monitor_check_interval = get_monitor_check_interval
        self._registered_futures: set[Future] = set()
        self._futures_lock = threading.Lock()

    def submit_login(
        self,
        is_manual: bool = False,
        config_snapshot: RuntimeConfig | None = None,
    ) -> bool:
        """提交登录到 LoginOrchestrator。"""
        # 清理已完成的 Future 引用，防止极端情况下残留
        with self._futures_lock:
            self._registered_futures = {f for f in self._registered_futures if not f.done()}

        orchestrator = self._get_orchestrator()
        if orchestrator is None:
            return False

        config = config_snapshot if config_snapshot is not None else self._get_runtime_config()

        # 自动登录前检查物理网络和认证地址可达性
        if not is_manual:
            m = config.monitor
            if m.enable_local_check or m.check_auth_url:
                from app.network.decision import check_login_prerequisites

                ok, reason = check_login_prerequisites(m, config.credentials.auth_url)
                if not ok:
                    self._record_log(
                        f"登录前置检查未通过: {reason}",
                        level="WARNING", source="backend",
                    )
                    return False

        source = "manual" if is_manual else "auto"
        handle = orchestrator.submit(source=source, config=config)

        if handle.rejected_reason is not None:
            # 手动登录的响应由 _handle_login 设置，此处仅记录自动登录的拒绝
            if not is_manual:
                self._record_log(handle.rejected_reason, level="WARNING", source="backend")
            return False

        if handle.future is None:
            # 复用了旧 handle（去重命中），不算新提交
            return False

        # 防止去重命中时重复注册回调
        with self._futures_lock:
            if handle.future in self._registered_futures:
                return False

        def _on_done(f: Future) -> None:
            with self._futures_lock:
                self._registered_futures.discard(f)
            self._status_update_callback()
            try:
                ok, msg = f.result()
                tag = "手动登录" if is_manual else "自动登录"
                if ok:
                    logger.info("{}完成: {}", tag, msg)
                    if not is_manual:
                        self._retry_policy.on_login_done(success=True)
                        self._on_login_success()
                else:
                    logger.warning("{}失败: {}", tag, msg)
                    if not is_manual:
                        delay = self._retry_policy.on_login_done(success=False)
                        if delay is None:
                            # 超过最大重试次数，不再尝试登录，等待网络检测恢复后重置
                            self._on_retry_exhausted()
                            logger.warning(
                                "登录重试次数已用尽（{}/{}），等待网络恢复（下次检测 {}s 后）",
                                self._retry_policy._attempt,
                                self._retry_policy.max_retries,
                                self._get_monitor_check_interval(),
                            )
                        else:
                            from datetime import datetime as _dt
                            next_time = _dt.fromtimestamp(
                                time.time() + delay
                            ).strftime("%H:%M:%S")
                            logger.info(
                                "重试 {}/{}, 下次重试: {}s 后 ({})",
                                self._retry_policy._attempt,
                                self._retry_policy.max_retries,
                                int(delay), next_time,
                            )
                            # 通过回调设置下次重试时间
                            self._on_retry_scheduled(delay)
            except CancelledError:
                logger.info("登录任务已取消")
            except Exception:
                logger.exception("登录任务异常")

        with self._futures_lock:
            self._registered_futures.add(handle.future)
        handle.future.add_done_callback(_on_done)
        return True

    def _on_retry_scheduled(self, delay: float) -> None:
        """重试已调度 — 由外部覆盖以设置 _next_retry_time。"""
        self._wakeup_event.set()

    def _on_login_success(self) -> None:
        """自动登录成功 — 由外部覆盖以清除重试计时。"""
        pass

    def _on_retry_exhausted(self) -> None:
        """重试次数用尽 — 由外部覆盖以清除重试计时。"""
        pass

    def cancel_login(self) -> tuple[bool, str]:
        """取消当前正在执行的登录。"""
        orchestrator = self._get_orchestrator()
        if orchestrator is None:
            return False, "登录服务未初始化"
        orchestrator.cancel_running()
        return True, "登录已取消"
