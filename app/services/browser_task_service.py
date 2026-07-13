"""BrowserTaskService — 通用浏览器自动化服务。

职责：
- 通用浏览器任务执行（签到、打卡、信息采集等）
- 独立线程池与去重（不与登录共享）
- Worker 提交与超时

不负责（交给调用方）：
- 登录特有逻辑（重试策略、网络验证、断网触发、登录历史）
- 定时调度（由 SchedulerService 触发）
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent.futures import CancelledError, Future
from dataclasses import dataclass
from typing import Any

from app.constants import WORKER_SUBMIT_TIMEOUT
from app.utils.cancel_token import CompositeCancelEvent
from app.utils.logging import get_logger

logger = get_logger("browser_task_service", source="backend")


@dataclass
class BrowserTaskHandle:
    """一次浏览器任务提交的句柄。"""

    future: Future | None
    cancel_event: CompositeCancelEvent
    rejected_reason: str | None = None

    def done(self) -> bool:
        """是否已完成（含被拒绝）。"""
        return self.future is None or self.future.done()

    def result(self, timeout: float | None = None) -> tuple[bool, str]:
        """同步等待结果。"""
        if self.rejected_reason is not None:
            return False, self.rejected_reason
        if self.future is None:
            return False, "任务未提交"
        try:
            return self.future.result(timeout=timeout)
        except CancelledError:
            return False, "任务已取消"

    def cancel(self) -> None:
        """取消此次任务。"""
        self.cancel_event.set()


# ── 哨兵 ──

# submit_task() 锁外 dispatch 时的占位哨兵，防止并发重复提交。
# future=None 不代表"无任务"，而是标记此句柄为占位符（非真实 Future），
# 通过 `is _DISPATCHING` 身份检查区分，不依赖 None 语义。
_DISPATCHING = BrowserTaskHandle(
    future=None,
    cancel_event=CompositeCancelEvent(),
    rejected_reason="__dispatching__",
)


class BrowserTaskService:
    """通用浏览器自动化服务 — 签到/打卡等非登录浏览器任务。

    与 LoginOrchestrator 平级，共享 Worker（Playwright Actor）但
    拥有独立线程池与去重槽。
    """

    def __init__(
        self,
        worker_getter: Callable,
        executor: Any,
    ) -> None:
        self._worker_getter = worker_getter
        self._executor = executor

        # 去重槽：同一 active_task 不重复提交
        self._slot_lock = threading.Condition(threading.Lock())
        self._slot: BrowserTaskHandle | None = None

        # 网卡绑定代理 URL（由引擎在监控启动时通过 set_bind_proxy 设置）
        # 与 LoginOrchestrator._bind_proxy_url 对齐，确保定时浏览器任务走绑定 NIC
        self._bind_proxy_url: str | None = None

    def is_running(self) -> bool:
        """是否有浏览器任务正在执行。"""
        with self._slot_lock:
            return self._slot is not None and not self._slot.done()

    def set_bind_proxy(self, bind_proxy_url: str | None) -> None:
        """设置网卡绑定代理 URL（由引擎在监控启动时调用）。

        与 LoginOrchestrator.set_bind_proxy 对齐，确保定时浏览器任务
        也走绑定网卡，而非默认路由。
        """
        self._bind_proxy_url = bind_proxy_url

    def submit_task(
        self,
        *,
        task_config: dict[str, Any],
        cancel_event: threading.Event | None = None,
        timeout: int = WORKER_SUBMIT_TIMEOUT,
    ) -> BrowserTaskHandle:
        """提交一次浏览器任务。

        Args:
            task_config: Worker 配置 dict（含 active_task、browser_settings 等）
            cancel_event: 取消事件；None 则内部新建
            timeout: Worker 超时（秒）

        Returns:
            BrowserTaskHandle
        """
        # 应用网卡绑定代理（与 LoginOrchestrator._dispatch 对齐）
        # 仅当 task_config 未显式设置 bind_proxy 时注入，避免覆盖调用方意图
        if self._bind_proxy_url:
            browser_settings = task_config.get("browser_settings", {})
            if "bind_proxy" not in browser_settings:
                browser_settings = {
                    **browser_settings,
                    "bind_proxy": self._bind_proxy_url,
                }
                task_config = {**task_config, "browser_settings": browser_settings}

        if cancel_event is None:
            cancel_event = CompositeCancelEvent()
        elif not isinstance(cancel_event, CompositeCancelEvent):
            wrapper = CompositeCancelEvent()
            wrapper.add_source(cancel_event)
            cancel_event = wrapper

        # 去重与抢占（Condition 保护）
        with self._slot_lock:
            # 等待 dispatch 完成（_slot 不再是 _DISPATCHING）
            while self._slot is _DISPATCHING:
                self._slot_lock.wait()

            existing = self._slot
            if existing is not None and not existing.done():
                # 复用进行中的任务
                existing.cancel_event.add_source(cancel_event)
                return existing
            # 哨兵占位，锁外提交
            self._slot = _DISPATCHING

        # 锁外提交新任务
        try:
            handle = self._dispatch(task_config, cancel_event, timeout=timeout)
        except Exception:
            # dispatch 失败，清除哨兵并唤醒等待者
            with self._slot_lock:
                self._slot = None
                self._slot_lock.notify_all()
            raise

        with self._slot_lock:
            self._slot = handle
            self._slot_lock.notify_all()

        return handle

    def cancel_running(self) -> None:
        """取消当前正在运行的浏览器任务。"""
        with self._slot_lock:
            if self._slot is not None and not self._slot.done():
                self._slot.cancel()

    def shutdown(self, wait: bool = True) -> None:
        """关闭服务。executor 由调用方管理。"""
        logger.info("浏览器任务服务已关闭")

    def _dispatch(
        self,
        task_config: dict[str, Any],
        cancel_event: threading.Event,
        timeout: int = WORKER_SUBMIT_TIMEOUT,
    ) -> BrowserTaskHandle:
        """提交到 Worker。"""
        # 延迟导入：避免模块级导入导致循环依赖
        from app.services.worker_port import CMD_BROWSER

        def _run() -> tuple[bool, str]:
            try:
                if cancel_event.is_set():
                    return False, "任务已取消"
                worker = self._worker_getter()
                result = worker.submit(
                    CMD_BROWSER,
                    data={"config": task_config, "cancel_event": cancel_event},
                    wait=True,
                    timeout=timeout,
                )
                if result.success:
                    msg = (
                        result.data
                        if isinstance(result.data, str)
                        else "浏览器任务执行成功"
                    )
                    return True, msg
                return False, result.error or "浏览器任务执行失败"
            except Exception as exc:
                logger.exception("浏览器任务执行异常: {}", exc)
                return False, f"浏览器任务执行异常: {exc}"

        try:
            future = self._executor.submit(_run)
        except RuntimeError as exc:
            logger.warning("浏览器任务提交被拒绝: {}", exc)
            return BrowserTaskHandle(
                future=None,
                cancel_event=cancel_event,
                rejected_reason="任务队列已满，请稍后重试",
            )
        handle = BrowserTaskHandle(future=future, cancel_event=cancel_event)

        def _on_done(_: Future) -> None:
            with self._slot_lock:
                if self._slot is handle:
                    self._slot = None
                self._slot_lock.notify_all()
            if isinstance(handle.cancel_event, CompositeCancelEvent):
                handle.cancel_event.clear_sources()

        future.add_done_callback(_on_done)
        return handle
