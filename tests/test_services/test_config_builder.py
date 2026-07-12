"""build_runtime_config 单元测试 — carrier→isp 转换、密码过滤、字段完整性。"""

from __future__ import annotations

import pytest

from app.schemas import (
    AppSettings,
    BrowserSettings,
    GlobalConfig,
    MonitorSettings,
    Profile,
)
from app.services.config_builder import build_runtime_config

# ── helper ──


def _default_global_config(**overrides) -> GlobalConfig:
    """创建默认 GlobalConfig，支持覆盖部分字段。

    app_settings 字段接受 AppSettings 实例。
    """
    return GlobalConfig(**overrides)


def _default_profile(**overrides) -> Profile:
    """创建默认 Profile，支持覆盖部分字段。"""
    return Profile(**overrides)


# ── ISP 转换 ──


class TestCarrierToIsp:
    """carrier → isp 转换逻辑（全项目唯一入口）。"""

    def test_carrier_custom_uses_carrier_custom(self):
        profile = _default_profile(carrier="自定义", carrier_custom="校园网ISP")
        rc = build_runtime_config(_default_global_config(), profile)
        assert rc.credentials.isp == "校园网ISP"
        assert rc.credentials.carrier_custom == "校园网ISP"

    def test_carrier_none_results_in_empty_isp(self):
        profile = _default_profile(carrier="无")
        rc = build_runtime_config(_default_global_config(), profile)
        assert rc.credentials.isp == ""
        assert rc.credentials.carrier_custom == ""

    def test_carrier_known_name_passes_through(self):
        profile = _default_profile(carrier="中国移动")
        rc = build_runtime_config(_default_global_config(), profile)
        assert rc.credentials.isp == "中国移动"

    def test_carrier_china_unicom(self):
        profile = _default_profile(carrier="中国联通")
        rc = build_runtime_config(_default_global_config(), profile)
        assert rc.credentials.isp == "中国联通"

    def test_carrier_china_telecom(self):
        profile = _default_profile(carrier="中国电信")
        rc = build_runtime_config(_default_global_config(), profile)
        assert rc.credentials.isp == "中国电信"

    def test_carrier_empty_string_treated_as_none(self):
        profile = _default_profile(carrier="")
        rc = build_runtime_config(_default_global_config(), profile)
        assert rc.credentials.isp == ""

    def test_carrier_whitespace_only_treated_as_none(self):
        profile = _default_profile(carrier="   ")
        rc = build_runtime_config(_default_global_config(), profile)
        assert rc.credentials.isp == ""

    def test_custom_carrier_ignores_known_name(self):
        """carrier='自定义' 时只使用 carrier_custom，即使 carrier_custom 为空。"""
        profile = _default_profile(carrier="自定义", carrier_custom="")
        rc = build_runtime_config(_default_global_config(), profile)
        assert rc.credentials.isp == ""


# ── 密码过滤 ──


class TestPasswordFiltering:
    """密码中 "•" 前缀表示掩码，应被过滤为空。"""

    def test_masked_password_becomes_empty(self):
        profile = _default_profile(password="••••••")
        rc = build_runtime_config(_default_global_config(), profile)
        assert rc.credentials.password == ""

    def test_plaintext_password_preserved(self):
        profile = _default_profile(password="mysecret123")
        rc = build_runtime_config(_default_global_config(), profile)
        assert rc.credentials.password == "mysecret123"

    def test_empty_password_stays_empty(self):
        profile = _default_profile(password="")
        rc = build_runtime_config(_default_global_config(), profile)
        assert rc.credentials.password == ""

    def test_whitespace_only_password_stays_empty(self):
        profile = _default_profile(password="   ")
        rc = build_runtime_config(_default_global_config(), profile)
        assert rc.credentials.password == ""

    def test_single_dot_prefix_is_masked(self):
        """单个 "•" 开头即视为掩码。"""
        profile = _default_profile(password="•")
        rc = build_runtime_config(_default_global_config(), profile)
        assert rc.credentials.password == ""

    def test_dot_prefix_with_content_is_masked(self):
        profile = _default_profile(password="•actual_password")
        rc = build_runtime_config(_default_global_config(), profile)
        assert rc.credentials.password == ""


