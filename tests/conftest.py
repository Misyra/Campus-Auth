"""Campus-Auth 测试配置"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# 确保项目根目录在 sys.path 中
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ── 无显示服务器环境（CI）下 mock pystray ─────────────────
# pystray 在 Linux/macOS 上需要 GUI 后端，CI 环境中没有可用显示。
# 使用 function 级 opt-in fixture，测试需要时通过参数注入。
@pytest.fixture
def mock_pystray(monkeypatch):
    """无显示服务器环境下 mock pystray。

    Windows 上为 no-op；Linux/macOS 上 mock pystray.Icon。
    测试需要时通过参数注入：def test_xxx(mock_pystray): ...
    """
    if sys.platform == "win32":
        return
    monkeypatch.setattr("pystray.Icon", MagicMock())


@pytest.fixture
def tmp_pid_dir(tmp_path: Path, monkeypatch):
    """创建临时 PID 目录，monkeypatch AUTH_DATA_DIR 指向它。"""
    pid_dir = tmp_path / "pid_data"
    pid_dir.mkdir()
    monkeypatch.setattr("app.utils.process.AUTH_DATA_DIR", pid_dir)
    return pid_dir


@pytest.fixture
def patched_webbrowser():
    """Mock webbrowser.open() 阻止真实打开浏览器。"""
    with patch("webbrowser.open") as mock_open:
        yield mock_open