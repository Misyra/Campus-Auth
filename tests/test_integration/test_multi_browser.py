"""多浏览器支持集成测试。"""

import pytest

from app.schemas import GlobalSettings, MonitorConfigPayload
from app.services.config_service import build_runtime_config
from app.utils.browser_registry import detect_browsers


def test_global_settings_default_channel():
    """GlobalSettings 默认 browser_channel 应为 playwright。"""
    gs = GlobalSettings()
    assert gs.browser_channel == "playwright"
    assert gs.browser_custom_path == ""


def test_build_runtime_config_includes_channel():
    """build_runtime_config 应包含 browser_channel。"""
    gs = GlobalSettings()
    gs.browser_channel = "msedge"
    payload = MonitorConfigPayload()
    config = build_runtime_config(payload, gs)
    assert config["browser_settings"]["browser_channel"] == "msedge"


def test_detect_browsers_returns_all_channels():
    """detect_browsers 应返回所有 5 种浏览器选项。"""
    browsers = detect_browsers()
    channels = [b.channel for b in browsers]
    assert len(channels) == 5
    assert "playwright" in channels
    assert "msedge" in channels
    assert "chrome" in channels
    assert "firefox" in channels
    assert "custom" in channels
