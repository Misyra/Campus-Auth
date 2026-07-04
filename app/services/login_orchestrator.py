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
from concurrent.futures import CancelledError, Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from app.schemas import RuntimeConfig
from app.utils.cancel_token import CompositeCancelEvent
from app.utils.logging import get_logger

if TYPE_CHECKING:
    from app.services.login_history_service import LoginHistoryService
    from app.services.profile_service import ProfileService

logger = get_logger("login_orchestrator", source="backend")

LoginSource = Literal["auto", "manual", "login_once", "browser"]


def runtime_config_to_worker_dict(config: RuntimeConfig, bind_proxy: str | None = None) -> dict:
    """将 RuntimeConfig 转换为 Worker 进程期望的 dict 格式。

    Worker 是独立进程，通过 dict 通信。
    """
    creds = config.credentials.model_dump()
    d: dict = {
        "username": creds["username"],
        "password": creds["password"],
        "auth_url": creds["auth_url"],
        "isp": creds["isp"],
        "carrier_custom": creds["carrier_custom"],
    }
    d["browser_settings"] = config.browser.model_dump()
    d["pause_login"] = config.pause.model_dump()
    d["monitor"] = config.monitor.model_dump()
    d["logging"] = {"level": config.logging.level}
    d["login_timeout"] = config.browser.login_timeout
    d["retry_settings"] = config.retry.model_dump()
    d["active_task"] = config.active_task
    d["block_proxy"] = config.app_settings.block_proxy
    d["shell_path"] = config.app_settings.shell_path
    d["access_log"] = config.logging.access_log
    d["log_retention_days"] = config.logging.log_retention_days

    # 注入网卡绑定代理（如果有）
    if bind_proxy:
        d["browser_settings"]["bind_proxy"] = bind_proxy

    return d


# ── 配置校验（F05 唯一实现）──


def validate_login_config(config: RuntimeConfig) -> str | None:
    """校验登录配置完整性。"""
    creds = config.credentials
    if not creds.username or not creds.password or not creds.auth_url:
        return "登录配置不完整（请先设置认证地址、用户名和密码）"
    return None


# ── 超时解析（F09 单一来源）──


def resolve_worker_timeout(config: RuntimeConfig, fallback: int = 300) -> int:
    """从 RuntimeConfig 解析 Worker 提交超时。

    优先用 login_timeout（用户在 UI 配置），缺失时用 fallback。
    下限 60s 防止误配导致登录必失败；上限 600s 与 BrowserSettings(le=600) 对齐。
    """
    raw = config.browser.login_timeout
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
    cancel_event: CompositeCancelEvent
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
        try:
            return self.future.result(timeout=timeout)
        except CancelledError:
            return False, "登录已取消"

    def cancel(self) -> None:
        """取消此次登录。"""
        self.cancel_event.set()


# ── 哨兵 ──

