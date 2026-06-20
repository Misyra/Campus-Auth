# tests/test_runtime_config_models.py
"""RuntimeConfig 子集模型的单元测试。"""
from __future__ import annotations

import pytest
from pydantic import ValidationError


def test_browser_settings_frozen():
    """BrowserSettings 不可变。"""
    from app.schemas import BrowserSettings
    bs = BrowserSettings()
    with pytest.raises(ValidationError):
        bs.headless = False


def test_browser_settings_defaults():
    """BrowserSettings 默认值与 SystemSettings 默认值一致。"""
    from app.schemas import BrowserSettings
    bs = BrowserSettings()
    assert bs.headless is True
    assert bs.timeout == 8
    assert bs.navigation_timeout == 15
    assert bs.viewport_width == 1280
    assert bs.viewport_height == 720


def test_login_credentials_required_fields():
    """LoginCredentials 必须有 username/password/auth_url。"""
    from app.schemas import LoginCredentials
    creds = LoginCredentials(username="user", password="pass", auth_url="https://example.com")
    assert creds.isp == ""
    assert creds.carrier_custom == ""


def test_monitor_settings_validation():
    """MonitorSettings 拒绝非法的 check_interval。"""
    from app.schemas import MonitorSettings
    with pytest.raises(ValidationError):
        MonitorSettings(check_interval_seconds=0)  # ge=10


def test_runtime_config_composition():
    """RuntimeConfig 组合所有子模型。"""
    from app.schemas import (
        RuntimeConfig, BrowserSettings, LoginCredentials,
        MonitorSettings, PauseSettings, LoggingSettings, RetrySettings,
    )
    rc = RuntimeConfig(
        browser=BrowserSettings(),
        credentials=LoginCredentials(username="u", password="p", auth_url="https://a.com"),
        monitor=MonitorSettings(),
        pause=PauseSettings(),
        logging=LoggingSettings(),
        retry=RetrySettings(),
    )
    assert rc.browser.headless is True
    assert rc.credentials.username == "u"
    assert rc.active_task is None
    assert rc.custom_variables == {}
    assert rc.block_proxy is False


def test_runtime_config_frozen():
    """RuntimeConfig 整体不可变。"""
    from app.schemas import RuntimeConfig, BrowserSettings, LoginCredentials, MonitorSettings, PauseSettings, LoggingSettings, RetrySettings
    rc = RuntimeConfig(
        browser=BrowserSettings(),
        credentials=LoginCredentials(username="u", password="p", auth_url="https://a.com"),
        monitor=MonitorSettings(),
        pause=PauseSettings(),
        logging=LoggingSettings(),
        retry=RetrySettings(),
    )
    with pytest.raises(ValidationError):
        rc.active_task = "new_task"