# ── 字段完整性 ──


class TestFieldCompleteness:
    """所有 global_config 字段都应传递到 RuntimeConfig。"""

    def test_browser_passed_through(self):
        browser = BrowserSettings(headless=False, timeout=15)
        gc = _default_global_config(browser=browser)
        rc = build_runtime_config(gc, _default_profile())
        assert rc.browser is browser

    def test_monitor_passed_through(self):
        monitor = MonitorSettings(check_interval_seconds=600)
        gc = _default_global_config(monitor=monitor)
        rc = build_runtime_config(gc, _default_profile())
        assert rc.monitor is monitor

    def test_all_direct_fields_passed(self):
        gc = _default_global_config(
            app_settings=AppSettings(
                block_proxy=False,
                minimize_to_tray=False,
                startup_action="monitor",
                runtime_mode="lightweight",
                lightweight_tray=False,
                auto_open_browser=True,
                proxy="http://proxy:8080",
                app_port=12345,
            ),
        )
        rc = build_runtime_config(gc, _default_profile())
        assert rc.app_settings.block_proxy is False
        assert rc.app_settings.minimize_to_tray is False
        assert rc.app_settings.startup_action == "monitor"
        assert rc.app_settings.runtime_mode == "lightweight"
        assert rc.app_settings.lightweight_tray is False
        assert rc.app_settings.auto_open_browser is True
        assert rc.app_settings.proxy == "http://proxy:8080"
        assert rc.app_settings.app_port == 12345

    def test_credentials_structure(self):
        profile = _default_profile(
            username="  user1  ",
            password="pass123",
            auth_url="  http://example.com  ",
            carrier="中国移动",
            carrier_custom="custom_isp",
        )
        rc = build_runtime_config(_default_global_config(), profile)
        cred = rc.credentials
        assert cred.username == "user1"
        assert cred.password == "pass123"
        assert cred.auth_url == "http://example.com"
        assert cred.isp == "中国移动"
        assert cred.carrier_custom == "custom_isp"


# ── active_task 传递 ──


class TestActiveTask:
    """active_task 应从 profile 传递到 RuntimeConfig。"""

    def test_active_task_from_profile(self):
        profile = _default_profile(active_task="run_script")
        rc = build_runtime_config(_default_global_config(), profile)
        assert rc.active_task == "run_script"

    def test_active_task_empty_default(self):
        rc = build_runtime_config(_default_global_config(), _default_profile())
        assert rc.active_task == ""

    def test_active_task_whitespace_stripped(self):
        profile = _default_profile(active_task="  monitor  ")
        rc = build_runtime_config(_default_global_config(), profile)
        assert rc.active_task == "monitor"


# ── 端到端组合场景 ──


class TestEndToEnd:
    """组合场景验证。"""

    def test_full_build_with_all_custom_values(self):
        """所有字段都自定义时，RuntimeConfig 完整反映设置。"""
        gc = _default_global_config(
            app_settings=AppSettings(
                block_proxy=False,
                minimize_to_tray=False,
                startup_action="login_once",
                runtime_mode="lightweight",
                lightweight_tray=False,
                auto_open_browser=True,
                proxy="socks5://127.0.0.1:1080",
                app_port=9999,
            ),
        )
        profile = _default_profile(
            username="student",
            password="realpass",
            auth_url="http://auth.example.com",
            carrier="自定义",
            carrier_custom="CampusNet",
            active_task="login_once",
        )
        rc = build_runtime_config(gc, profile)

        assert rc.credentials.username == "student"
        assert rc.credentials.password == "realpass"
        assert rc.credentials.auth_url == "http://auth.example.com"
        assert rc.credentials.isp == "CampusNet"
        assert rc.credentials.carrier_custom == "CampusNet"
        assert rc.active_task == "login_once"
        assert rc.app_settings.block_proxy is False
        assert rc.app_settings.proxy == "socks5://127.0.0.1:1080"
        assert rc.app_settings.app_port == 9999

    def test_build_returns_frozen_model(self):
        """RuntimeConfig 是 frozen 的，不允许修改。"""
        rc = build_runtime_config(_default_global_config(), _default_profile())
        with pytest.raises(Exception):  # ValidationError from pydantic
            rc.active_task = "modified"
