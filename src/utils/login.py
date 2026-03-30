#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
登录尝试处理器
"""

import datetime
import os
from pathlib import Path
from typing import Any, Dict

from ..task_executor import TaskExecutor, TaskManager
from .browser import BrowserContextManager
from .logging import LoggerSetup
from .time import TimeUtils


class LoginAttemptHandler:
    """登录尝试处理器 - 统一登录逻辑（解决循环依赖）"""

    def __init__(self, config: Dict[str, Any]):
        """
        初始化登录处理器

        参数:
            config: 配置字典
        """
        self.config = config
        self.logger = LoggerSetup.setup_logger(
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

        except Exception as e:
            error_msg = f"登录过程中发生错误: {str(e)}"
            self.logger.error(f"❌ {error_msg}")
            return False, error_msg

    async def _perform_login_with_auth_class(self) -> tuple[bool, str]:
        """优先使用活动任务执行登录，未配置任务时回退到认证类。"""
        task_result = await self._perform_login_with_active_task()
        if task_result is not None:
            return task_result

        # 回退到历史认证流程，兼容未配置任务的场景
        try:
            from ..campus_login import EnhancedCampusNetworkAuth

            auth = EnhancedCampusNetworkAuth(self.config)
            success, message = await auth.authenticate()

            if success:
                self.logger.info(f"✅ 校园网登录成功: {message}")
                return True, message
            else:
                self.logger.error(f"❌ 校园网登录失败: {message}")
                return False, message

        except ImportError as e:
            error_msg = f"无法导入认证模块: {e}"
            self.logger.error(f"❌ {error_msg}")
            return False, error_msg
        except Exception as e:
            error_msg = f"登录执行失败: {str(e)}"
            self.logger.error(f"❌ {error_msg}")
            return False, error_msg

    async def _perform_login_with_active_task(self) -> tuple[bool, str] | None:
        """执行当前活动任务；返回 None 表示未找到可执行任务。"""
        try:
            root_override = os.getenv("Campus-Auth_PROJECT_ROOT", "").strip()
            project_root = (
                Path(root_override).expanduser().resolve()
                if root_override
                else Path(__file__).resolve().parents[2]
            )

            task_manager = TaskManager(project_root / "tasks")
            active_task_id = task_manager.get_active_task().strip() or "default"
            task = task_manager.load_task(active_task_id)

            if not task:
                self.logger.warning(f"⚠️ 未找到活动任务: {active_task_id}")
                return None

            env_vars = dict(os.environ)
            self.logger.info(f"🧩 使用活动任务执行登录: {active_task_id}")

            async with BrowserContextManager(self.config) as browser_manager:
                if not browser_manager.page:
                    return False, "任务执行失败：浏览器页面初始化失败"

                executor = TaskExecutor(task, env_vars)
                success, message = await executor.execute(browser_manager.page)
                if success:
                    self.logger.info(f"✅ 任务登录成功: {message}")
                    return True, message

                self.logger.error(f"❌ 任务登录失败: {message}")
                return False, message

        except Exception as e:
            error_msg = f"任务执行异常: {e}"
            self.logger.error(f"❌ {error_msg}")
            return False, error_msg
