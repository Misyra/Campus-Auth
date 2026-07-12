"""定时任务集成测试 — 验证任务调度执行流程。

覆盖场景：
- 任务注册和执行（TaskRegistry + TaskExecutor 联动）
- 带变量解析的任务执行（VariableResolver 集成）
- 任务失败处理（执行异常、历史记录、状态更新）
- 任务取消（取消事件传播）
"""

from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.services.task_executor import BoundedExecutor, TaskExecutor
from app.services.task_registry import TaskHistoryStore, TaskRegistry

# ── 辅助工厂 ──


def _make_task_config(
    task_id: str = "test_task",
    task_type: str = "script",
    enabled: bool = True,
    **extra,
) -> dict:
    """创建定时任务配置。"""
    config = {
        "id": task_id,
        "name": f"测试任务 {task_id}",
        "type": task_type,
        "enabled": enabled,
        "timeout": 30,
        "schedule": {"hour": 8, "minute": 0},
        **extra,
    }
    return config


def _make_executor(
    registry: TaskRegistry | None = None,
    history_store: TaskHistoryStore | None = None,
    **kwargs,
) -> TaskExecutor:
    """创建 TaskExecutor 实例，外部依赖全部 mock。"""
    if registry is None:
        registry = MagicMock(spec=TaskRegistry)
    if history_store is None:
        history_store = MagicMock(spec=TaskHistoryStore)

    from app.schemas import RuntimeConfig

    executor = TaskExecutor(
        registry=registry,
        history_store=history_store,
        worker_getter=kwargs.get("worker_getter", MagicMock()),
        get_runtime_config=kwargs.get("get_runtime_config", lambda: RuntimeConfig()),
        login_orchestrator=kwargs.get("login_orchestrator", MagicMock()),
        task_manager=kwargs.get("task_manager", MagicMock()),
    )
    return executor


# =====================================================================
# 1. 任务注册和执行
# =====================================================================


class TestTaskRegistrationAndExecution:
    """任务注册和执行：TaskRegistry CRUD + TaskExecutor.execute_task 联动。"""

    def test_save_and_get_task(self, tmp_path: Path):
        """保存任务后能正确读取。"""
        registry = TaskRegistry(tmp_path)
        config = _make_task_config()

        success, message = registry.save_task("test_task", config)

        assert success is True
        assert "成功" in message

        task = registry.get_task("test_task")
        assert task is not None
        assert task["id"] == "test_task"
        assert task["type"] == "script"

    def test_list_tasks(self, tmp_path: Path):
        """注册多个任务后能正确列出。"""
        registry = TaskRegistry(tmp_path)

        registry.save_task("task_a", _make_task_config("task_a"))
        registry.save_task("task_b", _make_task_config("task_b", task_type="browser"))

        tasks = registry.list_tasks()
        assert len(tasks) == 2
        ids = {t["id"] for t in tasks}
        assert ids == {"task_a", "task_b"}

    def test_delete_task(self, tmp_path: Path):
        """删除任务后无法再读取。"""
        registry = TaskRegistry(tmp_path)
        registry.save_task("test_task", _make_task_config())

        success, message = registry.delete_task("test_task")

        assert success is True
        assert "删除" in message
        assert registry.get_task("test_task") is None

    def test_delete_task_clears_history(self, tmp_path: Path):
        """删除任务时 TaskExecutor 同时清理执行历史。"""
        registry = TaskRegistry(tmp_path)
        history_store = TaskHistoryStore(tmp_path / "history")
        executor = _make_executor(registry=registry, history_store=history_store)

        registry.save_task("test_task", _make_task_config())
        history_store.add_record("test_task", "success", "ok", 0.5)
        assert len(history_store.get_history("test_task")) == 1

        success, _ = executor.delete_task("test_task")

        assert success is True
        assert history_store.get_history("test_task") == []

    def test_execute_task_nonexistent(self, tmp_path: Path):
        """执行不存在的任务返回失败。"""
        registry = TaskRegistry(tmp_path)
        executor = _make_executor(registry=registry)

        success, message = executor.execute_task("nonexistent")

        assert success is False
        assert "不存在" in message

    def test_execute_task_records_history(self, tmp_path: Path):
        """任务执行成功后记录历史。"""
        registry = TaskRegistry(tmp_path)
        history_dir = tmp_path / "history"
        history_store = TaskHistoryStore(history_dir)
        executor = _make_executor(registry=registry, history_store=history_store)

        # 注册 script 任务，mock 实际执行
        config = _make_task_config(task_type="script", target_id="test_task")
        registry.save_task("test_task", config)

        with patch.object(executor, "_execute_script", return_value=(True, "hello")):
            success, message = executor.execute_task("test_task")

        assert success is True
        assert message == "hello"

        records = history_store.get_history("test_task")
        assert len(records) == 1
        assert records[0]["status"] == "success"

    def test_execute_task_updates_last_run(self, tmp_path: Path):
        """任务执行后更新 last_run 和 last_status。"""
        registry = TaskRegistry(tmp_path)
        executor = _make_executor(registry=registry)

        config = _make_task_config(task_type="script", target_id="test_task")
        registry.save_task("test_task", config)

        with patch.object(executor, "_execute_script", return_value=(True, "ok")):
            executor.execute_task("test_task")

        task = registry.get_task("test_task")
        assert task is not None
        assert "last_run" in task
        assert task["last_status"] == "success"

    def test_execute_unsupported_type(self, tmp_path: Path):
        """执行不支持的任务类型返回失败。"""
        registry = TaskRegistry(tmp_path)
        executor = _make_executor(registry=registry)

        config = _make_task_config(task_type="unknown_type")
        registry.save_task("bad_task", config)

        success, message = executor.execute_task("bad_task")

        assert success is False
        assert "不支持" in message

    def test_has_enabled_tasks(self, tmp_path: Path):
        """has_enabled_tasks 正确反映启用状态。"""
        registry = TaskRegistry(tmp_path)
        assert registry.has_enabled_tasks() is False

        registry.save_task("t1", _make_task_config(enabled=True))
        assert registry.has_enabled_tasks() is True

    def test_schedule_index_for_due_tasks(self, tmp_path: Path):
        """get_due_tasks 在正确时间返回到期任务。"""
        registry = TaskRegistry(tmp_path)

        config = _make_task_config(schedule={"hour": 14, "minute": 30}, enabled=True)
        registry.save_task("noon_task", config)

        due = registry.get_due_tasks(14, 30)
        assert "noon_task" in due

        not_due = registry.get_due_tasks(15, 0)
        assert "noon_task" not in not_due

    def test_schedule_index_updated_on_save(self, tmp_path: Path):
        """修改任务时间后调度索引同步更新。"""
        registry = TaskRegistry(tmp_path)

        config = _make_task_config(schedule={"hour": 10, "minute": 0}, enabled=True)
        registry.save_task("move_task", config)
        assert "move_task" in registry.get_due_tasks(10, 0)

        # 修改时间
        config["schedule"] = {"hour": 12, "minute": 0}
        registry.save_task("move_task", config)
        assert "move_task" not in registry.get_due_tasks(10, 0)
        assert "move_task" in registry.get_due_tasks(12, 0)


