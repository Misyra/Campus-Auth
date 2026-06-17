"""TaskExecutor — 任务执行中心。

双线程池架构：
- login_pool(1) — 登录专用，永不阻塞
- task_pool(2, queue=10, 懒初始化) — 定时任务，BoundedExecutor 限制队列

登录去重机制：_login_future 防止重复提交。
"""

from __future__ import annotations

import sys
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

from app.utils.logging import get_logger
from app.utils.shell_policy import ShellCommandPolicy
from app.utils.shell_utils import detect_shells, get_default_shell

logger = get_logger("task_executor", source="backend")


class NullTaskExecutor:
    """空任务执行器 — 轻量模式下使用，避免 None 检查。"""

    def has_enabled_tasks(self) -> bool:
        return False

    def shutdown(self, wait: bool = True) -> None:
        pass

    def execute_task_async(self, task_id: str) -> Future | None:
        return None

    def execute_login_async(self, cancel_event=None) -> Future | None:
        return None

    def execute_task(self, task_id: str) -> tuple[bool, str]:
        return False, "轻量模式下不支持定时任务"

    def execute_login(self, cancel_event=None) -> Any:
        return None

    def list_tasks(self) -> list[dict]:
        return []

    def get_task(self, task_id: str) -> dict | None:
        return None

    def save_task(self, task_id: str, config: dict) -> tuple[bool, str]:
        return False, "轻量模式下不支持定时任务"

    def delete_task(self, task_id: str) -> tuple[bool, str]:
        return False, "轻量模式下不支持定时任务"

    def get_history(self, task_id: str) -> list[dict]:
        return []


class BoundedExecutor:
    """带队列长度限制的线程池执行器。

    封装 ThreadPoolExecutor，用 Semaphore 限制待执行任务数量。
    队列满时 submit 抛出 RuntimeError，防止任务堆积。
    """

    def __init__(self, max_workers: int, queue_size: int) -> None:
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="task-exec",
        )
        # Semaphore 初始值 = queue_size，控制同时排队的任务数
        self._semaphore = threading.Semaphore(queue_size)

    def submit(self, func, *args, **kwargs) -> Future:
        """提交任务到线程池。

        Raises:
            RuntimeError: 队列已满，无法提交更多任务
        """
        if not self._semaphore.acquire(blocking=False):
            raise RuntimeError("任务队列已满，无法提交更多任务")

        try:
            future = self._executor.submit(func, *args, **kwargs)
        except Exception:
            self._semaphore.release()
            raise
        # 任务完成或取消时释放信号量
        future.add_done_callback(lambda _: self._semaphore.release())
        return future

    def shutdown(self, wait: bool = True) -> None:
        """关闭线程池。

        Note:
            当 wait=False 时，已提交但尚未执行的任务的信号量计数不会被释放，
            因为 done_callback 可能未被触发。这仅影响优雅退出场景，
            进程退出后信号量随资源回收，不会造成实际问题。
        """
        self._executor.shutdown(wait=wait)


