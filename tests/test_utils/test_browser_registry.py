"""浏览器注册表测试。"""

from pathlib import Path
from unittest.mock import patch

from app.utils.browser_registry import (
    BrowserInfo,
    _detect_edge,
    _edge_path,
    detect_browsers,
)


def test_detect_browsers_returns_list():
    """detect_browsers 应返回 BrowserInfo 列表。"""
    result = detect_browsers()
    assert isinstance(result, list)
    assert all(isinstance(b, BrowserInfo) for b in result)


def test_browser_info_fields():
    """BrowserInfo 应包含必要字段。"""
    info = BrowserInfo(
        channel="test",
        name="Test Browser",
        icon="/api/icons/test.svg",
        installed=True,
        needs_download=False,
        description="测试浏览器",
    )
    assert info.channel == "test"
    assert info.name == "Test Browser"
    assert info.icon == "/api/icons/test.svg"
    assert info.installed is True
    assert info.needs_download is False


def test_detect_browsers_contains_all_options():
    """detect_browsers 应返回 5 种浏览器选项。"""
    result = detect_browsers()
    channels = [b.channel for b in result]
    assert "playwright" in channels
    assert "msedge" in channels
    assert "chrome" in channels
    assert "firefox" in channels
    assert "custom" in channels
    assert len(channels) == 5


def test_edge_path_returns_x86_path_when_exists():
    """_edge_path 应优先返回 PROGRAMFILES(x86) 路径。"""
    fake_x86 = Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe")
    with (
        patch.dict(
            "os.environ",
            {
                "PROGRAMFILES(x86)": "C:/Program Files (x86)",
                "PROGRAMFILES": "C:/Program Files",
            },
        ),
        patch.object(Path, "exists", return_value=True),
    ):
        result = _edge_path()
        assert result == fake_x86


def test_edge_path_returns_none_when_not_found():
    """_edge_path 在两个路径都不存在时应返回 None。"""
    with (
        patch.dict(
            "os.environ",
            {
                "PROGRAMFILES(x86)": "C:/Program Files (x86)",
                "PROGRAMFILES": "C:/Program Files",
            },
        ),
        patch.object(Path, "exists", return_value=False),
    ):
        result = _edge_path()
        assert result is None


@patch("app.utils.browser_registry._edge_path")
@patch("app.utils.browser_registry.PLATFORM", "windows")
def test_detect_edge_windows_with_executable(mock_edge_path):
    """Windows 上 _edge_path 返回路径时 Edge 应标记为已安装。"""
    mock_edge_path.return_value = Path(
        "C:/Program Files/Microsoft/Edge/Application/msedge.exe"
    )
    info = _detect_edge()
    assert info.installed is True
    mock_edge_path.assert_called_once()


@patch("app.utils.browser_registry._edge_path")
@patch("app.utils.browser_registry.PLATFORM", "windows")
def test_detect_edge_windows_without_executable(mock_edge_path):
    """Windows 上 _edge_path 返回 None 时 Edge 应标记为未安装。"""
    mock_edge_path.return_value = None
    with patch("app.utils.browser_registry._check_command_exists", return_value=False):
        info = _detect_edge()
        assert info.installed is False