# =====================================================================
# 2. 带变量解析的任务执行
# =====================================================================


class TestTaskExecutionWithVariableResolution:
    """带变量解析的任务执行：VariableResolver 在任务执行链中正确解析变量。"""

    def test_variable_resolver_basic(self):
        """VariableResolver 基本变量替换。"""
        from app.tasks.models import TaskConfig
        from app.tasks.variable_resolver import VariableResolver

        config = TaskConfig(
            url="{{auth_url}}",
            variables={"auth_url": "http://auth.example.com"},
        )
        resolver = VariableResolver(config, {"username": "admin"})

        assert resolver.resolve("{{auth_url}}") == "http://auth.example.com"
        assert resolver.resolve("{{username}}") == "admin"
        assert resolver.resolve("plain text") == "plain text"

    def test_variable_resolver_nested(self):
        """VariableResolver 嵌套变量解析。"""
        from app.tasks.models import TaskConfig
        from app.tasks.variable_resolver import VariableResolver

        config = TaskConfig(
            variables={
                "base_url": "http://example.com",
                "login_url": "{{base_url}}/login",
            },
        )
        resolver = VariableResolver(config, {})

        assert resolver.resolve("{{login_url}}") == "http://example.com/login"

    def test_variable_resolver_runtime_vars(self):
        """VariableResolver 运行时变量优先级高于模板变量。"""
        from app.tasks.models import TaskConfig
        from app.tasks.variable_resolver import VariableResolver

        config = TaskConfig(variables={"greeting": "hello"})
        resolver = VariableResolver(config, {"greeting": "hi"})

        # template_vars 优先于 config.variables
        assert resolver.resolve("{{greeting}}") == "hi"

        # runtime_vars 优先于 template_vars
        resolver.set_runtime_var("greeting", "yo")
        assert resolver.resolve("{{greeting}}") == "yo"

    def test_variable_resolver_js_safe(self):
        """VariableResolver.resolve_for_js 安全转义特殊字符。"""
        from app.tasks.models import TaskConfig
        from app.tasks.variable_resolver import VariableResolver

        config = TaskConfig()
        resolver = VariableResolver(config, {"password": 'p@ss"word'})

        result = resolver.resolve_for_js("{{password}}")
        # 双引号应被 JSON 编码转义
        assert '\\"' in result
        # 结果应能作为合法 Python 字符串解析
        assert "p@ss" in result

    def test_variable_resolver_unresolved(self):
        """未解析的变量保留原样。"""
        from app.tasks.models import TaskConfig
        from app.tasks.variable_resolver import VariableResolver

        config = TaskConfig()
        resolver = VariableResolver(config, {})

        assert resolver.resolve("{{unknown}}") == "{{unknown}}"

    def test_variable_resolver_circular_reference(self):
        """循环引用抛出 StepError。"""
        from app.tasks.models import StepError, TaskConfig
        from app.tasks.variable_resolver import VariableResolver

        config = TaskConfig(variables={"a": "{{b}}", "b": "{{a}}"})
        resolver = VariableResolver(config, {})

        with pytest.raises(StepError, match="循环引用"):
            resolver.resolve("{{a}}")

    def test_variable_resolver_max_depth(self):
        """超过最大嵌套深度抛出 StepError。"""
        from app.tasks.models import StepError, TaskConfig
        from app.tasks.variable_resolver import VariableResolver

        # 构造超过 MAX_DEPTH 的嵌套链
        variables = {}
        for i in range(10):
            variables[f"v{i}"] = f"{{{{v{i + 1}}}}}"
        config = TaskConfig(variables=variables)
        resolver = VariableResolver(config, {})

        with pytest.raises(StepError, match="层级超过限制"):
            resolver.resolve("{{v0}}")

    def test_step_handler_resolve_params(self):
        """StepHandler.resolve_params 正确解析步骤参数。"""
        from app.tasks.models import StepConfig, TaskConfig
        from app.tasks.step_handlers import InputHandler
        from app.tasks.variable_resolver import VariableResolver

        config = TaskConfig(variables={"user": "admin", "pass": "secret"})
        resolver = VariableResolver(config, {})

        step = StepConfig(
            id="s1",
            type="input",
            selector="{{user}}_input",
            value="{{pass}}",
        )

        handler = InputHandler()
        params = handler.resolve_params(step, resolver)

        assert params["selector"] == "admin_input"
        assert params["value"] == "secret"

    def test_execute_browser_task_with_variables(self, tmp_path: Path):
        """浏览器任务执行时正确传递变量配置。"""
        from app.services.login_orchestrator import LoginHandle
        from app.utils.cancel_token import CompositeCancelEvent

        registry = TaskRegistry(tmp_path)
        config = _make_task_config(task_type="browser", target_id="test_task")
        registry.save_task("test_task", config)

        mock_orchestrator = MagicMock()
        mock_handle = LoginHandle(
            future=None,
            source="browser",
            cancel_event=CompositeCancelEvent(),
        )
        mock_handle.result = MagicMock(return_value=(True, "浏览器任务执行成功"))
        mock_handle.rejected_reason = None
        mock_orchestrator.submit.return_value = mock_handle

        executor = _make_executor(
            registry=registry, login_orchestrator=mock_orchestrator
        )

        success, message = executor._execute_browser("test_task", 30)

        assert success is True
        assert "成功" in message



