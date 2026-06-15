"""login.py 测试 — 覆盖 LoginAttemptHandler 核心逻辑。"""

from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.utils.exceptions import LoginCancelledError
from app.utils.login import (
    LOGIN_SUCCESS_SETTLE_SECONDS,
    SCREENSHOT_URL_PATTERN,
    LoginAttemptHandler,
)


# ── helpers ──────────────────────────────────────────────────────────

def _make_config(**overrides: Any) -> dict[str, Any]:
    """构建最小配置字典。"""
    base: dict[str, Any] = {
        "auth_url": "http://example.com/auth",
        "username": "testuser",
        "isp": "telecom",
        "active_task": "",
        "browser_settings": {"timeout": 8, "navigation_timeout": 15},
        "monitor": {},
        "custom_variables": {},
    }
    base.update(overrides)
    return base


def _make_task_config(task_id: str = "default", steps: list | None = None):
    """构建 mock TaskConfig（非 ScriptTaskInfo）。"""
    task = MagicMock()
    task.task_id = task_id
    task.url = "http://example.com"
    task.steps = steps or [{"type": "input", "selector": "#user"}]
    # 确保 isinstance(task, ScriptTaskInfo) 为 False
    type(task).__name__ = "TaskConfig"
    return task


def _make_script_task(task_id: str = "script1", script_path: str = "/tmp/login.py"):
    """构建 ScriptTaskInfo 实例。"""
    from app.tasks.models import ScriptTaskInfo

    return ScriptTaskInfo(
        task_id=task_id,
        name="test_script",
        script_path=Path(script_path),
    )


# ── attempt_login: skip_pause_check=True ──


class TestAttemptLoginSkipPauseCheck:
    """skip_pause_check=True 时跳过暂停和网络检查。"""

    @pytest.mark.asyncio
    async def test_skip_pause_delegates_to_perform(self):
        config = _make_config()
        handler = LoginAttemptHandler(config)

        with patch.object(
            handler, "_perform_login_with_auth_class", new_callable=AsyncMock
        ) as mock_perform:
            mock_perform.return_value = (True, "ok")
            ok, msg = await handler.attempt_login(skip_pause_check=True)

        assert ok is True
        assert msg == "ok"
        mock_perform.assert_awaited_once()


class TestAttemptLoginWithPause:
    """不跳过暂停检查时的分支覆盖。"""

    @pytest.mark.asyncio
    async def test_pause_period_returns_false(self):
        config = _make_config(
            pause_login={"start_hour": 0, "end_hour": 6},
        )
        handler = LoginAttemptHandler(config)

        with patch("app.utils.login.datetime") as mock_dt, patch(
            "app.network.decision.check_pause", return_value=(True, "暂停中")
        ):
            mock_dt.datetime.now.return_value = MagicMock(hour=3)
            ok, msg = await handler.attempt_login(skip_pause_check=False)

        assert ok is False
        assert "暂停登录时段" in msg

    @pytest.mark.asyncio
    async def test_network_ok_returns_false(self):
        config = _make_config()
        handler = LoginAttemptHandler(config)

        # check_network_status 是同步函数，通过 asyncio.to_thread 调用
        # mock asyncio.to_thread 返回结果即可
        with patch(
            "app.network.decision.check_pause", return_value=(False, None)
        ), patch(
            "app.utils.login.asyncio.to_thread", new_callable=AsyncMock
        ) as mock_to_thread:
            mock_to_thread.return_value = (True, "正常")
            ok, msg = await handler.attempt_login(skip_pause_check=False)

        assert ok is False
        assert "网络正常" in msg

    @pytest.mark.asyncio
    async def test_local_disconnected_returns_false(self):
        config = _make_config()
        handler = LoginAttemptHandler(config)

        with patch(
            "app.network.decision.check_pause", return_value=(False, None)
        ), patch(
            "app.utils.login.asyncio.to_thread", new_callable=AsyncMock
        ) as mock_to_thread, patch(
            "app.network.decision.check_login_prerequisites",
            return_value=(False, "local_disconnected"),
        ):
            mock_to_thread.return_value = (False, "不通")
            ok, msg = await handler.attempt_login(skip_pause_check=False)

        assert ok is False
        assert "物理网络未连接" in msg

    @pytest.mark.asyncio
    async def test_auth_url_unreachable_returns_false(self):
        config = _make_config(auth_url="http://10.0.0.1/auth")
        handler = LoginAttemptHandler(config)

        with patch(
            "app.network.decision.check_pause", return_value=(False, None)
        ), patch(
            "app.utils.login.asyncio.to_thread", new_callable=AsyncMock
        ) as mock_to_thread, patch(
            "app.network.decision.check_login_prerequisites",
            return_value=(False, "auth_url_unreachable"),
        ):
            mock_to_thread.return_value = (False, "不通")
            ok, msg = await handler.attempt_login(skip_pause_check=False)

        assert ok is False
        assert "不可达" in msg

    @pytest.mark.asyncio
    async def test_prereqs_ok_delegates_to_perform(self):
        config = _make_config()
        handler = LoginAttemptHandler(config)

        with patch(
            "app.network.decision.check_pause", return_value=(False, None)
        ), patch(
            "app.utils.login.asyncio.to_thread", new_callable=AsyncMock
        ) as mock_to_thread, patch(
            "app.network.decision.check_login_prerequisites",
            return_value=(True, ""),
        ), patch.object(
            handler, "_perform_login_with_auth_class", new_callable=AsyncMock
        ) as mock_perform:
            mock_to_thread.return_value = (False, "不通")
            mock_perform.return_value = (True, "ok")
            ok, msg = await handler.attempt_login(skip_pause_check=False)

        assert ok is True
        mock_perform.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_exception_caught_returns_false(self):
        config = _make_config()
        handler = LoginAttemptHandler(config)

        with patch.object(
            handler,
            "_perform_login_with_auth_class",
            new_callable=AsyncMock,
            side_effect=RuntimeError("boom"),
        ):
            ok, msg = await handler.attempt_login(skip_pause_check=True)

        assert ok is False
        assert "boom" in msg


