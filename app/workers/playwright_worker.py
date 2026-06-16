"""Playwright Worker — Actor 模型浏览器自动化工作线程。

架构说明:
  PlaywrightWorker 采用与 MonitorService 相同的 Actor 模型:
    - 外部调用者通过 submit() 提交 WorkerCommand 到内部队列
    - 常驻守护线程运行独立 asyncio 事件循环
    - _async_run() 协程轮询队列并派发命令
    - 所有 Playwright 操作限制在 Worker 线程内执行，避免跨线程竞争

命令派发流程:
  submit() → queue.put(cmd) → run_coroutine_threadsafe(_wake_async())
  → _async_run() 被唤醒 → get_nowait() 取出命令 → _dispatch() → handler
"""

from __future__ import annotations

import asyncio
import contextlib
import queue
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from playwright.async_api import Route

from app.constants import (
    WORKER_JOIN_TIMEOUT,
    WORKER_QUEUE_PUT_TIMEOUT,
    WORKER_READY_TIMEOUT,
    WORKER_SUBMIT_TIMEOUT,
)
from app.utils.logging import get_logger

logger = get_logger("playwright_worker", source="backend")


# ── 命令类型常量 ──

CMD_LOGIN = "login"  # 执行完整登录流程
CMD_DEBUG_START = "debug_start"  # 启动调试会话
CMD_DEBUG_STEP = "debug_step"  # 调试下一步
CMD_DEBUG_STOP = "debug_stop"  # 停止调试会话
CMD_BROWSER_HEALTH_CHECK = "browser_health_check"  # 浏览器健康检查
CMD_BROWSER_ACQUIRE = (
    "browser_acquire"  # 获取/确保浏览器就绪（供外部线程使用 submit 调用）
)
CMD_BROWSER_RELEASE = (
    "browser_release"  # 释放浏览器引用（浏览器常驻 Worker 不实际关闭）
)
CMD_BROWSER_CLOSE = "browser_close"  # 实际关闭浏览器进程
CMD_SHUTDOWN = "shutdown"  # 关闭 Worker


# ── 常量 ──

_DEFAULT_SUBMIT_TIMEOUT = WORKER_SUBMIT_TIMEOUT  # submit() 默认超时


# ── 数据结构 ──


@dataclass
class WorkerCommand:
    """从 API/服务线程提交到 Worker 线程的命令单元。"""

    type: str  # 命令类型，对应 CMD_* 常量
    data: dict = field(default_factory=dict)  # 命令参数
    response_event: threading.Event | None = None  # 调用方等待此事件以获取结果
    response_data: Any = None  # 消费者线程设置返回数据
    cancelled: bool = False  # 超时后标记为已取消，跳过执行


@dataclass
class WorkerResponse:
    """Worker 命令执行结果。"""

    success: bool
    data: Any = None
    error: str | None = None


# ── Worker 类 ──


