"""集成测试共享 fixture — 真实组件栈，只 mock 外部边界。"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.schemas import Profile, ProfilesData
from app.services.engine import ScheduleEngine
from app.services.login_history_service import LoginHistoryService
from app.services.login_orchestrator import LoginOrchestrator
from app.services.profile_service import ProfileService
from app.services.task_executor import TaskExecutor
from app.services.task_registry import TaskHistoryStore, TaskRegistry
from app.workers.playwright_worker import WorkerResponse


def _write_initial_config(tmp_path: Path, **overrides) -> None:
    """写入初始 settings.json 配置。"""
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)

    defaults = {
        "auto_switch": False,
        "active_profile": "default",
        "global_settings": {
            "check_interval_seconds": 10,  # 最小值，加速测试
            "max_retries": 3,
            "retry_interval": 1,
            "pause_enabled": False,
            "enable_tcp_check": True,
            "enable_http_check": False,
            "enable_local_check": False,
            "headless": True,
        },
        "profiles": {
            "default": {
                "name": "默认方案",
                "username": "testuser",
                "password": "",  # 测试中按需设置
                "auth_url": "http://10.0.0.1",
                "carrier": "无",
            }
        },
    }
    defaults.update(overrides)
    (config_dir / "settings.json").write_text(
        json.dumps(defaults, ensure_ascii=False, indent=2), encoding="utf-8"
    )


@pytest.fixture
def mock_worker():
    """Mock Playwright worker，模拟 submit 返回 WorkerResponse。"""
    worker = MagicMock()
    worker.submit.return_value = WorkerResponse(success=True, data="登录成功")
    return worker


@pytest.fixture
def integration_stack(tmp_path, mock_worker):
    """创建真实组件栈：ProfileService + TaskExecutor + ScheduleEngine。

    Mock 边界：Playwright worker。
    Returns:
        (engine, profile_service, task_executor, mock_worker)
    """
    _write_initial_config(tmp_path)

    profile_service = ProfileService(tmp_path)
    login_history = LoginHistoryService(tmp_path / "history")
    task_registry = TaskRegistry(tmp_path / "tasks" / "scheduled")
    task_history_store = TaskHistoryStore(tmp_path / "tasks" / "scheduled" / "history")

    task_executor = TaskExecutor(
        registry=task_registry,
        history_store=task_history_store,
        worker_getter=lambda: mock_worker,
    )

    engine = ScheduleEngine(
        project_root=tmp_path,
        profile_service=profile_service,
        ws_manager=None,
        login_history_service=login_history,
        worker_getter=lambda: mock_worker,
        task_registry=task_registry,
        task_executor=task_executor,
    )
    task_executor.set_runtime_config_getter(engine.get_runtime_config)

    orchestrator = LoginOrchestrator(
        worker_getter=lambda: mock_worker,
        login_history=login_history,
        profile_service=profile_service,
        get_runtime_config=engine.get_runtime_config,
    )
    engine._orchestrator = orchestrator
    task_executor._login_orchestrator = orchestrator

    # 启动引擎线程（BUG-007 修复后需要显式调用 boot）
    engine.boot()

    yield engine, profile_service, task_executor, mock_worker

    orchestrator.shutdown(wait=False)

    engine.shutdown()
    task_executor.shutdown()


@pytest.fixture
def full_stack(tmp_path, mock_worker):
    """完整模式组件栈：含 TaskRegistry + TaskHistoryStore。

    Returns:
        (engine, profile_service, task_executor, task_registry, mock_worker)
    """
    _write_initial_config(tmp_path)

    profile_service = ProfileService(tmp_path)
    login_history = LoginHistoryService(tmp_path / "history")
    task_registry = TaskRegistry(tmp_path / "tasks" / "scheduled")
    task_history_store = TaskHistoryStore(tmp_path / "tasks" / "scheduled" / "history")

    task_executor = TaskExecutor(
        registry=task_registry,
        history_store=task_history_store,
        worker_getter=lambda: mock_worker,
    )

    engine = ScheduleEngine(
        project_root=tmp_path,
        profile_service=profile_service,
        ws_manager=None,
        login_history_service=login_history,
        worker_getter=lambda: mock_worker,
        task_registry=task_registry,
        task_executor=task_executor,
    )
    task_executor.set_runtime_config_getter(engine.get_runtime_config)

    orchestrator = LoginOrchestrator(
        worker_getter=lambda: mock_worker,
        login_history=login_history,
        profile_service=profile_service,
        get_runtime_config=engine.get_runtime_config,
    )
    engine._orchestrator = orchestrator
    task_executor._login_orchestrator = orchestrator

    # 启动引擎线程（BUG-007 修复后需要显式调用 boot）
    engine.boot()

    yield engine, profile_service, task_executor, task_registry, mock_worker

    engine.shutdown()
    task_executor.shutdown()
    orchestrator.shutdown(wait=False)
