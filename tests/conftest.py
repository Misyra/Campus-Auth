"""Campus-Auth 测试配置"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# 确保项目根目录在 sys.path 中
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ── 无显示服务器环境（CI）下 mock pystray ─────────────────
# pystray 在 Linux/macOS 上需要 GUI 后端，CI 环境中没有可用显示
if sys.platform != "win32":
    _pystray_mock = MagicMock()
    sys.modules["pystray"] = _pystray_mock


# ── app.py 相关 fixtures ──────────────────────────────────────────────


@pytest.fixture
def tmp_pid_dir(tmp_path: Path, monkeypatch):
    """创建临时 PID 目录，monkeypatch AUTH_DATA_DIR 指向它。"""
    pid_dir = tmp_path / "pid_data"
    pid_dir.mkdir()
    monkeypatch.setattr("app.utils.process.AUTH_DATA_DIR", pid_dir)
    monkeypatch.setattr("main.AUTH_DATA_DIR", pid_dir)
    return pid_dir


@pytest.fixture
def patched_signal_handlers():
    """Mock signal.signal()，记录注册的 handlers。"""
    handlers: dict[int, object] = {}

    def _fake_signal(signum, handler):
        handlers[signum] = handler
        return handler

    with patch("signal.signal", side_effect=_fake_signal):
        yield handlers


@pytest.fixture
def patched_webbrowser():
    """Mock webbrowser.open() 阻止真实打开浏览器。"""
    with patch("webbrowser.open") as mock_open:
        yield mock_open


@pytest.fixture
def patched_uvicorn_run():
    """Mock uvicorn.run() 阻止真实启动服务。"""
    with patch("uvicorn.run") as mock_run:
        yield mock_run