# ── _perform_login_with_auth_class ───────────────────────────────────


class TestPerformLoginWithAuthClass:

    @pytest.mark.asyncio
    async def test_active_task_returns_result(self):
        config = _make_config()
        handler = LoginAttemptHandler(config)

        with patch.object(
            handler, "_perform_login_with_active_task", new_callable=AsyncMock
        ) as mock_active:
            mock_active.return_value = (True, "任务成功")
            ok, msg = await handler._perform_login_with_auth_class()

        assert ok is True
        assert msg == "任务成功"

    @pytest.mark.asyncio
    async def test_no_active_task_returns_error(self):
        config = _make_config()
        handler = LoginAttemptHandler(config)

        with patch.object(
            handler, "_perform_login_with_active_task", new_callable=AsyncMock
        ) as mock_active:
            mock_active.return_value = None
            ok, msg = await handler._perform_login_with_auth_class()

        assert ok is False
        assert "未找到可执行的任务" in msg


# ── _perform_login_with_active_task ──────────────────────────────────


class TestPerformLoginWithActiveTask:

    @pytest.mark.asyncio
    async def test_profile_task_id_path(self):
        """active_task 配置时走 load_task 分支（行 125-127）。"""
        config = _make_config(active_task="my_task")
        handler = LoginAttemptHandler(config)

        mock_tm = MagicMock()
        mock_tm.load_task.return_value = _make_task_config()

        with patch.object(handler, "_ensure_task_manager"), patch.object(
            handler, "_execute_browser_task", new_callable=AsyncMock
        ) as mock_exec:
            mock_exec.return_value = (True, "ok")
            handler._task_manager = mock_tm
            ok, msg = await handler._perform_login_with_active_task()

        assert ok is True
        mock_tm.load_task.assert_called_once_with("my_task")

    @pytest.mark.asyncio
    async def test_no_profile_id_uses_active(self):
        """无 active_task 配置时使用 get_active_task（行 129-130）。"""
        config = _make_config(active_task="")
        handler = LoginAttemptHandler(config)

        mock_tm = MagicMock()
        mock_tm.get_active_task.return_value = "auto_task"
        mock_tm.load_active_task.return_value = _make_task_config()

        with patch.object(handler, "_ensure_task_manager"), patch.object(
            handler, "_execute_browser_task", new_callable=AsyncMock
        ) as mock_exec:
            mock_exec.return_value = (True, "ok")
            handler._task_manager = mock_tm
            ok, msg = await handler._perform_login_with_active_task()

        assert ok is True
        mock_tm.load_active_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_task_is_none_returns_none(self):
        """task 为 None 时返回 None（行 132-134）。"""
        config = _make_config()
        handler = LoginAttemptHandler(config)

        mock_tm = MagicMock()
        mock_tm.get_active_task.return_value = None
        mock_tm.load_active_task.return_value = None

        with patch.object(handler, "_ensure_task_manager"):
            handler._task_manager = mock_tm
            result = await handler._perform_login_with_active_task()

        assert result is None

    @pytest.mark.asyncio
    async def test_script_task_branch(self):
        """ScriptTaskInfo 任务走脚本分支（行 137-138）。"""
        config = _make_config()
        handler = LoginAttemptHandler(config)
        script_task = _make_script_task()

        mock_tm = MagicMock()
        mock_tm.get_active_task.return_value = "script1"
        mock_tm.load_active_task.return_value = script_task

        with patch.object(handler, "_ensure_task_manager"), patch.object(
            handler, "_execute_script_task", new_callable=AsyncMock
        ) as mock_exec:
            mock_exec.return_value = (True, "脚本成功")
            handler._task_manager = mock_tm
            ok, msg = await handler._perform_login_with_active_task()

        assert ok is True
        mock_exec.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_login_cancelled_error(self):
        """LoginCancelledError 被捕获（行 143-145）。"""
        config = _make_config()
        handler = LoginAttemptHandler(config)

        mock_tm = MagicMock()
        mock_tm.get_active_task.return_value = "default"
        mock_tm.load_active_task.side_effect = LoginCancelledError("取消")

        with patch.object(handler, "_ensure_task_manager"):
            handler._task_manager = mock_tm
            ok, msg = await handler._perform_login_with_active_task()

        assert ok is False
        assert "登录已取消" in msg

    @pytest.mark.asyncio
    async def test_generic_exception(self):
        """通用异常被捕获（行 146-149）。"""
        config = _make_config()
        handler = LoginAttemptHandler(config)

        mock_tm = MagicMock()
        mock_tm.get_active_task.return_value = "default"
        mock_tm.load_active_task.side_effect = RuntimeError("task error")

        with patch.object(handler, "_ensure_task_manager"):
            handler._task_manager = mock_tm
            ok, msg = await handler._perform_login_with_active_task()

        assert ok is False
        assert "task error" in msg


