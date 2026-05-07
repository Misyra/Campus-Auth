#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
登录尝试处理器
"""

import datetime
import os
import threading
from pathlib import Path
from typing import Any, Dict

from ..task_executor import TaskExecutor, TaskManager
from .browser import BrowserContextManager
from .exceptions import LoginCancelledError
from .logging import setup_logger
from .time import TimeUtils


class LoginAttemptHandler:
    """登录尝试处理器 - 统一登录逻辑（解决循环依赖）"""

    def __init__(self, config: Dict[str, Any], cancel_event: threading.Event | None = None):
        """
        初始化登录处理器

        参数:
            config: 配置字典
            cancel_event: 取消事件，设置后中断登录操作
        """
        self.config = config
        self.cancel_event = cancel_event
        self.logger = setup_logger(
            f"{__name__}_login", config.get("logging", {})
        )

    async def attempt_login(self, skip_pause_check: bool = False) -> tuple[bool, str]:
        """
        尝试登录校园网（统一实现）

        参数:
            skip_pause_check: 是否跳过暂停时间检查

        返回:
            tuple[bool, str]: (是否成功, 详细信息)
        """
        try:
            # 检查当前时间是否在暂停登录时段（如果没有跳过检查）
            if not skip_pause_check:
                pause_config = self.config.get("pause_login", {})

                if TimeUtils.is_in_pause_period(pause_config):
                    current_hour = datetime.datetime.now().hour
                    start_hour = pause_config.get("start_hour", 0)
                    end_hour = pause_config.get("end_hour", 6)
                    msg = f"当前时间 {current_hour}:xx 在暂停登录时段（{start_hour}点-{end_hour}点），跳过登录"
                    self.logger.info(f"⏰ {msg}")
                    return False, msg

            # 使用延迟导入避免循环依赖
            return await self._perform_login_with_auth_class()

        except LoginCancelledError:
            self.logger.info("登录操作已取消")
            return False, "登录已取消"
        except Exception as e:
            error_msg = f"登录过程中发生错误: {str(e)}"
            self.logger.error(f"❌ {error_msg}")
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
        import time as _time
        phase_start = _time.perf_counter()
        try:
            root_override = os.getenv("Campus-Auth_PROJECT_ROOT", "").strip()
            project_root = (
                Path(root_override).expanduser().resolve()
                if root_override
                else Path(__file__).resolve().parents[2]
            )

            task_manager = TaskManager(project_root / "tasks")
            active_task_id = self.config.get("active_task", "").strip()
            if not active_task_id:
                active_task_id = task_manager.get_active_task().strip() or "default"
            task = task_manager.load_task(active_task_id)

            if not task:
                self.logger.warning("未找到活动任务: %s", active_task_id)
                return None

            login_url = self.config.get("auth_url", "")
            username = self.config.get("username", "")
            isp = self.config.get("isp", "")
            self.logger.info(
                "登录开始 → 任务=%s URL=%s 用户=%s 运营商=%s %d个步骤",
                active_task_id, login_url, username, isp or "无", len(task.steps))

            env_vars = dict(os.environ)
            if login_url:
                env_vars["LOGIN_URL"] = login_url
            if task.url:
                resolved_url = task.url
                for k, v in env_vars.items():
                    resolved_url = resolved_url.replace("{{" + k + "}}", v)
                env_vars["LOGIN_URL"] = resolved_url
            # 确保 LOGIN_URL 始终可用，避免无 URL 任务卡住浏览器
            if not env_vars.get("LOGIN_URL", "").strip() and login_url:
                env_vars["LOGIN_URL"] = login_url
            if isp:
                env_vars["ISP"] = isp
            if username:
                env_vars["USERNAME"] = username
            if self.config.get("password"):
                env_vars["PASSWORD"] = self.config["password"]
            custom_vars = self.config.get("custom_variables", {})
            if custom_vars and isinstance(custom_vars, dict):
                env_vars.update(custom_vars)

            if self.cancel_event and self.cancel_event.is_set():
                return False, "登录已取消"

            self.logger.info("启动浏览器...")
            browser_start = _time.perf_counter()
            async with BrowserContextManager(self.config, cancel_event=self.cancel_event) as browser_manager:
                self.logger.info("浏览器就绪 (%.1fs)", _time.perf_counter() - browser_start)
                if not browser_manager.page:
                    return False, "任务执行失败：浏览器页面初始化失败"

                browser_timeout = self.config.get("browser_settings", {}).get("timeout", 10000)
                executor = TaskExecutor(task, env_vars, default_timeout=browser_timeout)
                success, message = await executor.execute(browser_manager.page)
                total = _time.perf_counter() - phase_start
                if success:
                    self.logger.info("登录成功 (总耗时 %.1fs): %s", total, message)
                    return True, message
                self.logger.error("登录失败 (总耗时 %.1fs): %s", total, message)
                return False, message

        except LoginCancelledError:
            self.logger.info("登录已取消")
            return False, "登录已取消"
        except Exception as e:
            total = _time.perf_counter() - phase_start
            self.logger.error("登录异常 (总耗时 %.1fs): %s", total, e)
            return False, f"任务执行异常: {e}"
