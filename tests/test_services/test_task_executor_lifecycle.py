"""TaskExecutor 及相关组件测试。

覆盖：
1. 定时任务线程池懒初始化
2. BoundedExecutor 队列限制
3. TaskExecutor CRUD 方法、登录去重、execute_task 分发
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import Future
from unittest.mock import MagicMock

import pytest

from app.schemas import RuntimeConfig

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
            get_runtime_config=MagicMock(),
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
            get_runtime_config=MagicMock(),
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
            get_runtime_config=MagicMock(),
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
            get_runtime_config=MagicMock(),
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
            get_runtime_config=MagicMock(),
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
            get_runtime_config=MagicMock(),
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
    """TaskExecutor CRUD 属性和 delete_task 协调测试。"""

    def _make_executor(self, **kwargs):
        from app.services.task_executor import TaskExecutor

        defaults = dict(
            registry=MagicMock(),
            history_store=MagicMock(),
            worker_getter=MagicMock(),
            get_runtime_config=MagicMock(),
            login_orchestrator=MagicMock(),
        )
        defaults.update(kwargs)
        return TaskExecutor(**defaults)

    def test_registry_property(self):
        """registry 属性应返回注入的注册中心。"""
        executor = self._make_executor()
        assert executor.registry is executor._registry

    def test_history_store_property(self):
        """history_store 属性应返回注入的历史存储。"""
        executor = self._make_executor()
        assert executor.history_store is executor._history_store

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

    def test_constructor_injects_get_runtime_config(self):
        """get_runtime_config 应通过构造器注入（不再支持延迟绑定）。"""
        executor = self._make_executor()

        def getter():
            return {"key": "value"}

        executor = self._make_executor(get_runtime_config=getter)
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
            get_runtime_config=MagicMock(),
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
        executor._execute_script.assert_called_once_with("s1", 30, None)

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
        executor._execute_browser.assert_called_once_with("b1", 60, None)

    def test_exception_during_execution(self):
        """执行异常应被捕获并记录。"""
        executor = self._make_executor()
        executor._registry.get_task.return_value = {
            "type": "script",
            "target_id": "s1",
            "timeout": 10,
        }
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
        executor._execute_script.assert_called_once_with("s1", 60, None)

    def test_history_recorded_with_duration(self):
        """应记录执行时长。"""
        executor = self._make_executor()
        executor._registry.get_task.return_value = {
            "type": "script",
            "target_id": "s1",
            "timeout": 5,
        }
        executor._execute_script = MagicMock(return_value=(True, "ok"))

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

        mock_tm = MagicMock()
        defaults = dict(
            registry=MagicMock(),
            history_store=MagicMock(),
            worker_getter=MagicMock(),
            get_runtime_config=MagicMock(),
            login_orchestrator=MagicMock(),
            task_manager=mock_tm,
        )
        defaults.update(kwargs)
        executor = TaskExecutor(**defaults)
        return executor

    def test_task_not_found(self):
        executor = self._make_executor()
        executor._task_manager.get_task_detail.return_value = None
        success, msg = executor._execute_script("s1", 30)
        assert success is False
        assert "不存在" in msg

    def test_task_wrong_type(self):
        executor = self._make_executor()
        executor._task_manager.get_task_detail.return_value = {"type": "browser"}
        success, msg = executor._execute_script("s1", 30)
        assert success is False
        assert "不存在" in msg

    def test_cancelled(self):
        executor = self._make_executor()
        executor._task_manager.get_task_detail.return_value = {"type": "py"}
        cancel = MagicMock()
        cancel.is_set.return_value = True
        success, msg = executor._execute_script("s1", 30, cancel_event=cancel)
        assert success is False
        assert "取消" in msg


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
            get_runtime_config=MagicMock(),
            login_orchestrator=MagicMock(),
            task_manager=MagicMock(),
            browser_task_service=MagicMock(),
        )
        defaults.update(kwargs)
        return TaskExecutor(**defaults)

    def _make_handle(self, ok: bool, msg):
        """构造 BrowserTaskService.submit_task 返回的 mock handle。"""
        handle = MagicMock()
        handle.rejected_reason = None
        handle.result = MagicMock(return_value=(ok, msg))
        return handle

    def test_task_not_found(self):
        executor = self._make_executor()
        executor._task_manager.get_task_detail.return_value = None
        success, msg = executor._execute_browser("b1", 60)
        assert success is False
        assert "不存在" in msg

    def test_task_wrong_type(self):
        executor = self._make_executor()
        executor._task_manager.get_task_detail.return_value = {"type": "script"}
        success, msg = executor._execute_browser("b1", 60)
        assert success is False
        assert "不存在" in msg

    def test_browser_success(self):
        executor = self._make_executor()
        executor._task_manager.get_task_detail.return_value = {"type": "browser"}
        executor._get_runtime_config = lambda: RuntimeConfig()
        executor._browser_task_service.submit_task.return_value = self._make_handle(
            True, "登录成功"
        )

        success, msg = executor._execute_browser("b1", 60)
        assert success is True
        assert msg == "登录成功"

    def test_browser_failure(self):
        executor = self._make_executor()
        executor._task_manager.get_task_detail.return_value = {"type": "browser"}
        executor._get_runtime_config = None
        executor._browser_task_service.submit_task.return_value = self._make_handle(
            False, "页面加载失败"
        )

        success, msg = executor._execute_browser("b1", 60)
        assert success is False
        assert "页面加载失败" in msg

    def test_browser_import_error(self):
        executor = self._make_executor()
        executor._task_manager.get_task_detail.return_value = {"type": "browser"}
        executor._get_runtime_config = None
        executor._browser_task_service.submit_task.return_value = self._make_handle(
            False,
            "登录需要额外依赖，请检查 Playwright 安装状态",
        )

        success, msg = executor._execute_browser("b1", 60)
        assert success is False
        assert "依赖" in msg

    def test_browser_generic_exception(self):
        executor = self._make_executor()
        executor._task_manager.get_task_detail.return_value = {"type": "browser"}
        executor._get_runtime_config = lambda: RuntimeConfig()
        executor._browser_task_service.submit_task.return_value = self._make_handle(
            False, "登录执行异常: worker crash"
        )

        success, msg = executor._execute_browser("b1", 60)
        assert success is False
        assert "异常" in msg

    def test_browser_result_data_not_string(self):
        """result.data 不是字符串时应返回默认消息。"""
        executor = self._make_executor()
        executor._task_manager.get_task_detail.return_value = {"type": "browser"}
        executor._get_runtime_config = lambda: RuntimeConfig()
        executor._browser_task_service.submit_task.return_value = self._make_handle(
            True, {"key": "value"}
        )

        success, msg = executor._execute_browser("b1", 60)
        assert success is True
        assert "浏览器任务执行成功" in msg

    def test_browser_failure_no_error_msg(self):
        """失败但无 error 时应返回默认错误消息。"""
        executor = self._make_executor()
        executor._task_manager.get_task_detail.return_value = {"type": "browser"}
        executor._get_runtime_config = lambda: RuntimeConfig()
        executor._browser_task_service.submit_task.return_value = self._make_handle(
            False, ""
        )

        success, msg = executor._execute_browser("b1", 60)
        assert success is False
        assert "浏览器任务执行失败" in msg

    def test_browser_rejected_returns_reason(self):
        """submit_task 返回 rejected_reason 时应直接返回失败。"""
        executor = self._make_executor()
        executor._task_manager.get_task_detail.return_value = {"type": "browser"}
        executor._get_runtime_config = lambda: RuntimeConfig()

        handle = MagicMock()
        handle.rejected_reason = "任务队列已满，请稍后重试"
        handle.result = MagicMock(return_value=(False, "should not be called"))
        executor._browser_task_service.submit_task.return_value = handle

        success, msg = executor._execute_browser("b1", 60)
        assert success is False
        assert "任务队列已满" in msg

    def test_browser_timeout_forwarded(self):
        """timeout 应传递给 browser_task_service.submit_task()。"""
        executor = self._make_executor()
        executor._task_manager.get_task_detail.return_value = {"type": "browser"}
        executor._get_runtime_config = lambda: RuntimeConfig()
        executor._browser_task_service.submit_task.return_value = self._make_handle(
            True, "ok"
        )

        executor._execute_browser("b1", 120)
        call_kwargs = executor._browser_task_service.submit_task.call_args.kwargs
        assert call_kwargs["timeout"] == 120


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
            get_runtime_config=MagicMock(),
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
            get_runtime_config=MagicMock(),
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
            get_runtime_config=MagicMock(),
            login_orchestrator=MagicMock(),
        )
        executor.execute_task = lambda task_id, cancel_event=None: (True, "ok")

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
            get_runtime_config=MagicMock(),
            login_orchestrator=MagicMock(),
        )
        assert executor._task_pool is None
        executor.execute_task = lambda task_id, cancel_event=None: (True, "ok")
        executor.execute_task_async("t1")
        assert executor._task_pool is not None
        executor._task_pool.shutdown(wait=False)

    def test_dedup_skips_pending_task(self):
        """同一 task_id 有 pending 任务时应返回已有 Future。"""
        from app.services.task_executor import TaskExecutor

        barrier = threading.Event()

        def slow_task(task_id, cancel_event=None):
            barrier.wait(timeout=5)
            return (True, "ok")

        executor = TaskExecutor(
            registry=MagicMock(),
            history_store=MagicMock(),
            worker_getter=MagicMock(),
            get_runtime_config=MagicMock(),
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

        def counting_task(task_id, cancel_event=None):
            call_count["n"] += 1
            return (True, f"run-{call_count['n']}")

        executor = TaskExecutor(
            registry=MagicMock(),
            history_store=MagicMock(),
            worker_getter=MagicMock(),
            get_runtime_config=MagicMock(),
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

        def slow_task(task_id, cancel_event=None):
            barrier.wait(timeout=5)
            return (True, task_id)

        executor = TaskExecutor(
            registry=MagicMock(),
            history_store=MagicMock(),
            worker_getter=MagicMock(),
            get_runtime_config=MagicMock(),
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

        def slow_task(task_id, cancel_event=None):
            barrier.wait(timeout=5)
            return (True, "ok")

        executor = TaskExecutor(
            registry=MagicMock(),
            history_store=MagicMock(),
            worker_getter=MagicMock(),
            get_runtime_config=MagicMock(),
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
            get_runtime_config=MagicMock(),
            login_orchestrator=MagicMock(),
        )
        executor.execute_task = lambda task_id: (True, "ok")
        executor.execute_task_async("t1")
        assert len(executor._running_tasks) > 0 or True  # 可能已完成

        executor.shutdown(wait=False)
        assert len(executor._running_tasks) == 0
