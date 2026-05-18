#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
登录尝试处理器
"""

import datetime
import os
import re
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
        self._browser_ctx: BrowserContextManager | None = None

    async def attempt_login(self, skip_pause_check: bool = False, reuse_browser: bool = False) -> tuple[bool, str]:
        """
        尝试登录校园网（统一实现）

        参数:
            skip_pause_check: 是否跳过暂停时间检查
            reuse_browser: 是否复用已打开的浏览器（监控重试时使用）

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
            return await self._perform_login_with_auth_class(reuse_browser=reuse_browser)

        except LoginCancelledError:
            self.logger.info("登录操作已取消")
            return False, "登录已取消"
        except Exception as e:
            error_msg = f"登录过程中发生错误: {str(e)}"
            self.logger.error(f"❌ {error_msg}")
            return False, error_msg

    async def _perform_login_with_auth_class(self, *, reuse_browser: bool = False) -> tuple[bool, str]:
        """使用活动任务执行登录。"""
        task_result = await self._perform_login_with_active_task(reuse_browser=reuse_browser)
        if task_result is not None:
            return task_result

        error_msg = "未找到可执行的活动任务，请在任务管理页面配置并激活一个任务"
        self.logger.error(f"❌ {error_msg}")
        return False, error_msg

    async def _perform_login_with_active_task(self, *, reuse_browser: bool = False) -> tuple[bool, str] | None:
        """执行当前活动任务；返回 None 表示未找到可执行任务。

        reuse_browser=True 时，失败后保留浏览器供下次重试复用。
        """
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
                _ENV_DENYLIST = {"PATH", "PYTHONPATH", "HOME", "USER", "USERNAME",
                    "SYSTEMROOT", "TEMP", "TMP", "PATHEXT", "COMSPEC", "WINDIR",
                    "LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH", "DISPLAY", "SHELL",
                    "LANG", "LC_ALL"}
                for k, v in custom_vars.items():
                    if k.upper() not in _ENV_DENYLIST:
                        env_vars[k] = v

            if self.cancel_event and self.cancel_event.is_set():
                return False, "登录已取消"

            # 复用或创建浏览器
            if reuse_browser and self._browser_ctx is not None:
                browser_manager = self._browser_ctx
                # 健康检查：验证浏览器是否仍然存活
                try:
                    if not browser_manager.browser or not browser_manager.browser.is_connected():
                        raise RuntimeError("浏览器进程已断开")
                    if browser_manager.page and browser_manager.page.is_closed():
                        raise RuntimeError("浏览器页面已关闭")
                except Exception as exc:
                    self.logger.warning("浏览器健康检查失败，将重新启动: %s", exc)
                    await self.close_browser()
                    browser_manager = None
                    reuse_browser = False

                if browser_manager is not None:
                    self.logger.info("复用浏览器...")

            if not reuse_browser or self._browser_ctx is None:
                # 不复用：关闭旧的（如果有），新建
                await self.close_browser()
                self.logger.info("启动浏览器...")
                browser_start = _time.perf_counter()
                browser_manager = BrowserContextManager(self.config, cancel_event=self.cancel_event)
                await browser_manager.__aenter__()
                self._browser_ctx = browser_manager
                self.logger.info("浏览器就绪 (%.1fs)", _time.perf_counter() - browser_start)

            try:
                if not browser_manager.page:
                    raise RuntimeError("浏览器页面初始化失败")

                browser_timeout = self.config.get("browser_settings", {}).get("timeout", 10000)

                # 构建网络检测配置，传递给 TaskExecutor 用于成功判断
                network_test_config = self._build_network_test_config()

                executor = TaskExecutor(
                    task, env_vars, default_timeout=browser_timeout,
                    network_test_config=network_test_config,
                )
                success, message = await executor.execute(browser_manager.page)
                total = _time.perf_counter() - phase_start
                if success:
                    self.logger.info("登录成功 (总耗时 %.1fs): %s", total, message)
                    await self.close_browser()
                    return True, message
                log_msg = re.sub(r'\s*截图[:：]\s*/\S+\.(?:png|jpg|jpeg|webp|gif)', '', message)
                self.logger.error("登录失败 (总耗时 %.1fs): %s", total, log_msg)
                if not reuse_browser:
                    await self.close_browser()
                return False, message
            except Exception:
                await self.close_browser()
                raise

        except LoginCancelledError:
            self.logger.info("登录已取消")
            return False, "登录已取消"
        except Exception as e:
            total = _time.perf_counter() - phase_start
            self.logger.error("登录异常 (总耗时 %.1fs): %s", total, e)
            return False, f"任务执行异常: {e}"

    def _build_network_test_config(self) -> dict:
        """构建网络检测配置，供 TaskExecutor 成功判断使用。"""
        import re

        monitor = self.config.get("monitor", {})
        targets = monitor.get("ping_targets", [])
        if isinstance(targets, str):
            targets = [item.strip() for item in targets.split(",") if item.strip()]

        test_sites = []
        for item in targets:
            host = item
            port = 0
            if ":" in item:
                host_part, port_part = item.rsplit(":", 1)
                if host_part.strip() and port_part.strip().isdigit():
                    host = host_part.strip()
                    port = int(port_part.strip())
            if port <= 0:
                is_ipv4 = bool(re.fullmatch(r"\d+\.\d+\.\d+\.\d+", host))
                port = 53 if is_ipv4 else 443
            test_sites.append((host, port))

        return {
            "test_sites": test_sites if test_sites else None,
            "timeout": monitor.get("network_check_timeout", 2),
            "strict_mode": monitor.get("strict_mode", True),
        }

    async def close_browser(self) -> None:
        """关闭浏览器（登录成功或监控停止时调用）"""
        if self._browser_ctx:
            try:
                await self._browser_ctx.__aexit__(None, None, None)
            except Exception as exc:
                self.logger.debug("浏览器关闭时异常 (非关键): %s", exc)
            self._browser_ctx = None
            self.logger.info("浏览器已关闭")