# ── _execute_browser_task ────────────────────────────────────────────


class TestExecuteBrowserTask:
    """覆盖 _execute_browser_task（行 190-255）。"""

    @pytest.mark.asyncio
    async def test_cancel_event_set_returns_false(self):
        """cancel_event 已设置时返回取消（行 186-187）。"""
        config = _make_config()
        cancel = threading.Event()
        cancel.set()
        handler = LoginAttemptHandler(config, cancel_event=cancel)

        task = _make_task_config()
        ok, msg = await handler._execute_browser_task(task, "default", time.perf_counter())

        assert ok is False
        assert "登录已取消" in msg

    @pytest.mark.asyncio
    async def test_existing_browser_closed_first(self):
        """已有浏览器实例时先关闭（行 190-191）。"""
        config = _make_config()
        handler = LoginAttemptHandler(config)

        # 模拟已有浏览器上下文
        handler._browser_ctx = MagicMock()
        handler._browser_ctx.__aexit__ = AsyncMock()

        mock_page = MagicMock()
        mock_page.on = MagicMock()
        mock_page.remove_listener = MagicMock()

        mock_browser_mgr = MagicMock()
        mock_browser_mgr.page = mock_page
        mock_browser_mgr.__aenter__ = AsyncMock(return_value=mock_browser_mgr)
        mock_browser_mgr.__aexit__ = AsyncMock()

        task = _make_task_config()

        with patch(
            "app.utils.login.BrowserContextManager", return_value=mock_browser_mgr
        ), patch(
            "app.utils.login.build_login_template_vars", return_value={}
        ), patch(
            "app.tasks.browser_runner.TaskExecutor"
        ) as MockExecutor:
            MockExecutor.return_value.execute = AsyncMock(return_value=(True, "登录成功"))

            ok, msg = await handler._execute_browser_task(task, "default", time.perf_counter())

        assert ok is True
        assert msg == "登录成功"

    @pytest.mark.asyncio
    async def test_browser_enter_failure_raises(self):
        """浏览器 __aenter__ 失败时传播异常（行 201-206）。"""
        config = _make_config()
        handler = LoginAttemptHandler(config)

        mock_browser_mgr = MagicMock()
        mock_browser_mgr.__aenter__ = AsyncMock(side_effect=RuntimeError("browser fail"))
        mock_browser_mgr.__aexit__ = AsyncMock()

        task = _make_task_config()

        with patch(
            "app.utils.login.BrowserContextManager", return_value=mock_browser_mgr
        ), patch(
            "app.utils.login.build_login_template_vars", return_value={}
        ), pytest.raises(RuntimeError, match="browser fail"):
            await handler._execute_browser_task(task, "default", time.perf_counter())

        # __aexit__ 应被调用来清理
        mock_browser_mgr.__aexit__.assert_awaited()

    @pytest.mark.asyncio
    async def test_page_none_raises(self):
        """浏览器页面为 None 时抛出 RuntimeError（行 213-214）。"""
        config = _make_config()
        handler = LoginAttemptHandler(config)

        mock_browser_mgr = MagicMock()
        mock_browser_mgr.page = None
        mock_browser_mgr.__aenter__ = AsyncMock(return_value=mock_browser_mgr)
        mock_browser_mgr.__aexit__ = AsyncMock()

        task = _make_task_config()

        with patch(
            "app.utils.login.BrowserContextManager", return_value=mock_browser_mgr
        ), patch(
            "app.utils.login.build_login_template_vars", return_value={}
        ), pytest.raises(RuntimeError, match="浏览器页面初始化失败"):
            await handler._execute_browser_task(task, "default", time.perf_counter())

    @pytest.mark.asyncio
    async def test_login_success_closes_browser(self):
        """登录成功后关闭浏览器（行 243-248, 254）。"""
        config = _make_config()
        handler = LoginAttemptHandler(config)

        mock_page = MagicMock()
        mock_page.on = MagicMock()
        mock_page.remove_listener = MagicMock()

        mock_browser_mgr = MagicMock()
        mock_browser_mgr.page = mock_page
        mock_browser_mgr.__aenter__ = AsyncMock(return_value=mock_browser_mgr)
        mock_browser_mgr.__aexit__ = AsyncMock()

        task = _make_task_config()

        with patch(
            "app.utils.login.BrowserContextManager", return_value=mock_browser_mgr
        ), patch(
            "app.utils.login.build_login_template_vars", return_value={}
        ), patch(
            "app.tasks.browser_runner.TaskExecutor"
        ) as MockExecutor, patch(
            "app.utils.login.asyncio.sleep", new_callable=AsyncMock
        ) as mock_sleep:
            MockExecutor.return_value.execute = AsyncMock(return_value=(True, "成功"))

            ok, msg = await handler._execute_browser_task(task, "default", time.perf_counter())

        assert ok is True
        assert msg == "成功"
        mock_sleep.assert_awaited_with(LOGIN_SUCCESS_SETTLE_SECONDS)
        assert handler._browser_ctx is None

    @pytest.mark.asyncio
    async def test_login_failure_with_close_on_failure(self):
        """登录失败且 close_on_failure=True 时关闭浏览器（行 249-255）。"""
        config = _make_config()
        handler = LoginAttemptHandler(config, close_on_failure=True)

        mock_page = MagicMock()
        mock_page.on = MagicMock()
        mock_page.remove_listener = MagicMock()

        mock_browser_mgr = MagicMock()
        mock_browser_mgr.page = mock_page
        mock_browser_mgr.__aenter__ = AsyncMock(return_value=mock_browser_mgr)
        mock_browser_mgr.__aexit__ = AsyncMock()

        task = _make_task_config()

        with patch(
            "app.utils.login.BrowserContextManager", return_value=mock_browser_mgr
        ), patch(
            "app.utils.login.build_login_template_vars", return_value={}
        ), patch(
            "app.tasks.browser_runner.TaskExecutor"
        ) as MockExecutor:
            MockExecutor.return_value.execute = AsyncMock(
                return_value=(False, "密码错误")
            )

            ok, msg = await handler._execute_browser_task(task, "default", time.perf_counter())

        assert ok is False
        assert msg == "密码错误"
        assert handler._browser_ctx is None

    @pytest.mark.asyncio
    async def test_login_failure_no_close_on_failure(self):
        """登录失败且 close_on_failure=False 时保留浏览器（行 254）。"""
        config = _make_config()
        handler = LoginAttemptHandler(config, close_on_failure=False)

        mock_page = MagicMock()
        mock_page.on = MagicMock()
        mock_page.remove_listener = MagicMock()

        mock_browser_mgr = MagicMock()
        mock_browser_mgr.page = mock_page
        mock_browser_mgr.__aenter__ = AsyncMock(return_value=mock_browser_mgr)
        mock_browser_mgr.__aexit__ = AsyncMock()

        task = _make_task_config()

        with patch(
            "app.utils.login.BrowserContextManager", return_value=mock_browser_mgr
        ), patch(
            "app.utils.login.build_login_template_vars", return_value={}
        ), patch(
            "app.tasks.browser_runner.TaskExecutor"
        ) as MockExecutor:
            MockExecutor.return_value.execute = AsyncMock(
                return_value=(False, "超时")
            )

            ok, msg = await handler._execute_browser_task(task, "default", time.perf_counter())

        assert ok is False
        assert handler._browser_ctx is not None

    @pytest.mark.asyncio
    async def test_dialog_handler_registered_and_removed(self):
        """弹窗监听器注册后在 finally 中移除（行 232-241）。"""
        config = _make_config()
        handler = LoginAttemptHandler(config)

        mock_page = MagicMock()
        mock_page.on = MagicMock()
        mock_page.remove_listener = MagicMock()

        mock_browser_mgr = MagicMock()
        mock_browser_mgr.page = mock_page
        mock_browser_mgr.__aenter__ = AsyncMock(return_value=mock_browser_mgr)
        mock_browser_mgr.__aexit__ = AsyncMock()

        task = _make_task_config()

        with patch(
            "app.utils.login.BrowserContextManager", return_value=mock_browser_mgr
        ), patch(
            "app.utils.login.build_login_template_vars", return_value={}
        ), patch(
            "app.tasks.browser_runner.TaskExecutor"
        ) as MockExecutor:
            MockExecutor.return_value.execute = AsyncMock(return_value=(True, "ok"))

            await handler._execute_browser_task(task, "default", time.perf_counter())

        # 验证 on("dialog", ...) 被调用
        mock_page.on.assert_called_once()
        assert mock_page.on.call_args[0][0] == "dialog"
        # 验证 remove_listener("dialog", ...) 被调用
        mock_page.remove_listener.assert_called_once()
        assert mock_page.remove_listener.call_args[0][0] == "dialog"

    @pytest.mark.asyncio
    async def test_screenshot_url_in_message(self):
        """失败消息包含截图 URL（行 249）。"""
        config = _make_config()
        handler = LoginAttemptHandler(config, close_on_failure=True)

        mock_page = MagicMock()
        mock_page.on = MagicMock()
        mock_page.remove_listener = MagicMock()

        mock_browser_mgr = MagicMock()
        mock_browser_mgr.page = mock_page
        mock_browser_mgr.__aenter__ = AsyncMock(return_value=mock_browser_mgr)
        mock_browser_mgr.__aexit__ = AsyncMock()

        task = _make_task_config()

        with patch(
            "app.utils.login.BrowserContextManager", return_value=mock_browser_mgr
        ), patch(
            "app.utils.login.build_login_template_vars", return_value={}
        ), patch(
            "app.tasks.browser_runner.TaskExecutor"
        ) as MockExecutor:
            MockExecutor.return_value.execute = AsyncMock(
                return_value=(False, "操作失败 截图：/tmp/shot.png")
            )

            ok, msg = await handler._execute_browser_task(task, "default", time.perf_counter())

        assert ok is False
        assert "截图" in msg


