from __future__ import annotations

import asyncio
from unittest.mock import patch, AsyncMock

from src.utils.login import LoginAttemptHandler


class TestLoginAttemptHandlerInit:

    def test_default_config(self):
        handler = LoginAttemptHandler({})
        assert handler.config == {}
        assert handler.cancel_event is None

    def test_with_cancel_event(self):
        import threading
        evt = threading.Event()
        handler = LoginAttemptHandler({}, cancel_event=evt)
        assert handler.cancel_event is evt


class TestPausePeriod:

    def test_skip_pause_check(self):
        handler = LoginAttemptHandler({})
        async def run():
            with patch.object(handler, "_perform_login_with_auth_class", new_callable=AsyncMock) as mock:
                mock.return_value = (True, "success")
                return await handler.attempt_login(skip_pause_check=True)
        success, msg = asyncio.get_event_loop().run_until_complete(run())
        assert success is True

    def test_in_pause_period(self):
        config = {
            "pause_login": {"enabled": True, "start_hour": 0, "end_hour": 23},
        }
        handler = LoginAttemptHandler(config)
        with patch("src.utils.login.TimeUtils.is_in_pause_period", return_value=True):
            async def run():
                return await handler.attempt_login(skip_pause_check=False)
            success, msg = asyncio.get_event_loop().run_until_complete(run())
            assert success is False
            assert "暂停登录时段" in msg


class TestBuildNetworkTestConfig:

    def test_default(self):
        handler = LoginAttemptHandler({})
        cfg = handler._build_network_test_config()
        assert "test_sites" in cfg
        assert "timeout" in cfg
        assert "strict_mode" in cfg

    def test_custom_targets_string(self):
        config = {"monitor": {"ping_targets": "8.8.8.8:53"}}
        handler = LoginAttemptHandler(config)
        cfg = handler._build_network_test_config()
        assert cfg["test_sites"] == [("8.8.8.8", 53)]

    def test_custom_targets_list(self):
        config = {"monitor": {"ping_targets": ["1.1.1.1:443"]}}
        handler = LoginAttemptHandler(config)
        cfg = handler._build_network_test_config()
        assert cfg["test_sites"] == [("1.1.1.1", 443)]


class TestCloseBrowser:

    def test_close_when_no_browser(self):
        handler = LoginAttemptHandler({})
        async def run():
            await handler.close_browser()
        asyncio.get_event_loop().run_until_complete(run())
        assert handler._browser_ctx is None
