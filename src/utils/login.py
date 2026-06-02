#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
登录尝试处理器
"""

import asyncio
import datetime
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict

from .browser import BrowserContextManager
from .env import build_login_env_vars
from .exceptions import LoginCancelledError
from .logging import setup_logger

if False:  # Type-only import to avoid circular dependency at runtime
    from ..task_executor import TaskManager

# 用于从日志消息中移除截图路径的正则表达式
SCREENSHOT_URL_PATTERN = r"\s*截图[:：]\s*/\S+\.(?:png|jpg|jpeg|webp|gif)"


class LoginAttemptHandler:
    """登录尝试处理器 - 统一登录逻辑（解决循环依赖）"""

    def __init__(
        self,
        config: Dict[str, Any],
        cancel_event: threading.Event | None = None,
        close_on_failure: bool = True,
    ):
        """
        初始化登录处理器

        参数:
            config: 配置字典
            cancel_event: 取消事件，设置后中断登录操作
            close_on_failure: 登录失败时是否关闭浏览器（默认 True）。
                自动监控重试时设为 False 以复用浏览器，手动登录保持 True。
        """
        self.config = config
        self.cancel_event = cancel_event
        self.close_on_failure = close_on_failure
        self.logger = setup_logger("login", config.get("logging", {}))
        self._browser_ctx: BrowserContextManager | None = None
        self._task_manager: TaskManager | None = None
        self._project_root: Path | None = None

    async def attempt_login(
        self, skip_pause_check: bool = False
    ) -> tuple[bool, str]:
        """
        尝试登录校园网（统一实现）

        参数:
            skip_pause_check: 是否跳过暂停时间检查

        返回:
            tuple[bool, str]: (是否成功, 详细信息)
        """
        try:
            # 使用统一的登录前决策（暂停时段、网络状态等）
            if not skip_pause_check:
                from src.network_decision import check_network_status, check_pause

                is_paused, _ = check_pause(self.config)
                if is_paused:
                    pause_config = self.config.get("pause_login", {})
                    current_hour = datetime.datetime.now().hour
                    start_hour = pause_config.get("start_hour", 0)
                    end_hour = pause_config.get("end_hour", 6)
                    msg = f"当前时间 {current_hour}:xx 在暂停登录时段（{start_hour}点-{end_hour}点），跳过登录"
                    self.logger.info(msg)
                    return False, msg

                net_ok, _ = check_network_status(self.config)
                if net_ok:
                    msg = "网络正常，无需登录"
                    self.logger.info(msg)
                    return False, msg

                # 网络异常，检查登录前置条件
                from src.network_decision import check_login_prerequisites
                prereq_ok, prereq_reason = check_login_prerequisites(self.config)
                if not prereq_ok:
                    if prereq_reason == "local_disconnected":
                        msg = "物理网络未连接，跳过登录"
                        self.logger.info(msg)
                        return False, msg
                    elif prereq_reason == "auth_url_unreachable":
                        msg = f"认证地址 {self.config.get('auth_url', '?')} 不可达，跳过登录"
                        self.logger.info(msg)
                        return False, msg

            # 使用延迟导入避免循环依赖
            return await self._perform_login_with_auth_class()

        except Exception as e:
            error_msg = f"登录过程中发生错误: {str(e)}"
            self.logger.error(error_msg)
            return False, error_msg

    async def _perform_login_with_auth_class(self) -> tuple[bool, str]:
        """使用活动任务执行登录。"""
        task_result = await self._perform_login_with_active_task()
        if task_result is not None:
            return task_result

        error_msg = "未找到可执行的活动任务，请在任务管理页面配置并激活一个任务"
        self.logger.error(f"❌ {error_msg}")
        return False, error_msg

    async def _perform_login_with_active_task(self) -> tuple[bool, str] | None:
        """执行当前活动任务；返回 None 表示未找到可执行任务。"""
        from ..task_executor import TaskExecutor, TaskManager, ScriptTaskInfo

        phase_start = time.perf_counter()
        try:
            if self._task_manager is None:
                root_override = os.getenv("CAMPUS_AUTH_PROJECT_ROOT", "").strip()
                self._project_root = (
                    Path(root_override).expanduser().resolve()
                    if root_override
                    else Path(__file__).resolve().parents[2]
                )
                self._task_manager = TaskManager(self._project_root / "tasks")

            task_manager = self._task_manager
            active_task_id = self.config.get("active_task", "").strip()
            if not active_task_id:
                active_task_id = task_manager.get_active_task().strip() or "default"
            task = task_manager.load_task(active_task_id)

            if not task:
                self.logger.warning("未找到活动任务: %s", active_task_id)
                return None

            # ========== 脚本任务分支 ==========
            if isinstance(task, ScriptTaskInfo):
                return await self._execute_script_task(task, phase_start)

            # ========== 浏览器任务 ==========
            login_url = self.config.get("auth_url", "")
            username = self.config.get("username", "")
            isp = self.config.get("isp", "")
            self.logger.info(
                "登录开始 → 任务=%s URL=%s 用户=%s 运营商=%s %d个步骤",
                active_task_id,
                login_url,
                username,
                isp or "无",
                len(task.steps),
            )

            env_vars = build_login_env_vars(
                self.config, task.url, self.config.get("custom_variables", {})
            )

            if self.cancel_event and self.cancel_event.is_set():
                return False, "登录已取消"

            browser_manager: BrowserContextManager | None = None

            # 创建新浏览器实例
            if self._browser_ctx is not None:
                await self.close_browser()

            self.logger.info("启动浏览器...")
            browser_start = time.perf_counter()
            browser_manager = BrowserContextManager(
                self.config, cancel_event=self.cancel_event
            )
            try:
                await browser_manager.__aenter__()
            except Exception:
                # __aenter__ 失败时无需 __aexit__（Playwright 未初始化）
                raise
            self._browser_ctx = browser_manager
            self.logger.info(
                "浏览器就绪 (%.1fs)", time.perf_counter() - browser_start
            )

            try:
                if not browser_manager.page:
                    raise RuntimeError("浏览器页面初始化失败")

                browser_settings = self.config.get("browser_settings", {})
                browser_timeout = browser_settings.get("timeout", 8) * 1000  # 秒 → 毫秒
                navigation_timeout = browser_settings.get("navigation_timeout", 15) * 1000  # 秒 → 毫秒

                executor = TaskExecutor(
                    task,
                    env_vars,
                    default_timeout=browser_timeout,
                    navigation_timeout=navigation_timeout,
                    monitor_config=self.config.get("monitor", {}),
                )
                # 监听页面 alert/confirm/prompt，记录内容并延迟关闭让用户看到
                # 每次执行后清理监听器，避免浏览器复用时监听器泄漏
                async def _handle_dialog(dialog):
                    self.logger.info("页面弹窗 [%s]: %s", dialog.type, dialog.message)
                    await asyncio.sleep(1.5)  # 延迟关闭，让页面有时间处理弹窗
                    await dialog.accept()

                browser_manager.page.on("dialog", _handle_dialog)
                try:
                    success, message = await executor.execute(browser_manager.page)
                finally:
                    browser_manager.page.remove_listener("dialog", _handle_dialog)
                total = time.perf_counter() - phase_start
                if success:
                    self.logger.info("登录成功 (总耗时 %.1fs): %s", total, message)
                    await asyncio.sleep(2)  # 登录成功后等待，让页面完成跳转和状态更新
                    await self.close_browser()
                    return True, message
                log_msg = re.sub(SCREENSHOT_URL_PATTERN, "", message)
                self.logger.error("登录失败 (总耗时 %.1fs): %s", total, log_msg)
                if self.close_on_failure:
                    await self.close_browser()
                return False, message
            except Exception:
                if self.close_on_failure:
                    await self.close_browser()
                raise

        except LoginCancelledError:
            self.logger.info("登录已取消")
            return False, "登录已取消"
        except Exception as e:
            total = time.perf_counter() - phase_start
            self.logger.error("登录异常 (总耗时 %.1fs): %s", total, e)
            return False, f"任务执行异常: {e}"

    async def _execute_script_task(
        self, task: Any, phase_start: float
    ) -> tuple[bool, str]:
        """执行 Python 脚本任务（无浏览器）。

        脚本只负责发请求，登录是否成功通过网络检测判断。
        """
        from ..network_decision import check_network_status
        from ..script_runner import ScriptRunner

        self.logger.info(
            "脚本任务开始 → 任务=%s 脚本=%s",
            task.task_id, task.script_path,
        )

        if self.cancel_event and self.cancel_event.is_set():
            return False, "登录已取消"

        timeout = self.config.get("monitor", {}).get("script_timeout", 60)
        runner = ScriptRunner(task.script_path, timeout=timeout)

        loop = asyncio.get_running_loop()
        ran_ok, script_output = await loop.run_in_executor(None, runner.run)

        if not ran_ok:
            total = time.perf_counter() - phase_start
            self.logger.error("脚本执行失败 (总耗时 %.1fs): %s", total, script_output)
            return False, f"脚本执行失败: {script_output}"

        self.logger.info("脚本已执行，等待网络验证...")
        await asyncio.sleep(2)

        net_ok, net_msg = check_network_status(self.config)

        total = time.perf_counter() - phase_start
        if net_ok:
            self.logger.info("登录成功 (总耗时 %.1fs): 网络已连通", total)
            return True, "登录成功"
        else:
            self.logger.warning("登录可能失败 (总耗时 %.1fs): %s", total, net_msg)
            return False, f"网络未连通: {net_msg}"

    async def close_browser(self) -> None:
        """关闭浏览器（登录成功或监控停止时调用）"""
        if self._browser_ctx:
            try:
                # 实际关闭 Worker 中的浏览器进程（同线程安全）
                from src.playwright_worker import get_worker

                worker = get_worker()
                await worker.close_browser()

                # 释放本地引用
                await self._browser_ctx.__aexit__(None, None, None)
            except Exception as exc:
                self.logger.warning("浏览器关闭时异常: %s", exc)
            self._browser_ctx = None
            self.logger.info("浏览器已关闭")
