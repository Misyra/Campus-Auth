"""定时任务调度服务 — 管理和执行定时任务。"""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from app.tasks import is_valid_task_id
from app.utils.file_helpers import atomic_write
from app.utils.logging import get_logger
from app.utils.shell_policy import ShellCommandPolicy

scheduler_logger = get_logger("backend.scheduler", side="BACKEND")

# 执行历史最大保留条数
MAX_HISTORY_SIZE = 50


def detect_available_shells() -> list[dict[str, str]]:
    """检测系统可用的 Shell。"""
    shells = []

    if sys.platform == "win32":
        # Windows 系统
        candidates = [
            ("cmd", "cmd.exe", "Windows 命令提示符"),
            ("powershell", "powershell.exe", "Windows PowerShell"),
            ("pwsh", "pwsh.exe", "PowerShell 7+"),
            ("git-bash", "bash.exe", "Git Bash"),
        ]
        for name, exe, desc in candidates:
            path = shutil.which(exe)
            if path:
                shells.append({"name": name, "path": path, "description": desc})
    else:
        # Linux/macOS 系统
        candidates = [
            ("bash", "bash", "Bourne Again Shell"),
            ("sh", "sh", "POSIX Shell"),
            ("zsh", "zsh", "Z Shell"),
            ("fish", "fish", "Friendly Interactive Shell"),
        ]
        for name, exe, desc in candidates:
            path = shutil.which(exe)
            if path:
                shells.append({"name": name, "path": path, "description": desc})

    return shells


def get_default_shell() -> str:
    """获取默认 Shell 路径。"""
    if sys.platform == "win32":
        # Windows 优先使用 PowerShell
        pwsh = shutil.which("pwsh.exe")
        if pwsh:
            return pwsh
        powershell = shutil.which("powershell.exe")
        if powershell:
            return powershell
        return "cmd.exe"
    else:
        # Linux/macOS 使用 SHELL 环境变量或 bash
        import os
        return os.environ.get("SHELL", "/bin/bash")