# ── _execute_script_task ─────────────────────────────────────────────


class TestExecuteScriptTask:
    """覆盖 _execute_script_task（行 264-298）。"""

    @pytest.mark.asyncio
    async def test_cancel_event_set(self):
        """cancel_event 已设置时返回取消（行 273-274）。"""
        config = _make_config()
        cancel = threading.Event()
        cancel.set()
        handler = LoginAttemptHandler(config, cancel_event=cancel)

        task = _make_script_task()
        ok, msg = await handler._execute_script_task(task, time.perf_counter())

        assert ok is False
        assert "登录已取消" in msg

    @pytest.mark.asyncio
    async def test_script_execution_failure(self):
        """脚本执行失败时返回失败消息（行 282-285）。"""
        config = _make_config(monitor={"script_timeout": 30})
        handler = LoginAttemptHandler(config)

        task = _make_script_task()

        with patch(
            "app.workers.script_runner.ScriptRunner"
        ) as MockRunner, patch(
            "app.utils.login.asyncio.get_running_loop"
        ) as mock_get_loop:
            mock_runner_instance = MagicMock()
            MockRunner.return_value = mock_runner_instance

            mock_loop = MagicMock()
            mock_loop.run_in_executor = AsyncMock(return_value=(False, "脚本语法错误"))
            mock_get_loop.return_value = mock_loop

            ok, msg = await handler._execute_script_task(task, time.perf_counter())

        assert ok is False
        assert "脚本执行失败" in msg
        assert "脚本语法错误" in msg

    @pytest.mark.asyncio
    async def test_script_success_network_ok(self):
        """脚本成功且网络正常时返回成功（行 287-295）。"""
        config = _make_config()
        handler = LoginAttemptHandler(config)

        task = _make_script_task()

        with patch(
            "app.workers.script_runner.ScriptRunner"
        ) as MockRunner, patch(
            "app.utils.login.asyncio.get_running_loop"
        ) as mock_get_loop, patch(
            "app.utils.login.asyncio.to_thread", new_callable=AsyncMock
        ) as mock_to_thread, patch(
            "app.utils.login.asyncio.sleep", new_callable=AsyncMock
        ):
            mock_runner_instance = MagicMock()
            MockRunner.return_value = mock_runner_instance

            mock_loop = MagicMock()
            mock_loop.run_in_executor = AsyncMock(return_value=(True, "ok"))
            mock_get_loop.return_value = mock_loop

            mock_to_thread.return_value = (True, "网络正常")

            ok, msg = await handler._execute_script_task(task, time.perf_counter())

        assert ok is True
        assert msg == "登录成功"

    @pytest.mark.asyncio
    async def test_script_success_network_fail(self):
        """脚本成功但网络不通时返回失败（行 296-298）。"""
        config = _make_config()
        handler = LoginAttemptHandler(config)

        task = _make_script_task()

        with patch(
            "app.workers.script_runner.ScriptRunner"
        ) as MockRunner, patch(
            "app.utils.login.asyncio.get_running_loop"
        ) as mock_get_loop, patch(
            "app.utils.login.asyncio.to_thread", new_callable=AsyncMock
        ) as mock_to_thread, patch(
            "app.utils.login.asyncio.sleep", new_callable=AsyncMock
        ):
            mock_runner_instance = MagicMock()
            MockRunner.return_value = mock_runner_instance

            mock_loop = MagicMock()
            mock_loop.run_in_executor = AsyncMock(return_value=(True, "ok"))
            mock_get_loop.return_value = mock_loop

            mock_to_thread.return_value = (False, "连接超时")

            ok, msg = await handler._execute_script_task(task, time.perf_counter())

        assert ok is False
        assert "网络未连通" in msg
        assert "连接超时" in msg

    @pytest.mark.asyncio
    async def test_script_timeout_config_used(self):
        """脚本超时从 config.monitor.script_timeout 读取（行 276）。"""
        config = _make_config(monitor={"script_timeout": 42})
        handler = LoginAttemptHandler(config)

        task = _make_script_task()

        with patch(
            "app.workers.script_runner.ScriptRunner"
        ) as MockRunner, patch(
            "app.utils.login.asyncio.get_running_loop"
        ) as mock_get_loop, patch(
            "app.utils.login.asyncio.to_thread", new_callable=AsyncMock
        ) as mock_to_thread, patch(
            "app.utils.login.asyncio.sleep", new_callable=AsyncMock
        ):
            mock_runner_instance = MagicMock()
            MockRunner.return_value = mock_runner_instance

            mock_loop = MagicMock()
            mock_loop.run_in_executor = AsyncMock(return_value=(True, "ok"))
            mock_get_loop.return_value = mock_loop

            mock_to_thread.return_value = (True, "网络正常")

            await handler._execute_script_task(task, time.perf_counter())

        MockRunner.assert_called_once_with(task.script_path, timeout=42)


