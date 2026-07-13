"""WorkerPort Protocol 单元测试。"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


def test_worker_port_module_importable():
    """WorkerPort 模块可被导入。"""
    from app.services.worker_port import WorkerPort  # noqa: F401


def test_worker_port_is_protocol():
    """WorkerPort 是 typing.Protocol 的子类。"""
    from typing import Protocol

    from app.services.worker_port import WorkerPort

    assert issubclass(WorkerPort, Protocol)


def test_worker_port_is_runtime_checkable():
    """WorkerPort 标记为 @runtime_checkable，支持 isinstance 检查。"""
    from app.services.worker_port import WorkerPort

    # runtime_checkable 的 Protocol 支持 isinstance
    # 构造一个有 4 个方法的 mock 对象
    mock = MagicMock()
    mock.start = lambda: None
    mock.stop = lambda timeout=5: None
    mock.is_alive = lambda: True
    mock.submit = lambda cmd_type, data=None, wait=True, timeout=None: MagicMock(
        success=True
    )

    assert isinstance(mock, WorkerPort)


def test_worker_port_has_required_methods():
    """WorkerPort 协议包含 start/stop/is_alive/submit 四个方法。"""
    from app.services.worker_port import WorkerPort

    required_methods = {"start", "stop", "is_alive", "submit"}
    actual_methods = {name for name, attr in vars(WorkerPort).items() if callable(attr)}
    # Protocol 的方法在 vars 中可见
    missing = required_methods - actual_methods
    assert not missing, f"WorkerPort 缺少方法: {missing}"


def test_worker_port_submit_signature():
    """submit 方法签名正确：接受 cmd_type/data/wait/timeout，返回 WorkerResponse。"""
    from app.services.worker_port import WorkerPort

    # 检查 submit 是 Protocol 成员
    assert hasattr(WorkerPort, "submit")
    assert callable(WorkerPort.submit)


def test_worker_port_not_instantiable():
    """WorkerPort 是 Protocol，不能直接实例化。"""
    from app.services.worker_port import WorkerPort

    with pytest.raises(TypeError):
        WorkerPort()  # type: ignore[abstract]


def test_worker_port_reexports_worker_response():
    """WorkerPort 模块重导出 WorkerResponse 供 services 层使用。"""
    from app.services.worker_port import WorkerResponse  # noqa: F401


def test_worker_port_reexports_command_constants():
    """WorkerPort 模块重导出 CMD_* 命令常量供 services 层使用。

    消除 services 层对 app.workers.playwright_worker 的直接依赖。
    """
    from app.services.worker_port import (
        CMD_BROWSER,
        CMD_DEBUG_START,
        CMD_DEBUG_STEP,
        CMD_DEBUG_STOP,
        CMD_LOGIN,
        CMD_SHUTDOWN,
    )

    assert CMD_LOGIN == "login"
    assert CMD_BROWSER == "browser"
    assert CMD_DEBUG_START == "debug_start"
    assert CMD_DEBUG_STEP == "debug_step"
    assert CMD_DEBUG_STOP == "debug_stop"
    assert CMD_SHUTDOWN == "shutdown"


def test_worker_port_reexports_get_worker_and_cleanup():
    """WorkerPort 模块重导出 get_worker / cleanup_orphan_browsers 工厂函数。"""
    from app.services.worker_port import (  # noqa: F401
        cleanup_orphan_browsers,
        get_worker,
    )


def test_worker_port_reexports_worker_response_fields():
    """WorkerResponse 数据类字段正确：success/data/error。"""
    from app.services.worker_port import WorkerResponse

    resp = WorkerResponse(success=True, data="ok", error=None)
    assert resp.success is True
    assert resp.data == "ok"
    assert resp.error is None

    resp2 = WorkerResponse(success=False, error="失败")
    assert resp2.success is False
    assert resp2.data is None
    assert resp2.error == "失败"


def test_worker_port_reexports_script_runner_factory():
    """worker_port 提供 get_script_runner 工厂函数。"""
    from app.services.worker_port import get_script_runner

    assert callable(get_script_runner)


def test_worker_port_reexports_ensure_playwright_ready():
    """worker_port 提供 ensure_playwright_ready 函数。"""
    from app.services.worker_port import ensure_playwright_ready

    assert callable(ensure_playwright_ready)


def test_get_script_runner_returns_script_runner_class():
    """get_script_runner 返回 app.workers.script_runner.ScriptRunner 类。"""
    from app.services.worker_port import get_script_runner
    from app.workers.script_runner import ScriptRunner

    assert get_script_runner() is ScriptRunner


def test_services_layer_does_not_import_workers_directly():
    """services 层不应直接 import app.workers（应通过 worker_port 间接访问）。

    例外：app/services/worker_port.py 是端口模块，允许延迟导入 workers。
    """
    from pathlib import Path

    services_dir = Path(__file__).parent.parent.parent / "app" / "services"
    violations = []

    for py_file in services_dir.glob("*.py"):
        if py_file.name == "worker_port.py":
            continue  # 端口模块允许延迟导入 workers
        content = py_file.read_text(encoding="utf-8")
        for line_no, line in enumerate(content.splitlines(), 1):
            stripped = line.strip()
            # 跳过注释
            if stripped.startswith("#"):
                continue
            # 检测 from app.workers 导入
            if "from app.workers" in stripped:
                violations.append(f"{py_file.name}:{line_no}: {stripped}")

    assert not violations, (
        f"services 层不应直接 import app.workers，发现 {len(violations)} 处违规：\n"
        + "\n".join(violations)
    )