class PlaywrightWorker:
    """浏览器自动化工作线程。

    通过 Actor 模型的消息队列，将 Playwright 操作隔离在独立线程中执行。
    外部模块通过 submit() 提交任务，可选择同步等待执行结果。
    """

    def __init__(self) -> None:
        self._cmd_queue: queue.Queue[WorkerCommand] = queue.Queue(maxsize=50)
        self._stop_event = threading.Event()
        self._shutdown_permanent = (
            threading.Event()
        )  # 永久关闭标志，stop() 设置后不可重置
        self._consumer_thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._worker_ready = threading.Event()
        self._restart_lock = threading.Lock()  # 防止并发重启消费者线程

        # 浏览器状态（仅从事件循环线程访问，无需锁保护）
        self._playwright: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._page: Any = None
        self._debug_page: Any = None
        self._debug_executor: Any = (
            None  # TaskExecutor 实例，调试步骤执行时在 Worker 线程内使用
        )
        self._last_browser_settings: dict | None = None  # 缓存最近一次浏览器设置

        # _wake_event 用于立即唤醒 _async_run 协程处理新命令
        self._wake_event: asyncio.Event | None = None

    # ── 只读属性（供同线程调用者访问，如 BrowserContextManager）──

    @property
    def page(self) -> Any:
        """当前页面引用（仅限 Worker 事件循环线程内访问）"""
        return self._page

    @property
    def browser(self) -> Any:
        """浏览器实例（仅限 Worker 事件循环线程内访问）"""
        return self._browser

    @property
    def context(self) -> Any:
        """浏览器上下文（仅限 Worker 事件循环线程内访问）"""
        return self._context

    @property
    def playwright_instance(self) -> Any:
        """Playwright 实例（仅限 Worker 事件循环线程内访问）"""
        return self._playwright

    # ── 公共生命周期方法 ──

    def start(self) -> None:
        """启动消费者守护线程。

        创建 daemon Thread，线程内部运行持久 asyncio 事件循环，
        通过 _worker_ready 事件等待循环就绪后再返回。
        """
        self._stop_event.clear()
        self._worker_ready.clear()
        self._consumer_thread = threading.Thread(
            target=self._worker_entry,
            daemon=True,
            name="playwright-worker",
        )
        self._consumer_thread.start()
        # 等待事件循环就绪（最多 5 秒）
        self._worker_ready.wait(timeout=WORKER_READY_TIMEOUT)
        if not self._worker_ready.is_set():
            logger.warning(
                "PlaywrightWorker 事件循环启动超时 ({}s)", WORKER_READY_TIMEOUT
            )

    def stop(self, timeout: float = 5) -> None:
        """发送关闭信号并等待线程结束。

        设置 _stop_event → 放入 CMD_SHUTDOWN → 唤醒事件循环 → join 线程。
        如果线程未在 timeout 秒内退出，强制停止事件循环。

        参数:
            timeout: 等待线程结束的超时秒数
        """
        self._stop_event.set()
        self._shutdown_permanent.set()

        # 放入 SHUTDOWN 命令确保事件循环能正常退出
        try:
            self._cmd_queue.put_nowait(WorkerCommand(type=CMD_SHUTDOWN))
        except queue.Full:
            logger.warning(
                "命令队列已满 (maxsize={})，强制停止 Worker", self._cmd_queue.maxsize
            )
            if self._loop is not None and self._loop.is_running():
                self._loop.call_soon_threadsafe(self._loop.stop)
            return

        # 通过 run_coroutine_threadsafe 唤醒 Worker 的事件循环
        # 这是唯一允许的跨线程 asyncio 调用
        loop = self._loop
        if loop is not None:
            with contextlib.suppress(RuntimeError):
                asyncio.run_coroutine_threadsafe(self._wake_async(), loop)

        # 等待消费者线程正常退出
        if self._consumer_thread:
            self._consumer_thread.join(timeout=timeout)
            # 超时后强制停止事件循环
            if self._consumer_thread.is_alive():
                logger.warning("Worker 线程未在 {}s 内退出，强制停止", timeout)
                loop = self._loop
                if loop is not None:
                    loop.call_soon_threadsafe(loop.stop)
                self._consumer_thread.join(timeout=WORKER_JOIN_TIMEOUT)

        # 排干队列中残留的命令，通知等待方 Worker 已关闭
        while True:
            try:
                pending = self._cmd_queue.get_nowait()
            except queue.Empty:
                break
            if pending.response_event is not None:
                pending.response_data = WorkerResponse(
                    success=False, error="Worker 已关闭，命令未执行"
                )
                pending.response_event.set()

    def is_alive(self) -> bool:
        """检查 Worker 消费者线程是否存活。"""
        return self._consumer_thread is not None and self._consumer_thread.is_alive()

    def submit(
        self,
        cmd_type: str,
        data: dict | None = None,
        wait: bool = True,
        timeout: float | None = _DEFAULT_SUBMIT_TIMEOUT,
    ) -> WorkerResponse:
        """提交命令到 Worker 队列。

        创建 WorkerCommand 放入内部队列，通过 run_coroutine_threadsafe
        唤醒 Worker 的事件循环。若 wait=True 则阻塞等待命令执行完成。

        参数:
            cmd_type: 命令类型（CMD_* 常量）
            data: 命令参数字典
            wait: 是否同步等待执行结果
            timeout: 等待超时秒数（None 表示无限制）

        返回:
            WorkerResponse 对象
        """
        # Worker 已关闭时拒绝新命令（SHUTDOWN 命令走 stop() 路径不经过此检查）
        if self._stop_event.is_set() or self._shutdown_permanent.is_set():
            return WorkerResponse(success=False, error="Worker 已关闭，不接受新命令")

        # 检测消费者线程是否存活，若已死亡则尝试重启
        if not self.is_alive():
            with self._restart_lock:
                # 三重检查：获取锁后再次确认线程状态和关闭标志
                if (
                    not self.is_alive()
                    and not self._stop_event.is_set()
                    and not self._shutdown_permanent.is_set()
                ):
                    logger.warning("检测到消费者线程已死亡，尝试重启")
                    try:
                        self.start()
                    except Exception:
                        logger.exception("重启消费者线程失败")
                        return WorkerResponse(
                            success=False, error="消费者线程已死亡且重启失败"
                        )

        cmd = WorkerCommand(
            type=cmd_type,
            data=data or {},
            response_event=threading.Event() if wait else None,
        )
        try:
            self._cmd_queue.put(cmd, timeout=WORKER_QUEUE_PUT_TIMEOUT)
        except queue.Full:
            return WorkerResponse(success=False, error="命令队列已满，提交超时")

        # 通过 run_coroutine_threadsafe 唤醒 Worker 的事件循环，
        # 使 _async_run 立即处理新放入的命令
        loop = self._loop
        if loop is not None:
            with contextlib.suppress(RuntimeError):
                asyncio.run_coroutine_threadsafe(self._wake_async(), loop)

        if not wait:
            return WorkerResponse(success=True)

        # 阻塞等待命令执行完成
        cmd.response_event.wait(timeout=timeout)
        if cmd.response_data is not None:
            if isinstance(cmd.response_data, WorkerResponse):
                return cmd.response_data
            return WorkerResponse(success=True, data=cmd.response_data)

        # 超时：标记命令为已取消
        cmd.cancelled = True
        return WorkerResponse(success=False, error="命令执行超时或无响应")

    def submit_nowait(self, cmd_type: str, data: dict | None = None) -> None:
        """提交命令但不等待响应（fire-and-forget）。"""
        try:
            self._cmd_queue.put_nowait(WorkerCommand(type=cmd_type, data=data or {}))
        except queue.Full:
            logger.warning("submit_nowait 队列已满 (maxsize={})，丢弃命令 {}", self._cmd_queue.maxsize, cmd_type)
            return

        # 唤醒 Worker 事件循环处理新命令
        loop = self._loop
        if loop is not None:
            with contextlib.suppress(RuntimeError):
                asyncio.run_coroutine_threadsafe(self._wake_async(), loop)

    # ── Worker 线程入口 ──

    def _worker_entry(self) -> None:
        """Worker 线程入口函数。

        创建独立 asyncio 事件循环，调度 _async_run 协程，
        然后进入 run_forever() 永久运行。
        事件循环退出后执行 _force_cleanup() 并关闭循环。
        """
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        # 通知 start() 事件循环已就绪
        self._worker_ready.set()

        try:
            loop.create_task(self._async_run())
            loop.run_forever()
        finally:
            # 事件循环退出后执行强制清理
            if not loop.is_closed():
                try:
                    loop.run_until_complete(self._force_cleanup())
                except Exception:
                    logger.exception("Worker 清理时出现异常")
                try:
                    loop.close()
                except Exception:
                    logger.debug("关闭事件循环失败", exc_info=True)
            self._loop = None
            logger.info("PlaywrightWorker 事件循环已关闭")

    async def _async_run(self) -> None:
        """异步主循环 — 从队列获取命令并派发。

        使用 asyncio.Event 实现高效唤醒:
        - 空闲时 await wake_event.wait() 等待信号
        - submit() 通过 run_coroutine_threadsafe 设置 wake_event
        - 同时使用 0.5s 超时兜底，防止漏掉信号
        - 收到 CMD_SHUTDOWN 后退出循环，触发事件循环停止
        """
        wake_event = asyncio.Event()
        self._wake_event = wake_event

        try:
            while not self._stop_event.is_set():
                wake_event.clear()

                # 排干队列中所有待处理命令
                while True:
                    try:
                        cmd = self._cmd_queue.get_nowait()
                    except queue.Empty:
                        break

                    await self._dispatch(cmd)
                    self._cmd_queue.task_done()

                    # SHUTDOWN 命令：退出主循环
                    if cmd.type == CMD_SHUTDOWN:
                        logger.info("Worker 收到关闭命令，退出主循环")
                        return

                # 等待唤醒信号或超时
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(wake_event.wait(), timeout=0.5)
        finally:
            # 停止事件循环，使 _worker_entry() 中的 run_forever() 返回
            if self._loop and not self._loop.is_closed():
                self._loop.stop()

    # ── 命令派发 ──

    async def _dispatch(self, cmd: WorkerCommand) -> None:
        """派发 WorkerCommand 到对应的异步处理函数。

        根据 cmd.type 路由到对应的 _handle_* 方法，
        将返回值设为 cmd.response_data 并通知等待方。
        """
        # 超时命令已取消，跳过执行避免资源浪费
        if cmd.cancelled:
            return

        try:
            if cmd.type == CMD_LOGIN:
                result = await self._handle_login(cmd.data)
            elif cmd.type == CMD_DEBUG_START:
                result = await self._handle_debug_start(cmd.data)
            elif cmd.type == CMD_DEBUG_STEP:
                result = await self._handle_debug_step(cmd.data)
            elif cmd.type == CMD_DEBUG_STOP:
                result = await self._handle_debug_stop()
            elif cmd.type == CMD_BROWSER_ACQUIRE:
                result = await self._handle_browser_acquire(cmd.data)
            elif cmd.type == CMD_BROWSER_RELEASE:
                result = await self._handle_browser_release()
            elif cmd.type == CMD_BROWSER_CLOSE:
                result = await self._handle_browser_close()
            elif cmd.type == CMD_BROWSER_HEALTH_CHECK:
                result = await self._handle_health_check()
            elif cmd.type == CMD_SHUTDOWN:
                result = WorkerResponse(success=True, data="Worker 正在关闭")
            else:
                result = WorkerResponse(
                    success=False, error=f"未知命令类型: {cmd.type}"
                )

            cmd.response_data = result
        except Exception as e:
            logger.exception("命令 {} 执行异常", cmd.type)
            cmd.response_data = WorkerResponse(
                success=False, error=f"命令执行异常: {e}"
            )
        finally:
            if cmd.response_event:
                cmd.response_event.set()

    # ── 命令处理函数 ──

    async def _handle_login(self, data: dict) -> WorkerResponse:
        """处理登录命令。

        创建 LoginAttemptHandler 执行完整登录流程。
        LoginAttemptHandler 内部管理浏览器生命周期（创建/复用/关闭）。
        如果提供了 cancel_event，启动取消信号桥接线程。
        """
        from app.utils.login import LoginAttemptHandler

        config = data.get("config", {})
        cancel_event: threading.Event | None = data.get("cancel_event")

        try:
            handler = LoginAttemptHandler(
                config=config,
                cancel_event=cancel_event,
                close_on_failure=data.get("close_on_failure", True),
            )
            success, message = await handler.attempt_login(
                skip_pause_check=data.get("skip_pause_check", False),
            )
            return WorkerResponse(success=success, data=message)
        except Exception as e:
            logger.exception("登录执行异常")
            return WorkerResponse(success=False, error=str(e))

    async def _handle_debug_start(self, data: dict) -> WorkerResponse:
        """启动调试会话。

        在 Worker 线程内管理浏览器生命周期：
        1. 健康检查 → 不健康则重建浏览器
        2. 导航到任务 URL
        3. 创建 TaskExecutor（线程安全 — 所有 Playwright 操作在 Worker 线程内执行）
        4. 初始截图并返回 URL
        """
        from app.constants import DEFAULT_STEP_TIMEOUT_MS
        from app.tasks import TaskConfig, TaskExecutor

        config = data.get("config", {})
        task_url = data.get("task_url", "")
        task_data = data.get("task_data", {})
        template_vars = data.get("template_vars", data.get("env_vars", {}))
        screenshot_dir = data.get("screenshot_dir", "")
        default_timeout = data.get("default_timeout", DEFAULT_STEP_TIMEOUT_MS)
        navigation_timeout = data.get(
            "navigation_timeout", TaskExecutor.DEFAULT_NAVIGATION_TIMEOUT
        )

        # 检查浏览器健康状态，不健康则重建
        if not await self._health_check():
            await self._close_browser()
            await self._start_browser(config)

        if self._page is None:
            return WorkerResponse(success=False, error="浏览器页面初始化失败")

        # 保存调试页面引用
        self._debug_page = self._page
        self._debug_executor = None

        # 加载任务页面
        if task_url:
            try:
                await self._page.goto(
                    task_url, wait_until="domcontentloaded", timeout=30000
                )
            except Exception as e:
                logger.warning("调试页面加载失败: {}", e)
                return WorkerResponse(success=False, error=f"调试页面加载失败: {e}")

        # 创建 TaskExecutor（在 Worker 线程内，page 对象安全）
        if task_data:
            try:
                task_config = TaskConfig.from_dict(task_data)
                executor = TaskExecutor(
                    task_config,
                    template_vars,
                    screenshot_dir=Path(screenshot_dir) if screenshot_dir else None,
                    default_timeout=default_timeout,
                    navigation_timeout=navigation_timeout,
                )
                self._debug_executor = executor
            except Exception as e:
                logger.error("创建 TaskExecutor 失败: {}", e)
                return WorkerResponse(success=False, error=f"创建任务执行器失败: {e}")

        # 初始截图
        screenshot_url = None
        if self._debug_page and not self._debug_page.is_closed():
            try:
                from datetime import datetime

                stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                task_id = (
                    (task_data.get("task_id") or "debug")
                    if isinstance(task_data, dict)
                    else "debug"
                )
                filename = f"{task_id}_init_{stamp}.png"
                ss_dir = Path(screenshot_dir) if screenshot_dir else Path(".")
                ss_dir.mkdir(parents=True, exist_ok=True)
                local_path = str(ss_dir / filename)
                await self._debug_page.screenshot(path=local_path, full_page=True)
                screenshot_url = f"/temp/{filename}"
            except Exception as e:
                logger.warning("初始截图失败: {}", e)

        return WorkerResponse(
            success=True,
            data={"screenshot_url": screenshot_url},
        )

    async def _handle_debug_step(self, data: dict) -> WorkerResponse:
        """执行调试下一步。

        在 Worker 线程内调用 TaskExecutor.execute_step_at()，
        page 对象仅在 Worker 线程内访问，避免跨线程竞争。
        """
        if self._debug_page is None:
            return WorkerResponse(success=False, error="调试会话未启动，请先启动调试")
        if self._debug_page.is_closed():
            self._debug_page = None
            return WorkerResponse(success=False, error="调试页面已关闭")
        if self._debug_executor is None:
            return WorkerResponse(
                success=False, error="调试执行器未创建，请重新启动调试"
            )

        step_index = data.get("step_index", 0)
        logger.info("调试下一步: step_index={}", step_index)

        try:
            # TaskExecutor.execute_step_at 在 Worker 线程内执行，
            # page 对象安全访问，无需额外同步
            result = await self._debug_executor.execute_step_at(
                self._debug_page, step_index
            )
            return WorkerResponse(
                success=result.get("success", False),
                data=result,
            )
        except Exception as e:
            logger.exception("调试步骤执行异常 (step_index={})", step_index)
            return WorkerResponse(
                success=False,
                error=f"调试步骤执行异常: {e}",
            )

    async def _handle_debug_stop(self) -> WorkerResponse:
        """停止调试会话并清理 Worker 内部状态。"""
        # 清除调试执行器引用
        self._debug_executor = None

        # 关闭调试页面
        if self._debug_page is not None:
            same_as_main = self._debug_page is self._page
            try:
                if not self._debug_page.is_closed():
                    await self._debug_page.close()
            except Exception as e:
                logger.warning("关闭调试页面异常: {}", e)
            self._debug_page = None

            # 如果调试页面就是主页面，关闭后需要创建一个新页面，
            # 避免后续 browser 操作（_handle_debug_start / BrowserContextManager）因 _page 为空而失败
            if same_as_main:
                self._page = None
                try:
                    if self._context is not None and not self._context.is_closed():
                        self._page = await self._context.new_page()
                        # 重新应用反检测脚本和路由拦截（新页面未继承旧页面的设置）
                        # 使用与 _start_browser 一致的判断逻辑
                        if self._page is not None:
                            settings = self._last_browser_settings or {}
                            pure_mode = settings.get("pure_mode", False)
                            if not pure_mode or settings.get("stealth_mode", False):
                                await self._apply_stealth_and_routes(
                                    {"browser_settings": settings}
                                )
                except Exception:
                    logger.warning("创建替代页面失败，_page 保持 None")

        logger.info("调试会话已停止，Worker 内部状态已清理")
        return WorkerResponse(success=True, data="调试会话已停止")

    async def _handle_health_check(self) -> WorkerResponse:
        """处理浏览器健康检查命令。"""
        healthy = await self._health_check()
        return WorkerResponse(success=healthy, data=healthy)

    async def _handle_browser_acquire(self, data: dict) -> WorkerResponse:
        """处理浏览器获取命令（从 submit 队列派发）。

        外部线程（非 Worker 事件循环）通过 submit(CMD_BROWSER_ACQUIRE)
        调用此方法，确保 Worker 中的浏览器已就绪。
        """
        config = data.get("config", {})
        await self.ensure_browser(config)
        return WorkerResponse(success=True, data="Browser ready")

    async def _handle_browser_release(self) -> WorkerResponse:
        """处理浏览器释放命令。

        浏览器常驻 Worker 生命周期内，不会实际关闭。
        仅用于释放 BrowserContextManager 的引用计数。
        """
        return WorkerResponse(success=True, data="Browser released (alive in Worker)")

    async def close_browser(self) -> None:
        """关闭浏览器并释放所有资源。

        可从 Worker 事件循环内（同一线程）安全调用。
        外部调用者应使用 submit(CMD_BROWSER_CLOSE)。
        """
        await self._close_browser()

    async def _handle_browser_close(self) -> WorkerResponse:
        """处理 CMD_BROWSER_CLOSE —— 实际关闭浏览器进程。"""
        await self._close_browser()
        return WorkerResponse(success=True, data="Browser closed")

    async def ensure_browser(self, config: dict) -> None:
        """确保浏览器和页面已就绪（可从 Worker 事件循环内直接调用）。

        此方法供同线程调用者使用（如 BrowserContextManager），
        外部调用应使用 CMD_BROWSER_ACQUIRE 命令通过 submit 队列派发。
        每次调用都会关闭旧浏览器并启动新浏览器，不复用。
        """
        await self._close_browser()
        await self._start_browser(config)

    # ── 浏览器生命周期管理 ──

    def _build_launch_args(self, browser_settings: dict, channel: str = "playwright") -> list[str]:
        """构建浏览器启动参数。"""
        # Firefox 不支持 Chromium 专属参数
        if channel == "firefox":
            return []

        args = [
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--memory-pressure-off",
        ]
        if browser_settings.get("disable_web_security", False):
            args.append("--disable-web-security")
        if browser_settings.get("low_resource_mode", False):
            args.append("--blink-settings=imagesEnabled=false")

        # 用户自定义浏览器参数
        custom_args = str(browser_settings.get("browser_args", "") or "").strip()
        if custom_args:
            for flag in custom_args.splitlines():
                flag = flag.strip()
                if flag and flag not in args:
                    args.append(flag)
        return args

    def _build_context_options(self, browser_settings: dict) -> dict[str, Any]:
        """构建浏览器上下文选项。"""
        ctx_opts: dict[str, Any] = {
            "viewport": {
                "width": browser_settings.get("viewport_width", 1280),
                "height": browser_settings.get("viewport_height", 720),
            },
            "locale": browser_settings.get("locale", "zh-CN"),
            "timezone_id": browser_settings.get("timezone_id", "Asia/Shanghai"),
            "has_touch": False,
            "color_scheme": "light",
            "ignore_https_errors": browser_settings.get("ignore_https_errors", True),
        }

        # 自定义 User-Agent
        ua = (browser_settings.get("user_agent") or "").strip()
        if ua:
            ctx_opts["user_agent"] = ua

        # 自定义请求头
        extra_headers = self._get_extra_http_headers(browser_settings)
        if extra_headers:
            ctx_opts["extra_http_headers"] = extra_headers

        return ctx_opts

    async def _apply_stealth_and_routes(self, browser_settings: dict) -> None:
        """应用反检测脚本和路由拦截。"""
        # 低资源模式：路由拦截屏蔽图片/字体/媒体
        if browser_settings.get("low_resource_mode", False):
            await self._context.route("**/*", self._handle_low_resource_request)

        # 反检测脚本（默认关闭，需在方案设置中启用 stealth_mode）
        if browser_settings.get("stealth_mode", False):
            from app.utils.browser import STEALTH_INIT_SCRIPT

            custom = browser_settings.get("stealth_custom_script", "").strip()
            # 有自定义脚本则使用自定义，否则使用默认脚本
            script = custom or STEALTH_INIT_SCRIPT
            await self._page.add_init_script(script)

    async def _start_browser(self, config: dict) -> None:
        """启动浏览器。

        根据配置创建浏览器实例、上下文和页面。
        支持 headless/pure_mode/自定义启动参数/低资源模式/反检测脚本。
        根据 browser_channel 选择不同浏览器：playwright/msedge/chrome/firefox/custom。
        """
        from playwright.async_api import async_playwright

        browser_settings = config.get("browser_settings", {})
        self._last_browser_settings = browser_settings  # 缓存用于页面重建
        headless = browser_settings.get("headless", True)
        pure_mode = browser_settings.get("pure_mode", False)
        channel = browser_settings.get("browser_channel", "playwright")
        custom_path = browser_settings.get("browser_custom_path", "")

        logger.info("启动浏览器 (headless={}, pure_mode={}, channel={})", headless, pure_mode, channel)

        self._playwright = await async_playwright().start()

        try:
            if pure_mode:
                # 纯净模式：无扩展无自定义参数
                self._browser = await self._launch_browser(
                    self._playwright, channel, custom_path, headless, []
                )
                ctx_opts = {
                    "viewport": {
                        "width": browser_settings.get("viewport_width", 1280),
                        "height": browser_settings.get("viewport_height", 720),
                    }
                }
                self._context = await self._browser.new_context(**ctx_opts)
            else:
                launch_args = self._build_launch_args(browser_settings, channel)
                self._browser = await self._launch_browser(
                    self._playwright, channel, custom_path, headless, launch_args
                )
                ctx_opts = self._build_context_options(browser_settings)
                self._context = await self._browser.new_context(**ctx_opts)
                await self._apply_stealth_and_routes(browser_settings)

            self._page = await self._context.new_page()

            # 纯净模式下也需要应用反检测脚本（如果启用）
            if pure_mode and browser_settings.get("stealth_mode", False):
                await self._apply_stealth_and_routes(browser_settings)
        except Exception:
            logger.warning("浏览器启动中间步骤失败，回滚已创建的资源", exc_info=True)
            await self._close_browser()
            raise

        logger.info("浏览器启动完成")

    async def _launch_browser(self, playwright, channel: str, custom_path: str, headless: bool, launch_args: list):
        """根据 channel 启动对应的浏览器。"""
        if channel == "custom" and custom_path:
            # 检查路径是否存在
            if not Path(custom_path).exists():
                raise FileNotFoundError(f"自定义浏览器路径不存在: {custom_path}")
            logger.info("使用自定义浏览器路径: {}", custom_path)
            return await playwright.chromium.launch(
                executable_path=custom_path, headless=headless, args=launch_args
            )
        elif channel == "firefox":
            # Firefox 使用 firefox.launch()
            logger.info("使用 Firefox 浏览器")
            return await playwright.firefox.launch(headless=headless, args=launch_args)
        elif channel == "playwright":
            # Playwright 自带 Chromium
            logger.info("使用 Playwright Chromium")
            return await playwright.chromium.launch(headless=headless, args=launch_args)
        else:
            # msedge 或 chrome，使用 channel 参数
            logger.info("使用系统浏览器: {}", channel)
            return await playwright.chromium.launch(
                channel=channel, headless=headless, args=launch_args
            )

    async def _health_check(self) -> bool:
        """检查浏览器健康状态。

        调用 browser.is_connected() 判断浏览器实例是否仍存活。
        适用于命令执行前的预检查，避免使用已崩溃的浏览器。

        返回:
            bool: True 表示浏览器存活且可用，False 表示需要重建
        """
        if self._browser is None:
            return False
        try:
            return self._browser.is_connected()
        except Exception:
            logger.warning("浏览器健康检查异常", exc_info=True)
            return False

    @staticmethod
    def _is_normal_close_error(e: Exception) -> bool:
        """判断是否为正常的连接关闭错误。"""
        msg = str(e).lower()
        return "target closed" in msg or "connection closed" in msg

    async def _close_resource(
        self, resource: Any, name: str, graceful: bool, has_check: str = ""
    ) -> None:
        """统一关闭单个浏览器资源。

        参数:
            resource: 要关闭的资源对象
            name: 资源名称（用于日志）
            graceful: 是否优雅模式
            has_check: 可选的检查方法名（如 "is_closed", "is_connected"）
        """
        if resource is None:
            return
        try:
            # 如果指定了检查方法，先检查
            if has_check:
                check_fn = getattr(resource, has_check, None)
                if check_fn and check_fn():
                    return
            await resource.close()
        except Exception as e:
            if graceful:
                if self._is_normal_close_error(e):
                    logger.warning("关闭 {} 时连接已断开（正常）: {}", name, e)
                else:
                    logger.error("关闭 {} 异常: {}", name, e)

    async def _cleanup_browser(self, graceful: bool = True) -> None:
        """统一的浏览器资源清理方法。

        按 debug_page → page → context → browser → playwright 顺序关闭。

        参数:
            graceful: True 时区分日志级别（"target closed" → WARNING，其他 → ERROR）；
                      False 时异常全部静默（用于崩溃恢复等场景）。
        """
        if not graceful:
            logger.info("开始强制清理浏览器资源...")

        # 清除调试执行器
        self._debug_executor = None

        # 关闭调试页面
        if self._debug_page is not None:
            try:
                if not self._debug_page.is_closed():
                    await self._debug_page.close()
            except Exception:
                logger.debug("关闭调试页面失败", exc_info=True)
            self._debug_page = None

        # 关闭主页面
        await self._close_resource(self._page, "页面", graceful, "is_closed")
        self._page = None

        # 关闭上下文
        await self._close_resource(self._context, "上下文", graceful)
        self._context = None

        # 关闭浏览器
        if self._browser is not None:
            try:
                if self._browser.is_connected():
                    await self._browser.close()
                elif graceful:
                    logger.debug("浏览器已断开连接，跳过 close")
            except Exception as e:
                if graceful:
                    logger.error("关闭浏览器异常: {}", e)
        self._browser = None

        # 停止 Playwright 服务（AsyncPlaywright 使用 stop() 而非 close()）
        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception as e:
                if graceful:
                    if self._is_normal_close_error(e):
                        logger.warning("停止 Playwright 时连接已断开（正常）: {}", e)
                    else:
                        logger.error("停止 Playwright 异常: {}", e)
        self._playwright = None

        if graceful:
            logger.info("浏览器资源已清理")
        else:
            logger.warning("浏览器资源强制清理完成")

    async def _close_browser(self) -> None:
        """关闭浏览器并释放所有资源（优雅模式）。

        TargetClosedError / ConnectionClosedError 视为正常清理场景，
        仅记录 warning；其余异常记录为 ERROR。
        """
        await self._cleanup_browser(graceful=True)

    async def _force_cleanup(self) -> None:
        """强制清理所有浏览器资源。

        在 Worker 关闭或浏览器崩溃恢复时调用。
        所有异常静默处理，确保清理流程不会因单个资源关闭失败而中断。
        """
        await self._cleanup_browser(graceful=False)

    # ── 辅助方法 ──

    async def _wake_async(self) -> None:
        """唤醒事件循环。

        通过 run_coroutine_threadsafe 在 Worker 的事件循环上调度此协程，
        设置 _wake_event 使 _async_run 立即处理队列中的命令。
        """
        if self._wake_event is not None:
            self._wake_event.set()

    def _get_extra_http_headers(self, browser_settings: dict) -> dict[str, str]:
        """解析自定义 HTTP 请求头。

        从 browser_settings 中的 extra_headers_json 字段解析 JSON 对象。
        """
        import json

        raw_headers = str(browser_settings.get("extra_headers_json", "") or "").strip()
        if not raw_headers:
            return {}

        try:
            headers = json.loads(raw_headers)
            if isinstance(headers, dict):
                return {str(k): str(v) for k, v in headers.items() if k is not None}
            logger.warning("自定义请求头必须是 JSON 对象，已忽略")
        except Exception as exc:
            logger.warning("解析自定义请求头失败: {}", exc)
        return {}

    async def _handle_low_resource_request(self, route: Route) -> None:
        """低资源模式请求处理。

        拦截图片、字体、媒体资源请求并中止，减少内存和带宽消耗。
        """
        try:
            request = route.request
            blocked_types = {"image", "font", "media"}
            if request.resource_type in blocked_types:
                await route.abort()
                return
            await route.continue_()
        except Exception as e:
            # 页面/上下文已关闭时 route 操作会抛异常
            logger.debug("route 异常已忽略: {}", e)


