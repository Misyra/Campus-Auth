"""BrowserTaskService 测试 — 通用浏览器自动化服务。"""

from unittest.mock import MagicMock

from app.services.browser_task_service import BrowserTaskHandle, BrowserTaskService


def test_browser_task_service_can_be_instantiated():
    """BrowserTaskService 可用 worker_getter + executor 构造。"""
    svc = BrowserTaskService(
        worker_getter=MagicMock(),
        executor=MagicMock(),
    )
    assert svc is not None


def test_submit_task_returns_handle():
    """submit_task 返回 BrowserTaskHandle，rejected_reason 为 None。"""
    svc = BrowserTaskService(
        worker_getter=MagicMock(),
        executor=MagicMock(),
    )
    handle = svc.submit_task(
        task_config={"active_task": "test_task"}, cancel_event=None
    )
    assert isinstance(handle, BrowserTaskHandle)
    assert handle.rejected_reason is None
