"""launcher.py 基础测试。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestShutdownContainer:
    """shutdown_container 幂等性测试。"""

    def test_shutdown_calls_asyncio_run(self):
        """shutdown_container 应调用 asyncio.run。"""
        from app.services.launcher import shutdown_container

        mock_container = MagicMock()

        with (
            patch("app.services.launcher.asyncio.run") as mock_run,
            patch("app.services.launcher.asyncio.wait_for"),
        ):
            shutdown_container(mock_container, MagicMock())
            mock_run.assert_called_once()

    def test_shutdown_idempotent(self):
        """重复调用 shutdown_container 不应报错。"""
        from app.services.launcher import shutdown_container

        mock_container = MagicMock()
        logger = MagicMock()

        with (
            patch("app.services.launcher.asyncio.run"),
            patch("app.services.launcher.asyncio.wait_for"),
        ):
            shutdown_container(mock_container, logger)
            shutdown_container(mock_container, logger)


class TestOpenBrowser:
    """open_browser 测试。"""

    def test_no_open_when_setting_false(self):
        """setting=False 时不打开浏览器。"""
        from app.services.launcher import open_browser

        with patch("app.services.launcher.webbrowser.open") as mock_open:
            open_browser(8080, setting=False)
            mock_open.assert_not_called()

    def test_no_open_when_setting_none(self):
        """setting=None 时不打开浏览器。"""
        from app.services.launcher import open_browser

        with patch("app.services.launcher.webbrowser.open") as mock_open:
            open_browser(8080, setting=None)
            mock_open.assert_not_called()
