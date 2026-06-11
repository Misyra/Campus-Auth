"""ScheduledTaskService — 定时任务 CRUD、执行、历史管理。

从 ScheduleEngine 提取的定时任务职责，独立为服务类。
"""

from __future__ import annotations

import json
import sys
import threading
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from app.tasks import TaskManager, is_valid_task_id
from app.utils.file_helpers import atomic_write
from app.utils.logging import get_logger
from app.utils.shell_policy import ShellCommandPolicy
from app.utils.shell_utils import detect_shells, get_default_shell

scheduled_task_logger = get_logger("scheduled_task", source="backend")

# ── 常量 ──

# 执行历史最大保留条数
MAX_HISTORY_SIZE = 50

# 调度器检查间隔（秒）
SCHEDULER_CHECK_INTERVAL = 30


class ScheduledTaskService:
    """定时任务 CRUD、执行、历史管理。"""

    def __init__(
        self,
        project_root: Path,
        task_manager: TaskManager,
        worker_getter: Callable,
        login_history=None,
        profile_service=None,
        get_runtime_config: Callable[[], dict] | None = None,
    ):
        self._task_manager = task_manager
        self._worker_getter = worker_getter
        self._login_history = login_history
        self._profile_service = profile_service
        self._get_runtime_config = get_runtime_config

        # 目录
        self._tasks_dir = project_root / "tasks" / "scheduled"
        self._history_dir = self._tasks_dir / "history"
        self._tasks_dir.mkdir(parents=True, exist_ok=True)
        self._history_dir.mkdir(parents=True, exist_ok=True)

        # 调度器状态
        self._scheduler_running = False
        self._running_task_threads: list[threading.Thread] = []
        self._running_tasks_lock = threading.Lock()
        self._history_lock = threading.Lock()
        self._last_triggered_minute: tuple[int, int] | None = None
        self._has_enabled_cache: tuple[float, bool] | None = None

        # 登录并发控制
        self._login_in_progress = threading.Event()
        self._login_lock: threading.Lock = threading.Lock()

        # Shell 安全策略
        self._shell_policy = ShellCommandPolicy(
            allowlist=[s["path"] for s in detect_shells()]
        )

    # ── 公开属性 ──

    @property
    def login_in_progress(self) -> bool:
        """登录是否正在进行。"""
        return self._login_in_progress.is_set()

    @property
    def scheduler_running(self) -> bool:
        """调度器是否正在运行。"""
        return self._scheduler_running

    # ── 静态方法 ──

    @staticmethod
    def _validate_task_id(task_id: str) -> bool:
        """校验 task_id 是否安全且格式有效。"""
        return is_valid_task_id(task_id)

    # ── CRUD ──

    def has_enabled_tasks(self) -> bool:
        """检查是否存在启用的定时任务。"""
        now = time.time()
        if (
            self._has_enabled_cache is not None
            and (now - self._has_enabled_cache[0]) < 5
        ):
            return self._has_enabled_cache[1]
        for file in self._tasks_dir.glob("*.json"):
            if file.name.startswith("."):
                continue
            try:
                data = json.loads(file.read_text(encoding="utf-8"))
                if data.get("enabled", False):
                    self._has_enabled_cache = (now, True)
                    return True
            except Exception:
                continue
        self._has_enabled_cache = (now, False)
        return False

    def list_tasks(self) -> list[dict[str, Any]]:
        """列出所有定时任务。"""
        tasks = []
        for file in self._tasks_dir.glob("*.json"):
            if file.name.startswith("."):
                continue
            try:
                data = json.loads(file.read_text(encoding="utf-8"))
                data["id"] = file.stem
                tasks.append(data)
            except Exception as e:
                scheduled_task_logger.error("读取定时任务失败 {}: {}", file, e)
        return sorted(tasks, key=lambda t: t.get("name", ""))

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        """获取定时任务详情。"""
        if not self._validate_task_id(task_id):
            return None
        file = self._tasks_dir / f"{task_id}.json"
        if not file.exists():
            return None
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
            data["id"] = task_id
            return data
        except Exception as e:
            scheduled_task_logger.error("读取定时任务失败 {}: {}", file, e)
            return None

    def save_task(self, task_id: str, config: dict[str, Any]) -> tuple[bool, str]:
        """保存定时任务。"""
        if not self._validate_task_id(task_id):
            return False, "无效的任务 ID"
        file = self._tasks_dir / f"{task_id}.json"
        try:
            atomic_write(str(file), json.dumps(config, ensure_ascii=False, indent=2))
            self._has_enabled_cache = None  # 清除缓存，确保调度器感知变更
            scheduled_task_logger.info("定时任务已保存: {}", task_id)
            return True, "定时任务保存成功"
        except Exception as e:
            scheduled_task_logger.error("保存定时任务失败 {}: {}", task_id, e)
            return False, f"定时任务保存失败，请检查配置后重试: {e}"

    def delete_task(self, task_id: str) -> tuple[bool, str]:
        """删除定时任务。"""
        if not self._validate_task_id(task_id):
            return False, "无效的任务 ID"
        file = self._tasks_dir / f"{task_id}.json"
        if not file.exists():
            return False, "定时任务不存在"
        try:
            file.unlink()
            self._has_enabled_cache = None  # 清除缓存，确保调度器感知变更
            # 同时删除历史记录
            history_file = self._history_dir / f"{task_id}.json"
            if history_file.exists():
                history_file.unlink()
            scheduled_task_logger.info("定时任务已删除: {}", task_id)
            return True, "定时任务删除成功"
        except Exception as e:
            scheduled_task_logger.error("删除定时任务失败 {}: {}", task_id, e)
            return False, f"定时任务删除失败，请稍后重试: {e}"

    # ── 历史 ──

    def get_history(self, task_id: str) -> list[dict[str, Any]]:
        """获取任务执行历史。"""
        if not self._validate_task_id(task_id):
            return []
        history_file = self._history_dir / f"{task_id}.json"
        if not history_file.exists():
            return []
        try:
            data = json.loads(history_file.read_text(encoding="utf-8"))
            return data.get("runs", [])
        except Exception as e:
            scheduled_task_logger.error("读取执行历史失败 {}: {}", task_id, e)
            return []

    def _add_history_sync(
        self, task_id: str, status: str, message: str, duration: float
    ) -> None:
        """添加执行历史记录（同步，使用 threading.Lock 保护并发写入）。"""
        if not self._validate_task_id(task_id):
            return
        with self._history_lock:
            history_file = self._history_dir / f"{task_id}.json"
            try:
                if history_file.exists():
                    data = json.loads(history_file.read_text(encoding="utf-8"))
                else:
                    data = {"runs": []}

                data["runs"].insert(
                    0,
                    {
                        "timestamp": datetime.now().isoformat(),
                        "status": status,
                        "message": message[:500],
                        "duration": round(duration, 2),
                    },
                )

                # 保留最近 N 条
                data["runs"] = data["runs"][:MAX_HISTORY_SIZE]

                atomic_write(
                    str(history_file),
                    json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except Exception as e:
                scheduled_task_logger.error("保存执行历史失败 {}: {}", task_id, e)

    # ── 执行 ──

    def execute_task(self, task_id: str) -> tuple[bool, str]:
        """执行定时任务。"""
        task = self.get_task(task_id)
        if not task:
            return False, "定时任务不存在"

        task_type = task.get("type", "")
        timeout = task.get("timeout", 60)
        start = time.perf_counter()

        try:
            if task_type == "script":
                success, message = self._execute_script_sync(
                    task.get("target_id", ""), timeout
                )
            elif task_type == "browser":
                success, message = self._execute_browser_sync(
                    task.get("target_id", ""), timeout
                )
            elif task_type == "shell":
                success, message = self._execute_shell_sync(
                    task.get("command", ""), timeout, task.get("shell_path", "")
                )
            else:
                success, message = (
                    False,
                    f"不支持的任务类型: {task_type}，当前支持: script、browser、shell",
                )
        except Exception as e:
            success, message = False, f"执行异常: {e}"

        duration = time.perf_counter() - start
        self._add_history_sync(
            task_id, "success" if success else "failure", message, duration
        )

        # 更新最后执行时间（重新读取配置，避免覆盖用户在执行期间的修改）
        fresh_task = self.get_task(task_id)
        if fresh_task is not None:
            fresh_task["last_run"] = datetime.now().isoformat()
            fresh_task["last_status"] = "success" if success else "failure"
            self.save_task(task_id, fresh_task)

        scheduled_task_logger.info(
            "定时任务执行完成 {}: success={}, message={}",
            task_id,
            success,
            message[:100],
        )
        return success, message

    def _execute_script_sync(self, script_id: str, timeout: int) -> tuple[bool, str]:
        """执行自定义脚本任务。"""
        if not self._task_manager:
            return False, "任务服务未初始化"

        task = self._task_manager.get_task(script_id)
        if not task or task.get("type") != "script":
            return False, f"脚本任务不存在: {script_id}"

        script_path = self._task_manager.get_script_path(script_id)
        if not script_path or not script_path.exists():
            return False, f"脚本文件不存在: {script_id}"

        from app.workers.script_runner import ScriptRunner

        runner = ScriptRunner(
            script_path,
            timeout=timeout,
            binary_path=task.get("binary_path", ""),
        )

        return runner.run()

    def _execute_browser_sync(self, task_id: str, timeout: int) -> tuple[bool, str]:
        """执行浏览器任务。

        通过 PlaywrightWorker 执行浏览器自动化任务。
        使用 _login_lock 与监控登录互斥。
        """
        if not self._task_manager:
            return False, "任务服务未初始化"

        task = self._task_manager.get_task(task_id)
        if not task or task.get("type") != "browser":
            return False, f"浏览器任务不存在: {task_id}"

        # 等待监控登录完成，避免重复执行
        if self.login_in_progress:
            scheduled_task_logger.info("监控正在登录，等待完成后再执行定时任务")

        start_time = time.perf_counter()
        try:
            from app.workers.playwright_worker import CMD_LOGIN, get_worker

            # 获取登录锁，防止与监控核心的登录流程并发
            acquired = False
            with self._login_lock:
                if self._login_in_progress.is_set():
                    scheduled_task_logger.info(
                        "获取登录锁时发现登录正在进行，跳过本次执行"
                    )
                    return False, "登录操作正在进行中，定时任务跳过"
                self._login_in_progress.set()
                acquired = True

            try:
                # 获取运行时配置
                config = self._get_runtime_config() if self._get_runtime_config else {}
                pure_mode = config.get("browser_settings", {}).get("pure_mode", False)

                # 获取 Worker 并提交登录命令
                worker = get_worker()
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
            finally:
                if acquired:
                    self._login_in_progress.clear()

            duration_ms = int((time.perf_counter() - start_time) * 1000)
            if result.success:
                self._record_login_history(True, duration_ms)
                return True, result.data if isinstance(
                    result.data, str
                ) else "浏览器任务执行成功"
            else:
                error_msg = result.error or "浏览器任务执行失败"
                self._record_login_history(False, duration_ms, error=error_msg)
                return False, error_msg

        except ImportError as e:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            scheduled_task_logger.warning("浏览器任务执行缺少依赖: {}", e)
            self._record_login_history(False, duration_ms, error=str(e))
            return (
                False,
                "浏览器任务执行需要额外依赖，请在设置中检查 Playwright 安装状态",
            )
        except Exception as e:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            scheduled_task_logger.error("浏览器任务执行异常: {}", e)
            self._record_login_history(False, duration_ms, error=str(e))
            return False, f"浏览器任务执行异常: {e}"

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
                task_manager=self._task_manager,
                error=error,
            )
        except Exception:
            scheduled_task_logger.debug("记录登录历史失败", exc_info=True)

    def _execute_shell_sync(
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
                scheduled_task_logger.debug(
                    "获取运行时 shell_path 失败，使用默认值", exc_info=True
                )

        if not shell_path:
            shell_path = get_default_shell()

        # 使用缓存的 ShellCommandPolicy 进行安全校验和执行
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

        except PermissionError as e:
            return False, str(e)
        except Exception as e:
            return False, f"执行异常: {e}"

    # ── 调度器生命周期 ──

    def start_scheduler(self) -> None:
        """启动定时任务调度（由引擎循环驱动）。"""
        if self._scheduler_running:
            return
        self._scheduler_running = True
        self._last_triggered_minute = None
        scheduled_task_logger.info("定时任务调度器已启动（引擎驱动）")

    def stop_scheduler(self) -> None:
        """停止调度器，等待运行中的任务线程完成。"""
        if not self._scheduler_running:
            return
        self._scheduler_running = False

        # 等待所有运行中的任务线程
        with self._running_tasks_lock:
            running = list(self._running_task_threads)
        for t in running:
            t.join(timeout=30)
        with self._running_tasks_lock:
            self._running_task_threads.clear()

        scheduled_task_logger.info("定时任务调度器已停止")

    def _execute_task_wrapper(self, task_id: str) -> None:
        """任务执行包装器（在守护线程中运行），负责清理线程引用。"""
        try:
            self.execute_task(task_id)
        except Exception as e:
            scheduled_task_logger.error("定时任务执行异常: {}", e)
        finally:
            with self._running_tasks_lock:
                if threading.current_thread() in self._running_task_threads:
                    self._running_task_threads.remove(threading.current_thread())

    def check_and_execute(self) -> None:
        """检查并执行到期的定时任务。"""
        now = datetime.now()
        current_minute = (now.hour, now.minute)
        if current_minute == self._last_triggered_minute:
            return
        if not self.has_enabled_tasks():
            return
        self._last_triggered_minute = current_minute

        tasks = self.list_tasks()
        for task in tasks:
            if not task.get("enabled", False):
                continue
            schedule = task.get("schedule", {})
            if now.hour != schedule.get("hour", -1) or now.minute != schedule.get(
                "minute", -1
            ):
                continue
            task_id = task.get("id", "")
            scheduled_task_logger.info("触发定时任务: {}", task_id)
            t = threading.Thread(
                target=self._execute_task_wrapper, args=(task_id,), daemon=True
            )
            with self._running_tasks_lock:
                self._running_task_threads.append(t)
            t.start()
