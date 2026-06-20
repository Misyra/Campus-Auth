"""登录尝试处理器。"""

import asyncio
import contextlib
import os
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any

from .browser import BrowserContextManager
from .env import build_login_template_vars
from .exceptions import LoginCancelledError
from .logging import get_logger

# 用于从日志消息中移除截图路径的正则表达式
SCREENSHOT_URL_PATTERN = r"\s*截图[:：]\s*/\S+\.(?:png|jpg|jpeg|webp|gif)"

# 登录成功后等待页面完成跳转和状态更新的时间（秒）
LOGIN_SUCCESS_SETTLE_SECONDS = 2


class LoginAttemptHandler:
    """登录尝试处理器 - 统一登录逻辑（解决循环依赖）"""

    def __init__(
        self,
        config: dict[str, Any],
        cancel_event: threading.Event | None = None,
    ):
        """
        初始化登录处理器

        参数:
            config: 配置字典
            cancel_event: 取消事件，设置后中断登录操作
        """
        self.config = config
        self.cancel_event = cancel_event
        self.logger = get_logger("login", source="backend")
        self._browser_ctx: BrowserContextManager | None = None
        self._task_manager: Any | None = None
        self._project_root: Path | None = None

        # 解构常用字段为命名属性（dict 结构由 _runtime_config_to_worker_dict 保证）
        self._credentials: dict[str, str] = {
            "username": config.get("username", ""),
            "password": config.get("password", ""),
            "auth_url": config.get("auth_url", ""),
            "isp": config.get("isp", ""),
        }
        self._browser_settings: dict[str, Any] = config.get("browser_settings", {})
        self._monitor_settings: dict[str, Any] = config.get("monitor", {})
        self._active_task: str = config.get("active_task", "").strip()
        self._custom_variables: dict[str, str] = config.get("custom_variables", {})

    async def attempt_login(self) -> tuple[bool, str]:
        """
        尝试登录校园网（统一实现）

        前置检查（暂停时段、网络状态、登录前置条件）由调用方负责。
        本方法只负责执行登录任务。

        返回:
            tuple[bool, str]: (是否成功, 详细信息)
        """
        try:
            return await self._perform_login_with_auth_class()
        except Exception as e:
            error_msg = f"登录过程中发生错误: {e!s}"
            self.logger.error(error_msg)
            return False, error_msg

    async def _perform_login_with_auth_class(self) -> tuple[bool, str]:
        """使用活动任务执行登录。"""
        task_result = await self._perform_login_with_active_task()
        if task_result is not None:
            return task_result

        error_msg = "未找到可执行的任务，请先在任务管理页面创建并启用一个登录任务"
        self.logger.error("{}", error_msg)
        return False, error_msg

    async def _perform_login_with_active_task(self) -> tuple[bool, str] | None:
        """执行当前活动任务；返回 None 表示未找到可执行任务。"""
        from ..tasks.models import ScriptTaskInfo

        phase_start = time.perf_counter()
        try:
            self._ensure_task_manager()

            task_manager = self._task_manager
            profile_task_id = self._active_task
            if profile_task_id:
                active_task_id = profile_task_id
                task = task_manager.load_task(profile_task_id)
            else:
                active_task_id = task_manager.get_active_task() or "default"
                task = task_manager.load_active_task()

            if not task:
                self.logger.warning("未找到活动任务: {}", active_task_id)
                return None

            # ========== 脚本任务分支 ==========
            if isinstance(task, ScriptTaskInfo):
                return await self._execute_script_task(task, phase_start)

            # ========== 浏览器任务 ==========
            return await self._execute_browser_task(task, active_task_id, phase_start)

        except LoginCancelledError:
            self.logger.info("登录已取消")
            return False, "登录已取消"
        except Exception as e:
            total = time.perf_counter() - phase_start
            self.logger.error("登录异常 (总耗时 {:.1f}s): {}", total, e)
            return False, f"任务执行异常: {e}"

    def _ensure_task_manager(self) -> None:
        """懒初始化 TaskManager。"""
        if self._task_manager is None:
            from ..tasks.manager import TaskManager

            root_override = os.getenv("CAMPUS_AUTH_PROJECT_ROOT", "").strip()
            self._project_root = (
                Path(root_override).expanduser().resolve()
                if root_override
                else Path(__file__).resolve().parents[2]
            )
            self._task_manager = TaskManager(self._project_root / "tasks")

    async def _execute_browser_task(
        self, task: Any, active_task_id: str, phase_start: float
    ) -> tuple[bool, str]:
        """执行浏览器任务。"""
        from ..tasks.browser_runner import TaskExecutor

        login_url = self._credentials["auth_url"]
        username = self._credentials["username"]
        isp = self._credentials["isp"]
        self.logger.info(
            "登录开始 -> 任务={} URL={} 用户={} 运营商={} {}个步骤",
            active_task_id,
            login_url,
            username,
            isp or "无",
            len(task.steps),
        )

        template_vars = build_login_template_vars(
            self.config, task.url, self._custom_variables
        )

        if self.cancel_event and self.cancel_event.is_set():
            return False, "登录已取消"

        # 创建新浏览器实例
        if self._browser_ctx is not None:
            await self.close_browser()

        self.logger.info("启动浏览器...")
        browser_start = time.perf_counter()
        browser_manager = BrowserContextManager(
            self.config, cancel_event=self.cancel_event
        )
        self._browser_ctx = browser_manager  # 先赋值，确保异常时 close_browser 能清理
        try:
            await browser_manager.__aenter__()
        except Exception:
            # __aenter__ 失败时手动调用 __aexit__ 释放已获取的资源
            self._browser_ctx = None
            with contextlib.suppress(Exception):
                await browser_manager.__aexit__(*sys.exc_info())
            raise
        self.logger.info("浏览器就绪 ({:.1f}s)", time.perf_counter() - browser_start)

        success = False
        try:
            if not browser_manager.page:
                raise RuntimeError("浏览器页面初始化失败")

            browser_timeout = self._browser_settings.get("timeout", 8) * 1000  # 秒 → 毫秒
            navigation_timeout = (
                self._browser_settings.get("navigation_timeout", 15) * 1000
            )  # 秒 → 毫秒

            executor = TaskExecutor(
                task,
                template_vars,
                default_timeout=browser_timeout,
                navigation_timeout=navigation_timeout,
                monitor_config=self._monitor_settings,
            )

            # 监听页面 alert/confirm/prompt，记录内容并延迟关闭让用户看到
            # 执行后清理监听器，避免泄漏
            async def _handle_dialog(dialog):
                self.logger.info("页面弹窗 [{}]: {}", dialog.type, dialog.message)
                await asyncio.sleep(1.5)  # 延迟关闭，让页面有时间处理弹窗
                await dialog.accept()

            browser_manager.page.on("dialog", _handle_dialog)
            try:
                success, message = await executor.execute(browser_manager.page)
            finally:
                browser_manager.page.remove_listener("dialog", _handle_dialog)
            total = time.perf_counter() - phase_start
            if success:
                self.logger.info("登录成功 (总耗时 {:.1f}s): {}", total, message)
                await asyncio.sleep(
                    LOGIN_SUCCESS_SETTLE_SECONDS
                )  # 登录成功后等待，让页面完成跳转和状态更新
                return True, message
            log_msg = re.sub(SCREENSHOT_URL_PATTERN, "", message)
            self.logger.error("登录失败 (总耗时 {:.1f}s): {}", total, log_msg)
            return False, message
        finally:
            await self.close_browser()

    async def _execute_script_task(
        self, task: Any, phase_start: float
    ) -> tuple[bool, str]:
        """执行 Python 脚本任务（无浏览器）。

        脚本只负责发请求，登录是否成功通过网络检测判断。
        """
        from ..network.decision import check_network_status
        from ..workers.script_runner import ScriptRunner

        self.logger.info(
            "脚本任务开始 -> 任务={} 脚本={}",
            task.task_id,
            task.script_path,
        )

        if self.cancel_event and self.cancel_event.is_set():
            return False, "登录已取消"

        timeout = self._monitor_settings.get("script_timeout", 60)
        runner = ScriptRunner(task.script_path, timeout=timeout)

        loop = asyncio.get_running_loop()
        ran_ok, script_output = await loop.run_in_executor(None, runner.run)

        if not ran_ok:
            total = time.perf_counter() - phase_start
            self.logger.error("脚本执行失败 (总耗时 {:.1f}s): {}", total, script_output)
            return False, f"脚本执行失败: {script_output}"

        self.logger.info("脚本已执行，等待网络验证...")
        await asyncio.sleep(LOGIN_SUCCESS_SETTLE_SECONDS)

        net_ok, net_msg, _ = await asyncio.to_thread(check_network_status, self.config)

        total = time.perf_counter() - phase_start
        if net_ok:
            self.logger.info("登录成功 (总耗时 {:.1f}s): 网络已连通", total)
            return True, "登录成功"
        else:
            self.logger.warning("登录可能失败 (总耗时 {:.1f}s): {}", total, net_msg)
            return False, f"网络未连通: {net_msg}"

    async def close_browser(self) -> None:
        """释放浏览器上下文引用（不销毁浏览器实例）"""
        if self._browser_ctx:
            try:
                await self._browser_ctx.__aexit__(None, None, None)
            except Exception as exc:
                self.logger.warning("浏览器上下文关闭异常: {}", exc)
            finally:
                self._browser_ctx = None
                self.logger.info("浏览器上下文已释放")
