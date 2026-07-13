"""Playwright Worker — Actor 模型浏览器自动化工作线程。

架构说明:
  PlaywrightWorker 采用与 MonitorService 相同的 Actor 模型:
    - 外部调用者通过 submit() 提交 WorkerCommand 到内部队列
    - 常驻守护线程运行独立 asyncio 事件循环
    - _async_run() 协程从队列取命令并派发
    - 所有 Playwright 操作限制在 Worker 线程内执行，避免跨线程竞争

命令派发流程:
  submit() → asyncio.Queue.put_nowait(cmd) → await get() 唤醒
  → _async_run() 取出命令 → _dispatch() → handler

NOT-TO-DO: 不要拆分此文件。Worker 是浏览器自动化核心，生命周期紧密
（启动、命令分发、清理），拆分收益不大反而增加复杂度。
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from playwright.async_api import Route

from app.constants import (
    BROWSER_DATA_DIR,
    WORKER_JOIN_TIMEOUT,
    WORKER_READY_TIMEOUT,
    WORKER_SUBMIT_TIMEOUT,
)
from app.services.worker_port import (
    CMD_BROWSER,
    CMD_DEBUG_START,
    CMD_DEBUG_STEP,
    CMD_DEBUG_STOP,
    CMD_LOGIN,
    CMD_SHUTDOWN,
    WorkerPort,
    WorkerResponse,
)
from app.utils.logging import get_logger

logger = get_logger("playwright_worker", source="backend")


# ── 数据结构 ──


@dataclass
class WorkerCommand:
    """从 API/服务线程提交到 Worker 线程的命令单元。"""

    type: str  # 命令类型，对应 CMD_* 常量
    data: dict = field(default_factory=dict)  # 命令参数
    response_event: threading.Event | None = None  # 调用方等待此事件以获取结果
    response_data: Any = None  # 消费者线程设置返回数据
    cancelled: bool = False  # 超时后标记为已取消，跳过执行


# ── Worker 类 ──


class PlaywrightWorker(WorkerPort):
    """浏览器自动化工作线程。

    通过 Actor 模型的消息队列，将 Playwright 操作隔离在独立线程中执行。
    外部模块通过 submit() 提交任务，可选择同步等待执行结果。
    """

    def __init__(self) -> None:
        self._cmd_queue: asyncio.Queue[WorkerCommand] = asyncio.Queue(maxsize=50)
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
            None  # BrowserTaskRunner 实例，调试步骤执行时在 Worker 线程内使用
        )
        self._last_browser_settings: dict | None = None  # 缓存最近一次浏览器设置

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
        if self.is_alive():
            return
        self._stop_event.clear()
        self._worker_ready.clear()

        # BUG-036 修复：重启时防御性重置浏览器相关状态
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._debug_page = None
        self._debug_executor = None
        self._last_browser_settings = None
        self._consumer_thread = threading.Thread(
            target=self._worker_entry,
            daemon=True,
            name="playwright-worker",
        )
        self._consumer_thread.start()
        # 等待事件循环就绪（最多 5 秒）
        self._worker_ready.wait(timeout=WORKER_READY_TIMEOUT)
        if not self._worker_ready.is_set():
            logger.warning("Worker 启动失败: 事件循环超时 ({}s)", WORKER_READY_TIMEOUT)
        else:
            logger.info("Worker 启动成功")

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
        loop = self._loop
        shutdown_cmd = WorkerCommand(type=CMD_SHUTDOWN)
        if loop is not None and loop.is_running():

            def _put_shutdown():
                try:
                    self._cmd_queue.put_nowait(shutdown_cmd)
                except asyncio.QueueFull:
                    logger.warning("Worker 命令队列已满，强制停止事件循环")
                    with contextlib.suppress(RuntimeError):
                        loop.call_soon_threadsafe(loop.stop)

            try:
                loop.call_soon_threadsafe(_put_shutdown)
            except RuntimeError:
                logger.warning("loop 已关闭，无法入队 SHUTDOWN 命令")
        else:
            try:
                self._cmd_queue.put_nowait(shutdown_cmd)
            except asyncio.QueueFull:
                logger.warning("Worker 命令队列已满，强制停止事件循环")
                if loop is not None:
                    with contextlib.suppress(RuntimeError):
                        loop.call_soon_threadsafe(loop.stop)

        # 等待消费者线程正常退出
        if self._consumer_thread:
            self._consumer_thread.join(timeout=timeout)
            # 超时后强制停止事件循环
            if self._consumer_thread.is_alive():
                logger.warning("Worker 线程退出超时 ({}s)，强制停止", timeout)
                loop = self._loop
                if loop is not None:
                    loop.call_soon_threadsafe(loop.stop)
                self._consumer_thread.join(timeout=WORKER_JOIN_TIMEOUT)

        # 排干队列中残留的命令，通知等待方 Worker 已关闭
        while True:
            try:
                pending = self._cmd_queue.get_nowait()
            except asyncio.QueueEmpty:
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
        timeout: float | None = None,
    ) -> WorkerResponse:
        """提交命令到 Worker 队列。

        创建 WorkerCommand 放入内部 asyncio.Queue。
        若 wait=True 则阻塞等待命令执行完成。

        参数:
            cmd_type: 命令类型（CMD_* 常量）
            data: 命令参数字典
            wait: 是否同步等待执行结果
            timeout: 等待超时秒数（None 表示使用 WORKER_SUBMIT_TIMEOUT 默认值）

        返回:
            WorkerResponse 对象
        """
        # timeout=None 时回退到默认超时（与 WorkerPort 协议签名一致）
        if timeout is None:
            timeout = WORKER_SUBMIT_TIMEOUT

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
                    logger.warning("Worker 消费者线程已死亡，尝试重启")
                    try:
                        self.start()
                    except Exception as e:
                        logger.exception("重启消费者线程异常: {}", e)
                        return WorkerResponse(
                            success=False, error="消费者线程已死亡且重启失败"
                        )

        cmd = WorkerCommand(
            type=cmd_type,
            data=data or {},
            response_event=threading.Event() if wait else None,
        )
        loop = self._loop
        if loop is not None and loop.is_running():
            # QueueFull 在 loop 线程内被吞，wait=True 靠 response_event.wait(timeout) 超时返回
            # wait=False 无法同步获知队列满，但 maxsize=50 几乎不会满
            try:
                loop.call_soon_threadsafe(self._cmd_queue.put_nowait, cmd)
            except RuntimeError:
                # loop 关闭瞬间，回退直接 put_nowait
                try:
                    self._cmd_queue.put_nowait(cmd)
                except asyncio.QueueFull:
                    return WorkerResponse(success=False, error="命令队列已满，提交超时")
        else:
            # loop 未运行，直接 put_nowait（同步方法，无需 loop）
            try:
                self._cmd_queue.put_nowait(cmd)
            except asyncio.QueueFull:
                return WorkerResponse(success=False, error="命令队列已满，提交超时")

        if not wait:
            return WorkerResponse(success=True)

        # 阻塞等待命令执行完成
        if not cmd.response_event.wait(timeout=timeout):
            # 超时：标记命令为已取消
            cmd.cancelled = True
            # 传播取消信号：若命令携带 cancel_event，设置它以中断正在执行的会话
            # （例如 LoginSession 在重试循环中会检查 cancel_event）
            cancel = cmd.data.get("cancel_event")
            if cancel is not None:
                cancel.set()
            return WorkerResponse(success=False, error="命令执行超时或无响应")

        if isinstance(cmd.response_data, WorkerResponse):
            return cmd.response_data
        return WorkerResponse(success=True, data=cmd.response_data)

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
                except Exception as e:
                    logger.exception("Worker 清理异常: {}", e)
                try:
                    loop.close()
                except Exception:
                    logger.warning("关闭事件循环失败", exc_info=True)
            self._loop = None
            logger.info("Worker 事件循环已关闭")

    async def _async_run(self) -> None:
        """异步主循环 — 从 asyncio.Queue 获取命令并派发。

        使用 asyncio.Queue.get() 原生阻塞，零延迟、零轮询。
        外部 submit()/stop() 通过 put_nowait(cmd) 直接入队，asyncio.Queue.get() 自动唤醒。
        收到 CMD_SHUTDOWN 后退出循环，触发事件循环停止。
        """
        try:
            while not self._stop_event.is_set():
                cmd = await self._cmd_queue.get()
                await self._dispatch(cmd)
                self._cmd_queue.task_done()

                # SHUTDOWN 命令：退出主循环
                if cmd.type == CMD_SHUTDOWN:
                    logger.debug("Worker 收到关闭命令，退出主循环")
                    return
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
            elif cmd.type == CMD_BROWSER:
                result = await self._handle_browser_task(cmd.data)
            elif cmd.type == CMD_DEBUG_START:
                result = await self._handle_debug_start(cmd.data)
            elif cmd.type == CMD_DEBUG_STEP:
                result = await self._handle_debug_step(cmd.data)
            elif cmd.type == CMD_DEBUG_STOP:
                result = await self._handle_debug_stop()
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
        """处理登录命令 — 委托给 LoginSession。

        LoginSession 在单次 Worker 调用内复用浏览器并管理重试循环，
        所有终态（成功/失败/取消/耗尽）都关闭浏览器。
        """
        from app.workers.login_models import AttemptOutcomeType
        from app.workers.login_session import LoginSession

        config = data.get("config", {})
        cancel_event: threading.Event | None = data.get("cancel_event")

        if cancel_event is None:
            # 防御性：Worker 不应收到无 cancel_event 的登录命令
            logger.error(
                "登录命令缺少 cancel_event: task_id={}",
                config.get("task_id", "unknown"),
            )
            return WorkerResponse(success=False, error="cancel_event 缺失")

        try:
            session = LoginSession(config, cancel_event)
            outcome = await session.run()
            return WorkerResponse(
                success=outcome.type == AttemptOutcomeType.SUCCESS,
                data=outcome.message
                if outcome.type == AttemptOutcomeType.SUCCESS
                else None,
                error=outcome.message
                if outcome.type != AttemptOutcomeType.SUCCESS
                else None,
            )
        except Exception as e:
            # 程序异常（Attempt 未捕获的）在此兜底，与现有行为一致
            logger.exception(
                "登录执行异常: task_id={}", config.get("task_id", "unknown")
            )
            return WorkerResponse(success=False, error=str(e))

    async def _handle_browser_task(self, data: dict) -> WorkerResponse:
        """处理通用浏览器任务（签到/打卡等）。

        与 _handle_login 的区别：
        - 不走 LoginSession 重试循环
        - 不记录登录历史
        - 直接用 BrowserTaskRunner.execute(page) 执行步骤
        """
        from app.constants import PROJECT_ROOT
        from app.tasks import BrowserTaskRunner, TaskConfig, TaskManager

        config = data.get("config", {})
        cancel_event: threading.Event | None = data.get("cancel_event")

        if cancel_event is None:
            logger.error("浏览器任务命令缺少 cancel_event")
            return WorkerResponse(success=False, error="cancel_event 缺失")

        task_id = config.get("active_task", "")
        if not task_id:
            logger.warning("浏览器任务命令缺少 active_task")
            return WorkerResponse(success=False, error="未指定任务")

        # 加载任务定义
        task_mgr = TaskManager(PROJECT_ROOT / "tasks")
        task_detail = task_mgr.get_task_detail(task_id)
        if not task_detail or task_detail.get("type") != "browser":
            logger.warning("浏览器任务不存在或类型不匹配: task_id={}", task_id)
            return WorkerResponse(success=False, error=f"浏览器任务不存在: {task_id}")

        # TaskConfig 是 dataclass，用 from_dict 而非 **dict
        # （dict 含 id/type/raw_json 等非字段键）
        try:
            task_config = TaskConfig.from_dict(task_detail)
        except Exception as e:
            logger.exception("解析 TaskConfig 失败: task_id={}", task_id)
            return WorkerResponse(success=False, error=f"任务配置解析失败: {e}")

        try:
            # 确保浏览器就绪（复用现有 ensure_browser）
            await self.ensure_browser(config)

            if self._page is None or self._page.is_closed():
                return WorkerResponse(success=False, error="浏览器页面初始化失败")

            # 执行任务
            runner = BrowserTaskRunner(
                task_config,
                template_vars=config.get("template_vars", {}),
                cancel_event=cancel_event,
            )
            success, message = await runner.execute(self._page)
            return WorkerResponse(
                success=success,
                data=message if success else None,
                error=None if success else message,
            )
        except Exception as e:
            logger.exception("浏览器任务执行异常: task_id={}", task_id)
            return WorkerResponse(success=False, error=str(e))
        finally:
            # 一次性任务，完成后关闭浏览器（与 _handle_login 一致）
            await self._close_browser()

    async def _cleanup_debug_session(self):
        """统一清理调试会话资源。"""
        self._debug_executor = None
        if self._debug_page is not None:
            try:
                if not self._debug_page.is_closed():
                    await self._debug_page.close()
            except Exception as e:
                logger.warning("关闭旧调试页面失败: {}", e)
            self._debug_page = None
        self._page = None

    async def _handle_debug_start(self, data: dict) -> WorkerResponse:
        """启动调试会话。

        在 Worker 线程内管理浏览器生命周期：
        1. 健康检查 → 不健康则重建浏览器
        2. 导航到任务 URL
        3. 创建 BrowserTaskRunner（线程安全 — 所有 Playwright 操作在 Worker 线程内执行）
        4. 初始截图并返回 URL

        注意：_debug_page 与 _page 共享同一 page 对象引用（别名），
        调试会话结束后 _cleanup_debug_session 会将 _debug_page 置 None。
        """
        from app.constants import DEFAULT_STEP_TIMEOUT_MS
        from app.tasks import BrowserTaskRunner, TaskConfig

        config = data.get("config", {})
        task_url = data.get("task_url", "")
        task_data = data.get("task_data", {})
        template_vars = data.get("template_vars", data.get("env_vars", {}))
        screenshot_dir = data.get("screenshot_dir", "")
        default_timeout = data.get("default_timeout", DEFAULT_STEP_TIMEOUT_MS)
        navigation_timeout = data.get(
            "navigation_timeout", BrowserTaskRunner.DEFAULT_NAVIGATION_TIMEOUT
        )

        # 守卫：若已有调试会话，先清理
        if self._debug_page is not None:
            logger.debug("检测到残留调试会话，自动清理")
            await self._cleanup_debug_session()

        # 检查浏览器健康状态，不健康则重建
        if not await self._health_check():
            await self._close_browser()
            await self._start_browser(config)

        if self._page is None or self._page.is_closed():
            if self._context is None:
                return WorkerResponse(success=False, error="浏览器页面初始化失败")
            try:
                self._page = await self._context.new_page()
            except Exception as e:
                logger.warning(
                    "调试页面重建失败 (task_id={}): {}",
                    task_data.get("task_id", "unknown")
                    if isinstance(task_data, dict)
                    else "unknown",
                    e,
                )
                return WorkerResponse(success=False, error=f"浏览器页面初始化失败: {e}")

        # _debug_page 是当前调试会话的页面；_page 保持为普通任务页面，二者不应混用
        # 此处共享同一底层 page 对象引用，调试会话结束后由 _cleanup_debug_session 置 None
        self._debug_page = self._page
        self._debug_executor = None

        # 加载任务页面
        if task_url:
            try:
                await self._page.goto(
                    task_url, wait_until="domcontentloaded", timeout=navigation_timeout
                )
            except Exception as e:
                logger.warning(
                    "调试页面加载失败 (task_id={}): {}",
                    task_data.get("task_id", "unknown")
                    if isinstance(task_data, dict)
                    else "unknown",
                    e,
                )
                return WorkerResponse(success=False, error=f"调试页面加载失败: {e}")

        # 创建 BrowserTaskRunner（在 Worker 线程内，page 对象安全）
        if task_data:
            try:
                task_config = TaskConfig.from_dict(task_data)
                executor = BrowserTaskRunner(
                    task_config,
                    template_vars,
                    screenshot_dir=Path(screenshot_dir) if screenshot_dir else None,
                    default_timeout=default_timeout,
                    navigation_timeout=navigation_timeout,
                )
                self._debug_executor = executor
            except Exception as e:
                logger.exception("创建 BrowserTaskRunner 异常: {}", e)
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
                # 计算相对于 temp 目录的子路径，确保 URL 与实际存储路径一致
                from app.constants import TEMP_DIR

                try:
                    rel = ss_dir.relative_to(TEMP_DIR)
                    screenshot_url = (
                        f"/temp/{rel.as_posix()}/{filename}"
                        if str(rel) != "."
                        else f"/temp/{filename}"
                    )
                except ValueError:
                    screenshot_url = f"/temp/{filename}"
            except Exception as e:
                logger.warning("初始截图失败 (task_id={}): {}", task_id, e)

        return WorkerResponse(
            success=True,
            data={"screenshot_url": screenshot_url},
        )

    async def _handle_debug_step(self, data: dict) -> WorkerResponse:
        """执行调试下一步。

        在 Worker 线程内调用 BrowserTaskRunner.execute_step_at()，
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
        logger.debug("调试下一步: step_index={}", step_index)

        try:
            # BrowserTaskRunner.execute_step_at 在 Worker 线程内执行，
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
        await self._cleanup_debug_session()

        # 关闭整个浏览器（用户点击"停止并关闭"期望完全关闭）
        await self._close_browser()

        logger.info("停止调试会话成功")
        return WorkerResponse(success=True, data="调试会话已停止")

    async def ensure_browser(self, config: dict) -> None:
        """确保浏览器和页面已就绪（可从 Worker 事件循环内直接调用）。

        此方法供同线程调用者使用（如 BrowserContextManager）。
        复用已存在的浏览器实例，仅在未就绪或配置变更时重建。
        """
        browser_settings = config.get("browser_settings", {})
        has_browser = self._browser is not None or self._context is not None
        if (
            has_browser
            and await self._health_check()
            and self._last_browser_settings == browser_settings
        ):
            return
        await self._close_browser()
        await self._start_browser(config)

    # ── 浏览器生命周期管理 ──

    _CHROMIUM_ONLY_FLAGS = {
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu",
        "--memory-pressure-off",
        "--disable-web-security",
    }

    # 安全敏感参数黑名单：用户自定义 browser_args 中不允许出现
    _BLOCKED_BROWSER_ARGS = {
        "--remote-debugging-port",
        "--remote-debugging-address",
        "--user-data-dir",
        "--load-extension",
        "--disable-extensions-except",
        "--enable-automation",
        "--remote-allow-origins",
        "--proxy-server",
        "--proxy-bypass-list",
    }

    @staticmethod
    def _get_user_data_dir(channel: str) -> Path:
        """获取持久化上下文的用户数据目录（按浏览器 channel 隔离）。"""
        return BROWSER_DATA_DIR / channel

    def _build_launch_args(
        self, browser_settings: dict, channel: str = "playwright"
    ) -> list[str]:
        """构建浏览器启动参数。"""
        args = []

        if channel != "firefox":
            args.extend(
                [
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--memory-pressure-off",
                ]
            )
            if browser_settings.get("disable_web_security", False):
                args.append("--disable-web-security")
            if browser_settings.get("low_resource_mode", False):
                args.append("--blink-settings=imagesEnabled=false")

        # 用户自定义参数（所有 engine 都解析）
        custom_args = str(browser_settings.get("browser_args", "") or "").strip()
        if custom_args:
            for flag in custom_args.splitlines():
                flag = flag.strip()
                if not flag or flag.startswith("#"):
                    continue
                if channel == "firefox" and flag in self._CHROMIUM_ONLY_FLAGS:
                    continue
                # 检查安全敏感参数黑名单（匹配 flag 名称部分，忽略 = 后的值）
                flag_name = flag.split("=", 1)[0]
                if flag_name in self._BLOCKED_BROWSER_ARGS:
                    logger.warning("已过滤安全敏感浏览器参数: {}", flag_name)
                    continue
                if flag not in args:
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

        # 网卡绑定代理（SOCKS5 Forwarder）
        if browser_settings.get("bind_proxy"):
            ctx_opts["proxy"] = {"server": browser_settings["bind_proxy"]}

        return ctx_opts

    async def _apply_stealth_and_routes(self, browser_settings: dict) -> None:
        """应用反检测脚本和路由拦截。"""
        if self._context is None:
            return

        # 低资源模式：路由拦截屏蔽图片/字体/媒体
        if browser_settings.get("low_resource_mode", False):
            await self._context.route("**/*", self._handle_low_resource_request)

        # 反检测脚本（默认关闭，需在方案设置中启用 stealth_mode）
        if browser_settings.get("stealth_mode", False):
            from app.utils.browser import STEALTH_INIT_SCRIPT

            custom = browser_settings.get("stealth_custom_script", "").strip()
            # 有自定义脚本则使用自定义，否则使用默认脚本
            script = custom or STEALTH_INIT_SCRIPT
            # 挂载到 context 级别，自动继承到所有新页面（含 popup、debug_page）
            await self._context.add_init_script(script)

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

        logger.debug(
            "启动浏览器 (headless={}, pure_mode={}, channel={})",
            headless,
            pure_mode,
            channel,
        )

        self._playwright = await async_playwright().start()
        persistent = browser_settings.get("persistent_context", False)

        try:
            if persistent:
                # 持久化上下文：使用独立用户数据目录，保留 cookies
                user_data_dir = self._get_user_data_dir(channel)
                user_data_dir.mkdir(parents=True, exist_ok=True)
                launch_args = (
                    []
                    if pure_mode
                    else self._build_launch_args(browser_settings, channel)
                )
                ctx_opts = self._build_context_options(browser_settings)
                logger.debug("使用持久化上下文: {}", user_data_dir)
                self._context = await self._launch_persistent_context(
                    self._playwright,
                    channel,
                    custom_path,
                    headless,
                    launch_args,
                    str(user_data_dir),
                    ctx_opts,
                )
                # launch_persistent_context 直接返回 context，无独立 browser 对象
                self._browser = None
                # 非纯净模式下应用反检测和路由拦截
                if not pure_mode:
                    await self._apply_stealth_and_routes(browser_settings)
            elif pure_mode:
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
                # 网卡绑定代理（pure_mode 也要注入，否则浏览器流量不走指定网卡）
                if browser_settings.get("bind_proxy"):
                    ctx_opts["proxy"] = {"server": browser_settings["bind_proxy"]}
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
            # 纯净模式不注入反检测脚本——设计意图
        except Exception:
            logger.warning("浏览器启动失败，回滚资源", exc_info=True)
            await self._close_browser()
            raise

        logger.info("浏览器启动成功")

    def _resolve_launcher(self, playwright, channel: str, custom_path: str):
        """根据 channel 解析对应的 launcher 对象。"""
        if channel == "custom" and custom_path:
            if not Path(custom_path).exists():
                raise FileNotFoundError(f"自定义浏览器路径不存在: {custom_path}")
            custom_engine = (self._last_browser_settings or {}).get(
                "custom_browser_engine", "auto"
            )
            if custom_engine == "firefox":
                engine = "firefox"
            elif custom_engine == "webkit":
                engine = "webkit"
            else:
                engine = "chromium"
            logger.debug("使用自定义浏览器: {} (engine={})", custom_path, engine)
            return getattr(playwright, engine), custom_path
        elif channel == "firefox":
            logger.debug("使用 Firefox 浏览器")
            return playwright.firefox, None
        elif channel == "playwright":
            logger.debug("使用 Playwright Chromium")
            return playwright.chromium, None
        else:
            logger.debug("使用系统浏览器: {}", channel)
            return playwright.chromium, None

    async def _launch_browser(
        self,
        playwright,
        channel: str,
        custom_path: str,
        headless: bool,
        launch_args: list,
    ):
        """根据 channel 启动对应的浏览器（非持久化模式）。"""
        launcher, resolved_path = self._resolve_launcher(
            playwright, channel, custom_path
        )
        kwargs = {"headless": headless, "args": launch_args}
        if resolved_path:
            kwargs["executable_path"] = resolved_path
        elif channel not in ("firefox", "playwright"):
            kwargs["channel"] = channel
        return await launcher.launch(**kwargs)

    async def _launch_persistent_context(
        self,
        playwright,
        channel: str,
        custom_path: str,
        headless: bool,
        launch_args: list,
        user_data_dir: str,
        ctx_opts: dict,
    ):
        """使用持久化上下文启动浏览器（保留 cookies）。"""
        launcher, resolved_path = self._resolve_launcher(
            playwright, channel, custom_path
        )
        kwargs = {"headless": headless, "args": launch_args, **ctx_opts}
        if resolved_path:
            kwargs["executable_path"] = resolved_path
        elif channel not in ("firefox", "playwright"):
            kwargs["channel"] = channel
        return await launcher.launch_persistent_context(user_data_dir, **kwargs)

    async def _health_check(self) -> bool:
        """检查浏览器健康状态。

        持久化上下文模式下尝试访问 pages 检测存活；
        非持久化模式调用 browser.is_connected()。

        返回:
            bool: True 表示浏览器存活且可用，False 表示需要重建
        """
        # 持久化上下文模式：browser 为 None，通过 context.pages 检测
        if self._browser is None:
            if self._context is None:
                return False
            try:
                # 访问 pages 属性会抛出异常如果底层浏览器已崩溃
                _ = self._context.pages
                return True
            except Exception:
                logger.debug("持久化上下文健康检查失败，浏览器可能已崩溃")
                return False
        try:
            return self._browser.is_connected()
        except Exception:
            logger.exception("浏览器健康检查异常")
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
                    logger.debug("关闭 {} 时连接已断开（正常）", name)
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
            logger.debug("开始强制清理浏览器资源")

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
                        logger.debug("停止 Playwright 时连接已断开（正常）")
                    else:
                        logger.error("停止 Playwright 异常: {}", e)
        self._playwright = None

        if graceful:
            logger.info("浏览器资源清理成功")
        else:
            logger.info("浏览器资源强制清理成功")

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
                result = {}
                for k, v in headers.items():
                    if k is None:
                        continue
                    k_str, v_str = str(k), str(v)
                    if len(k_str) > 256 or len(v_str) > 4096:
                        logger.warning(
                            "请求头过长，已跳过: {} ({}B)", k_str[:32], len(k_str)
                        )
                        continue
                    if "\r" in k_str or "\n" in k_str:
                        logger.warning("请求头 key 含换行符，已跳过: {}", k_str[:32])
                        continue
                    result[k_str] = v_str
                return result
            logger.warning("自定义请求头格式无效: 应为 JSON 对象，已忽略")
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
            logger.debug("路由异常已忽略: {}", e)


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