# ── 模块级单例 ──

_worker: PlaywrightWorker | None = None
"""模块级全局 Worker 实例，首次调用 get_worker() 时创建。"""
_worker_lock = threading.Lock()


def get_worker() -> PlaywrightWorker:
    """获取全局 PlaywrightWorker 单例。

    首次调用时创建实例并自动 start()。
    后续调用返回已有实例；若实例已停止则自动重建。
    """
    global _worker
    if _worker is None or not _worker.is_alive():
        with _worker_lock:
            if _worker is None or not _worker.is_alive():
                if _worker is not None:
                    try:
                        _worker.stop()
                    except Exception:
                        logger.debug("停止旧 Worker 失败", exc_info=True)
                cleanup_orphan_browsers()
                new_worker = PlaywrightWorker()
                new_worker.start()
                _worker = new_worker
    return _worker


def shutdown_worker(timeout: float = 5) -> None:
    """关闭并清理全局 Worker 单例。shutdown 场景专用，不创建新实例。"""
    global _worker
    with _worker_lock:
        if _worker is not None and _worker.is_alive():
            _worker.stop(timeout=timeout)
        _worker = None


# ── 孤儿浏览器清理 ──


def cleanup_orphan_browsers() -> None:
    """清理孤儿 Playwright 浏览器进程。

    扫描并杀掉由 Campus-Auth 启动但已失去 Python 父进程的浏览器实例。
    仅清理 Playwright 管理的浏览器（可执行路径或命令行包含 "ms-playwright"），
    不会误杀用户自行安装的 Chrome/Edge/Brave 等浏览器。
    """
    import psutil

    killed = 0
    for proc in psutil.process_iter(["pid", "exe", "cmdline"]):
        try:
            info = proc.info
            exe = (info.get("exe") or "").lower()
            cmdline = " ".join(info.get("cmdline") or []).lower()
            is_playwright_managed = "ms-playwright" in exe or "ms-playwright" in cmdline
            is_browser = any(
                kw in exe or kw in cmdline
                for kw in ("chrom", "firefox")
            )
            if is_playwright_managed and is_browser:
                proc.kill()
                killed += 1
                logger.debug("已终止孤儿浏览器进程 PID={}", info["pid"])
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        except Exception:
            logger.debug("终止进程异常", exc_info=True)

    if killed:
        logger.info("已终止 {} 个孤儿浏览器进程", killed)
    else:
        logger.debug("未发现孤儿 Playwright 浏览器进程")
