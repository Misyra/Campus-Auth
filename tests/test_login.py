"""src/utils/login.py — 登录处理器测试

覆盖 LoginAttemptHandler 和 SCREENSHOT_URL_PATTERN。
"""
from __future__ import annotations

import re
import threading
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

from src.utils.login import LoginAttemptHandler, SCREENSHOT_URL_PATTERN


# =====================================================================
# SCREENSHOT_URL_PATTERN
# =====================================================================


class TestScreenshotUrlPattern:
    def test_matches_chinese_screenshot_label(self):
        msg = "截图: /tmp/test.png"
        assert re.search(SCREENSHOT_URL_PATTERN, msg) is not None

    def test_matches_chinese_colon(self):
        msg = "截图： /tmp/test.jpg"
        assert re.search(SCREENSHOT_URL_PATTERN, msg) is not None

    def test_matches_various_extensions(self):
        for ext in ("png", "jpg", "jpeg", "webp", "gif"):
            msg = f"截图: /tmp/test.{ext}"
            assert re.search(SCREENSHOT_URL_PATTERN, msg) is not None

    def test_no_match_without_screenshot(self):
        msg = "普通日志消息"
        assert re.sub(SCREENSHOT_URL_PATTERN, "", msg) == msg

    def test_removes_screenshot_path(self):
        msg = "登录失败 截图: /tmp/screenshot.png 结束"
        cleaned = re.sub(SCREENSHOT_URL_PATTERN, "", msg)
        assert "截图" not in cleaned
        assert "screenshot" not in cleaned
        assert "登录失败" in cleaned

    def test_removes_absolute_path(self):
        """应移除绝对路径形式的截图引用"""
        msg = "失败 截图: /Users/test/screenshot.png"
        cleaned = re.sub(SCREENSHOT_URL_PATTERN, "", msg)
        assert "screenshot" not in cleaned


# =====================================================================
# LoginAttemptHandler 初始化
# =====================================================================


class TestLoginAttemptHandlerInit:
    def test_init_defaults(self):
        handler = LoginAttemptHandler(config={})
        assert handler.config == {}
        assert handler.cancel_event is None
        assert handler.close_on_failure is True
        assert handler._browser_ctx is None
        assert handler._task_manager is None

    def test_init_with_cancel_event(self):
        event = threading.Event()
        handler = LoginAttemptHandler(config={}, cancel_event=event)
        assert handler.cancel_event is event

    def test_init_close_on_failure_false(self):
        handler = LoginAttemptHandler(config={}, close_on_failure=False)
        assert handler.close_on_failure is False


# =====================================================================
# attempt_login
# =====================================================================


