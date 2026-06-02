"""调试会话管理器 — 封装调试会话的状态管理和浏览器生命周期。

从 main.py 提取，解决 DebugSession 命名冲突：
- DebugBrowserSession: 管理浏览器生命周期（原 main.py 中的 DebugSession 类）
- DebugSessionManager: 封装锁、信号量、定时器等状态管理
- debug_session.DebugSession: dataclass，表示会话状态（保持不变）
"""

from __future__ import annotations

import asyncio
import shutil
import time
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Request

from src.playwright_worker import (
    CMD_DEBUG_START,
    CMD_DEBUG_STEP,
    CMD_DEBUG_STOP,
    get_worker,
)
from src.utils.env import build_login_env_vars
from src.utils.logging import get_logger

from .debug_session import (
    _current_gen,
    _next_debug_gen,
    debug_to_response,
    empty_debug_session,
)

api_logger = get_logger("backend.debug_manager", side="BACKEND")


class DebugBrowserSession:
    """调试浏览器会话 — 管理浏览器生命周期。

    浏览器生命周期由 PlaywrightWorker 管理。
    所有浏览器操作通过 Worker 的命令队列提交执行。
    TaskExecutor 在 Worker 线程内创建和运行，确保 page 对象线程安全。
    """

    def __init__(self):
        self.page = None  # 向后兼容标记，实际 page 由 Worker 管理

    async def start(
        self, runtime_config: dict, url: str | None, pure_mode: bool = False
    ) -> None:
        """启动调试会话 — 委托 Worker 处理浏览器初始化。"""
        data = {
            "config": runtime_config,
            "task_url": url or "",
            "pure_mode": pure_mode,
        }
        response = await asyncio.to_thread(
            lambda: get_worker().submit(CMD_DEBUG_START, data=data)
        )
        if not response.success:
            raise RuntimeError(f"调试会话启动失败: {response.error}")
        self.page = True  # 标记已启动

    async def close(self) -> None:
        """关闭调试会话 — 委托 Worker 关闭浏览器页面。"""
        try:
            await asyncio.to_thread(
                lambda: get_worker().submit(CMD_DEBUG_STOP)
            )
        except Exception:
            api_logger.debug("关闭调试会话 Worker 提交失败", exc_info=True)
        self.page = None