# ── close_browser ────────────────────────────────────────────────────


class TestCloseBrowser:

    @pytest.mark.asyncio
    async def test_close_with_active_context(self):
        config = _make_config()
        handler = LoginAttemptHandler(config)

        mock_ctx = AsyncMock()
        handler._browser_ctx = mock_ctx

        await handler.close_browser()

        mock_ctx.__aexit__.assert_awaited_once_with(None, None, None)
        assert handler._browser_ctx is None

    @pytest.mark.asyncio
    async def test_close_without_context(self):
        config = _make_config()
        handler = LoginAttemptHandler(config)
        handler._browser_ctx = None

        await handler.close_browser()
        assert handler._browser_ctx is None

    @pytest.mark.asyncio
    async def test_close_with_exception_in_aexit(self):
        config = _make_config()
        handler = LoginAttemptHandler(config)

        mock_ctx = AsyncMock()
        mock_ctx.__aexit__ = AsyncMock(side_effect=RuntimeError("close error"))
        handler._browser_ctx = mock_ctx

        await handler.close_browser()
        assert handler._browser_ctx is None


# ── SCREENSHOT_URL_PATTERN 正则 ──────────────────────────────────────


class TestScreenshotUrlPattern:

    def test_removes_chinese_colon(self):
        import re
        msg = "操作失败 截图：/tmp/shot.png"
        result = re.sub(SCREENSHOT_URL_PATTERN, "", msg)
        assert result == "操作失败"

    def test_removes_english_colon(self):
        import re
        msg = "操作失败 截图: /tmp/shot.png"
        result = re.sub(SCREENSHOT_URL_PATTERN, "", msg)
        assert result == "操作失败"

    def test_removes_jpg(self):
        import re
        msg = "失败 截图：/path/to/screen.jpg"
        result = re.sub(SCREENSHOT_URL_PATTERN, "", msg)
        assert result == "失败"

    def test_no_screenshot_unchanged(self):
        import re
        msg = "普通错误消息"
        result = re.sub(SCREENSHOT_URL_PATTERN, "", msg)
        assert result == msg


