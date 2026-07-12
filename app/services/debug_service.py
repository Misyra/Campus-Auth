"""调试会话管理器 — 封装调试会话的状态管理和浏览器生命周期。

从 main.py 提取，解决 DebugSession 命名冲突：
- DebugSessionManager: 封装锁、信号量、定时器等状态管理，直接管理浏览器生命周期
- debug_session.DebugSession: dataclass，表示会话状态（保持不变）
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.services.login_orchestrator import runtime_config_to_worker_dict
from app.utils.env import build_login_template_vars
from app.utils.logging import get_logger

if TYPE_CHECKING:
    from starlette.requests import Request

from .debug_session import (
    DebugSession,
    _current_gen,
    _next_debug_gen,
    debug_to_response,
)

debug_logger = get_logger("debug_manager", source="backend")


_MAX_DELETE_RETRIES = 5
_DELETE_RETRY_INTERVAL = 0.1


def _rm(path: Path) -> None:
    """删除文件，Windows 下文件被占用时自动重试。"""
    for _ in range(_MAX_DELETE_RETRIES):
        try:
            path.unlink()
            return
        except PermissionError:
            time.sleep(_DELETE_RETRY_INTERVAL)
    raise OSError(f"无法删除被占用文件: {path}")


class DebugSessionManager:
    """调试会话管理器 — 封装所有调试会话的状态和操作。"""

    DEBUG_SESSION_TIMEOUT_SECONDS: float = 1800.0

    def __init__(self, project_root: Path):
        self._project_root = project_root
        self._temp_dir = project_root / "temp" / "debug"
        self._session = DebugSession()
        self._lock = asyncio.Lock()
        self._exec_sem = asyncio.Semaphore(1)

    async def _cancel_debug_timer(self) -> None:
        """取消调试会话的超时定时器（如存在）。"""
        timer = self._session._timer_task
        if timer and not timer.done():
            timer.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await timer

    def _require_debug_session(self) -> None:
        """验证调试会话处于活跃状态。"""
        if not self._session.running:
            from fastapi import HTTPException

            raise HTTPException(status_code=400, detail="没有活跃的调试会话")

    async def _close_debug_browser(self) -> None:
        """关闭调试浏览器 — 委托 Worker 处理。"""
        from app.workers.playwright_worker import CMD_DEBUG_STOP, get_worker

        try:
            await asyncio.to_thread(lambda: get_worker().submit(CMD_DEBUG_STOP))
        except Exception:
            debug_logger.warning("关闭调试会话失败: Worker 提交失败", exc_info=True)
        self._session._browser_active = False

    async def _debug_timeout_watcher(
        self, gen: int, *, timeout_seconds: float = DEBUG_SESSION_TIMEOUT_SECONDS
    ) -> None:
        """监控调试会话超时，超过 timeout_seconds 无操作则关闭浏览器。"""
        check_interval = min(60, timeout_seconds / 10)
        try:
            while True:
                await asyncio.sleep(check_interval)
                async with self._lock:
                    if gen != _current_gen:
                        return
                    if (
                        time.monotonic() - self._session._last_activity
                        > timeout_seconds
                    ):
                        debug_logger.debug(
                            "调试会话超时 ({}s 无操作)，关闭浏览器",
                            timeout_seconds,
                        )
                        try:
                            if self._session._browser_active:
                                await self._close_debug_browser()
                        finally:
                            self._session = DebugSession()
                        return  # 超时后退出，不再空转
                    # 未超时时释放锁，下一轮 sleep 后重新检查
        except asyncio.CancelledError:
            pass

    async def start(self, request: Request, monitor_service: Any) -> dict:
        """启动调试会话。"""
        from fastapi import HTTPException

        from app.workers.playwright_worker import CMD_DEBUG_START, get_worker

        body = await request.json()
        task_id = body.get("task_id", "")
        if not task_id:
            raise HTTPException(status_code=400, detail="缺少 task_id")

        task_mgr = request.app.state.services.task_manager
        task = task_mgr.load_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")

        # 构建模板变量（复用 service 的运行时配置）— 通过 to_thread 避免磁盘 I/O 与加密操作阻塞事件循环
        def _build_template_vars():
            rc = monitor_service.get_runtime_config()
            tv = build_login_template_vars(
                auth_url=rc.credentials.auth_url,
                username=rc.credentials.username,
                password=rc.credentials.password,
                isp=rc.credentials.isp,
                task_url=task.url,
            )
            return rc, tv

        runtime_config, template_vars = await asyncio.to_thread(_build_template_vars)

        # 解析任务 URL
        url = task.url or ""
        for k, v in template_vars.items():
            url = url.replace("{{" + k + "}}", v)

        browser_timeout = runtime_config.browser.timeout * 1000
        navigation_timeout = runtime_config.browser.navigation_timeout * 1000

        # 构建 Worker 启动数据
        # 注入网卡绑定代理（与 LoginOrchestrator 一致，监控未启动时为 None）
        # monitor_service 实际是 ScheduleEngine，bind_proxy_url 在其 _monitor_core 上
        core = getattr(monitor_service, "_monitor_core", None)
        bind_proxy = getattr(core, "bind_proxy_url", None) if core else None
        worker_data = {
            "config": runtime_config_to_worker_dict(
                runtime_config, bind_proxy=bind_proxy
            ),
            "task_url": url if url else "",
            "task_data": task.to_dict(),
            "template_vars": template_vars,
            "screenshot_dir": str(self._temp_dir),
            "default_timeout": browser_timeout,
            "navigation_timeout": navigation_timeout,
        }

        async with self._lock:
            if self._session._browser_active:
                await self._close_debug_browser()
            await self._cancel_debug_timer()

            steps_info = [
                {
                    "index": i,
                    "id": step.id,
                    "type": step.type,
                    "description": step.description or step.type,
                }
                for i, step in enumerate(task.steps)
            ]

            gen = _next_debug_gen()
            self._session = DebugSession()
            self._session._browser_active = True
            self._session.task_id = task_id
            self._session.steps = steps_info
            self._session.running = True
            self._session._last_activity = time.monotonic()
            self._session._timer_task = asyncio.create_task(
                self._debug_timeout_watcher(gen)
            )
            self._session.executor = None

        # Worker 启动在锁外执行，避免持锁等待线程
        try:
            response = await asyncio.to_thread(
                lambda: get_worker().submit(CMD_DEBUG_START, data=worker_data)
            )
        except Exception:
            async with self._lock:
                await self._cancel_debug_timer()
                await self._close_debug_browser()
                self._session = DebugSession()
            raise

        if not response.success:
            async with self._lock:
                await self._cancel_debug_timer()
                await self._close_debug_browser()
                self._session = DebugSession()
            debug_logger.warning(
                "调试会话启动失败: task={}, {}", task_id, response.error
            )
            raise RuntimeError(f"调试会话启动失败: {response.error}")

        if isinstance(response.data, dict):
            async with self._lock:
                self._session.screenshot_url = response.data.get("screenshot_url")

        debug_logger.info("启动调试会话成功: task={}", task_id)
        return debug_to_response(self._session)

    async def next_step(self) -> dict:
        """执行下一步。"""
        from app.workers.playwright_worker import CMD_DEBUG_STEP, get_worker

        async with self._exec_sem:
            async with self._lock:
                self._require_debug_session()
                session = self._session
                idx = session.current_step

                if idx >= len(session.steps):
                    return {
                        **debug_to_response(self._session),
                        "message": "所有步骤已执行完毕",
                    }

            response = await asyncio.to_thread(
                lambda: get_worker().submit(CMD_DEBUG_STEP, data={"step_index": idx})
            )
            if not response.success:
                async with self._lock:
                    if self._session is not session:
                        return debug_to_response(self._session)
                    session.results.append(
                        {
                            "step_index": idx,
                            "success": False,
                            "message": response.error or "步骤执行失败",
                            "screenshot_url": None,
                        }
                    )
                    session.current_step = idx + 1
                    session._last_activity = time.monotonic()
                    return debug_to_response(self._session)

            result = response.data

            async with self._lock:
                if self._session is not session:
                    return debug_to_response(self._session)
                session.results.append(result)
                session.screenshot_url = result.get("screenshot_url")
                session.current_step = idx + 1
                session._last_activity = time.monotonic()
                return debug_to_response(self._session)

    async def run_all(self) -> dict:
        """执行所有步骤。"""
        from app.workers.playwright_worker import CMD_DEBUG_STEP, get_worker

        debug_logger.debug("调试运行所有步骤: task={}", self._session.task_id)

        async with self._lock:
            self._require_debug_session()
            session = self._session

        # 一次性获取信号量，持有到整个批量执行完成，防止 next_step 插入
        async with self._exec_sem:
            async with self._lock:
                from_idx = session.current_step
                if from_idx >= len(session.steps):
                    return {
                        **debug_to_response(self._session),
                        "message": "所有步骤已执行完毕",
                    }

            worker = get_worker()

            results: list[dict] = []
            all_success = True

            for i in range(from_idx, len(session.steps)):
                # 会话有效性检查在锁内执行
                async with self._lock:
                    if self._session is not session or not session.running:
                        all_success = False
                        break

                response = await asyncio.to_thread(
                    lambda idx=i: worker.submit(
                        CMD_DEBUG_STEP, data={"step_index": idx}
                    )
                )

                # 响应后在锁内检查会话状态
                async with self._lock:
                    if self._session is not session or not session.running:
                        all_success = False
                        break

                if not response.success:
                    results.append(
                        {
                            "step_index": i,
                            "success": False,
                            "message": response.error or "步骤执行异常",
                            "screenshot_url": None,
                        }
                    )
                    all_success = False
                    break

                step_result = response.data
                results.append(step_result)
                if not step_result.get("success", False):
                    all_success = False
                    break

        async with self._lock:
            if self._session is not session:
                return debug_to_response(self._session)
            session.results.extend(results)
            session.current_step = (
                len(session.steps) if all_success else from_idx + len(results)
            )
            session._last_activity = time.monotonic()
            if results:
                session.screenshot_url = results[-1].get("screenshot_url")
            return debug_to_response(self._session)

    async def stop(self) -> dict:
        """停止调试会话。"""
        async with self._exec_sem, self._lock:
            await self._cancel_debug_timer()
            if self._session._browser_active:
                await self._close_debug_browser()
            self._session = DebugSession()
        # 清理临时调试截图（仅删除调试专用子目录中的文件）
        try:
            if self._temp_dir.exists():
                for item in self._temp_dir.iterdir():
                    if item.is_file():
                        _rm(item)
        except FileNotFoundError:
            pass
        except Exception:
            debug_logger.warning(
                "调试临时目录清理失败: {}", self._temp_dir, exc_info=True
            )
        debug_logger.info("停止调试会话成功")
        return {"running": False, "message": "调试会话已关闭"}

    async def close(self):
        """关闭调试会话（用于 lifespan 清理）。"""
        async with self._lock:
            try:
                await self._cancel_debug_timer()
                if self._session._browser_active:
                    await self._close_debug_browser()
            finally:
                self._session = DebugSession()
