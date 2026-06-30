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
# 使用 autouse session 级 fixture，会话结束后恢复 sys.modules，避免全局污染。
@pytest.fixture(autouse=True, scope="session")
def _mock_pystray_headless():
    """无显示服务器环境下 mock pystray，会话结束后恢复 sys.modules。

    替代原模块级 sys.modules 赋值：原写法在收集阶段即污染全局且无 finalizer；
    此 fixture 以 session 级 autouse 应用，会话结束 try/finally 恢复原始状态。
    """
    if sys.platform == "win32":
        yield
        return
    original = sys.modules.get("pystray")
    sys.modules["pystray"] = MagicMock()
    try:
        yield
    finally:
        if original is None:
            sys.modules.pop("pystray", None)
        else:
            sys.modules["pystray"] = original


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