"""单次登录尝试 — 任务加载、Script/Browser 分支、表单提交与结果解析。"""

import asyncio
import contextlib
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

from app.utils.browser import BrowserContextManager
from app.utils.env import build_login_template_vars
from app.utils.exceptions import LoginCancelledError
from app.utils.logging import get_logger
from app.workers.login_models import AttemptOutcome, AttemptOutcomeType


class LoginAttempt:
    """单次登录尝试 — 任务加载、Script/Browser 分支、表单提交与结果解析。"""

    def __init__(
        self,
        config: dict[str, Any],
        cancel_event: threading.Event | None = None,
        *,
        browser: BrowserContextManager | None = None,
    ):
        """
        初始化登录尝试器。

        参数:
            config: 配置字典
            cancel_event: 取消事件，设置后中断登录操作
            browser: Session 模式下由 LoginSession 传入的浏览器上下文。
                     非 None 时复用该浏览器，不自行创建/关闭；
                     None 时保持旧行为（自行创建/关闭，兼容旧调用方）。
        """
        self.config = config
        self.cancel_event = cancel_event
        self.logger = get_logger("login", source="backend")
        self._browser_ctx: BrowserContextManager | None = browser
        self._task_manager: Any | None = None
        self._project_root: Path | None = None

        # 解构常用字段为命名属性（dict 结构由 runtime_config_to_worker_dict 保证）
        self._credentials: dict[str, str] = {
            "username": config.get("username", ""),
            "password": config.get("password", ""),
            "auth_url": config.get("auth_url", ""),
            "isp": config.get("isp", ""),
        }
        self._browser_settings: dict[str, Any] = config.get("browser_settings", {})
        self._monitor_settings: dict[str, Any] = config.get("monitor", {})
        self._active_task: str = config.get("active_task", "").strip()

    async def attempt_login(self) -> tuple[bool, str]:
        """
        尝试登录校园网（统一实现）

        前置检查（暂停时段、网络状态、登录前置条件）由调用方负责。
        本方法只负责执行登录任务。

        返回:
            tuple[bool, str]: (是否成功, 详细信息)
        """
        self.logger.debug("登录开始")
        try:
            task_result = await self._perform_login_with_active_task()
            if task_result is not None:
                return task_result
        except LoginCancelledError:
            raise
        except Exception as exc:
            self.logger.error("登录异常: {}", exc)
            return False, str(exc)

        error_msg = "未找到可执行的任务，请先在任务管理页面创建并启用一个登录任务"
        self.logger.warning("登录失败: {}", error_msg)
        return False, error_msg

    async def execute(self) -> AttemptOutcome:
        """执行单次登录尝试，返回 AttemptOutcome。

        失败统一标记为 RETRYABLE（按重试策略重试）。

        异常处理：
        - LoginCancelledError → CANCELLED
        - attempt_login() 内部已 catch 所有非取消异常（login_attempt.py:77-79），
          返回 (False, str(exc))，本方法无需重复 catch
        """
        try:
            success, message = await self.attempt_login()
            if success:
                return AttemptOutcome(AttemptOutcomeType.SUCCESS, message)
            return AttemptOutcome(AttemptOutcomeType.RETRYABLE, message)
        except LoginCancelledError:
            return AttemptOutcome(AttemptOutcomeType.CANCELLED, "登录已取消")

    async def _perform_login_with_active_task(self) -> tuple[bool, str] | None:
        """执行当前活动任务；返回 None 表示未找到可执行任务。"""
        from app.tasks.models import ScriptTaskInfo

        phase_start = time.perf_counter()
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

    def _ensure_task_manager(self) -> None:
        """懒初始化 TaskManager。"""
        if self._task_manager is None:
            from app.tasks.manager import TaskManager

            root_override = os.getenv("CAMPUS_AUTH_PROJECT_ROOT", "").strip()
            self._project_root = (
                Path(root_override).expanduser().resolve()
                if root_override
                else Path(__file__).resolve().parents[2]
            )
            self._task_manager = TaskManager(self._project_root / "tasks")

    async def _verify_network_after_login(self) -> tuple[bool, str]:
        """登录步骤通过后，等待 portal 生效并执行网络检测。

        Returns:
            (ok, msg)：网络恢复返回 (True, "network_ok (...)")；
            未恢复返回 (False, 状态描述)；
            所有检测禁用时返回 (True, "all_disabled")（信任步骤结果）。
        """
        from app.network.decision import check_network_status
        from app.schemas import MonitorSettings

        cfg = self._monitor_settings
        monitor = MonitorSettings(
            **{
                k: v
                for k, v in cfg.items()
                if k in MonitorSettings.model_fields
                and v is not None
                and not (isinstance(v, list | str | dict) and not v)
            }
        )

        # post_login_delay：让 portal 完成跳转和会话生效
        delay = monitor.post_login_delay
        await asyncio.sleep(delay)

        ok, status, method = await check_network_status(monitor)
        if status == "all_disabled":
            self.logger.debug("[network_check] 所有检测方式已禁用，信任步骤结果")
            return True, "all_disabled"
        if ok:
            return True, f"network_ok ({method})"
        return False, status

    async def _execute_browser_task(
        self, task: Any, active_task_id: str, phase_start: float
    ) -> tuple[bool, str]:
        """执行浏览器任务。"""
        from app.tasks import BrowserTaskRunner

        login_url = self._credentials["auth_url"]
        username = self._credentials["username"]
        isp = self._credentials["isp"]
        self.logger.debug(
            "登录开始: task={}, url={}, 用户={}, 运营商={}, 步骤数={}",
            active_task_id,
            login_url,
            username[:3] + "***" if username else "",
            isp or "无",
            len(task.steps),
        )

        template_vars = build_login_template_vars(
            auth_url=self._credentials.get("auth_url", ""),
            username=self._credentials.get("username", ""),
            password=self._credentials.get("password", ""),
            isp=self._credentials.get("isp", ""),
            task_url=task.url,
        )

        if self.cancel_event and self.cancel_event.is_set():
            return False, "登录已取消"

        # 浏览器获取：Session 模式复用传入的 browser，旧模式自行创建
        if self._browser_ctx is not None:
            # Session 模式：browser 已由 LoginSession 通过 __init__ 传入并就绪
            browser_manager = self._browser_ctx
            browser_owned = False

            # Attempt 间浏览器可能崩溃（TargetClosedError 等），
            # 检查 page 有效性，无效则通过 worker.ensure_browser 重建。
            # ensure_browser 是幂等的：浏览器健康则跳过，崩溃则重建。
            if browser_manager.page is None or browser_manager.page.is_closed():
                self.logger.debug("Session 浏览器 page 已失效，重建")
                from app.workers.playwright_worker import get_worker

                worker = get_worker()
                await worker.ensure_browser(self.config)
                # 刷新引用（ensure_browser 重建后 worker 的属性是新对象）
                browser_manager.page = worker.page
                browser_manager.context = worker.context
                browser_manager.browser = worker.browser

            self.logger.debug("复用 Session 浏览器")
        else:
            # 旧模式：自行创建浏览器（兼容调试会话等旧调用方）
            browser_owned = True
            self.logger.debug("启动浏览器")
            browser_start = time.perf_counter()
            browser_manager = BrowserContextManager(
                self.config, cancel_event=self.cancel_event
            )
            self._browser_ctx = (
                browser_manager  # 先赋值，确保异常时 close_browser 能清理
            )
            try:
                await browser_manager.__aenter__()
            except Exception:
                # __aenter__ 失败时手动调用 __aexit__ 释放已获取的资源
                self._browser_ctx = None
                with contextlib.suppress(Exception):
                    await browser_manager.__aexit__(*sys.exc_info())
                raise
            self.logger.debug(
                "浏览器就绪 ({:.1f}s)", time.perf_counter() - browser_start
            )

        success = False
        try:
            if not browser_manager.page:
                raise RuntimeError("浏览器页面初始化失败")

            browser_timeout = (
                self._browser_settings.get("timeout", 8) * 1000
            )  # 秒 → 毫秒
            navigation_timeout = (
                self._browser_settings.get("navigation_timeout", 15) * 1000
            )  # 秒 → 毫秒

            executor = BrowserTaskRunner(
                task,
                template_vars,
                default_timeout=browser_timeout,
                navigation_timeout=navigation_timeout,
                cancel_event=self.cancel_event,
            )

            # 监听页面 alert/confirm/prompt，记录内容并延迟关闭让用户看到
            # 执行后清理监听器，避免泄漏
            async def _handle_dialog(dialog):
                self.logger.debug("页面弹窗 [{}]: {}", dialog.type, dialog.message)
                await asyncio.sleep(1.5)  # 延迟关闭，让页面有时间处理弹窗
                await dialog.accept()

            browser_manager.page.on("dialog", _handle_dialog)
            try:
                success, message = await executor.execute(browser_manager.page)
            finally:
                browser_manager.page.remove_listener("dialog", _handle_dialog)
            total = time.perf_counter() - phase_start
            if success:
                # 任务声明了 success_condition → 信任 runner 的判定，不走网络检测
                # 未声明 → 登录路径追加网络检测作为兜底确认
                has_explicit_condition = bool(task.success_condition.strip())
                if has_explicit_condition:
                    self.logger.info(
                        "登录成功: {} (已声明成功条件, 跳过网络检测, 耗时 {:.1f}s)",
                        message,
                        total,
                    )
                    return True, message
                # 未声明成功条件 → 网络检测兜底
                net_ok, net_msg = await self._verify_network_after_login()
                if net_ok:
                    self.logger.info(
                        "登录成功: {} (网络验证通过, 耗时 {:.1f}s)",
                        message,
                        total,
                    )
                    return True, message
                self.logger.warning(
                    "登录失败: 步骤通过但网络未恢复 (耗时 {:.1f}s)", total
                )
                return False, f"步骤通过但网络未恢复: {net_msg}"
            self.logger.warning("登录失败: {} (耗时 {:.1f}s)", message, total)
            return False, message
        finally:
            # 旧模式（自行创建）需要关闭浏览器；
            # Session 模式（外部传入）由 LoginSession 的 async with 负责关闭。
            if browser_owned:
                await self.close_browser()

    async def _execute_script_task(
        self, task: Any, phase_start: float
    ) -> tuple[bool, str]:
        """执行 Python 脚本任务（无浏览器）。

        脚本只负责发请求，登录是否成功通过网络检测判断。
        """
        from app.network.decision import check_network_status
        from app.workers.script_runner import ScriptRunner

        self.logger.debug(
            "脚本任务开始: task={}, 脚本={}",
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
            self.logger.warning("脚本执行失败: {} (耗时 {:.1f}s)", script_output, total)
            return False, f"脚本执行失败: {script_output}"

        self.logger.debug("脚本已执行，等待网络验证")
        # 等待 portal 生效（与浏览器路径一致）
        await asyncio.sleep(self._monitor_settings.get("post_login_delay", 5))

        from app.schemas import MonitorSettings

        # Pydantic 默认会静默丢弃未知字段（model_config 忽略多余参数），
        # 此处显式过滤仅为可读性，功能上等价于直接 **self._monitor_settings。
        monitor_settings = MonitorSettings(
            **{
                k: v
                for k, v in self._monitor_settings.items()
                if k in MonitorSettings.model_fields
            }
        )
        net_ok, net_msg, _ = await asyncio.to_thread(
            check_network_status, monitor_settings
        )

        total = time.perf_counter() - phase_start
        if net_ok:
            self.logger.info("登录成功: 网络已连通 (耗时 {:.1f}s)", total)
            return True, "登录成功"
        else:
            self.logger.warning("登录失败: {} (耗时 {:.1f}s)", net_msg, total)
            return False, f"网络未连通: {net_msg}"

    async def close_browser(self) -> None:
        """释放浏览器上下文引用（不销毁浏览器实例）"""
        if self._browser_ctx:
            try:
                await self._browser_ctx.__aexit__(None, None, None)
            except Exception as exc:
                self.logger.warning("浏览器上下文关闭失败: {}", exc)
            finally:
                self._browser_ctx = None
                self.logger.debug("浏览器上下文已释放")
