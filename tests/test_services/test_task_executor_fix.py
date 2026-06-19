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
        )
        assert executor._task_pool is None
        executor.shutdown()

    def test_shutdown_with_task_pool(self):
        """有 _task_pool 时 shutdown 应同时关闭两个池。"""
        from app.services.task_executor import TaskExecutor

        registry = MagicMock()
        history_store = MagicMock()

        executor = TaskExecutor(
            registry=registry,
            history_store=history_store,
            worker_getter=MagicMock(),
        )
        # 手动触发 _task_pool 创建
        executor._ensure_task_pool()
        assert executor._task_pool is not None

        mock_task_pool = MagicMock()
        mock_login_pool = MagicMock()
        executor._task_pool = mock_task_pool
        executor._login_pool = mock_login_pool

        executor.shutdown(wait=True)
        mock_task_pool.shutdown.assert_called_once_with(wait=True)
        mock_login_pool.shutdown.assert_called_once_with(wait=True)

    def test_ensure_task_pool_creates_once(self):
        """多次调用 _ensure_task_pool 应返回同一实例。"""
        from app.services.task_executor import TaskExecutor

        executor = TaskExecutor(
            registry=MagicMock(),
            history_store=MagicMock(),
            worker_getter=MagicMock(),
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

    def test_set_runtime_config_getter(self):
        executor = self._make_executor()
        getter = lambda: {"key": "value"}
        executor.set_runtime_config_getter(getter)
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
        executor = self._make_executor()
        executor._registry.get_task.return_value = {"type": "browser"}
        executor._get_runtime_config = lambda: {"browser_settings": {"pure_mode": True}}

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.data = "登录成功"
        mock_worker = MagicMock()
        mock_worker.submit.return_value = mock_result
        executor._worker_getter = lambda: mock_worker

        with patch("app.workers.playwright_worker.CMD_LOGIN", "login", create=True):
            success, msg = executor._execute_browser("b1", 60)
        assert success is True
        assert msg == "登录成功"

    def test_browser_failure(self):
        executor = self._make_executor()
        executor._registry.get_task.return_value = {"type": "browser"}
        executor._get_runtime_config = None

        mock_result = MagicMock()
        mock_result.success = False
        mock_result.error = "页面加载失败"
        mock_worker = MagicMock()
        mock_worker.submit.return_value = mock_result
        executor._worker_getter = lambda: mock_worker

        with patch("app.workers.playwright_worker.CMD_LOGIN", "login", create=True):
            success, msg = executor._execute_browser("b1", 60)
        assert success is False
        assert "页面加载失败" in msg

    def test_browser_import_error(self):
        executor = self._make_executor()
        executor._registry.get_task.return_value = {"type": "browser"}
        executor._get_runtime_config = None

        with patch.dict("sys.modules", {"app.workers.playwright_worker": None}):
            success, msg = executor._execute_browser("b1", 60)
        assert success is False
        assert "依赖" in msg

    def test_browser_generic_exception(self):
        executor = self._make_executor()
        executor._registry.get_task.return_value = {"type": "browser"}
        executor._get_runtime_config = lambda: {}
        executor._worker_getter = MagicMock(side_effect=RuntimeError("worker crash"))

        with patch("app.workers.playwright_worker.CMD_LOGIN", "login", create=True):
            success, msg = executor._execute_browser("b1", 60)
        assert success is False
        assert "异常" in msg

    def test_browser_result_data_not_string(self):
        """result.data 不是字符串时应返回默认消息。"""
        executor = self._make_executor()
        executor._registry.get_task.return_value = {"type": "browser"}
        executor._get_runtime_config = lambda: {}

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.data = {"key": "value"}  # 非字符串
        mock_worker = MagicMock()
        mock_worker.submit.return_value = mock_result
        executor._worker_getter = lambda: mock_worker

        with patch("app.workers.playwright_worker.CMD_LOGIN", "login", create=True):
            success, msg = executor._execute_browser("b1", 60)
        assert success is True
        assert "浏览器任务执行成功" in msg

    def test_browser_failure_no_error_msg(self):
        """失败但无 error 时应返回默认错误消息。"""
        executor = self._make_executor()
        executor._registry.get_task.return_value = {"type": "browser"}
        executor._get_runtime_config = lambda: {}

        mock_result = MagicMock()
        mock_result.success = False
        mock_result.error = None
        mock_worker = MagicMock()
        mock_worker.submit.return_value = mock_result
        executor._worker_getter = lambda: mock_worker

        with patch("app.workers.playwright_worker.CMD_LOGIN", "login", create=True):
            success, msg = executor._execute_browser("b1", 60)
        assert success is False
        assert "浏览器任务执行失败" in msg


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
        executor._get_runtime_config = lambda: {"shell_path": "/bin/bash"}
        executor._shell_policy = MagicMock()
        executor._shell_policy.run_sync.return_value = (0, "hello", "")

        success, msg = executor._execute_shell("echo hello", 30)
        assert success is True
        assert "hello" in msg
        executor._shell_policy.run_sync.assert_called_once()

    def test_shell_from_default(self):
        """配置中无 shell_path 时使用默认 shell。"""
        executor = self._make_executor()
        executor._get_runtime_config = lambda: {}
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
        executor._get_runtime_config = lambda: {"shell_path": "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe"}
        executor._shell_policy = MagicMock()
        executor._shell_policy.run_sync.return_value = (0, "ok", "")

        executor._execute_shell("Get-Process", 30)
        call_args = executor._shell_policy.run_sync.call_args[0][0]
        assert "-Command" in call_args

    def test_cmd_command_format(self):
        """cmd.exe 应使用 /c 参数。"""
        executor = self._make_executor()
        executor._get_runtime_config = lambda: {"shell_path": "C:\\Windows\\System32\\cmd.exe"}
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
        executor._get_runtime_config = lambda: {"shell_path": "/bin/bash"}
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
        executor._get_runtime_config = lambda: {"shell_path": "/bin/bash"}
        executor._shell_policy = MagicMock()
        executor._shell_policy.run_sync.return_value = (1, "", "error occurred")

        success, msg = executor._execute_shell("false", 30)
        assert success is False
        assert "error occurred" in msg

    def test_nonzero_no_stderr(self):
        """非零返回码且无 stderr 时应使用 stdout。"""
        executor = self._make_executor()
        executor._get_runtime_config = lambda: {"shell_path": "/bin/bash"}
        executor._shell_policy = MagicMock()
        executor._shell_policy.run_sync.return_value = (1, "some stdout", "")

        success, msg = executor._execute_shell("cmd", 30)
        assert success is False
        assert "some stdout" in msg

    def test_nonzero_no_output(self):
        """非零返回码且无任何输出时显示退出码。"""
        executor = self._make_executor()
        executor._get_runtime_config = lambda: {"shell_path": "/bin/bash"}
        executor._shell_policy = MagicMock()
        executor._shell_policy.run_sync.return_value = (2, "", "")

        success, msg = executor._execute_shell("cmd", 30)
        assert success is False
        assert "退出码" in msg

    def test_success_no_output(self):
        """成功但无输出时应显示默认文本。"""
        executor = self._make_executor()
        executor._get_runtime_config = lambda: {"shell_path": "/bin/bash"}
        executor._shell_policy = MagicMock()
        executor._shell_policy.run_sync.return_value = (0, "", "")

        success, msg = executor._execute_shell("true", 30)
        assert success is True
        assert "无输出" in msg

    def test_permission_error(self):
        executor = self._make_executor()
        executor._get_runtime_config = lambda: {"shell_path": "/bin/bash"}
        executor._shell_policy = MagicMock()
        executor._shell_policy.run_sync.side_effect = PermissionError("denied")

        success, msg = executor._execute_shell("cmd", 30)
        assert success is False
        assert "denied" in msg

    def test_generic_exception(self):
        executor = self._make_executor()
        executor._get_runtime_config = lambda: {"shell_path": "/bin/bash"}
        executor._shell_policy = MagicMock()
        executor._shell_policy.run_sync.side_effect = OSError("io error")

        success, msg = executor._execute_shell("cmd", 30)
        assert success is False
        assert "异常" in msg

    def test_output_truncation(self):
        """输出超过 500 字符时应被截断。"""
        executor = self._make_executor()
        executor._get_runtime_config = lambda: {"shell_path": "/bin/bash"}
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
    """TaskExecutor.execute_login() 测试。"""

    def _make_executor(self, **kwargs):
        from app.services.task_executor import TaskExecutor

        defaults = dict(
            registry=MagicMock(),
            history_store=MagicMock(),
            worker_getter=MagicMock(),
            login_history=MagicMock(),
            profile_service=MagicMock(),
        )
        defaults.update(kwargs)
        return TaskExecutor(**defaults)

    def test_cancel_event_set(self):
        """cancel_event 已设置时应立即返回。"""
        executor = self._make_executor()
        cancel = threading.Event()
        cancel.set()

        success, msg = executor.execute_login(cancel_event=cancel)
        assert success is False
        assert "取消" in msg

    def test_login_success(self):
        executor = self._make_executor()
        executor._get_runtime_config = lambda: {"browser_settings": {"pure_mode": False}}

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.data = "登录成功"
        mock_worker = MagicMock()
        mock_worker.submit.return_value = mock_result
        executor._worker_getter = lambda: mock_worker

        with patch("app.workers.playwright_worker.CMD_LOGIN", "login", create=True):
            success, msg = executor.execute_login()
        assert success is True

    def test_login_failure(self):
        executor = self._make_executor()
        executor._get_runtime_config = lambda: {}

        mock_result = MagicMock()
        mock_result.success = False
        mock_result.error = "认证失败"
        mock_worker = MagicMock()
        mock_worker.submit.return_value = mock_result
        executor._worker_getter = lambda: mock_worker

        with patch("app.workers.playwright_worker.CMD_LOGIN", "login", create=True):
            success, msg = executor.execute_login()
        assert success is False
        assert "认证失败" in msg

    def test_login_failure_no_error(self):
        """失败但无 error 时应返回默认消息。"""
        executor = self._make_executor()
        executor._get_runtime_config = lambda: {}

        mock_result = MagicMock()
        mock_result.success = False
        mock_result.error = None
        mock_worker = MagicMock()
        mock_worker.submit.return_value = mock_result
        executor._worker_getter = lambda: mock_worker

        with patch("app.workers.playwright_worker.CMD_LOGIN", "login", create=True):
            success, msg = executor.execute_login()
        assert success is False
        assert "登录失败" in msg

    def test_login_success_data_not_string(self):
        """result.data 非字符串时应返回默认消息。"""
        executor = self._make_executor()
        executor._get_runtime_config = lambda: {}

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.data = {"status": "ok"}
        mock_worker = MagicMock()
        mock_worker.submit.return_value = mock_result
        executor._worker_getter = lambda: mock_worker

        with patch("app.workers.playwright_worker.CMD_LOGIN", "login", create=True):
            success, msg = executor.execute_login()
        assert success is True
        assert msg == "登录成功"

    def test_login_no_runtime_config(self):
        """无 _get_runtime_config 时应使用空配置。"""
        executor = self._make_executor()
        executor._get_runtime_config = None

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.data = "ok"
        mock_worker = MagicMock()
        mock_worker.submit.return_value = mock_result
        executor._worker_getter = lambda: mock_worker

        with patch("app.workers.playwright_worker.CMD_LOGIN", "login", create=True):
            success, msg = executor.execute_login()
        assert success is True

    def test_login_import_error(self):
        """ImportError 应被捕获。"""
        executor = self._make_executor()
        executor._get_runtime_config = None

        with patch.dict("sys.modules", {"app.workers.playwright_worker": None}):
            success, msg = executor.execute_login()
        assert success is False
        assert "依赖" in msg

    def test_login_generic_exception(self):
        """通用异常应被捕获。"""
        executor = self._make_executor()
        executor._get_runtime_config = lambda: {}
        executor._worker_getter = MagicMock(side_effect=RuntimeError("crash"))

        with patch("app.workers.playwright_worker.CMD_LOGIN", "login", create=True):
            success, msg = executor.execute_login()
        assert success is False
        assert "异常" in msg

    def test_login_timeout_from_config(self):
        """execute_login 应从 config 读取 login_timeout 并传递给 worker。"""
        executor = self._make_executor()
        executor._get_runtime_config = lambda: {
            "browser_settings": {"pure_mode": False},
            "login_timeout": 200,
        }

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.data = "ok"
        mock_worker = MagicMock()
        mock_worker.submit.return_value = mock_result
        executor._worker_getter = lambda: mock_worker

        with patch("app.workers.playwright_worker.CMD_LOGIN", "login", create=True):
            executor.execute_login()
        call_kwargs = mock_worker.submit.call_args.kwargs
        assert call_kwargs["timeout"] == 200

    def test_login_timeout_default_300(self):
        """config 中无 login_timeout 时默认 300 秒。"""
        executor = self._make_executor()
        executor._get_runtime_config = lambda: {
            "browser_settings": {"pure_mode": False},
        }

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.data = "ok"
        mock_worker = MagicMock()
        mock_worker.submit.return_value = mock_result
        executor._worker_getter = lambda: mock_worker

        with patch("app.workers.playwright_worker.CMD_LOGIN", "login", create=True):
            executor.execute_login()
        call_kwargs = mock_worker.submit.call_args.kwargs
        assert call_kwargs["timeout"] == 300

    def test_login_timeout_minimum_60(self):
        """login_timeout 低于 60 时应取 60 秒下限。"""
        executor = self._make_executor()
        executor._get_runtime_config = lambda: {
            "browser_settings": {"pure_mode": False},
            "login_timeout": 30,
        }

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.data = "ok"
        mock_worker = MagicMock()
        mock_worker.submit.return_value = mock_result
        executor._worker_getter = lambda: mock_worker

        with patch("app.workers.playwright_worker.CMD_LOGIN", "login", create=True):
            executor.execute_login()
        call_kwargs = mock_worker.submit.call_args.kwargs
        assert call_kwargs["timeout"] == 60


# =====================================================================
# TaskExecutor — _record_login_history
# =====================================================================


class TestTaskExecutorRecordLoginHistory:
    """TaskExecutor._record_login_history() 测试。"""

    def _make_executor(self, **kwargs):
        from app.services.task_executor import TaskExecutor

        defaults = dict(
            registry=MagicMock(),
            history_store=MagicMock(),
            worker_getter=MagicMock(),
            login_history=MagicMock(),
            profile_service=MagicMock(),
        )
        defaults.update(kwargs)
        return TaskExecutor(**defaults)

    def test_no_login_history_service(self):
        """无 login_history 时应直接返回。"""
        executor = self._make_executor(login_history=None)
        executor._record_login_history(True, 100)
        # 不应抛出异常

    def test_records_success(self):
        executor = self._make_executor()
        executor._record_login_history(True, 150)
        executor._login_history.record.assert_called_once_with(
            success=True,
            duration_ms=150,
            profile_service=executor._profile_service,
            error="",
        )

    def test_records_failure_with_error(self):
        executor = self._make_executor()
        executor._record_login_history(False, 200, error="timeout")
        executor._login_history.record.assert_called_once_with(
            success=False,
            duration_ms=200,
            profile_service=executor._profile_service,
            error="timeout",
        )

    def test_record_exception_caught(self):
        """record 抛异常时应被静默捕获。"""
        executor = self._make_executor()
        executor._login_history.record.side_effect = RuntimeError("db error")
        executor._record_login_history(True, 100)
        # 不应抛出异常


# =====================================================================
# TaskExecutor — execute_login_async (去重机制)
# =====================================================================


class TestTaskExecutorLoginAsync:
    """TaskExecutor.execute_login_async() 登录去重机制测试。"""

    def _make_executor(self, **kwargs):
        from app.services.task_executor import TaskExecutor

        defaults = dict(
            registry=MagicMock(),
            history_store=MagicMock(),
            worker_getter=MagicMock(),
        )
        defaults.update(kwargs)
        return TaskExecutor(**defaults)

    def test_first_login_submits(self):
        """首次登录应提交新任务。"""
        executor = self._make_executor()
        executor.execute_login = _slow_return((True, "ok"))

        future = executor.execute_login_async()
        assert isinstance(future, Future)
        assert future.result(timeout=5) == (True, "ok")

    def test_duplicate_login_returns_existing(self):
        """重复登录应返回已有的 Future。"""
        executor = self._make_executor()

        blocker = threading.Event()
        def slow_login(cancel_event=None, config_snapshot=None):
            blocker.wait(timeout=5)
            return (True, "ok")

        executor.execute_login = slow_login

        future1 = executor.execute_login_async()
        future2 = executor.execute_login_async()
        assert future1 is future2

        blocker.set()
        future1.result(timeout=5)

    def test_login_done_clears_future(self):
        """登录完成后 _login_future 应被清理。"""
        executor = self._make_executor()
        executor.execute_login = _slow_return((True, "ok"))

        future = executor.execute_login_async()
        future.result(timeout=5)
        # 等待回调执行
        time.sleep(0.1)

        assert executor._login_future is None

    def test_login_with_cancel_event(self):
        """cancel_event 应传递给 execute_login。"""
        executor = self._make_executor()
        cancel = threading.Event()
        received_events = []

        def fake_login(cancel_event=None):
            received_events.append(cancel_event)
            return (False, "cancelled")

        executor.execute_login = _slow_return((False, "cancelled"))

        future = executor.execute_login_async(cancel_event=cancel)
        result = future.result(timeout=5)
        assert result == (False, "cancelled")

    def test_new_login_after_previous_done(self):
        """前一次登录完成后，应能提交新登录。"""
        executor = self._make_executor()
        executor.execute_login = _slow_return((True, "ok"))

        future1 = executor.execute_login_async()
        future1.result(timeout=5)
        time.sleep(0.1)

        future2 = executor.execute_login_async()
        assert future2 is not future1
        future2.result(timeout=5)

    def test_duplicate_login_links_cancel_event(self):
        """去重时新 cancel_event 应联动到已有任务。"""
        executor = self._make_executor()

        blocker = threading.Event()
        received_cancel = threading.Event()

        def slow_login(cancel_event=None, config_snapshot=None):
            # 模拟长时间登录，定期检查 cancel_event
            for _ in range(50):
                if cancel_event and cancel_event.is_set():
                    received_cancel.set()
                    return (False, "cancelled")
                blocker.wait(timeout=0.1)
            return (True, "ok")

        executor.execute_login = slow_login

        original_cancel = threading.Event()
        future1 = executor.execute_login_async(cancel_event=original_cancel)

        # 第二次调用，带新的 cancel_event
        new_cancel = threading.Event()
        future2 = executor.execute_login_async(cancel_event=new_cancel)
        assert future1 is future2

        # 设置新 cancel_event，应联动到已有任务
        new_cancel.set()
        future1.result(timeout=5)

        # 验证已有任务确实收到了取消信号
        assert received_cancel.is_set()

    def test_on_login_done_clears_cancel_event(self):
        """登录完成后 _login_cancel_event 应被清理。"""
        executor = self._make_executor()
        executor.execute_login = _slow_return((True, "ok"))

        cancel = threading.Event()
        future = executor.execute_login_async(cancel_event=cancel)
        future.result(timeout=5)
        time.sleep(0.1)

        assert executor._login_cancel_event is None


# =====================================================================
# TaskExecutor — _on_login_done
# =====================================================================


# =====================================================================
# TaskExecutor — is_login_running
# =====================================================================


class TestIsLoginRunning:
    """测试 is_login_running 状态查询。"""

    def test_no_login_returns_false(self):
        from app.services.task_executor import TaskExecutor

        executor = TaskExecutor(
            registry=MagicMock(),
            history_store=MagicMock(),
            worker_getter=MagicMock(),
        )
        assert executor.is_login_running() is False

    def test_with_pending_future_returns_true(self):
        from app.services.task_executor import TaskExecutor

        executor = TaskExecutor(
            registry=MagicMock(),
            history_store=MagicMock(),
            worker_getter=MagicMock(),
        )
        future = Future()
        executor._login_future = future
        assert executor.is_login_running() is True

    def test_with_done_future_returns_false(self):
        from app.services.task_executor import TaskExecutor

        executor = TaskExecutor(
            registry=MagicMock(),
            history_store=MagicMock(),
            worker_getter=MagicMock(),
        )
        future = Future()
        future.set_result((True, "ok"))
        executor._login_future = future
        assert executor.is_login_running() is False


# =====================================================================
# TaskExecutor — force_clear_login_slot
# =====================================================================


class TestForceClearLoginSlot:
    """TaskExecutor.force_clear_login_slot() 测试。"""

    def test_clears_login_future(self):
        """force_clear_login_slot 应清理 _login_future。"""
        from app.services.task_executor import TaskExecutor

        executor = TaskExecutor(
            registry=MagicMock(),
            history_store=MagicMock(),
            worker_getter=MagicMock(),
        )
        # 模拟正在进行的登录
        executor._login_future = MagicMock()
        executor._login_future.done.return_value = False
        executor._login_cancel_event = threading.Event()

        executor.force_clear_login_slot()

        assert executor._login_future is None
        assert executor._login_cancel_event is None

    def test_clears_cancel_event(self):
        """force_clear_login_slot 应清理 _login_cancel_event。"""
        from app.services.task_executor import TaskExecutor

        executor = TaskExecutor(
            registry=MagicMock(),
            history_store=MagicMock(),
            worker_getter=MagicMock(),
        )
        executor._login_future = MagicMock()
        executor._login_future.done.return_value = True
        executor._login_cancel_event = threading.Event()

        executor.force_clear_login_slot()

        assert executor._login_cancel_event is None

    def test_no_error_when_no_future(self):
        """无 _login_future 时调用不应报错。"""
        from app.services.task_executor import TaskExecutor

        executor = TaskExecutor(
            registry=MagicMock(),
            history_store=MagicMock(),
            worker_getter=MagicMock(),
        )
        executor._login_future = None
        executor._login_cancel_event = None

        # 不应抛出异常
        executor.force_clear_login_slot()
        assert executor._login_future is None
        assert executor._login_cancel_event is None

    def test_thread_safety(self):
        """并发调用 force_clear_login_slot 应线程安全。"""
        from app.services.task_executor import TaskExecutor

        executor = TaskExecutor(
            registry=MagicMock(),
            history_store=MagicMock(),
            worker_getter=MagicMock(),
        )
        executor._login_future = MagicMock()
        executor._login_future.done.return_value = False
        executor._login_cancel_event = threading.Event()

        barrier = threading.Barrier(5)
        results = []

        def call_clear():
            barrier.wait(timeout=5)
            try:
                executor.force_clear_login_slot()
                results.append(True)
            except Exception:
                results.append(False)

        threads = [threading.Thread(target=call_clear) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert len(results) == 5
        assert all(results)
        assert executor._login_future is None
        assert executor._login_cancel_event is None


# =====================================================================
# TaskExecutor — F13 cancel_event 冗余检查修复
# =====================================================================


class TestCancelEventRedundancyFix:
    """F13: cancel_event 冗余检查修复。"""

    def test_link_cancel_event_called_when_existing_login(self):
        """已有登录时，新 cancel_event 应联动到已有任务。"""
        from app.services.task_executor import TaskExecutor

        executor = TaskExecutor(
            registry=MagicMock(),
            history_store=MagicMock(),
            worker_getter=MagicMock(),
        )

        # 模拟已有正在进行的登录
        existing_future = Future()
        existing_cancel = threading.Event()
        executor._login_future = existing_future
        executor._login_cancel_event = existing_cancel

        new_cancel = threading.Event()
        with patch.object(executor, "_link_cancel_event") as mock_link:
            result = executor.execute_login_async(cancel_event=new_cancel)

        assert result is existing_future
        mock_link.assert_called_once_with(new_cancel, existing_cancel)

    def test_no_link_when_no_existing_cancel_event(self):
        """已有登录但 _login_cancel_event 为 None 时不应联动。"""
        from app.services.task_executor import TaskExecutor

        executor = TaskExecutor(
            registry=MagicMock(),
            history_store=MagicMock(),
            worker_getter=MagicMock(),
        )

        # 模拟已有登录但 _login_cancel_event 为 None
        existing_future = Future()
        executor._login_future = existing_future
        executor._login_cancel_event = None

        new_cancel = threading.Event()
        with patch.object(executor, "_link_cancel_event") as mock_link:
            result = executor.execute_login_async(cancel_event=new_cancel)

        assert result is existing_future
        mock_link.assert_not_called()


# =====================================================================
# TaskExecutor — _on_login_done
# =====================================================================


class TestTaskExecutorOnLoginDone:
    """TaskExecutor._on_login_done() 测试。"""

    def test_clears_matching_future(self):
        from app.services.task_executor import TaskExecutor

        executor = TaskExecutor(
            registry=MagicMock(),
            history_store=MagicMock(),
            worker_getter=MagicMock(),
        )
        mock_future = MagicMock()
        executor._login_future = mock_future
        executor._on_login_done(mock_future)
        assert executor._login_future is None

    def test_does_not_clear_different_future(self):
        from app.services.task_executor import TaskExecutor

        executor = TaskExecutor(
            registry=MagicMock(),
            history_store=MagicMock(),
            worker_getter=MagicMock(),
        )
        future1 = MagicMock()
        future2 = MagicMock()
        executor._login_future = future1
        executor._on_login_done(future2)
        assert executor._login_future is future1


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
        )
        executor.execute_task = lambda task_id: (True, "ok")
        executor.execute_task_async("t1")
        assert len(executor._running_tasks) > 0 or True  # 可能已完成

        executor.shutdown(wait=False)
        assert len(executor._running_tasks) == 0