class SchedulerService:
    """定时任务调度服务。"""

    def __init__(self, project_root: Path, task_service: Any = None, monitor_service: Any = None, login_history: Any = None):
        self.project_root = project_root
        self.tasks_dir = project_root / "tasks" / "scheduled"
        self.history_dir = self.tasks_dir / "history"
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
        self.history_dir.mkdir(parents=True, exist_ok=True)
        self.task_service = task_service
        self.monitor_service = monitor_service
        self._login_history = login_history
        self._running = False
        self._task: asyncio.Task | None = None
        self._running_tasks: set[asyncio.Task] = set()
        # 缓存 Shell 安全策略实例（可用 shell 列表不会在运行时变化）
        self._shell_policy = ShellCommandPolicy(
            allowlist=[s["path"] for s in detect_available_shells()]
        )

    @staticmethod
    def _validate_task_id(task_id: str) -> bool:
        """校验 task_id 是否安全且格式有效。"""
        return is_valid_task_id(task_id)

    def has_enabled_tasks(self) -> bool:
        """检查是否存在启用的定时任务。"""
        for file in self.tasks_dir.glob("*.json"):
            if file.name.startswith("."):
                continue
            try:
                data = json.loads(file.read_text(encoding="utf-8"))
                if data.get("enabled", False):
                    return True
            except Exception:
                continue
        return False

    def list_tasks(self) -> list[dict[str, Any]]:
        """列出所有定时任务。"""
        tasks = []
        for file in self.tasks_dir.glob("*.json"):
            if file.name.startswith("."):
                continue
            try:
                data = json.loads(file.read_text(encoding="utf-8"))
                data["id"] = file.stem
                tasks.append(data)
            except Exception as e:
                scheduler_logger.error("读取定时任务失败 {}: {}", file, e)
        return sorted(tasks, key=lambda t: t.get("name", ""))

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        """获取定时任务详情。"""
        if not self._validate_task_id(task_id):
            return None
        file = self.tasks_dir / f"{task_id}.json"
        if not file.exists():
            return None
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
            data["id"] = task_id
            return data
        except Exception as e:
            scheduler_logger.error("读取定时任务失败 {}: {}", file, e)
            return None

    def save_task(self, task_id: str, config: dict[str, Any]) -> tuple[bool, str]:
        """保存定时任务。"""
        if not self._validate_task_id(task_id):
            return False, "无效的任务 ID"
        file = self.tasks_dir / f"{task_id}.json"
        try:
            atomic_write(str(file), json.dumps(config, ensure_ascii=False, indent=2))
            scheduler_logger.info("定时任务已保存: {}", task_id)
            return True, "定时任务保存成功"
        except Exception as e:
            scheduler_logger.error("保存定时任务失败 {}: {}", task_id, e)
            return False, f"保存失败: {e}"

    def delete_task(self, task_id: str) -> tuple[bool, str]:
        """删除定时任务。"""
        if not self._validate_task_id(task_id):
            return False, "无效的任务 ID"
        file = self.tasks_dir / f"{task_id}.json"
        if not file.exists():
            return False, "定时任务不存在"
        try:
            file.unlink()
            # 同时删除历史记录
            history_file = self.history_dir / f"{task_id}.json"
            if history_file.exists():
                history_file.unlink()
            scheduler_logger.info("定时任务已删除: {}", task_id)
            return True, "定时任务删除成功"
        except Exception as e:
            scheduler_logger.error("删除定时任务失败 {}: {}", task_id, e)
            return False, f"删除失败: {e}"

    def get_history(self, task_id: str) -> list[dict[str, Any]]:
        """获取任务执行历史。"""
        if not self._validate_task_id(task_id):
            return []
        history_file = self.history_dir / f"{task_id}.json"
        if not history_file.exists():
            return []
        try:
            data = json.loads(history_file.read_text(encoding="utf-8"))
            return data.get("runs", [])
        except Exception as e:
            scheduler_logger.error("读取执行历史失败 {}: {}", task_id, e)
            return []

    async def _add_history(self, task_id: str, status: str, message: str, duration: float):
        """添加执行历史记录（async，使用 asyncio.Lock 保护并发写入）。"""
        if not self._validate_task_id(task_id):
            return
        # 惰性创建锁，确保在事件循环中初始化
        if not hasattr(self, "_history_lock"):
            self._history_lock = asyncio.Lock()
        async with self._history_lock:
            history_file = self.history_dir / f"{task_id}.json"
            try:
                if history_file.exists():
                    data = json.loads(history_file.read_text(encoding="utf-8"))
                else:
                    data = {"runs": []}

                data["runs"].insert(0, {
                    "timestamp": datetime.now().isoformat(),
                    "status": status,
                    "message": message[:500],
                    "duration": round(duration, 2),
                })

                # 保留最近 N 条
                data["runs"] = data["runs"][:MAX_HISTORY_SIZE]

                from app.utils.file_helpers import atomic_write
                atomic_write(
                    str(history_file),
                    json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except Exception as e:
                scheduler_logger.error("保存执行历史失败 {}: {}", task_id, e)

    async def execute_task(self, task_id: str) -> tuple[bool, str]:
        """执行定时任务。"""
        task = self.get_task(task_id)
        if not task:
            return False, "定时任务不存在"

        task_type = task.get("type", "")
        timeout = task.get("timeout", 60)
        start = time.perf_counter()

        try:
            if task_type == "script":
                success, message = await self._execute_script(task.get("target_id", ""), timeout)
            elif task_type == "browser":
                success, message = await self._execute_browser_task(task.get("target_id", ""), timeout)
            elif task_type == "shell":
                success, message = await self._execute_shell(
                    task.get("command", ""), timeout, task.get("shell_path", "")
                )
            else:
                success, message = False, f"未知任务类型: {task_type}"
        except Exception as e:
            success, message = False, f"执行异常: {e}"

        duration = time.perf_counter() - start
        await self._add_history(task_id, "success" if success else "failure", message, duration)

        # 更新最后执行时间
        task["last_run"] = datetime.now().isoformat()
        task["last_status"] = "success" if success else "failure"
        self.save_task(task_id, task)

        scheduler_logger.info("定时任务执行完成 {}: success={}, message={}", task_id, success, message[:100])
        return success, message

    async def _execute_script(self, script_id: str, timeout: int) -> tuple[bool, str]:
        """执行自定义脚本任务。"""
        if not self.task_service:
            return False, "任务服务未初始化"

        task = self.task_service.get_task(script_id)
        if not task or task.get("type") != "script":
            return False, f"脚本任务不存在: {script_id}"

        script_path = self.task_service.task_manager._safe_task_path(script_id, task_type="scripts")
        if not script_path or not script_path.exists():
            return False, f"脚本文件不存在: {script_id}"

        from app.workers.script_runner import ScriptRunner
        runner = ScriptRunner(
            script_path,
            timeout=timeout,
            binary_path=task.get("binary_path", ""),
        )

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, runner.run)

    async def _execute_browser_task(self, task_id: str, _timeout: int) -> tuple[bool, str]:
        """执行浏览器任务。

        通过 PlaywrightWorker 执行浏览器自动化任务。
        """
        if not self.task_service:
            return False, "任务服务未初始化"

        task = self.task_service.get_task(task_id)
        if not task or task.get("type") != "browser":
            return False, f"浏览器任务不存在: {task_id}"

        if not self.monitor_service:
            return False, "监控服务未初始化，无法执行浏览器任务"

        # 等待监控登录恢复完成，避免重复执行
        if self.monitor_service.login_in_progress or self.monitor_service.login_recovery_in_progress:
            scheduler_logger.info("监控正在登录，等待完成后再执行定时任务")
            await asyncio.get_running_loop().run_in_executor(
                None, self.monitor_service.wait_for_login_recovery
            )

        start_time = time.perf_counter()
        try:
            from app.workers.playwright_worker import get_worker, CMD_LOGIN

            # 获取运行时配置
            config = self.monitor_service.get_runtime_config()
            pure_mode = config.get("browser_settings", {}).get("pure_mode", False)

            # 获取 Worker 并提交登录命令（通过线程池避免阻塞事件循环）
            worker = get_worker()
            result = await asyncio.to_thread(
                lambda: worker.submit(
                    CMD_LOGIN,
                    data={
                        "config": config,
                        "pure_mode": pure_mode,
                        "skip_pause_check": True,  # 定时任务跳过暂停检查
                    },
                    wait=True,
                    timeout=_timeout,
                )
            )

            duration_ms = int((time.perf_counter() - start_time) * 1000)
            task_name = task.get("name", task_id)
            if result.success:
                self._record_login_history(True, duration_ms, task_name)
                return True, result.data if isinstance(result.data, str) else "浏览器任务执行成功"
            else:
                error_msg = result.error or "浏览器任务执行失败"
                self._record_login_history(False, duration_ms, task_name, error_msg)
                return False, error_msg

        except ImportError as e:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            scheduler_logger.warning("浏览器任务执行缺少依赖: {}", e)
            self._record_login_history(False, duration_ms, task.get("name", task_id), str(e))
            return False, "浏览器任务执行需要 Playwright 环境，请确保已安装"
        except Exception as e:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            scheduler_logger.error("浏览器任务执行异常: {}", e)
            self._record_login_history(False, duration_ms, task.get("name", task_id), str(e))
            return False, f"浏览器任务执行异常: {e}"

    def _record_login_history(
        self, success: bool, duration_ms: int, task_name: str = "", error: str = ""
    ) -> None:
        """记录登录历史（如果 login_history 服务可用）。"""
        if self._login_history is None:
            return
        try:
            profile_name = ""
            if self.monitor_service:
                try:
                    config = self.monitor_service.get_runtime_config()
                    profile_name = config.get("profile_name", "")
                except Exception:
                    scheduler_logger.debug("获取方案名称失败", exc_info=True)
            self._login_history.add(
                success=success,
                duration_ms=duration_ms,
                profile_name=profile_name,
                task_name=task_name,
                error=error,
            )
        except Exception:
            scheduler_logger.debug("记录登录历史失败", exc_info=True)

    async def _execute_shell(self, command: str, timeout: int, shell_path: str = "") -> tuple[bool, str]:
        """执行 Shell 命令。"""
        if not command.strip():
            return False, "命令为空"

        # 如果没有指定 shell，使用全局配置或默认值
        if not shell_path:
            if self.monitor_service:
                try:
                    config = self.monitor_service.get_runtime_config()
                    shell_path = config.get("shell_path", "")
                except Exception:
                    scheduler_logger.debug("获取运行时 shell_path 失败", exc_info=True)

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

            returncode, stdout_str, stderr_str = await policy.run(
                cmd_args, timeout=timeout,
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

    def start(self):
        """启动调度器。"""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._scheduler_loop())
        scheduler_logger.info("定时任务调度器已启动")

    def stop(self):
        """停止调度器。"""
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None
        for task in self._running_tasks:
            task.cancel()
        self._running_tasks.clear()
        scheduler_logger.info("定时任务调度器已停止")

    def _on_task_done(self, task: asyncio.Task) -> None:
        """任务完成回调：清理引用并记录异常。"""
        self._running_tasks.discard(task)
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            scheduler_logger.error("定时任务执行异常: {}", exc)

    async def _scheduler_loop(self):
        """调度器主循环，每分钟检查一次。"""
        scheduler_logger.info("调度器循环已启动")
        last_checked_minute = -1

        while self._running:
            try:
                # 没有启用的任务时自动退出
                if not self.has_enabled_tasks():
                    scheduler_logger.info("没有启用的定时任务，调度器自动退出")
                    break

                now = datetime.now()
                current_minute = now.hour * 60 + now.minute

                # 每分钟只检查一次
                if current_minute != last_checked_minute:
                    last_checked_minute = current_minute
                    await self._check_and_execute(now)

                # 每 30 秒检查一次，减少无意义唤醒
                await asyncio.sleep(30)

            except asyncio.CancelledError:
                break
            except Exception as e:
                scheduler_logger.error("调度器循环异常: {}", e)
                await asyncio.sleep(5)

        self._running = False
        scheduler_logger.info("调度器循环已退出")

    async def _check_and_execute(self, now: datetime):
        """检查并执行到期的任务。"""
        tasks = self.list_tasks()
        for task in tasks:
            if not task.get("enabled", False):
                continue

            schedule = task.get("schedule", {})
            hour = schedule.get("hour", -1)
            minute = schedule.get("minute", -1)

            # 检查时间是否匹配
            if now.hour != hour or now.minute != minute:
                continue

            # 执行任务
            task_id = task.get("id", "")
            scheduler_logger.info("触发定时任务: {}", task_id)
            task_obj = asyncio.create_task(self.execute_task(task_id))
            self._running_tasks.add(task_obj)
            task_obj.add_done_callback(self._on_task_done)