class DebugSessionManager:
    """调试会话管理器 — 封装所有调试会话的状态和操作。"""

    def __init__(self, project_root: Path):
        self._project_root = project_root
        self._temp_dir = project_root / "temp"
        self._session = empty_debug_session()
        self._lock = asyncio.Lock()
        self._exec_sem = asyncio.Semaphore(1)

    def _debug_response(self) -> dict:
        return debug_to_response(self._session)

    async def _cancel_debug_timer(self) -> None:
        """取消调试会话的超时定时器（如存在）。"""
        timer = self._session._timer_task
        if timer and not timer.done():
            timer.cancel()
            try:
                await timer
            except asyncio.CancelledError:
                pass

    def _require_debug_session(self) -> None:
        """验证调试会话处于活跃状态。"""
        if not self._session.running:
            raise HTTPException(status_code=400, detail="没有活跃的调试会话")

    async def _debug_timeout_watcher(
        self, gen: int, *, timeout_seconds: float = 1800.0
    ) -> None:
        """监控调试会话超时，超过 timeout_seconds 无操作则关闭浏览器。"""
        check_interval = min(60, timeout_seconds / 10)
        try:
            while True:
                await asyncio.sleep(check_interval)
                if gen != _current_gen:
                    return
                if time.monotonic() - self._session._last_activity > timeout_seconds:
                    async with self._lock:
                        if gen != _current_gen:
                            return
                        api_logger.info(
                            "调试会话超时（%ds 无操作），正在关闭浏览器",
                            timeout_seconds,
                        )
                        if self._session.session:
                            await self._session.session.close()
                        self._session = empty_debug_session()
        except asyncio.CancelledError:
            pass

    async def start(self, request: Request, monitor_service: Any) -> dict:
        """启动调试会话。"""
        body = await request.json()
        task_id = body.get("task_id", "")
        if not task_id:
            raise HTTPException(status_code=400, detail="缺少 task_id")

        from src.task_executor import TaskManager

        tm = TaskManager(self._project_root / "tasks")
        task = tm.load_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")

        # 构建环境变量（复用 service 的运行时配置）
        runtime_config = monitor_service.get_runtime_config()
        env_vars = build_login_env_vars(
            runtime_config, task.url, runtime_config.get("custom_variables", {})
        )

        # 解析任务 URL
        url = task.url or ""
        for k, v in env_vars.items():
            url = url.replace("{{" + k + "}}", v)

        browser_settings = runtime_config.get("browser_settings", {})
        browser_timeout = browser_settings.get("timeout", 8) * 1000
        navigation_timeout = browser_settings.get("navigation_timeout", 15) * 1000

        # 构建 Worker 启动数据
        worker_data = {
            "config": runtime_config,
            "task_url": url if url else "",
            "task_data": task.to_dict(),
            "env_vars": env_vars,
            "screenshot_dir": str(self._temp_dir),
            "default_timeout": browser_timeout,
            "navigation_timeout": navigation_timeout,
        }

        async with self._lock:
            if self._session.session:
                await self._session.session.close()
            await self._cancel_debug_timer()

            session = DebugBrowserSession()
            try:
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
                self._session = empty_debug_session()
                self._session.session = session
                self._session.task_id = task_id
                self._session.steps = steps_info
                self._session.running = True
                self._session._last_activity = time.monotonic()
                self._session._timer_task = asyncio.create_task(
                    self._debug_timeout_watcher(gen)
                )
                self._session.executor = None

                response = await asyncio.to_thread(
                    lambda: get_worker().submit(CMD_DEBUG_START, data=worker_data)
                )
                if not response.success:
                    raise RuntimeError(f"调试会话启动失败: {response.error}")
                session.page = True
                if isinstance(response.data, dict):
                    self._session.screenshot_url = response.data.get("screenshot_url")
            except Exception:
                await session.close()
                raise

        api_logger.info("Debug session started for task %s", task_id)
        return self._debug_response()

    async def next_step(self) -> dict:
        """执行下一步。"""
        async with self._exec_sem:
            async with self._lock:
                self._require_debug_session()
                idx = self._session.current_step

                if idx >= len(self._session.steps):
                    return {**self._debug_response(), "message": "所有步骤已执行完毕"}

            response = await asyncio.to_thread(
                lambda: get_worker().submit(
                    CMD_DEBUG_STEP, data={"step_index": idx}
                )
            )
            if not response.success:
                async with self._lock:
                    self._session.results.append(
                        {
                            "step_index": idx,
                            "success": False,
                            "message": response.error or "步骤执行失败",
                            "screenshot_url": None,
                        }
                    )
                    self._session.current_step = idx + 1
                    self._session._last_activity = time.monotonic()
                    return self._debug_response()

            result = response.data

            async with self._lock:
                self._session.results.append(result)
                self._session.screenshot_url = result.get("screenshot_url")
                self._session.current_step = idx + 1
                self._session._last_activity = time.monotonic()
                return self._debug_response()

    async def run_all(self) -> dict:
        """执行所有步骤。"""
        async with self._lock:
            self._require_debug_session()
            from_idx = self._session.current_step

            if from_idx >= len(self._session.steps):
                return {**self._debug_response(), "message": "所有步骤已执行完毕"}

        worker = get_worker()
        results: list[dict] = []
        all_success = True

        for i in range(from_idx, len(self._session.steps)):
            async with self._exec_sem:
                async with self._lock:
                    if not self._session.running:
                        all_success = False
                        break

                response = await asyncio.to_thread(
                    lambda idx=i: worker.submit(
                        CMD_DEBUG_STEP, data={"step_index": idx}
                    )
                )

            if not self._session.running:
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
            self._session.results.extend(results)
            self._session.current_step = (
                len(self._session.steps) if all_success else from_idx + len(results)
            )
            self._session._last_activity = time.monotonic()
            if results:
                self._session.screenshot_url = results[-1].get("screenshot_url")
            return self._debug_response()

    async def stop(self) -> dict:
        """停止调试会话。"""
        async with self._exec_sem:
            async with self._lock:
                await self._cancel_debug_timer()
                if self._session.session:
                    await self._session.session.close()
                self._session = empty_debug_session()
        # 清理临时调试截图（仅删除文件，保留目录结构）
        try:
            if self._temp_dir.exists():
                for item in self._temp_dir.iterdir():
                    if item.is_file():
                        item.unlink(missing_ok=True)
        except Exception:
            api_logger.debug("调试临时目录清理失败", exc_info=True)
        api_logger.info("Debug session stopped")
        return {"running": False, "message": "调试会话已关闭"}

    def get_status(self) -> dict:
        """获取会话状态。"""
        return self._debug_response()

    async def close(self):
        """关闭调试会话（用于 lifespan 清理）。"""
        if self._session.session:
            await self._session.session.close()
        self._session = empty_debug_session()
