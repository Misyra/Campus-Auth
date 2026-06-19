"""LoginOrchestrator — 登录执行的唯一入口。

职责：
- 配置校验（validate_login_config）
- 去重与抢占（_slot，替代 task_executor._login_future 散落逻辑）
- Worker 提交与超时（resolve_worker_timeout）
- 登录历史记录（LoginHistoryService）
- cancel_event 生命周期
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from app.utils.logging import get_logger

if TYPE_CHECKING:
    from app.services.login_history_service import LoginHistoryService
    from app.services.profile_service import ProfileService

logger = get_logger("login_orchestrator", source="backend")

LoginSource = Literal["auto", "manual", "login_once"]


# ── 配置校验（F05 唯一实现）──


def validate_login_config(config: dict) -> str | None:
    """校验登录配置完整性。

    Returns:
        None 表示通过；否则返回中文错误信息。
    """
    if not config.get("username") or not config.get("password") or not config.get("auth_url"):
        return "登录配置不完整（请先设置认证地址、用户名和密码）"
    return None


# ── 超时解析（F09 单一来源）──


def resolve_worker_timeout(config: dict, fallback: int = 300) -> int:
    """从运行时配置解析 Worker 提交超时。

    优先用 login_timeout（用户在 UI 配置），缺失时用 fallback。
    下限 60s 防止误配导致登录必失败；上限 600s 与 MonitorConfigPayload(le=600) 对齐。
    """
    raw = config.get("login_timeout", fallback)
    try:
        timeout = int(raw)
    except (TypeError, ValueError):
        return fallback
    return max(60, min(timeout, 600))


# ── 登录句柄 ──


@dataclass
class LoginHandle:
    """一次登录提交的句柄。"""

    future: Future | None
    source: LoginSource
    cancel_event: threading.Event
    rejected_reason: str | None = None

    def done(self) -> bool:
        """是否已完成（含被拒绝）。"""
        return self.future is None or self.future.done()

    def result(self, timeout: float | None = None) -> tuple[bool, str]:
        """同步等待结果。被拒绝时立即返回 (False, reason)。"""
        if self.rejected_reason is not None:
            return False, self.rejected_reason
        if self.future is None:
            return False, "登录未提交"
        return self.future.result(timeout=timeout)

    def cancel(self) -> None:
        """取消此次登录。"""
        self.cancel_event.set()


# ── 编排器 ──


class LoginOrchestrator:
    """登录执行的唯一入口。

    职责（收敛点）：
    - 配置校验（validate_login_config）
    - 去重与抢占（_slot，替代 task_executor._login_future 散落逻辑）
    - Worker 提交与超时（resolve_worker_timeout）
    - 登录历史记录（LoginHistoryService，替代三处各自的记录逻辑）
    - cancel_event 生命周期

    不负责（交给调用方/RetryPolicy）：
    - 重试间隔与停止策略（RetryPolicy）
    - 网络检测触发（engine）
    """

    def __init__(
        self,
        worker_getter: Callable,
        login_history: LoginHistoryService | None = None,
        profile_service: ProfileService | None = None,
        get_runtime_config: Callable[[], dict] | None = None,
    ) -> None:
        self._worker_getter = worker_getter
        self._login_history = login_history
        self._profile_service = profile_service
        self._get_runtime_config = get_runtime_config

        # 去重槽（替代 task_executor._login_future + _login_cancel_event）
        self._slot_lock = threading.RLock()
        self._slot: LoginHandle | None = None

        # 线程池：默认单线程，外部可注入（TaskExecutor._login_pool）
        self._pool: ThreadPoolExecutor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="login-exec",
        )

    # ── 公共 API ──

    def validate(self, config: dict | None = None) -> str | None:
        """校验。config 为 None 时从 get_runtime_config 读取。"""
        cfg = config if config is not None else self._runtime_config()
        return validate_login_config(cfg)

    def is_running(self) -> bool:
        """是否有登录正在执行。"""
        with self._slot_lock:
            return self._slot is not None and not self._slot.done()

    def submit(
        self,
        *,
        source: LoginSource,
        config: dict | None = None,
        cancel_event: threading.Event | None = None,
    ) -> LoginHandle:
        """提交一次登录。

        Args:
            source: "auto" | "manual" | "login_once"
                - manual 可抢占 auto（取消旧的、提交新的）
                - auto 命中运行中的 handle 则复用（去重）
                - login_once 总是新提交（进程级一次性任务）
            config: 配置快照；None 则从 get_runtime_config 读取
            cancel_event: 取消事件；None 则内部新建

        Returns:
            LoginHandle。若校验失败，future 为 None 且 rejected_reason 非空。
        """
        cfg = config if config is not None else self._runtime_config()

        # 1. 校验（F05 唯一实现）
        err = validate_login_config(cfg)
        if err is not None:
            logger.warning("跳过登录(source={}): {}", source, err)
            return LoginHandle(
                future=None,
                source=source,
                cancel_event=cancel_event or threading.Event(),
                rejected_reason=err,
            )

        if cancel_event is None:
            cancel_event = threading.Event()

        # 2. 去重与抢占
        with self._slot_lock:
            existing = self._slot
            if existing is not None and not existing.done():
                # login_once 一次性任务，不复用
                if source == "login_once":
                    pass  # 落到下方新建分支
                # manual 抢占 auto：取消旧的，提交新的
                elif source == "manual" and existing.source == "auto":
                    logger.info("手动登录抢占自动登录(source={})", existing.source)
                    existing.cancel()
                    # 不立即 return，落到下方提交新 handle
                else:
                    # 复用旧 handle（auto→auto, auto→manual 同源, manual→*）
                    # 联动新 cancel_event 到旧任务
                    self._link_cancel(cancel_event, existing.cancel_event)
                    return existing

            # 3. 提交新登录
            handle = self._dispatch(cfg, source, cancel_event)
            self._slot = handle

        return handle

    def cancel_running(self) -> None:
        """取消当前正在运行的登录（供外部主动取消）。"""
        with self._slot_lock:
            if self._slot is not None and not self._slot.done():
                self._slot.cancel()

    def shutdown(self, wait: bool = True) -> None:
        """关闭编排器，清理线程池。"""
        self._pool.shutdown(wait=wait)

    # ── 内部 ──

    def _dispatch(
        self, config: dict, source: LoginSource, cancel_event: threading.Event
    ) -> LoginHandle:
        """提交到 Worker，注册历史/状态回调。"""
        # 延迟导入：避免模块级导入导致循环依赖
        from app.workers.playwright_worker import CMD_LOGIN

        worker_timeout = resolve_worker_timeout(config)  # F09 单一来源

        def _run() -> tuple[bool, str]:
            start = time.perf_counter()
            try:
                if cancel_event.is_set():
                    return False, "登录已取消"
                worker = self._worker_getter()
                result = worker.submit(
                    CMD_LOGIN,
                    data={
                        "config": config,
                        "cancel_event": cancel_event,
                    },
                    wait=True,
                    timeout=worker_timeout,
                )
                duration_ms = int((time.perf_counter() - start) * 1000)
                if result.success:
                    self._record_history(True, duration_ms)
                    msg = result.data if isinstance(result.data, str) else "登录成功"
                    return True, msg
                err_msg = result.error or "登录失败"
                self._record_history(False, duration_ms, error=err_msg)
                return False, err_msg
            except ImportError as exc:
                duration_ms = int((time.perf_counter() - start) * 1000)
                self._record_history(False, duration_ms, error=str(exc))
                return False, "登录需要额外依赖，请检查 Playwright 安装状态"
            except Exception as exc:
                duration_ms = int((time.perf_counter() - start) * 1000)
                self._record_history(False, duration_ms, error=str(exc))
                logger.error("登录执行异常: {}", exc, exc_info=True)
                return False, f"登录执行异常: {exc}"

        # 提交到登录线程池
        future = self._pool.submit(_run)
        handle = LoginHandle(future=future, source=source, cancel_event=cancel_event)

        # 清理槽位（替代 task_executor._on_login_done）
        def _on_done(_: Future) -> None:
            with self._slot_lock:
                if self._slot is handle:
                    self._slot = None

        future.add_done_callback(_on_done)
        return handle

    def _record_history(
        self, success: bool, duration_ms: int, error: str = ""
    ) -> None:
        """记录登录历史（原 F02：login_once 路径此前不记录）。"""
        if self._login_history is None:
            return
        try:
            self._login_history.record(
                success=success,
                duration_ms=duration_ms,
                profile_service=self._profile_service,
                error=error,
            )
        except Exception:
            logger.debug("记录登录历史失败", exc_info=True)

    def _runtime_config(self) -> dict:
        """获取运行时配置快照。"""
        if self._get_runtime_config is None:
            return {}
        return self._get_runtime_config()

    def _link_cancel(
        self, new_event: threading.Event, target_event: threading.Event
    ) -> None:
        """联动取消事件（Task 11 会替换为事件循环实现）。

        当前使用简单的 watcher 线程：监控 new_event，set 时联动到 target_event。
        300 秒超时自动退出，防止线程泄漏。
        """
        deadline = time.time() + 300  # 5 分钟超时自动退出

        def _watcher() -> None:
            while time.time() < deadline:
                if new_event.is_set():
                    target_event.set()
                    return
                if target_event.is_set():
                    return
                time.sleep(0.2)

        t = threading.Thread(target=_watcher, daemon=True, name="cancel-link-watcher")
        t.start()
