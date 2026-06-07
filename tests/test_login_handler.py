"""登录处理器测试 — 覆盖 LoginAttemptHandler 的核心流程。"""

from __future__ import annotations

import asyncio
import re
import threading
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

from app.utils.login import LoginAttemptHandler, SCREENSHOT_URL_PATTERN


# ── fixtures ──


def _make_config(**overrides):
    """创建测试用配置。"""
    config = {
        "username": "testuser",
        "password": "testpass",
        "auth_url": "http://example.com/login",
        "isp": "中国移动",
        "monitor": {
            "enable_tcp_check": True,
            "enable_http_check": True,
        },
        "pause_login": {"enabled": False},
    }
    config.update(overrides)
    return config


# ── SCREENSHOT_URL_PATTERN ──


class TestScreenshotUrlPattern:
    """截图 URL 正则。"""

    def test_removes_chinese_screenshot_label(self):
        """移除中文截图标签。"""
        msg = "登录成功 截图: /logs/2024-01-01/screenshot.png"
        cleaned = re.sub(SCREENSHOT_URL_PATTERN, "", msg).strip()
        assert cleaned == "登录成功"

    def test_removes_english_screenshot_label(self):
        """移除英文截图标签。"""
        msg = "登录成功 截图: /temp/debug_screenshot.jpg"
        cleaned = re.sub(SCREENSHOT_URL_PATTERN, "", msg).strip()
        assert cleaned == "登录成功"

    def test_no_screenshot_unchanged(self):
        """无截图标签时不变。"""
        msg = "登录成功"
        assert re.sub(SCREENSHOT_URL_PATTERN, "", msg) == "登录成功"


# ── attempt_login 前置检查 ──


class TestAttemptLoginChecks:
    """登录前置检查逻辑。"""

    @pytest.mark.asyncio
    async def test_skip_pause_check(self):
        """skip_pause_check=True 时跳过所有前置检查。"""
        handler = LoginAttemptHandler(_make_config())
        with patch.object(handler, "_perform_login_with_auth_class", new_callable=AsyncMock) as mock_login:
            mock_login.return_value = (True, "登录成功")
            ok, msg = await handler.attempt_login(skip_pause_check=True)
            assert ok is True
            mock_login.assert_called_once()

    @pytest.mark.asyncio
    @patch("app.network.decision.check_pause", return_value=(True, "pause_period"))
    async def test_pause_period_blocks_login(self, mock_pause):
        """暂停时段阻止登录。"""
        handler = LoginAttemptHandler(_make_config())
        ok, msg = await handler.attempt_login(skip_pause_check=False)
        assert ok is False
        assert "暂停" in msg

    @pytest.mark.asyncio
    @patch("app.network.decision.check_pause", return_value=(False, ""))
    @patch("app.network.decision.check_network_status", return_value=(True, "network_ok"))
    async def test_network_ok_skips_login(self, mock_net, mock_pause):
        """网络正常时跳过登录。"""
        handler = LoginAttemptHandler(_make_config())
        ok, msg = await handler.attempt_login(skip_pause_check=False)
        assert ok is False
        assert "网络正常" in msg

    @pytest.mark.asyncio
    @patch("app.network.decision.check_pause", return_value=(False, ""))
    @patch("app.network.decision.check_network_status", return_value=(False, "network_down"))
    @patch("app.network.decision.check_login_prerequisites", return_value=(False, "local_disconnected"))
    async def test_local_disconnected_blocks(self, mock_prereq, mock_net, mock_pause):
        """物理网络断开阻止登录。"""
        handler = LoginAttemptHandler(_make_config())
        ok, msg = await handler.attempt_login(skip_pause_check=False)
        assert ok is False
        assert "物理网络" in msg

    @pytest.mark.asyncio
    @patch("app.network.decision.check_pause", return_value=(False, ""))
    @patch("app.network.decision.check_network_status", return_value=(False, "network_down"))
    @patch("app.network.decision.check_login_prerequisites", return_value=(False, "auth_url_unreachable"))
    async def test_auth_url_unreachable_blocks(self, mock_prereq, mock_net, mock_pause):
        """认证地址不可达阻止登录。"""
        config = _make_config(auth_url="http://auth.example.com")
        handler = LoginAttemptHandler(config)
        ok, msg = await handler.attempt_login(skip_pause_check=False)
        assert ok is False
        assert "不可达" in msg


# ── LoginAttemptHandler 初始化 ──


class TestHandlerInit:
    """处理器初始化。"""

    def test_basic_init(self):
        """基本初始化。"""
        handler = LoginAttemptHandler(_make_config())
        assert handler.config["username"] == "testuser"
        assert handler._browser_ctx is None
        assert handler._task_manager is None

    def test_cancel_event(self):
        """传入取消事件。"""
        event = threading.Event()
        handler = LoginAttemptHandler(_make_config(), cancel_event=event)
        assert handler.cancel_event is event

    def test_close_on_failure_default(self):
        """默认 close_on_failure=True。"""
        handler = LoginAttemptHandler(_make_config())
        assert handler.close_on_failure is True

    def test_close_on_failure_custom(self):
        """自定义 close_on_failure。"""
        handler = LoginAttemptHandler(_make_config(), close_on_failure=False)
        assert handler.close_on_failure is False