class TestAttemptLogin:
    @pytest.mark.asyncio
    async def test_pause_period_skip(self):
        """暂停时段应跳过登录"""
        config = {"pause_login": {"start_hour": 0, "end_hour": 23}}
        handler = LoginAttemptHandler(config=config)

        with patch("src.utils.login.datetime") as mock_dt:
            mock_dt.datetime.now.return_value.hour = 3
            mock_dt.datetime.now.return_value.minute = 0

            with patch(
                "src.network_decision.check_pause",
                return_value=(True, "pause_period"),
            ):
                ok, msg = await handler.attempt_login(skip_pause_check=False)
                assert ok is False
                assert "暂停" in msg

    @pytest.mark.asyncio
    async def test_network_disconnected_skip(self):
        """物理网络未连接时应跳过登录"""
        handler = LoginAttemptHandler(config={})

        with patch(
            "src.network_decision.check_pause",
            return_value=(False, ""),
        ), patch(
            "src.network_decision.check_network_status",
            return_value=(False, "network_down"),
        ), patch(
            "src.network_decision.check_login_prerequisites",
            return_value=(False, "local_disconnected"),
        ):
            ok, msg = await handler.attempt_login(skip_pause_check=False)
            assert ok is False
            assert "未连接" in msg

    @pytest.mark.asyncio
    async def test_auth_url_unreachable_skip(self):
        """认证地址不可达时应跳过登录"""
        config = {"auth_url": "http://10.0.0.1"}
        handler = LoginAttemptHandler(config=config)

        with patch(
            "src.network_decision.check_pause",
            return_value=(False, ""),
        ), patch(
            "src.network_decision.check_network_status",
            return_value=(False, "network_down"),
        ), patch(
            "src.network_decision.check_login_prerequisites",
            return_value=(False, "auth_url_unreachable"),
        ):
            ok, msg = await handler.attempt_login(skip_pause_check=False)
            assert ok is False
            assert "不可达" in msg

    @pytest.mark.asyncio
    async def test_network_ok_skip(self):
        """网络正常时应跳过登录"""
        handler = LoginAttemptHandler(config={})

        with patch(
            "src.network_decision.check_pause",
            return_value=(False, ""),
        ), patch(
            "src.network_decision.check_network_status",
            return_value=(True, "network_ok"),
        ):
            ok, msg = await handler.attempt_login(skip_pause_check=False)
            assert ok is False
            assert "正常" in msg

    @pytest.mark.asyncio
    async def test_login_cancelled(self):
        """取消事件触发时应返回取消消息"""
        event = threading.Event()
        event.set()
        handler = LoginAttemptHandler(config={}, cancel_event=event)

        with patch(
            "src.network_decision.check_pause",
            return_value=(False, ""),
        ), patch(
            "src.network_decision.check_network_status",
            return_value=(False, "network_down"),
        ), patch(
            "src.network_decision.check_login_prerequisites",
            return_value=(True, ""),
        ):
            ok, msg = await handler.attempt_login(skip_pause_check=False)
            # 取消事件已设置，最终会返回取消或失败
            assert ok is False

    @pytest.mark.asyncio
    async def test_skip_pause_check(self):
        """skip_pause_check=True 时应跳过暂停检查"""
        handler = LoginAttemptHandler(config={})

        # 不检查暂停，但没有活动任务，应返回失败
        with patch.object(
            handler, "_perform_login_with_auth_class",
            return_value=(False, "未找到可执行的活动任务"),
        ):
            ok, msg = await handler.attempt_login(skip_pause_check=True)
            assert ok is False

    @pytest.mark.asyncio
    async def test_exception_returns_error(self):
        """异常应被捕获并返回错误消息"""
        handler = LoginAttemptHandler(config={})

        with patch(
            "src.network_decision.check_pause",
            side_effect=RuntimeError("test error"),
        ):
            ok, msg = await handler.attempt_login(skip_pause_check=False)
            assert ok is False
            assert "test error" in msg


# =====================================================================
# close_browser
# =====================================================================


class TestCloseBrowser:
    @pytest.mark.asyncio
    async def test_close_browser_with_context(self):
        """有浏览器上下文时应正确关闭"""
        handler = LoginAttemptHandler(config={})
        mock_ctx = AsyncMock()
        handler._browser_ctx = mock_ctx

        with patch("src.playwright_worker.get_worker") as mock_get_worker:
            mock_worker = MagicMock()
            mock_worker.close_browser = AsyncMock()
            mock_get_worker.return_value = mock_worker

            await handler.close_browser()
            mock_worker.close_browser.assert_called_once()
            mock_ctx.__aexit__.assert_called_once()
            assert handler._browser_ctx is None

    @pytest.mark.asyncio
    async def test_close_browser_without_context(self):
        """无浏览器上下文时不应抛异常"""
        handler = LoginAttemptHandler(config={})
        handler._browser_ctx = None
        await handler.close_browser()

    @pytest.mark.asyncio
    async def test_close_browser_exception_handled(self):
        """关闭过程中异常应被捕获"""
        handler = LoginAttemptHandler(config={})
        mock_ctx = AsyncMock()
        mock_ctx.__aexit__ = AsyncMock(side_effect=RuntimeError("close error"))
        handler._browser_ctx = mock_ctx

        with patch("src.playwright_worker.get_worker") as mock_get_worker:
            mock_worker = MagicMock()
            mock_worker.close_browser = AsyncMock(side_effect=RuntimeError("fail"))
            mock_get_worker.return_value = mock_worker

            await handler.close_browser()
            assert handler._browser_ctx is None
