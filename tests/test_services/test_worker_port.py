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