# =====================================================================
# 3. 任务失败处理
# =====================================================================


class TestTaskFailureHandling:
    """任务失败处理：执行异常、历史记录、状态更新。"""

    def test_execute_task_exception_records_failure(self, tmp_path: Path):
        """任务执行抛异常时记录失败历史。"""
        registry = TaskRegistry(tmp_path)
        history_store = TaskHistoryStore(tmp_path / "history")
        executor = _make_executor(registry=registry, history_store=history_store)

        config = _make_task_config(task_type="script", target_id="bad_script")
        registry.save_task("bad_script", config)

        with patch.object(
            executor,
            "_execute_script",
            side_effect=RuntimeError("脚本执行出错"),
        ):
            success, message = executor.execute_task("bad_script")

        assert success is False
        assert "异常" in message

        records = history_store.get_history("bad_script")
        assert len(records) == 1
        assert records[0]["status"] == "failure"

    def test_execute_task_failure_updates_last_status(self, tmp_path: Path):
        """任务执行失败后 last_status 更新为 failure。"""
        registry = TaskRegistry(tmp_path)
        executor = _make_executor(registry=registry)

        config = _make_task_config(task_type="script", target_id="fail_task")
        registry.save_task("fail_task", config)

        with patch.object(
            executor, "_execute_script", return_value=(False, "脚本不存在")
        ):
            executor.execute_task("fail_task")

        task = registry.get_task("fail_task")
        assert task["last_status"] == "failure"

    def test_execute_script_nonexistent(self, tmp_path: Path):
        """执行不存在的脚本任务返回失败。"""
        mock_tm = MagicMock()
        mock_tm.get_task_detail.return_value = None
        executor = _make_executor(task_manager=mock_tm)

        success, message = executor._execute_script("no_script", 30)

        assert success is False
        assert "不存在" in message

    def test_execute_browser_nonexistent(self):
        """执行不存在的浏览器任务返回失败。"""
        registry = MagicMock()
        registry.get_task.return_value = None
        executor = _make_executor(registry=registry)

        success, message = executor._execute_browser("no_browser", 30)

        assert success is False
        assert "不存在" in message

    def test_history_store_persistence(self, tmp_path: Path):
        """历史记录持久化到磁盘。"""
        history_dir = tmp_path / "history"
        store = TaskHistoryStore(history_dir)

        store.add_record("task_1", "success", "ok", 1.5)
        store.add_record("task_1", "failure", "error", 0.3)

        # 从新实例读取
        store2 = TaskHistoryStore(history_dir)
        records = store2.get_history("task_1")
        assert len(records) == 2
        # 最新的在前
        assert records[0]["status"] == "failure"
        assert records[1]["status"] == "success"

    def test_history_store_max_size(self, tmp_path: Path):
        """历史记录超过上限自动裁剪。"""
        from app.services.task_registry import MAX_HISTORY_SIZE

        store = TaskHistoryStore(tmp_path / "history")

        for i in range(MAX_HISTORY_SIZE + 10):
            store.add_record("task_1", "success", f"run {i}", 1.0)

        records = store.get_history("task_1")
        assert len(records) == MAX_HISTORY_SIZE

    def test_history_store_invalid_task_id(self, tmp_path: Path):
        """无效任务 ID 不会产生历史记录。"""
        store = TaskHistoryStore(tmp_path / "history")

        store.add_record("", "success", "ok", 1.0)
        store.add_record("bad id!", "success", "ok", 1.0)

        assert store.get_history("") == []
        assert store.get_history("bad id!") == []

    def test_multiple_failures_accumulate_history(self, tmp_path: Path):
        """多次失败累积历史记录。"""
        registry = TaskRegistry(tmp_path)
        history_store = TaskHistoryStore(tmp_path / "history")
        executor = _make_executor(registry=registry, history_store=history_store)

        config = _make_task_config(task_type="script", target_id="failing_task")
        registry.save_task("failing_task", config)

        for i in range(3):
            with patch.object(
                executor, "_execute_script", return_value=(False, f"错误 {i}")
            ):
                success, _ = executor.execute_task("failing_task")
                assert success is False

        records = history_store.get_history("failing_task")
        assert len(records) == 3
        assert all(r["status"] == "failure" for r in records)