# ── _ensure_task_manager ─────────────────────────────────────────────


class TestEnsureTaskManager:

    def test_initializes_task_manager(self):
        """首次调用时初始化 TaskManager（行 153-162）。"""
        config = _make_config()
        handler = LoginAttemptHandler(config)

        assert handler._task_manager is None

        with patch("app.tasks.manager.TaskManager") as MockTM:
            handler._ensure_task_manager()

        assert handler._task_manager is not None
        MockTM.assert_called_once()

    def test_already_initialized_skips(self):
        """已初始化时跳过（行 153）。"""
        config = _make_config()
        handler = LoginAttemptHandler(config)
        handler._task_manager = MagicMock()

        with patch("app.tasks.manager.TaskManager") as MockTM:
            handler._ensure_task_manager()

        MockTM.assert_not_called()

    def test_project_root_override(self):
        """CAMPUS_AUTH_PROJECT_ROOT 环境变量覆盖项目根目录（行 156-161）。"""
        config = _make_config()
        handler = LoginAttemptHandler(config)

        with patch("app.tasks.manager.TaskManager") as MockTM, patch.dict(
            "os.environ", {"CAMPUS_AUTH_PROJECT_ROOT": "/custom/root"}
        ):
            handler._ensure_task_manager()

        call_path = MockTM.call_args[0][0]
        # Path.resolve() 在 Windows 上会加上盘符，只验证路径包含 custom/root
        normalized = str(call_path).replace("\\", "/")
        assert "custom/root" in normalized


# ── __init__ ─────────────────────────────────────────────────────────


class TestInit:

    def test_default_values(self):
        config = _make_config()
        handler = LoginAttemptHandler(config)

        assert handler.config is config
        assert handler.cancel_event is None
        assert handler.close_on_failure is True
        assert handler._browser_ctx is None
        assert handler._task_manager is None

    def test_custom_values(self):
        config = _make_config()
        cancel = threading.Event()
        handler = LoginAttemptHandler(config, cancel_event=cancel, close_on_failure=False)

        assert handler.cancel_event is cancel
        assert handler.close_on_failure is False