# submit() 锁外 dispatch 时的占位哨兵，防止并发重复提交
_DISPATCHING = LoginHandle(future=None, source="auto", cancel_event=CompositeCancelEvent())


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
        get_runtime_config: Callable[[], RuntimeConfig] | None = None,
        pool: ThreadPoolExecutor | None = None,
        executor=None,
    ) -> None:
        self._worker_getter = worker_getter
        self._login_history = login_history
        self._profile_service = profile_service
        self._get_runtime_config = get_runtime_config

        # 去重槽（替代 task_executor._login_future + _login_cancel_event）
        self._slot_lock = threading.Condition(threading.Lock())
        self._slot: LoginHandle | None = None

        # 优先使用外部 executor（BoundedExecutor），否则 fallback 到自建池
        self._executor = executor
        self._pool: ThreadPoolExecutor | None = pool
        if self._executor is None and self._pool is None:
            self._pool = ThreadPoolExecutor(
                max_workers=1,
                thread_name_prefix="login-exec",
            )

    def set_executor(self, executor: Any) -> None:
        """绑定外部 BoundedExecutor，关闭自建 fallback pool。

        在 container 初始化时调用，将 LoginOrchestrator 的执行器
        替换为 TaskExecutor 内部的 login_executor（BoundedExecutor）。
        """
        if executor is None:
            raise ValueError("executor 不能为 None")
        if self._pool is not None:
            self._pool.shutdown(wait=False)
            self._pool = None
        self._executor = executor

    def bind_runtime_config(self, getter: Callable[[], RuntimeConfig]) -> None:
        """延迟绑定运行时配置获取器（用于解决 Engine 循环依赖）。"""
        self._get_runtime_config = getter

    def set_bind_proxy(self, bind_proxy_url: str | None) -> None:
        """设置网卡绑定代理 URL（由引擎在监控启动时调用）。"""
        self._bind_proxy_url = bind_proxy_url

    # ── 公共 API ──

    def validate(self, config: RuntimeConfig | None = None) -> str | None:
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
        config: RuntimeConfig | None = None,
        cancel_event: threading.Event | None = None,
        timeout: int | None = None,
    ) -> LoginHandle:
        """提交一次登录。

        Args:
            source: "auto" | "manual" | "login_once" | "browser"
                - manual 可抢占 auto（取消旧的、提交新的）
                - auto 命中运行中的 handle 则复用（去重）
                - login_once 总是新提交（进程级一次性任务）
                - browser 由调用方自行校验，跳过登录配置校验和历史记录
            config: RuntimeConfig；None 则从 get_runtime_config 读取
            cancel_event: 取消事件；None 则内部新建
            timeout: Worker 超时（秒）；None 则从 config 解析

        Returns:
            LoginHandle。若校验失败，future 为 None 且 rejected_reason 非空。
        """
        cfg = config if config is not None else self._runtime_config()

        # 1. 校验（browser 任务由调用方自行校验）
        if source != "browser":
            err = validate_login_config(cfg)
            if err is not None:
                logger.warning("跳过登录: {} (source={})", err, source)
                return LoginHandle(
                    future=None,
                    source=source,
                    cancel_event=cancel_event or CompositeCancelEvent(),
                    rejected_reason=err,
                )

        if cancel_event is None:
            cancel_event = CompositeCancelEvent()
        elif not isinstance(cancel_event, CompositeCancelEvent):
            wrapper = CompositeCancelEvent()
            wrapper.add_source(cancel_event)
            cancel_event = wrapper

        # 2. 去重与抢占（Condition 保护）
        with self._slot_lock:
            # 等待 dispatch 完成（_slot 不再是 _DISPATCHING）
            while self._slot is _DISPATCHING:
                self._slot_lock.wait()

            existing = self._slot
            if existing is not None and not existing.done():
                if source == "login_once":
                    logger.warning("取消旧登录任务 (source={})", existing.source)
                    existing.cancel()
                elif source == "manual" and existing.source == "auto":
                    logger.debug("手动登录抢占自动登录 (source={})", existing.source)
                    existing.cancel()
                else:
                    self._link_cancel(cancel_event, existing.cancel_event)
                    return existing

            # 哨兵占位
            self._slot = _DISPATCHING

        # 3. 锁外提交新登录
        try:
            handle = self._dispatch(cfg, source, cancel_event, timeout=timeout)
        except Exception:
            # dispatch 失败，清除哨兵并唤醒等待者
            with self._slot_lock:
                self._slot = None
                self._slot_lock.notify_all()
            raise

        with self._slot_lock:
            self._slot = handle
            self._slot_lock.notify_all()

        logger.debug("登录已提交 (source={})", source)
        return handle

    def cancel_running(self) -> None:
        """取消当前正在运行的登录（供外部主动取消）。"""
        with self._slot_lock:
            if self._slot is not None and not self._slot.done():
                logger.warning("取消正在运行的登录任务")
                self._slot.cancel()

    def shutdown(self, wait: bool = True) -> None:
        """关闭编排器。仅关闭自建池（外部 executor 由调用方管理）。"""
        if self._pool is not None:
            self._pool.shutdown(wait=wait)
        logger.info("登录调度器已关闭")

    # ── 内部 ──

    def _dispatch(
        self, config: RuntimeConfig, source: LoginSource, cancel_event: threading.Event,
        timeout: int | None = None,
    ) -> LoginHandle:
        """提交到 Worker，注册历史/状态回调。"""
        # 延迟导入：避免模块级导入导致循环依赖
        from app.workers.playwright_worker import CMD_LOGIN

        # Build compatible dict for Worker process (Worker is separate process, communicates via dict)
        bind_proxy = getattr(self, "_bind_proxy_url", None)
        worker_config = runtime_config_to_worker_dict(config, bind_proxy=bind_proxy)
        worker_timeout = timeout if timeout is not None else resolve_worker_timeout(config)  # F09 单一来源

        def _run() -> tuple[bool, str]:
            start = time.perf_counter()
            try:
                if cancel_event.is_set():
                    return False, "登录已取消"
                worker = self._worker_getter()
                result = worker.submit(
                    CMD_LOGIN,
                    data={
                        "config": worker_config,
                        "cancel_event": cancel_event,
                    },
                    wait=True,
                    timeout=worker_timeout,
                )
                duration_ms = int((time.perf_counter() - start) * 1000)
                if result.success:
                    if source != "browser":
                        self._record_history(True, duration_ms)
                    msg = result.data if isinstance(result.data, str) else "登录成功"
                    return True, msg
                err_msg = result.error or "登录失败"
                if source != "browser":
                    self._record_history(False, duration_ms, error=err_msg)
                return False, err_msg
            except ImportError as exc:
                duration_ms = int((time.perf_counter() - start) * 1000)
                if source != "browser":
                    self._record_history(False, duration_ms, error=str(exc))
                return False, "登录需要额外依赖，请检查 Playwright 安装状态"
            except Exception as exc:
                duration_ms = int((time.perf_counter() - start) * 1000)
                # 超时场景：给 Worker 短暂时间响应 cancel_event
                if "超时" in str(exc) or "timed out" in str(exc).lower():
                    cancel_event.set()
                    time.sleep(0.5)
                if source != "browser":
                    self._record_history(False, duration_ms, error=str(exc))
                logger.exception("登录执行异常: {}", exc)
                return False, f"登录执行异常: {exc}"

        # 提交到登录线程池
        try:
            if self._executor is not None:
                future = self._executor.submit(_run)
            else:
                future = self._pool.submit(_run)
        except RuntimeError as exc:
            # BoundedExecutor 队列满时抛出 RuntimeError，转为 rejected handle
            logger.warning("登录提交被拒绝: {} (source={})", exc, source)
            return LoginHandle(
                future=None, source=source, cancel_event=cancel_event,
                rejected_reason=f"登录队列已满，请稍后重试",
            )
        handle = LoginHandle(future=future, source=source, cancel_event=cancel_event)

        # 清理槽位（替代 task_executor._on_login_done）
        def _on_done(_: Future) -> None:
            with self._slot_lock:
                if self._slot is handle:
                    self._slot = None
                self._slot_lock.notify_all()
            # 释放 CompositeCancelEvent 的源引用，防止内存泄漏
            if isinstance(handle.cancel_event, CompositeCancelEvent):
                handle.cancel_event.clear_sources()

        future.add_done_callback(_on_done)
        return handle

    def _record_history(
        self, success: bool, duration_ms: int, error: str = ""
    ) -> None:
        """记录登录历史（使用 add() 直接传入名称）。"""
        if self._login_history is None:
            return
        try:
            profile_name = ""
            if self._profile_service is not None:
                try:
                    active = self._profile_service.get_active_profile()
                    if active:
                        profile_name = getattr(active, "name", "")
                except Exception:
                    pass

            self._login_history.add(
                success=success,
                duration_ms=duration_ms,
                profile_name=profile_name,
                error=error,
            )
        except Exception:
            logger.warning("记录登录历史失败", exc_info=True)

    def _runtime_config(self) -> RuntimeConfig:
        """获取运行时配置。"""
        if self._get_runtime_config is None:
            return RuntimeConfig()
        return self._get_runtime_config()

    def _link_cancel(
        self, new_event: threading.Event, target_event: CompositeCancelEvent
    ) -> None:
        """将新 cancel_event 添加为源（无线程，惰性扫描）。"""
        target_event.add_source(new_event)