# 冷却期：启动流程中 application.py → engine.py 短时间内连续调用，
# 第二次起直接跳过，避免重复 5-8s 的全进程扫描
_CLEANUP_COOLDOWN: float = 30.0
_last_cleanup_time: float = 0.0
_cleanup_lock = threading.Lock()

# 浏览器进程名关键字（用于快速过滤，psutil 的 name 缓存廉价）
_BROWSER_NAME_KEYWORDS = ("chrome", "chromium", "msedge", "firefox", "brave")


def cleanup_orphan_browsers(*, force: bool = False) -> None:
    """清理孤儿 Playwright 浏览器进程。

    扫描并杀掉由 Campus-Auth 启动但已失去 Python 父进程的浏览器实例。
    仅清理 Playwright 管理的浏览器（可执行路径或命令行包含 "ms-playwright"），
    不会误杀用户自行安装的 Chrome/Edge/Brave 等浏览器。
    同时验证父进程存活状态，避免误杀仍在运行的浏览器进程。

    启动流程中多处调用时通过 30s 冷却期自动去重，避免重复全进程扫描。

    Args:
        force: 强制执行，忽略冷却期（用于确保清理完成的场景）
    """
    global _last_cleanup_time

    # 冷却期检查：启动流程中 application.py → engine.py 短时间内连续调用
    with _cleanup_lock:
        now = time.monotonic()
        if (
            not force
            and _last_cleanup_time
            and now - _last_cleanup_time < _CLEANUP_COOLDOWN
        ):
            logger.debug(
                "孤儿浏览器清理在冷却期内，跳过 (距上次 {:.1f}s)",
                now - _last_cleanup_time,
            )
            return
        _last_cleanup_time = now

    import psutil

    killed = 0
    # 关键优化：process_iter 只取 name（廉价，psutil 内部缓存），
    # 用 name 快速过滤后再对候选进程做 exe/cmdline/parent 检查（昂贵）
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            name = (proc.info.get("name") or "").lower()
            # 快速过滤：名称不含浏览器关键字的直接跳过
            if not any(kw in name for kw in _BROWSER_NAME_KEYWORDS):
                continue

            # 仅对浏览器候选进程做昂贵检查（打开进程句柄读 exe/cmdline）
            try:
                exe = (proc.exe() or "").lower()
                cmdline = " ".join(proc.cmdline() or []).lower()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

            is_playwright_managed = "ms-playwright" in exe or "ms-playwright" in cmdline
            if not is_playwright_managed:
                continue

            try:
                parent = proc.parent()
                is_orphan = parent is None or not parent.is_running()
            except psutil.NoSuchProcess:
                is_orphan = True

            if is_orphan:
                proc.kill()
                killed += 1
                logger.debug("已终止孤儿浏览器进程 PID={}", proc.pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        except Exception as e:
            logger.warning("终止进程失败: {}", e, exc_info=True)

    if killed:
        logger.info("终止孤儿浏览器进程成功: {} 个", killed)
    else:
        logger.debug("未发现孤儿 Playwright 浏览器进程")