# =====================================================================
# 4. 任务取消
# =====================================================================


class TestTaskCancellation:
    """任务取消：取消事件传播、线程池行为。"""

    def test_bounded_executor_rejects_when_full(self):
        """BoundedExecutor 队列满时拒绝提交。"""
        pool = BoundedExecutor(max_workers=1, queue_size=1)

        # 用 Event 阻塞工作线程
        blocker = threading.Event()

        def blocking_task():
            blocker.wait(timeout=5)

        # 第一次 submit：acquire 信号量（1->0），任务进入线程池
        pool.submit(blocking_task)

        # 第二次 submit：信号量为 0，acquire 失败，应被拒绝
        with pytest.raises(RuntimeError, match="队列已满"):
            pool.submit(lambda: None)

        # 清理
        blocker.set()
        pool.shutdown(wait=True)

    def test_task_executor_shutdown(self, tmp_path: Path):
        """TaskExecutor.shutdown 正确关闭线程池。"""
        registry = TaskRegistry(tmp_path)
        executor = _make_executor(registry=registry)

        # 触发 task_pool 创建
        executor._ensure_task_pool()

        # shutdown 不抛异常
        executor.shutdown(wait=False)

    def test_bounded_executor_semaphore_cleanup(self):
        """BoundedExecutor 任务完成后释放信号量。"""
        pool = BoundedExecutor(max_workers=1, queue_size=1)

        results = []

        def quick_task(v):
            results.append(v)

        # 提交两个任务（一个运行，一个排队）
        f1 = pool.submit(quick_task, 1)
        f2 = pool.submit(quick_task, 2)

        f1.result(timeout=5)
        f2.result(timeout=5)

        assert results == [1, 2]

        # 信号量应已释放，可以继续提交
        f3 = pool.submit(quick_task, 3)
        f3.result(timeout=5)
        assert results == [1, 2, 3]

        pool.shutdown(wait=True)

    def test_task_pool_lazy_initialization(self, tmp_path: Path):
        """任务线程池懒初始化：无任务时不创建。"""
        registry = TaskRegistry(tmp_path)
        executor = _make_executor(registry=registry)

        # 初始状态 task_pool 为 None
        assert executor._task_pool is None

        # 触发初始化
        pool = executor._ensure_task_pool()
        assert pool is not None
        assert executor._task_pool is pool

        # 再次调用返回同一实例
        assert executor._ensure_task_pool() is pool

        pool.shutdown(wait=False)
