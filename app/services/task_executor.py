"""TaskExecutor — 任务执行中心。

线程池架构：
- task_pool(2, queue=10, 懒初始化) — 定时任务，BoundedExecutor 限制队列
- 登录逻辑委托 LoginOrchestrator（自行管理登录线程池）
"""

from __future__ import annotations

import sys
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

from app.schemas import RuntimeConfig
from app.utils.logging import get_logger
from app.utils.shell_policy import ShellCommandPolicy
from app.utils.shell_utils import detect_shells, get_default_shell

logger = get_logger("task_executor", source="backend")


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
    """任务执行中心 — 任务线程池 + 登录委托。

    Attributes:
        _task_pool: 定时任务线程池（懒初始化，无定时任务时不创建）
        _login_orchestrator: 登录编排器（由 container 注入，必填）
    """

    def __init__(
        self,
        registry: Any,
        history_store: Any,
        worker_getter: Callable,
        login_orchestrator: Any,
        task_manager: Any = None,
        get_runtime_config: Callable[[], RuntimeConfig] | None = None,
    ) -> None:
        self._registry = registry
        self._history_store = history_store
        self._worker_getter = worker_getter
        self._get_runtime_config = get_runtime_config
        self._login_orchestrator = login_orchestrator
        self._task_manager = task_manager

        # 线程池：任务池懒初始化（无定时任务时不创建线程）
        self._task_pool: BoundedExecutor | None = None
        self._task_pool_lock = threading.Lock()

        # 登录专用执行器（max_workers=1, queue_size=1 — 信号量天然保证单并发）
        self._login_executor = BoundedExecutor(max_workers=1, queue_size=1)

        # 定时任务去重
        self._running_tasks: dict[str, Future] = {}
        self._running_tasks_lock = threading.Lock()

        # Shell 安全策略
        self._shell_policy = ShellCommandPolicy(
            allowlist=[shell["path"] for shell in detect_shells()]
        )

    def set_runtime_config_getter(self, getter: Callable[[], RuntimeConfig]) -> None:
        """设置运行时配置获取器（公共接口）。"""
        self._get_runtime_config = getter

    @property
    def task_manager(self):
        """浏览器/脚本任务管理器（供 API 路由访问）。"""
        return self._task_manager

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
        """异步执行定时任务（提交到 task_pool），带 task_id 去重。

        如果同一 task_id 已有 pending 任务，返回已有 Future 而非重复提交。

        Returns:
            Future 对象，调用方可选择等待结果

        Raises:
            RuntimeError: 任务队列已满
        """
        with self._running_tasks_lock:
            existing = self._running_tasks.get(task_id)
            if existing is not None and not existing.done():
                logger.info("定时任务 {} 已在执行中，跳过重复提交", task_id)
                return existing

            try:
                future = self._ensure_task_pool().submit(self.execute_task, task_id)
            except RuntimeError:
                logger.warning("任务队列已满，任务 {} 被拒绝", task_id)
                f: Future = Future()
                f.set_exception(RuntimeError(f"任务队列已满，无法提交任务 {task_id}"))
                return f
            self._running_tasks[task_id] = future

        # 锁外注册清理回调
        def _cleanup(f: Future, tid=task_id):
            with self._running_tasks_lock:
                if self._running_tasks.get(tid) is f:
                    del self._running_tasks[tid]

        future.add_done_callback(_cleanup)
        return future

    # ── 登录接口（委托 LoginOrchestrator）──

    def execute_login_async(
        self,
        cancel_event: threading.Event | None = None,
        config_snapshot: RuntimeConfig | None = None,
    ) -> Future:
        """异步执行登录。签名兼容。"""
        handle = self._login_orchestrator.submit(
            source="auto", config=config_snapshot, cancel_event=cancel_event,
        )
        if handle.future is not None:
            return handle.future
        # 被拒绝：返回已完成的 failed future
        f: Future = Future()
        f.set_result((False, handle.rejected_reason or "登录被拒绝"))
        return f

    def execute_login(
        self,
        cancel_event: threading.Event | None = None,
        config_snapshot: RuntimeConfig | None = None,
    ) -> tuple[bool, str]:
        """同步执行登录。签名兼容。"""
        cfg = config_snapshot if config_snapshot is not None else (
            self._get_runtime_config() if self._get_runtime_config else RuntimeConfig()
        )
        handle = self._login_orchestrator.submit(
            source="auto", config=cfg, cancel_event=cancel_event,
        )
        return handle.result()

    def is_login_running(self) -> bool:
        """检查是否有登录在执行。"""
        return self._login_orchestrator.is_running()

    def cancel_login(self) -> None:
        """取消当前登录。"""
        self._login_orchestrator.cancel_running()

    def force_clear_login_slot(self) -> None:
        """强制清理旧登录引用（仅用于旧任务无法正常取消的兜底场景）。"""
        self._login_orchestrator.cancel_running()

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

        # 延迟导入：避免顶层导入 playwright/script_runner 的启动开销
        from app.workers.script_runner import ScriptRunner

        runner = ScriptRunner(
            script_path,
            timeout=timeout,
            binary_path=task.get("binary_path", ""),
        )

        return runner.run()

    def _execute_browser(
        self,
        task_id: str,
        timeout: int,
        cancel_event: threading.Event | None = None,
    ) -> tuple[bool, str]:
        """执行浏览器任务。委托 LoginOrchestrator，与登录共享去重。"""
        task = self._registry.get_task(task_id)
        if not task or task.get("type") != "browser":
            return False, f"浏览器任务不存在: {task_id}"

        config = self._get_runtime_config() if self._get_runtime_config else RuntimeConfig()
        handle = self._login_orchestrator.submit(
            source="browser", config=config,
            cancel_event=cancel_event, timeout=timeout,
        )

        if handle.rejected_reason is not None:
            return False, handle.rejected_reason

        ok, msg = handle.result()
        if ok:
            return True, msg if isinstance(msg, str) else "浏览器任务执行成功"
        return False, msg or "浏览器任务执行失败"

    def _execute_shell(
        self, command: str, timeout: int, shell_path: str = ""
    ) -> tuple[bool, str]:
        """执行 Shell 命令。"""
        if not command.strip():
            return False, "命令为空"

        # 如果没有指定 shell，使用全局配置或默认值
        if not shell_path:
            try:
                config = self._get_runtime_config() if self._get_runtime_config else RuntimeConfig()
                shell_path = config.shell_path
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
        self._login_executor.shutdown(wait=wait)
        with self._running_tasks_lock:
            self._running_tasks.clear()
        if self._login_orchestrator is not None:
            self._login_orchestrator.shutdown(wait=wait)
        logger.info("TaskExecutor 已关闭")