class TaskExecutor:
    """任务执行中心 — 双线程池 + 登录去重。

    Attributes:
        _login_pool: 登录专用线程池（1 个工作线程，立即创建）
        _task_pool: 定时任务线程池（懒初始化，无定时任务时不创建）
        _login_future: 当前登录 Future，用于去重
        _login_lock: 保护 _login_future 的锁
    """

    def __init__(
        self,
        registry: Any,
        history_store: Any,
        worker_getter: Callable,
        login_history: Any = None,
        profile_service: Any = None,
        get_runtime_config: Callable[[], dict] | None = None,
    ) -> None:
        self._registry = registry
        self._history_store = history_store
        self._worker_getter = worker_getter
        self._login_history = login_history
        self._profile_service = profile_service
        self._get_runtime_config = get_runtime_config

        # 线程池：登录池立即创建，任务池懒初始化（无定时任务时不创建线程）
        self._login_pool = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="login-exec",
        )
        self._task_pool: BoundedExecutor | None = None
        self._task_pool_lock = threading.Lock()

        # 登录去重
        self._login_future: Future | None = None
        self._login_lock = threading.Lock()
        self._login_cancel_event: threading.Event | None = None

        # Shell 安全策略
        self._shell_policy = ShellCommandPolicy(
            allowlist=[shell["path"] for shell in detect_shells()]
        )

    def set_runtime_config_getter(self, getter: Callable[[], dict]) -> None:
        """设置运行时配置获取器（公共接口）。"""
        self._get_runtime_config = getter

    def _ensure_task_pool(self) -> BoundedExecutor:
        """确保定时任务线程池存在（懒初始化，双检锁）。"""
        if self._task_pool is None:
            with self._task_pool_lock:
                if self._task_pool is None:
                    self._task_pool = BoundedExecutor(max_workers=2, queue_size=10)
        return self._task_pool

    # ── 定时任务 CRUD（原 TaskFacade 方法）──

    def list_tasks(self) -> list[dict]:
        """列出所有定时任务。"""
        return self._registry.list_tasks()

    def get_task(self, task_id: str) -> dict | None:
        """获取单个定时任务。"""
        return self._registry.get_task(task_id)

    def save_task(self, task_id: str, config: dict) -> tuple[bool, str]:
        """保存定时任务。"""
        return self._registry.save_task(task_id, config)

    def delete_task(self, task_id: str) -> tuple[bool, str]:
        """删除定时任务及其历史。"""
        success, message = self._registry.delete_task(task_id)
        if success:
            self._history_store.delete_history(task_id)
        return success, message

    def get_history(self, task_id: str) -> list[dict]:
        """获取任务执行历史。"""
        return self._history_store.get_history(task_id)

    def has_enabled_tasks(self) -> bool:
        """检查是否存在启用的定时任务。"""
        return self._registry.has_enabled_tasks()

    # ── 异步提交接口 ──

    def execute_task_async(self, task_id: str) -> Future:
        """异步执行定时任务（提交到 task_pool）。

        Returns:
            Future 对象，调用方可选择等待结果

        Raises:
            RuntimeError: 任务队列已满
        """
        return self._ensure_task_pool().submit(self.execute_task, task_id)

    def execute_login_async(
        self,
        cancel_event: threading.Event | None = None,
        skip_pause_check: bool = False,
    ) -> Future:
        """异步执行登录（提交到 login_pool），带去重。

        如果已有登录任务在执行中，返回已有的 Future 而非重复提交。
        去重时，新调用方的 cancel_event 会联动到已有任务：
        当新 cancel_event 被设置时，已有任务的 cancel_event 也会被设置。

        Args:
            cancel_event: 取消事件，设置后登录流程应尽快退出
            skip_pause_check: 是否跳过暂停时段和网络检测

        Returns:
            Future 对象（新的或已有的）
        """
        future = None
        with self._login_lock:
            # 检查是否已有登录在进行
            if self._login_future is not None and not self._login_future.done():
                logger.debug("登录任务已在执行中，跳过重复提交")
                # 联动新 cancel_event 到已有任务
                if cancel_event is not None and self._login_cancel_event is not None:
                    self._link_cancel_event(cancel_event, self._login_cancel_event)
                return self._login_future

            # 提交新的登录任务
            future = self._login_pool.submit(
                self.execute_login, cancel_event, skip_pause_check
            )
            self._login_future = future
            self._login_cancel_event = cancel_event

        # 锁外注册回调，避免时序问题
        future.add_done_callback(self._on_login_done)
        return future

    @staticmethod
    def _link_cancel_event(
        new_event: threading.Event, target_event: threading.Event
    ) -> None:
        """在后台线程监控 new_event，设置时联动到 target_event。"""

        def _watcher() -> None:
            new_event.wait(timeout=300)
            if new_event.is_set():
                target_event.set()

        t = threading.Thread(target=_watcher, daemon=True, name="cancel-link")
        t.start()

    def _on_login_done(self, future: Future) -> None:
        """登录任务完成后清理引用。"""
        with self._login_lock:
            if self._login_future is future:
                self._login_future = None
                self._login_cancel_event = None

    # ── 同步执行接口 ──

    def execute_task(self, task_id: str) -> tuple[bool, str]:
        """同步执行定时任务（在线程池工作线程中运行）。

        根据任务类型分发到 _execute_script / _execute_browser / _execute_shell。
        执行完成后记录历史和更新 last_run。
        """
        task = self._registry.get_task(task_id)
        if not task:
            return False, "定时任务不存在"

        task_type = task.get("type", "")
        timeout = task.get("timeout", 60)
        start = time.perf_counter()

        try:
            if task_type == "script":
                success, message = self._execute_script(
                    task.get("target_id", ""), timeout
                )
            elif task_type == "browser":
                success, message = self._execute_browser(
                    task.get("target_id", ""), timeout
                )
            elif task_type == "shell":
                success, message = self._execute_shell(
                    task.get("command", ""), timeout, task.get("shell_path", "")
                )
            else:
                success, message = (
                    False,
                    f"不支持的任务类型: {task_type}，当前支持: script、browser、shell",
                )
        except Exception as exc:
            success, message = False, f"执行异常: {exc}"

        duration = time.perf_counter() - start
        status = "success" if success else "failure"

        # 记录执行历史
        self._history_store.add_record(task_id, status, message, duration)

        # 更新最后执行时间
        self._registry.update_last_run(task_id, status)

        logger.info(
            "定时任务执行完成 {}: success={}, message={}",
            task_id,
            success,
            message[:100],
        )
        return success, message

    def execute_login(
        self,
        cancel_event: threading.Event | None = None,
        skip_pause_check: bool = False,
    ) -> tuple[bool, str]:
        """同步执行登录（在 login_pool 工作线程中运行）。

        通过 PlaywrightWorker 执行浏览器自动化登录。
        """
        start = time.perf_counter()

        try:
            from app.workers.playwright_worker import CMD_LOGIN

            # 获取运行时配置
            config = self._get_runtime_config() if self._get_runtime_config else {}
            pure_mode = config.get("browser_settings", {}).get("pure_mode", False)

            # 检查取消
            if cancel_event and cancel_event.is_set():
                return False, "登录已取消"

            # 获取 Worker 并提交登录命令
            worker = self._worker_getter()
            result = worker.submit(
                CMD_LOGIN,
                data={
                    "config": config,
                    "pure_mode": pure_mode,
                    "skip_pause_check": skip_pause_check,
                    "cancel_event": cancel_event,
                },
                wait=True,
                timeout=300,
            )

            duration_ms = int((time.perf_counter() - start) * 1000)

            if result.success:
                self._record_login_history(True, duration_ms)
                message = result.data if isinstance(result.data, str) else "登录成功"
                return True, message
            else:
                error_msg = result.error or "登录失败"
                self._record_login_history(False, duration_ms, error=error_msg)
                return False, error_msg

        except ImportError as exc:
            duration_ms = int((time.perf_counter() - start) * 1000)
            logger.warning("登录执行缺少依赖: {}", exc)
            self._record_login_history(False, duration_ms, error=str(exc))
            return False, "登录需要额外依赖，请检查 Playwright 安装状态"
        except Exception as exc:
            duration_ms = int((time.perf_counter() - start) * 1000)
            logger.error("登录执行异常: {}", exc)
            self._record_login_history(False, duration_ms, error=str(exc))
            return False, f"登录执行异常: {exc}"

    # ── 内部执行方法 ──

    def _execute_script(self, script_id: str, timeout: int) -> tuple[bool, str]:
        """执行自定义脚本任务。"""
        if not self._registry:
            return False, "任务服务未初始化"

        task = self._registry.get_task(script_id)
        if not task or task.get("type") != "script":
            return False, f"脚本任务不存在: {script_id}"

        # 获取脚本路径（通过 registry 的 TaskManager）
        script_path = self._get_script_path(script_id)
        if not script_path or not script_path.exists():
            return False, f"脚本文件不存在: {script_id}"

        from app.workers.script_runner import ScriptRunner

        runner = ScriptRunner(
            script_path,
            timeout=timeout,
            binary_path=task.get("binary_path", ""),
        )

        return runner.run()

    def _execute_browser(self, task_id: str, timeout: int) -> tuple[bool, str]:
        """执行浏览器任务。

        通过 PlaywrightWorker 执行浏览器自动化任务。
        """
        task = self._registry.get_task(task_id)
        if not task or task.get("type") != "browser":
            return False, f"浏览器任务不存在: {task_id}"

        start_time = time.perf_counter()

        try:
            from app.workers.playwright_worker import CMD_LOGIN

            # 获取运行时配置
            config = self._get_runtime_config() if self._get_runtime_config else {}
            pure_mode = config.get("browser_settings", {}).get("pure_mode", False)

            # 获取 Worker 并提交登录命令
            worker = self._worker_getter()
            result = worker.submit(
                CMD_LOGIN,
                data={
                    "config": config,
                    "pure_mode": pure_mode,
                    "skip_pause_check": True,  # 定时任务跳过暂停检查
                },
                wait=True,
                timeout=timeout,
            )

            duration_ms = int((time.perf_counter() - start_time) * 1000)

            if result.success:
                return True, (
                    result.data
                    if isinstance(result.data, str)
                    else "浏览器任务执行成功"
                )
            else:
                return False, result.error or "浏览器任务执行失败"

        except ImportError as exc:
            logger.warning("浏览器任务执行缺少依赖: {}", exc)
            return False, "浏览器任务需要额外依赖，请检查 Playwright 安装状态"
        except Exception as exc:
            logger.error("浏览器任务执行异常: {}", exc)
            return False, f"浏览器任务执行异常: {exc}"

    def _execute_shell(
        self, command: str, timeout: int, shell_path: str = ""
    ) -> tuple[bool, str]:
        """执行 Shell 命令。"""
        if not command.strip():
            return False, "命令为空"

        # 如果没有指定 shell，使用全局配置或默认值
        if not shell_path:
            try:
                config = self._get_runtime_config() if self._get_runtime_config else {}
                shell_path = config.get("shell_path", "")
            except Exception:
                logger.debug("获取运行时 shell_path 失败，使用默认值", exc_info=True)

        if not shell_path:
            shell_path = get_default_shell()

        policy = self._shell_policy

        try:
            # 根据 shell 类型构建命令
            shell_lower = shell_path.lower()
            if "powershell" in shell_lower or "pwsh" in shell_lower:
                cmd_args = [shell_path, "-Command", command]
            elif sys.platform == "win32" and "cmd" in shell_lower:
                cmd_args = [shell_path, "/c", command]
            else:
                # bash / zsh / fish / git-bash 等 POSIX shell
                cmd_args = [shell_path, "-c", command]

            returncode, stdout_str, stderr_str = policy.run_sync(
                cmd_args,
                timeout=timeout,
            )

            if returncode == 0:
                output = stdout_str[:500] or "(无输出)"
                return True, output
            else:
                output = stderr_str[:500] or stdout_str[:500] or f"退出码: {returncode}"
                return False, output

        except PermissionError as exc:
            return False, str(exc)
        except Exception as exc:
            return False, f"执行异常: {exc}"

    # ── 辅助方法 ──

    def _record_login_history(
        self, success: bool, duration_ms: int, error: str = ""
    ) -> None:
        """记录登录历史（委托 LoginHistoryService.record 自动提取方案/任务名称）。"""
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

    def _get_script_path(self, script_id: str):
        """获取脚本任务的文件路径。

        委托 TaskRegistry.get_script_path() 查找。
        """
        if hasattr(self._registry, "get_script_path"):
            return self._registry.get_script_path(script_id)
        return None

    # ── 生命周期 ──

    def shutdown(self, wait: bool = True) -> None:
        """关闭线程池。"""
        logger.info("TaskExecutor 开始关闭...")
        if self._task_pool is not None:
            self._task_pool.shutdown(wait=wait)
        self._login_pool.shutdown(wait=wait)
        logger.info("TaskExecutor 已关闭")
