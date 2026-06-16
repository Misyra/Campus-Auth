"""浏览器注册表测试。"""

from app.utils.browser_registry import BrowserInfo, detect_browsers


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
        icon="test-icon",
        installed=True,
        needs_download=False,
        description="测试浏览器"
    )
    assert info.channel == "test"
    assert info.name == "Test Browser"
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
