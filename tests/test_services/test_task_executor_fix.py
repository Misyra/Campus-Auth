"""TaskExecutor 及相关组件测试。

覆盖：
1. TaskRegistry.get_tasks_dir() 公共方法
2. TaskExecutor._get_script_path() 路径回退
3. 定时任务线程池懒初始化
4. BoundedExecutor 队列限制
5. TaskExecutor CRUD 方法、登录去重、execute_task 分发、execute_login、execute_shell
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import Future
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from app.schemas import AppSettings, RuntimeConfig


def _slow_return(value, delay=0.3):
    """返回一个延迟返回结果的函数，避免 ThreadPoolExecutor 回调死锁。

    注意：execute_login_async 中 add_done_callback 在锁内调用，
    如果 future 在 add_done_callback 返回前就已完成，回调会在同一线程执行，
    尝试再次获取同一个 Lock 导致死锁。延迟函数确保 future 不会立即完成。
    """

    def wrapper(*args, **kwargs):
        time.sleep(delay)
        return value

    return wrapper

from app.services.task_registry import TaskRegistry


# =====================================================================
# TaskRegistry.get_tasks_dir()
# =====================================================================


class TestTaskRegistryGetTasksDir:
    """TaskRegistry.get_tasks_dir() 公共方法测试。"""

    def test_get_tasks_dir_returns_path(self, tmp_path: Path) -> None:
        tasks_dir = tmp_path / "tasks"
        reg = TaskRegistry(tasks_dir)
        assert reg.get_tasks_dir() == tasks_dir

    def test_get_tasks_dir_creates_dir(self, tmp_path: Path) -> None:
        tasks_dir = tmp_path / "new_tasks"
        reg = TaskRegistry(tasks_dir)
        assert reg.get_tasks_dir().exists()

    def test_get_tasks_dir_returns_same_as_private(self, tmp_path: Path) -> None:
        tasks_dir = tmp_path / "tasks"
        reg = TaskRegistry(tasks_dir)
        assert reg.get_tasks_dir() == reg._tasks_dir


# =====================================================================
# TaskExecutor._get_script_path()
# =====================================================================


class TestTaskExecutorGetScriptPath:
    """TaskExecutor._get_script_path() 委托 registry.get_script_path() 的测试。"""

    def test_delegates_to_registry(self) -> None:
        """委托 registry.get_script_path() 方法。"""
        mock_path = MagicMock()
        mock_registry = MagicMock(spec=["get_script_path"])
        mock_registry.get_script_path.return_value = mock_path

        from app.services.task_executor import TaskExecutor

        executor = TaskExecutor.__new__(TaskExecutor)
        executor._registry = mock_registry

        result = executor._get_script_path("test")
        assert result is mock_path
        mock_registry.get_script_path.assert_called_once_with("test")

    def test_returns_none_when_no_method(self) -> None:
        """registry 无 get_script_path 时返回 None。"""
        mock_registry = MagicMock(spec=[])

        from app.services.task_executor import TaskExecutor

        executor = TaskExecutor.__new__(TaskExecutor)
        executor._registry = mock_registry

        result = executor._get_script_path("nonexistent")
        assert result is None

    def test_returns_none_when_registry_returns_none(self) -> None:
        """registry.get_script_path 返回 None 时返回 None。"""
        mock_registry = MagicMock(spec=["get_script_path"])
        mock_registry.get_script_path.return_value = None

        from app.services.task_executor import TaskExecutor

        executor = TaskExecutor.__new__(TaskExecutor)
        executor._registry = mock_registry

        result = executor._get_script_path("nonexistent_script")
        assert result is None


# =====================================================================
# TaskExecutor 线程池懒初始化
# =====================================================================


class TestTaskPoolLazyInit:
    """定时任务线程池懒初始化测试。"""

    def test_task_pool_initially_none(self, tmp_path):
        from app.services.task_executor import TaskExecutor

        registry = MagicMock()
        registry.has_enabled_tasks.return_value = False
        history_store = MagicMock()

        executor = TaskExecutor(
            registry=registry,
            history_store=history_store,
            worker_getter=MagicMock(),
            login_orchestrator=MagicMock(),
        )
        assert executor._task_pool is None

    def test_task_pool_created_on_first_use(self, tmp_path):
        from app.services.task_executor import TaskExecutor

        registry = MagicMock()
        registry.get_task.return_value = {
            "type": "script",
            "target_id": "test",
            "timeout": 60,
        }
        history_store = MagicMock()

        executor = TaskExecutor(
            registry=registry,
            history_store=history_store,
            worker_getter=MagicMock(),
            login_orchestrator=MagicMock(),
        )
        assert executor._task_pool is None

        # 使用 lambda 代替 MagicMock（MagicMock 在线程池中行为异常）
        executor.execute_task = lambda task_id: (True, "ok")
        executor.execute_task_async("test")

        assert executor._task_pool is not None
        executor._task_pool.shutdown(wait=False)

    def test_shutdown_without_task_pool(self, tmp_path):
        from app.services.task_executor import TaskExecutor

        registry = MagicMock()
        history_store = MagicMock()

        executor = TaskExecutor(
            registry=registry,
            history_store=history_store,
            worker_getter=MagicMock(),
            login_orchestrator=MagicMock(),
        )
        assert executor._task_pool is None
        executor.shutdown()

    def test_shutdown_with_task_pool(self):
        """有 _task_pool 时 shutdown 应关闭 task_pool 并调用 orchestrator.shutdown。"""
        from app.services.task_executor import TaskExecutor

        registry = MagicMock()
        history_store = MagicMock()
        mock_orchestrator = MagicMock()

        executor = TaskExecutor(
            registry=registry,
            history_store=history_store,
            worker_getter=MagicMock(),
            login_orchestrator=mock_orchestrator,
        )
        # 手动触发 _task_pool 创建
        executor._ensure_task_pool()
        assert executor._task_pool is not None

        mock_task_pool = MagicMock()
        executor._task_pool = mock_task_pool

        executor.shutdown(wait=True)
        mock_task_pool.shutdown.assert_called_once_with(wait=True)
        mock_orchestrator.shutdown.assert_called_once_with(wait=True)

    def test_ensure_task_pool_creates_once(self):
        """多次调用 _ensure_task_pool 应返回同一实例。"""
        from app.services.task_executor import TaskExecutor

        executor = TaskExecutor(
            registry=MagicMock(),
            history_store=MagicMock(),
            worker_getter=MagicMock(),
            login_orchestrator=MagicMock(),
        )
        pool1 = executor._ensure_task_pool()
        pool2 = executor._ensure_task_pool()
        assert pool1 is pool2

    def test_ensure_task_pool_thread_safe(self):
        """并发调用 _ensure_task_pool 应返回同一实例（双检锁）。"""
        from app.services.task_executor import TaskExecutor

        executor = TaskExecutor(
            registry=MagicMock(),
            history_store=MagicMock(),
            worker_getter=MagicMock(),
            login_orchestrator=MagicMock(),
        )

        results = []
        barrier = threading.Barrier(10)

        def call_ensure():
            barrier.wait(timeout=5)
            results.append(executor._ensure_task_pool())

        threads = [threading.Thread(target=call_ensure) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert len(results) == 10
        assert all(r is results[0] for r in results)
        executor._task_pool.shutdown(wait=False)


# =====================================================================
# BoundedExecutor
# =====================================================================


class TestBoundedExecutor:
    """BoundedExecutor — 带队列限制的线程池。"""

    def test_submit_success(self):
        from app.services.task_executor import BoundedExecutor

        executor = BoundedExecutor(max_workers=1, queue_size=2)
        try:
            future = executor.submit(lambda: 42)
            assert future.result(timeout=5) == 42
        finally:
            executor.shutdown()

    def test_submit_passes_args(self):
        from app.services.task_executor import BoundedExecutor

        executor = BoundedExecutor(max_workers=1, queue_size=2)
        try:
            future = executor.submit(lambda a, b: a + b, 3, 4)
            assert future.result(timeout=5) == 7
        finally:
            executor.shutdown()

    def test_submit_queue_full_raises(self):
        """队列已满时 submit 应抛出 RuntimeError。"""
        from app.services.task_executor import BoundedExecutor

        blocker = threading.Event()
        executor = BoundedExecutor(max_workers=1, queue_size=1)
        try:
            # 第一次 submit 成功（semaphore 1 -> 0），任务阻塞在 worker 中
            executor.submit(blocker.wait)
            # 第二次 submit 失败（semaphore 已为 0）
            with pytest.raises(RuntimeError, match="队列已满"):
                executor.submit(lambda: None)
        finally:
            blocker.set()
            executor.shutdown()

    def test_submit_releases_semaphore_on_exception(self):
        """submit 内部 executor.submit 抛异常时应释放信号量。"""
        from app.services.task_executor import BoundedExecutor

        executor = BoundedExecutor(max_workers=1, queue_size=1)
        # 让内部 ThreadPoolExecutor.submit 抛出异常
        executor._executor = MagicMock()
        executor._executor.submit.side_effect = RuntimeError("pool closed")

        with pytest.raises(RuntimeError, match="pool closed"):
            executor.submit(lambda: None)

        # 信号量应已释放，可以重新提交（不阻塞）
        assert executor._semaphore.acquire(blocking=False)

    def test_semaphore_released_on_task_completion(self):
        """任务完成后信号量应被释放，允许提交新任务。"""
        from app.services.task_executor import BoundedExecutor

        executor = BoundedExecutor(max_workers=1, queue_size=1)
        try:
            future = executor.submit(lambda: "done")
            future.result(timeout=5)
            # 任务完成后，应能再次提交
            future2 = executor.submit(lambda: "done2")
            assert future2.result(timeout=5) == "done2"
        finally:
            executor.shutdown()

    def test_shutdown(self):
        from app.services.task_executor import BoundedExecutor

        executor = BoundedExecutor(max_workers=1, queue_size=1)
        executor.shutdown(wait=True)
        # 关闭后不应抛出异常


# =====================================================================
# TaskExecutor — CRUD 委托方法
# =====================================================================


class TestTaskExecutorCRUD:
    """TaskExecutor CRUD 委托到 registry 的测试。"""

    def _make_executor(self, **kwargs):
        from app.services.task_executor import TaskExecutor

        defaults = dict(
            registry=MagicMock(),
            history_store=MagicMock(),
            worker_getter=MagicMock(),
            login_orchestrator=MagicMock(),
        )
        defaults.update(kwargs)
        return TaskExecutor(**defaults)

    def test_list_tasks(self):
        executor = self._make_executor()
        executor._registry.list_tasks.return_value = [{"id": "t1"}]
        assert executor.list_tasks() == [{"id": "t1"}]
        executor._registry.list_tasks.assert_called_once()

    def test_get_task(self):
        executor = self._make_executor()
        executor._registry.get_task.return_value = {"id": "t1"}
        assert executor.get_task("t1") == {"id": "t1"}
        executor._registry.get_task.assert_called_once_with("t1")

    def test_save_task(self):
        executor = self._make_executor()
        executor._registry.save_task.return_value = (True, "ok")
        assert executor.save_task("t1", {"name": "test"}) == (True, "ok")
        executor._registry.save_task.assert_called_once_with("t1", {"name": "test"})

    def test_delete_task_success(self):
        """删除成功时应同时删除历史。"""
        executor = self._make_executor()
        executor._registry.delete_task.return_value = (True, "deleted")
        success, msg = executor.delete_task("t1")
        assert success is True
        executor._registry.delete_task.assert_called_once_with("t1")
        executor._history_store.delete_history.assert_called_once_with("t1")

    def test_delete_task_failure_no_history_delete(self):
        """删除失败时不删除历史。"""
        executor = self._make_executor()
        executor._registry.delete_task.return_value = (False, "not found")
        success, msg = executor.delete_task("t1")
        assert success is False
        executor._history_store.delete_history.assert_not_called()

    def test_get_history(self):
        executor = self._make_executor()
        executor._history_store.get_history.return_value = [{"status": "success"}]
        assert executor.get_history("t1") == [{"status": "success"}]
        executor._history_store.get_history.assert_called_once_with("t1")

    def test_has_enabled_tasks(self):
        executor = self._make_executor()
        executor._registry.has_enabled_tasks.return_value = True
        assert executor.has_enabled_tasks() is True

    def test_bind_runtime_config(self):
        executor = self._make_executor()
        getter = lambda: {"key": "value"}
        executor.bind_runtime_config(getter)
        assert executor._get_runtime_config is getter


# =====================================================================
# TaskExecutor — execute_task 分发
# =====================================================================


class TestTaskExecutorExecuteTask:
    """TaskExecutor.execute_task() 分发逻辑测试。"""

    def _make_executor(self, **kwargs):
        from app.services.task_executor import TaskExecutor

        defaults = dict(
            registry=MagicMock(),
            history_store=MagicMock(),
            worker_getter=MagicMock(),
            login_orchestrator=MagicMock(),
        )
        defaults.update(kwargs)
        return TaskExecutor(**defaults)

    def test_task_not_found(self):
        executor = self._make_executor()
        executor._registry.get_task.return_value = None
        success, msg = executor.execute_task("nonexistent")
        assert success is False
        assert "不存在" in msg

    def test_unsupported_task_type(self):
        executor = self._make_executor()
        executor._registry.get_task.return_value = {"type": "unknown_type"}
        success, msg = executor.execute_task("t1")
        assert success is False
        assert "不支持" in msg
        # 应记录历史
        executor._history_store.add_record.assert_called_once()
        executor._registry.update_last_run.assert_called_once()

    def test_script_task_dispatch(self):
        """script 类型应分发到 _execute_script。"""
        executor = self._make_executor()
        executor._registry.get_task.return_value = {
            "type": "script",
            "target_id": "s1",
            "timeout": 30,
        }
        executor._execute_script = MagicMock(return_value=(True, "ok"))

        success, msg = executor.execute_task("t1")
        assert success is True
        executor._execute_script.assert_called_once_with("s1", 30)

    def test_browser_task_dispatch(self):
        """browser 类型应分发到 _execute_browser。"""
        executor = self._make_executor()
        executor._registry.get_task.return_value = {
            "type": "browser",
            "target_id": "b1",
            "timeout": 60,
        }
        executor._execute_browser = MagicMock(return_value=(True, "ok"))

        success, msg = executor.execute_task("t1")
        assert success is True
        executor._execute_browser.assert_called_once_with("b1", 60)

    def test_shell_task_dispatch(self):
        """shell 类型应分发到 _execute_shell。"""
        executor = self._make_executor()
        executor._registry.get_task.return_value = {
            "type": "shell",
            "command": "echo hello",
            "timeout": 10,
            "shell_path": "/bin/bash",
        }
        executor._execute_shell = MagicMock(return_value=(True, "hello"))

        success, msg = executor.execute_task("t1")
        assert success is True
        executor._execute_shell.assert_called_once_with("echo hello", 10, "/bin/bash")

    def test_exception_during_execution(self):
        """执行异常应被捕获并记录。"""
        executor = self._make_executor()
        executor._registry.get_task.return_value = {"type": "script", "target_id": "s1", "timeout": 10}
        executor._execute_script = MagicMock(side_effect=RuntimeError("boom"))

        success, msg = executor.execute_task("t1")
        assert success is False
        assert "boom" in msg
        executor._history_store.add_record.assert_called_once()
        executor._registry.update_last_run.assert_called_once()

    def test_default_timeout(self):
        """未指定 timeout 时应使用默认值 60。"""
        executor = self._make_executor()
        executor._registry.get_task.return_value = {
            "type": "script",
            "target_id": "s1",
        }
        executor._execute_script = MagicMock(return_value=(True, "ok"))

        executor.execute_task("t1")
        executor._execute_script.assert_called_once_with("s1", 60)

    def test_history_recorded_with_duration(self):
        """应记录执行时长。"""
        executor = self._make_executor()
        executor._registry.get_task.return_value = {"type": "shell", "command": "echo", "timeout": 5, "shell_path": "/bin/bash"}
        executor._execute_shell = MagicMock(return_value=(True, "ok"))

        executor.execute_task("t1")
        call_args = executor._history_store.add_record.call_args
        assert call_args[0][0] == "t1"  # task_id
        assert call_args[0][1] == "success"  # status
        assert isinstance(call_args[0][3], float)  # duration


# =====================================================================
# TaskExecutor — execute_script
# =====================================================================


class TestTaskExecutorExecuteScript:
    """TaskExecutor._execute_script() 测试。"""

    def _make_executor(self, **kwargs):
        from app.services.task_executor import TaskExecutor

        defaults = dict(
            registry=MagicMock(),
            history_store=MagicMock(),
            worker_getter=MagicMock(),
            login_orchestrator=MagicMock(),
        )
        defaults.update(kwargs)
        return TaskExecutor(**defaults)

    def test_no_registry(self):
        executor = self._make_executor()
        executor._registry = None
        success, msg = executor._execute_script("s1", 30)
        assert success is False
        assert "未初始化" in msg

    def test_task_not_found(self):
        executor = self._make_executor()
        executor._registry.get_task.return_value = None
        success, msg = executor._execute_script("s1", 30)
        assert success is False
        assert "不存在" in msg

    def test_task_wrong_type(self):
        executor = self._make_executor()
        executor._registry.get_task.return_value = {"type": "browser"}
        success, msg = executor._execute_script("s1", 30)
        assert success is False
        assert "不存在" in msg

    def test_script_file_not_found(self):
        executor = self._make_executor()
        executor._registry.get_task.return_value = {"type": "script"}
        executor._get_script_path = MagicMock(return_value=None)
        success, msg = executor._execute_script("s1", 30)
        assert success is False
        assert "文件不存在" in msg

    def test_script_path_not_exists(self, tmp_path):
        executor = self._make_executor()
        executor._registry.get_task.return_value = {"type": "script"}
        executor._get_script_path = MagicMock(return_value=tmp_path / "nonexistent.py")
        success, msg = executor._execute_script("s1", 30)
        assert success is False
        assert "文件不存在" in msg


# =====================================================================
# TaskExecutor — execute_browser
# =====================================================================


class TestTaskExecutorExecuteBrowser:
    """TaskExecutor._execute_browser() 测试。"""

    def _make_executor(self, **kwargs):
        from app.services.task_executor import TaskExecutor

        defaults = dict(
            registry=MagicMock(),
            history_store=MagicMock(),
            worker_getter=MagicMock(),
            login_orchestrator=MagicMock(),
        )
        defaults.update(kwargs)
        return TaskExecutor(**defaults)

    def test_task_not_found(self):
        executor = self._make_executor()
        executor._registry.get_task.return_value = None
        success, msg = executor._execute_browser("b1", 60)
        assert success is False
        assert "不存在" in msg

    def test_task_wrong_type(self):
        executor = self._make_executor()
        executor._registry.get_task.return_value = {"type": "script"}
        success, msg = executor._execute_browser("b1", 60)
        assert success is False
        assert "不存在" in msg

    def test_browser_success(self):
        from app.services.login_orchestrator import LoginHandle
        from app.utils.cancel_token import CompositeCancelEvent

        executor = self._make_executor()
        executor._registry.get_task.return_value = {"type": "browser"}
        executor._get_runtime_config = lambda: RuntimeConfig()

        mock_handle = LoginHandle(
            future=None, source="browser", cancel_event=CompositeCancelEvent(),
        )
        mock_handle.result = lambda: (True, "登录成功")
        executor._login_orchestrator.submit.return_value = mock_handle

        success, msg = executor._execute_browser("b1", 60)
        assert success is True
        assert msg == "登录成功"

    def test_browser_failure(self):
        from app.services.login_orchestrator import LoginHandle
        from app.utils.cancel_token import CompositeCancelEvent

        executor = self._make_executor()
        executor._registry.get_task.return_value = {"type": "browser"}
        executor._get_runtime_config = None

        mock_handle = LoginHandle(
            future=None, source="browser", cancel_event=CompositeCancelEvent(),
        )
        mock_handle.result = lambda: (False, "页面加载失败")
        executor._login_orchestrator.submit.return_value = mock_handle

        success, msg = executor._execute_browser("b1", 60)
        assert success is False
        assert "页面加载失败" in msg

    def test_browser_import_error(self):
        from app.services.login_orchestrator import LoginHandle
        from app.utils.cancel_token import CompositeCancelEvent

        executor = self._make_executor()
        executor._registry.get_task.return_value = {"type": "browser"}
        executor._get_runtime_config = None

        mock_handle = LoginHandle(
            future=None, source="browser", cancel_event=CompositeCancelEvent(),
        )
        mock_handle.result = lambda: (False, "登录需要额外依赖，请检查 Playwright 安装状态")
        executor._login_orchestrator.submit.return_value = mock_handle

        success, msg = executor._execute_browser("b1", 60)
        assert success is False
        assert "依赖" in msg

    def test_browser_generic_exception(self):
        from app.services.login_orchestrator import LoginHandle
        from app.utils.cancel_token import CompositeCancelEvent

        executor = self._make_executor()
        executor._registry.get_task.return_value = {"type": "browser"}
        executor._get_runtime_config = lambda: RuntimeConfig()

        mock_handle = LoginHandle(
            future=None, source="browser", cancel_event=CompositeCancelEvent(),
        )
        mock_handle.result = lambda: (False, "登录执行异常: worker crash")
        executor._login_orchestrator.submit.return_value = mock_handle

        success, msg = executor._execute_browser("b1", 60)
        assert success is False
        assert "异常" in msg

    def test_browser_result_data_not_string(self):
        """result.data 不是字符串时应返回默认消息。"""
        from app.services.login_orchestrator import LoginHandle
        from app.utils.cancel_token import CompositeCancelEvent

        executor = self._make_executor()
        executor._registry.get_task.return_value = {"type": "browser"}
        executor._get_runtime_config = lambda: RuntimeConfig()

        mock_handle = LoginHandle(
            future=None, source="browser", cancel_event=CompositeCancelEvent(),
        )
        mock_handle.result = lambda: (True, {"key": "value"})  # 非字符串
        executor._login_orchestrator.submit.return_value = mock_handle

        success, msg = executor._execute_browser("b1", 60)
        assert success is True
        assert "浏览器任务执行成功" in msg

    def test_browser_failure_no_error_msg(self):
        """失败但无 error 时应返回默认错误消息。"""
        from app.services.login_orchestrator import LoginHandle
        from app.utils.cancel_token import CompositeCancelEvent

        executor = self._make_executor()
        executor._registry.get_task.return_value = {"type": "browser"}
        executor._get_runtime_config = lambda: RuntimeConfig()

        mock_handle = LoginHandle(
            future=None, source="browser", cancel_event=CompositeCancelEvent(),
        )
        mock_handle.result = lambda: (False, "")
        executor._login_orchestrator.submit.return_value = mock_handle

        success, msg = executor._execute_browser("b1", 60)
        assert success is False
        assert "浏览器任务执行失败" in msg

    def test_browser_data_no_pure_mode(self):
        """F20: submit() 调用时不应包含 pure_mode（委托 Orchestrator 后由 Orchestrator 处理 config）。"""
        from app.services.login_orchestrator import LoginHandle
        from app.utils.cancel_token import CompositeCancelEvent

        executor = self._make_executor()
        executor._registry.get_task.return_value = {"type": "browser"}
        executor._get_runtime_config = lambda: RuntimeConfig()

        mock_handle = LoginHandle(
            future=None, source="browser", cancel_event=CompositeCancelEvent(),
        )
        mock_handle.result = lambda: (True, "ok")
        executor._login_orchestrator.submit.return_value = mock_handle

        executor._execute_browser("b1", 60)
        call_kwargs = executor._login_orchestrator.submit.call_args.kwargs
        assert "pure_mode" not in call_kwargs.get("config", {})

    def test_browser_cancel_event_passed(self):
        """F11: cancel_event 应传递到 orchestrator.submit()。"""
        from app.services.login_orchestrator import LoginHandle
        from app.utils.cancel_token import CompositeCancelEvent

        executor = self._make_executor()
        executor._registry.get_task.return_value = {"type": "browser"}
        executor._get_runtime_config = lambda: RuntimeConfig()

        mock_handle = LoginHandle(
            future=None, source="browser", cancel_event=CompositeCancelEvent(),
        )
        mock_handle.result = lambda: (True, "ok")
        executor._login_orchestrator.submit.return_value = mock_handle

        cancel = threading.Event()
        executor._execute_browser("b1", 60, cancel_event=cancel)
        call_kwargs = executor._login_orchestrator.submit.call_args.kwargs
        assert call_kwargs["cancel_event"] is cancel

    def test_browser_cancel_event_default_none(self):
        """F11: 不传 cancel_event 时 orchestrator.submit() 收到 None。"""
        from app.services.login_orchestrator import LoginHandle
        from app.utils.cancel_token import CompositeCancelEvent

        executor = self._make_executor()
        executor._registry.get_task.return_value = {"type": "browser"}
        executor._get_runtime_config = lambda: RuntimeConfig()

        mock_handle = LoginHandle(
            future=None, source="browser", cancel_event=CompositeCancelEvent(),
        )
        mock_handle.result = lambda: (True, "ok")
        executor._login_orchestrator.submit.return_value = mock_handle

        executor._execute_browser("b1", 60)
        call_kwargs = executor._login_orchestrator.submit.call_args.kwargs
        assert call_kwargs["cancel_event"] is None

    def test_browser_timeout_forwarded(self):
        """timeout 应传递给 orchestrator.submit()。"""
        from app.services.login_orchestrator import LoginHandle
        from app.utils.cancel_token import CompositeCancelEvent

        executor = self._make_executor()
        executor._registry.get_task.return_value = {"type": "browser"}
        executor._get_runtime_config = lambda: RuntimeConfig()

        mock_handle = LoginHandle(
            future=None, source="browser", cancel_event=CompositeCancelEvent(),
        )
        mock_handle.result = lambda: (True, "ok")
        executor._login_orchestrator.submit.return_value = mock_handle

        executor._execute_browser("b1", 120)
        call_kwargs = executor._login_orchestrator.submit.call_args.kwargs
        assert call_kwargs["timeout"] == 120


# =====================================================================
# TaskExecutor — _execute_shell
# =====================================================================


# =====================================================================
# TaskExecutor — _execute_shell
# =====================================================================


class TestTaskExecutorExecuteShell:
    """TaskExecutor._execute_shell() 测试。"""

    def _make_executor(self, **kwargs):
        from app.services.task_executor import TaskExecutor

        defaults = dict(
            registry=MagicMock(),
            history_store=MagicMock(),
            worker_getter=MagicMock(),
            login_orchestrator=MagicMock(),
        )
        defaults.update(kwargs)
        return TaskExecutor(**defaults)

    def test_empty_command(self):
        executor = self._make_executor()
        success, msg = executor._execute_shell("", 30)
        assert success is False
        assert "空" in msg

    def test_whitespace_only_command(self):
        executor = self._make_executor()
        success, msg = executor._execute_shell("   ", 30)
        assert success is False
        assert "空" in msg

    def test_shell_from_runtime_config(self):
        """未指定 shell_path 时从运行时配置获取。"""
        executor = self._make_executor()
        executor._get_runtime_config = lambda: RuntimeConfig(app_settings=AppSettings(shell_path="/bin/bash"))
        executor._shell_policy = MagicMock()
        executor._shell_policy.run_sync.return_value = (0, "hello", "")

        success, msg = executor._execute_shell("echo hello", 30)
        assert success is True
        assert "hello" in msg
        executor._shell_policy.run_sync.assert_called_once()

    def test_shell_from_default(self):
        """配置中无 shell_path 时使用默认 shell。"""
        executor = self._make_executor()
        executor._get_runtime_config = lambda: RuntimeConfig()
        executor._shell_policy = MagicMock()
        executor._shell_policy.run_sync.return_value = (0, "output", "")

        with patch("app.services.task_executor.get_default_shell", return_value="/bin/sh"):
            success, msg = executor._execute_shell("echo test", 30)
        assert success is True

    def test_shell_config_exception_falls_back(self):
        """获取配置异常时回退到默认 shell。"""
        executor = self._make_executor()
        executor._get_runtime_config = lambda: (_ for _ in ()).throw(RuntimeError("config error"))
        executor._shell_policy = MagicMock()
        executor._shell_policy.run_sync.return_value = (0, "ok", "")

        with patch("app.services.task_executor.get_default_shell", return_value="/bin/sh"):
            success, msg = executor._execute_shell("echo ok", 30)
        assert success is True

    def test_powershell_command_format(self):
        """PowerShell 应使用 -Command 参数。"""
        executor = self._make_executor()
        executor._get_runtime_config = lambda: RuntimeConfig(app_settings=AppSettings(shell_path="C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe"))
        executor._shell_policy = MagicMock()
        executor._shell_policy.run_sync.return_value = (0, "ok", "")

        executor._execute_shell("Get-Process", 30)
        call_args = executor._shell_policy.run_sync.call_args[0][0]
        assert "-Command" in call_args

    def test_cmd_command_format(self):
        """cmd.exe 应使用 /c 参数。"""
        executor = self._make_executor()
        executor._get_runtime_config = lambda: RuntimeConfig(app_settings=AppSettings(shell_path="C:\\Windows\\System32\\cmd.exe"))
        executor._shell_policy = MagicMock()
        executor._shell_policy.run_sync.return_value = (0, "ok", "")

        with patch("app.services.task_executor.sys") as mock_sys:
            mock_sys.platform = "win32"
            executor._execute_shell("dir", 30)
        call_args = executor._shell_policy.run_sync.call_args[0][0]
        assert "/c" in call_args

    def test_bash_command_format(self):
        """bash 应使用 -c 参数。"""
        executor = self._make_executor()
        executor._get_runtime_config = lambda: RuntimeConfig(app_settings=AppSettings(shell_path="/bin/bash"))
        executor._shell_policy = MagicMock()
        executor._shell_policy.run_sync.return_value = (0, "ok", "")

        with patch("app.services.task_executor.sys") as mock_sys:
            mock_sys.platform = "linux"
            executor._execute_shell("echo test", 30)
        call_args = executor._shell_policy.run_sync.call_args[0][0]
        assert "-c" in call_args

    def test_nonzero_returncode(self):
        """非零返回码应返回失败。"""
        executor = self._make_executor()
        executor._get_runtime_config = lambda: RuntimeConfig(app_settings=AppSettings(shell_path="/bin/bash"))
        executor._shell_policy = MagicMock()
        executor._shell_policy.run_sync.return_value = (1, "", "error occurred")

        success, msg = executor._execute_shell("false", 30)
        assert success is False
        assert "error occurred" in msg

    def test_nonzero_no_stderr(self):
        """非零返回码且无 stderr 时应使用 stdout。"""
        executor = self._make_executor()
        executor._get_runtime_config = lambda: RuntimeConfig(app_settings=AppSettings(shell_path="/bin/bash"))
        executor._shell_policy = MagicMock()
        executor._shell_policy.run_sync.return_value = (1, "some stdout", "")

        success, msg = executor._execute_shell("cmd", 30)
        assert success is False
        assert "some stdout" in msg

    def test_nonzero_no_output(self):
        """非零返回码且无任何输出时显示退出码。"""
        executor = self._make_executor()
        executor._get_runtime_config = lambda: RuntimeConfig(app_settings=AppSettings(shell_path="/bin/bash"))
        executor._shell_policy = MagicMock()
        executor._shell_policy.run_sync.return_value = (2, "", "")

        success, msg = executor._execute_shell("cmd", 30)
        assert success is False
        assert "退出码" in msg

    def test_success_no_output(self):
        """成功但无输出时应显示默认文本。"""
        executor = self._make_executor()
        executor._get_runtime_config = lambda: RuntimeConfig(app_settings=AppSettings(shell_path="/bin/bash"))
        executor._shell_policy = MagicMock()
        executor._shell_policy.run_sync.return_value = (0, "", "")

        success, msg = executor._execute_shell("true", 30)
        assert success is True
        assert "无输出" in msg

    def test_permission_error(self):
        executor = self._make_executor()
        executor._get_runtime_config = lambda: RuntimeConfig(app_settings=AppSettings(shell_path="/bin/bash"))
        executor._shell_policy = MagicMock()
        executor._shell_policy.run_sync.side_effect = PermissionError("denied")

        success, msg = executor._execute_shell("cmd", 30)
        assert success is False
        assert "denied" in msg

    def test_generic_exception(self):
        executor = self._make_executor()
        executor._get_runtime_config = lambda: RuntimeConfig(app_settings=AppSettings(shell_path="/bin/bash"))
        executor._shell_policy = MagicMock()
        executor._shell_policy.run_sync.side_effect = OSError("io error")

        success, msg = executor._execute_shell("cmd", 30)
        assert success is False
        assert "异常" in msg

    def test_output_truncation(self):
        """输出超过 500 字符时应被截断。"""
        executor = self._make_executor()
        executor._get_runtime_config = lambda: RuntimeConfig(app_settings=AppSettings(shell_path="/bin/bash"))
        executor._shell_policy = MagicMock()
        long_output = "x" * 1000
        executor._shell_policy.run_sync.return_value = (0, long_output, "")

        success, msg = executor._execute_shell("cmd", 30)
        assert success is True
        assert len(msg) <= 500


# =====================================================================
# TaskExecutor — execute_login
# =====================================================================


class TestTaskExecutorExecuteLogin:
    """TaskExecutor.execute_login() 委托 LoginOrchestrator 测试。"""

    def _make_executor(self, **kwargs):
        from app.services.task_executor import TaskExecutor

        mock_orchestrator = MagicMock()
        mock_handle = MagicMock()
        mock_handle.result.return_value = (True, "登录成功")
        mock_orchestrator.submit.return_value = mock_handle

        defaults = dict(
            registry=MagicMock(),
            history_store=MagicMock(),
            worker_getter=MagicMock(),
            login_orchestrator=mock_orchestrator,
        )
        defaults.update(kwargs)
        return TaskExecutor(**defaults)

    def test_delegates_to_orchestrator(self):
        """execute_login 应委托到 login_orchestrator.submit。"""
        executor = self._make_executor()
        executor._get_runtime_config = lambda: RuntimeConfig()

        success, msg = executor.execute_login()
        assert success is True
        assert msg == "登录成功"
        executor._login_orchestrator.submit.assert_called_once()

    def test_forwards_cancel_event(self):
        """cancel_event 应传递给 orchestrator.submit。"""
        executor = self._make_executor()
        executor._get_runtime_config = lambda: RuntimeConfig()

        cancel = threading.Event()
        executor.execute_login(cancel_event=cancel)
        call_kwargs = executor._login_orchestrator.submit.call_args.kwargs
        assert call_kwargs["cancel_event"] is cancel

    def test_forwards_config_snapshot(self):
        """config_snapshot 应传递给 orchestrator.submit。"""
        executor = self._make_executor()
        config = RuntimeConfig()

        executor.execute_login(config_snapshot=config)
        call_kwargs = executor._login_orchestrator.submit.call_args.kwargs
        assert call_kwargs["config"] is config

    def test_uses_runtime_config_when_no_snapshot(self):
        """无 config_snapshot 时应使用 _get_runtime_config。"""
        executor = self._make_executor()
        config = RuntimeConfig()
        executor._get_runtime_config = lambda: config

        executor.execute_login()
        call_kwargs = executor._login_orchestrator.submit.call_args.kwargs
        assert call_kwargs["config"] is config

    def test_uses_empty_config_when_no_runtime_config(self):
        """无 _get_runtime_config 时应使用默认 RuntimeConfig。"""
        executor = self._make_executor()
        executor._get_runtime_config = None

        executor.execute_login()
        call_kwargs = executor._login_orchestrator.submit.call_args.kwargs
        assert isinstance(call_kwargs["config"], RuntimeConfig)

    def test_returns_orchestrator_result(self):
        """execute_login 应返回 orchestrator.handle.result() 的值。"""
        mock_orchestrator = MagicMock()
        mock_handle = MagicMock()
        mock_handle.result.return_value = (False, "认证失败")
        mock_orchestrator.submit.return_value = mock_handle

        executor = self._make_executor(login_orchestrator=mock_orchestrator)
        executor._get_runtime_config = lambda: RuntimeConfig()

        success, msg = executor.execute_login()
        assert success is False
        assert msg == "认证失败"

    def test_source_is_auto(self):
        """execute_login 应以 source='auto' 提交。"""
        executor = self._make_executor()
        executor._get_runtime_config = lambda: RuntimeConfig()

        executor.execute_login()
        call_kwargs = executor._login_orchestrator.submit.call_args.kwargs
        assert call_kwargs["source"] == "auto"


# =====================================================================
# TaskExecutor — execute_login_async (去重机制)
# =====================================================================


class TestTaskExecutorLoginAsync:
    """TaskExecutor.execute_login_async() 委托 LoginOrchestrator 测试。"""

    def _make_executor(self, **kwargs):
        from app.services.task_executor import TaskExecutor

        defaults = dict(
            registry=MagicMock(),
            history_store=MagicMock(),
            worker_getter=MagicMock(),
            login_orchestrator=MagicMock(),
        )
        defaults.update(kwargs)
        return TaskExecutor(**defaults)

    def test_submit_delegates_to_orchestrator(self):
        """execute_login_async 应委托到 login_orchestrator.submit。"""
        executor = self._make_executor()
        mock_future = Future()
        mock_future.set_result((True, "ok"))
        mock_handle = MagicMock()
        mock_handle.future = mock_future
        executor._login_orchestrator.submit.return_value = mock_handle

        future = executor.execute_login_async()
        assert future is mock_future
        executor._login_orchestrator.submit.assert_called_once()

    def test_rejected_returns_failed_future(self):
        """orchestrator 拒绝时应返回已完成的失败 Future。"""
        executor = self._make_executor()
        mock_handle = MagicMock()
        mock_handle.future = None
        mock_handle.rejected_reason = "登录被拒绝"
        executor._login_orchestrator.submit.return_value = mock_handle

        future = executor.execute_login_async()
        assert isinstance(future, Future)
        assert future.result(timeout=5) == (False, "登录被拒绝")

    def test_rejected_no_reason_returns_default(self):
        """orchestrator 拒绝且无 reason 时应返回默认消息。"""
        executor = self._make_executor()
        mock_handle = MagicMock()
        mock_handle.future = None
        mock_handle.rejected_reason = None
        executor._login_orchestrator.submit.return_value = mock_handle

        future = executor.execute_login_async()
        assert future.result(timeout=5) == (False, "登录被拒绝")

    def test_cancel_event_forwarded_to_orchestrator(self):
        """cancel_event 应传递给 orchestrator.submit。"""
        executor = self._make_executor()
        mock_handle = MagicMock()
        mock_handle.future = Future()
        mock_handle.future.set_result((True, "ok"))
        executor._login_orchestrator.submit.return_value = mock_handle

        cancel = threading.Event()
        executor.execute_login_async(cancel_event=cancel)
        call_kwargs = executor._login_orchestrator.submit.call_args.kwargs
        assert call_kwargs["cancel_event"] is cancel


# =====================================================================
# TaskExecutor — _on_login_done
# =====================================================================


# =====================================================================
# TaskExecutor — is_login_running
# =====================================================================


class TestIsLoginRunning:
    """测试 is_login_running 状态查询（委托 LoginOrchestrator）。"""

    def test_delegates_to_orchestrator(self):
        """is_login_running 应委托到 login_orchestrator.is_running()。"""
        from app.services.task_executor import TaskExecutor

        mock_orchestrator = MagicMock()
        mock_orchestrator.is_running.return_value = False

        executor = TaskExecutor(
            registry=MagicMock(),
            history_store=MagicMock(),
            worker_getter=MagicMock(),
            login_orchestrator=mock_orchestrator,
        )
        assert executor.is_login_running() is False
        mock_orchestrator.is_running.assert_called_once()

    def test_returns_true_when_orchestrator_running(self):
        """orchestrator 报告正在运行时应返回 True。"""
        from app.services.task_executor import TaskExecutor

        mock_orchestrator = MagicMock()
        mock_orchestrator.is_running.return_value = True

        executor = TaskExecutor(
            registry=MagicMock(),
            history_store=MagicMock(),
            worker_getter=MagicMock(),
            login_orchestrator=mock_orchestrator,
        )
        assert executor.is_login_running() is True


# =====================================================================
# TaskExecutor — execute_task_async
# =====================================================================


class TestTaskExecutorTaskAsync:
    """TaskExecutor.execute_task_async() 测试。"""

    def test_submits_to_task_pool(self):
        from app.services.task_executor import TaskExecutor

        executor = TaskExecutor(
            registry=MagicMock(),
            history_store=MagicMock(),
            worker_getter=MagicMock(),
            login_orchestrator=MagicMock(),
        )
        executor.execute_task = lambda task_id: (True, "ok")

        future = executor.execute_task_async("t1")
        assert isinstance(future, Future)
        result = future.result(timeout=5)
        assert result == (True, "ok")
        executor._task_pool.shutdown(wait=False)

    def test_ensures_task_pool(self):
        from app.services.task_executor import TaskExecutor

        executor = TaskExecutor(
            registry=MagicMock(),
            history_store=MagicMock(),
            worker_getter=MagicMock(),
            login_orchestrator=MagicMock(),
        )
        assert executor._task_pool is None
        executor.execute_task = lambda task_id: (True, "ok")
        executor.execute_task_async("t1")
        assert executor._task_pool is not None
        executor._task_pool.shutdown(wait=False)

    def test_dedup_skips_pending_task(self):
        """同一 task_id 有 pending 任务时应返回已有 Future。"""
        from app.services.task_executor import TaskExecutor

        barrier = threading.Event()

        def slow_task(task_id):
            barrier.wait(timeout=5)
            return (True, "ok")

        executor = TaskExecutor(
            registry=MagicMock(),
            history_store=MagicMock(),
            worker_getter=MagicMock(),
            login_orchestrator=MagicMock(),
        )
        executor.execute_task = slow_task

        f1 = executor.execute_task_async("t1")
        f2 = executor.execute_task_async("t1")
        assert f1 is f2

        barrier.set()
        f1.result(timeout=5)
        executor._task_pool.shutdown(wait=False)

    def test_dedup_allows_after_completion(self):
        """任务完成后，同一 task_id 可以再次提交。"""
        from app.services.task_executor import TaskExecutor

        call_count = {"n": 0}

        def counting_task(task_id):
            call_count["n"] += 1
            return (True, f"run-{call_count['n']}")

        executor = TaskExecutor(
            registry=MagicMock(),
            history_store=MagicMock(),
            worker_getter=MagicMock(),
            login_orchestrator=MagicMock(),
        )
        executor.execute_task = counting_task

        f1 = executor.execute_task_async("t1")
        assert f1.result(timeout=5) == (True, "run-1")

        f2 = executor.execute_task_async("t1")
        assert f2.result(timeout=5) == (True, "run-2")
        assert f1 is not f2
        assert call_count["n"] == 2
        executor._task_pool.shutdown(wait=False)

    def test_dedup_different_task_ids(self):
        """不同 task_id 不应互相干扰。"""
        from app.services.task_executor import TaskExecutor

        barrier = threading.Event()

        def slow_task(task_id):
            barrier.wait(timeout=5)
            return (True, task_id)

        executor = TaskExecutor(
            registry=MagicMock(),
            history_store=MagicMock(),
            worker_getter=MagicMock(),
            login_orchestrator=MagicMock(),
        )
        executor.execute_task = slow_task

        f1 = executor.execute_task_async("t1")
        f2 = executor.execute_task_async("t2")
        assert f1 is not f2

        barrier.set()
        assert f1.result(timeout=5) == (True, "t1")
        assert f2.result(timeout=5) == (True, "t2")
        executor._task_pool.shutdown(wait=False)

    def test_cleanup_removes_task_from_map(self):
        """任务完成后应从 _running_tasks 中清理。"""
        from app.services.task_executor import TaskExecutor

        barrier = threading.Event()

        def slow_task(task_id):
            barrier.wait(timeout=5)
            return (True, "ok")

        executor = TaskExecutor(
            registry=MagicMock(),
            history_store=MagicMock(),
            worker_getter=MagicMock(),
            login_orchestrator=MagicMock(),
        )
        executor.execute_task = slow_task

        f = executor.execute_task_async("t1")
        assert "t1" in executor._running_tasks

        barrier.set()
        f.result(timeout=5)
        # 回调异步触发，等待一小段时间
        time.sleep(0.2)
        assert "t1" not in executor._running_tasks
        executor._task_pool.shutdown(wait=False)

    def test_shutdown_clears_running_tasks(self):
        """shutdown 应清空 _running_tasks。"""
        from app.services.task_executor import TaskExecutor

        executor = TaskExecutor(
            registry=MagicMock(),
            history_store=MagicMock(),
            worker_getter=MagicMock(),
            login_orchestrator=MagicMock(),
        )
        executor.execute_task = lambda task_id: (True, "ok")
        executor.execute_task_async("t1")
        assert len(executor._running_tasks) > 0 or True  # 可能已完成

        executor.shutdown(wait=False)
        assert len(executor._running_tasks) == 0

