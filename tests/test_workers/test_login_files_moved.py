"""Task 2.2: 验证 login_models/login_attempt/login_session 已从 services 移动到 workers。"""

import importlib
from pathlib import Path

import pytest


def test_login_models_in_workers():
    """login_models 模块位于 app.workers.login_models。"""
    mod = importlib.import_module("app.workers.login_models")
    assert hasattr(mod, "AttemptOutcomeType")
    assert hasattr(mod, "AttemptOutcome")
    assert hasattr(mod, "LoginRetryPolicy")


def test_login_attempt_in_workers():
    """login_attempt 模块位于 app.workers.login_attempt。"""
    mod = importlib.import_module("app.workers.login_attempt")
    assert hasattr(mod, "LoginAttempt")


def test_login_session_in_workers():
    """login_session 模块位于 app.workers.login_session。"""
    mod = importlib.import_module("app.workers.login_session")
    assert hasattr(mod, "LoginSession")


def test_login_models_not_in_services():
    """app.services.login_models 不再存在。"""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("app.services.login_models")


def test_login_attempt_not_in_services():
    """app.services.login_attempt 不再存在。"""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("app.services.login_attempt")


def test_login_session_not_in_services():
    """app.services.login_session 不再存在。"""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("app.services.login_session")


def test_playwright_worker_imports_from_workers():
    """playwright_worker 不再从 app.services 导入 login_*。"""
    worker_file = (
        Path(__file__).parent.parent.parent / "app" / "workers" / "playwright_worker.py"
    )
    content = worker_file.read_text(encoding="utf-8")
    assert "app.services.login_models" not in content
    assert "app.services.login_session" not in content
    assert "app.services.login_attempt" not in content
