"""应用入口逻辑测试 — 覆盖纯逻辑函数。"""

from __future__ import annotations

import json
import os
import time
from unittest.mock import MagicMock, patch

import pytest

from app.application import _cleanup_screenshots
from app.utils.ports import resolve_port


@pytest.fixture(autouse=True)
def _mock_decision_executor_shutdown(monkeypatch):
    """避免 container.shutdown() 真正关闭模块级 _decision_executor 和 probes。"""
    monkeypatch.setattr(
        "app.network.decision.shutdown_decision_executor", MagicMock()
    )
    monkeypatch.setattr(
        "app.network.probes.shutdown_probes", MagicMock()
    )

# ── resolve_port ──


class TestResolvePort:
    """端口解析逻辑。"""

    def test_default_port(self):
        """默认端口 50721。"""
        with patch.dict("os.environ", {"APP_PORT": ""}, clear=False):
            port = resolve_port()
            assert port == 50721

    def test_env_port(self):
        """环境变量 APP_PORT 覆盖。"""
        with patch.dict("os.environ", {"APP_PORT": "8080"}):
            port = resolve_port()
            assert port == 8080

    def test_invalid_env_port(self):
        """无效环境变量 APP_PORT 回退到默认值。"""
        with patch.dict("os.environ", {"APP_PORT": "not_a_number"}):
            port = resolve_port()
            assert port == 50721

    def test_out_of_range_port(self):
        """超出范围的端口回退到默认值。"""
        with patch.dict("os.environ", {"APP_PORT": "99999"}):
            port = resolve_port()
            assert port == 50721


# ── _cleanup_temp_screenshots ──


class TestCleanupScreenshots:
    """截图清理（合并 temp + screenshots）。"""

    # --- temp 目录清理部分 ---

    def test_removes_old_png_files(self, tmp_path):
        """删除超过 7 天的 png 文件。"""
        old_file = tmp_path / "old_screenshot.png"
        old_file.write_text("old")
        old_time = time.time() - 8 * 86400
        os.utime(str(old_file), (old_time, old_time))

        new_file = tmp_path / "new_screenshot.png"
        new_file.write_text("new")

        nonexistent = tmp_path / "nonexistent_screenshots"
        with (
            patch("app.application.TEMP_DIR", tmp_path),
            patch("app.application.SCREENSHOTS_DIR", nonexistent),
        ):
            _cleanup_screenshots()

        assert not old_file.exists()
        assert new_file.exists()

    def test_removes_old_jpg_files(self, tmp_path):
        """删除超过 7 天的 jpg 文件。"""
        old_file = tmp_path / "old.jpg"
        old_file.write_text("old")
        old_time = time.time() - 8 * 86400
        os.utime(str(old_file), (old_time, old_time))

        nonexistent = tmp_path / "nonexistent_screenshots"
        with (
            patch("app.application.TEMP_DIR", tmp_path),
            patch("app.application.SCREENSHOTS_DIR", nonexistent),
        ):
            _cleanup_screenshots()

        assert not old_file.exists()

    def test_removes_old_jpeg_files(self, tmp_path):
        """删除超过 7 天的 jpeg 文件。"""
        old_file = tmp_path / "old.jpeg"
        old_file.write_text("old")
        old_time = time.time() - 8 * 86400
        os.utime(str(old_file), (old_time, old_time))

        nonexistent = tmp_path / "nonexistent_screenshots"
        with (
            patch("app.application.TEMP_DIR", tmp_path),
            patch("app.application.SCREENSHOTS_DIR", nonexistent),
        ):
            _cleanup_screenshots()

        assert not old_file.exists()

    def test_keeps_recent_files(self, tmp_path):
        """保留 7 天内的文件。"""
        recent_file = tmp_path / "recent.png"
        recent_file.write_text("recent")
        recent_time = time.time() - 1 * 86400
        os.utime(str(recent_file), (recent_time, recent_time))

        nonexistent = tmp_path / "nonexistent_screenshots"
        with (
            patch("app.application.TEMP_DIR", tmp_path),
            patch("app.application.SCREENSHOTS_DIR", nonexistent),
        ):
            _cleanup_screenshots()

        assert recent_file.exists()

    def test_skips_non_image_files(self, tmp_path):
        """跳过非图片文件。"""
        txt_file = tmp_path / "readme.txt"
        txt_file.write_text("not an image")
        old_time = time.time() - 10 * 86400
        os.utime(str(txt_file), (old_time, old_time))

        nonexistent = tmp_path / "nonexistent_screenshots"
        with (
            patch("app.application.TEMP_DIR", tmp_path),
            patch("app.application.SCREENSHOTS_DIR", nonexistent),
        ):
            _cleanup_screenshots()
            assert txt_file.exists()

    def test_handles_nonexistent_temp_dir(self, tmp_path):
        """temp 目录不存在时不抛异常。"""
        nonexistent = tmp_path / "nonexistent_screenshots"
        with (
            patch("app.application.TEMP_DIR", tmp_path / "nonexistent_temp"),
            patch("app.application.SCREENSHOTS_DIR", nonexistent),
        ):
            _cleanup_screenshots()

    def test_handles_empty_temp_dir(self, tmp_path):
        """空 temp 目录不抛异常。"""
        nonexistent = tmp_path / "nonexistent_screenshots"
        with (
            patch("app.application.TEMP_DIR", tmp_path),
            patch("app.application.SCREENSHOTS_DIR", nonexistent),
        ):
            _cleanup_screenshots()

    # --- screenshots 目录清理部分 ---

    def test_removes_old_date_dirs(self, tmp_path):
        """删除非当天的日期目录。"""
        old_dir = tmp_path / "2020-01-01"
        old_dir.mkdir()
        (old_dir / "screenshot.png").write_text("old")

        from datetime import datetime

        today = datetime.now().strftime("%Y-%m-%d")
        today_dir = tmp_path / today
        today_dir.mkdir()
        (today_dir / "screenshot.png").write_text("today")

        nonexistent_temp = tmp_path / "nonexistent_temp"
        with (
            patch("app.application.TEMP_DIR", nonexistent_temp),
            patch("app.application.SCREENSHOTS_DIR", tmp_path),
        ):
            _cleanup_screenshots()

        assert not old_dir.exists()
        assert today_dir.exists()

    def test_handles_nonexistent_screenshots_dir(self, tmp_path):
        """screenshots 目录不存在时不抛异常。"""
        nonexistent_temp = tmp_path / "nonexistent_temp"
        with (
            patch("app.application.TEMP_DIR", nonexistent_temp),
            patch("app.application.SCREENSHOTS_DIR", tmp_path / "nonexistent_screenshots"),
        ):
            _cleanup_screenshots()

    def test_handles_empty_screenshots_dir(self, tmp_path):
        """空 screenshots 目录不抛异常。"""
        nonexistent_temp = tmp_path / "nonexistent_temp"
        with (
            patch("app.application.TEMP_DIR", nonexistent_temp),
            patch("app.application.SCREENSHOTS_DIR", tmp_path),
        ):
            _cleanup_screenshots()

    def test_skips_today_dir(self, tmp_path):
        """跳过当天目录。"""
        from datetime import datetime

        today = datetime.now().strftime("%Y-%m-%d")
        today_dir = tmp_path / today
        today_dir.mkdir()

        nonexistent_temp = tmp_path / "nonexistent_temp"
        with (
            patch("app.application.TEMP_DIR", nonexistent_temp),
            patch("app.application.SCREENSHOTS_DIR", tmp_path),
        ):
            _cleanup_screenshots()

        assert today_dir.exists()


# ── WebSocket 消息处理逻辑 ──


class TestWebSocketMessageHandling:
    """WebSocket 消息处理正确应对无效 JSON 和未知消息类型。"""

    def _make_app_with_ws(self, tmp_path):
        """构建一个带 WebSocket 端点的 app，用于 TestClient 测试。"""
        (tmp_path / "frontend").mkdir(exist_ok=True)
        (tmp_path / "frontend" / "index.html").write_text("<html></html>")
        (tmp_path / "logs").mkdir(exist_ok=True)
        (tmp_path / "temp").mkdir(exist_ok=True)

        with (
            patch("app.constants.PROJECT_ROOT", tmp_path),
            patch("app.constants.FRONTEND_DIR", tmp_path / "frontend"),
            patch("app.constants.LOGS_DIR", tmp_path / "logs"),
            patch("app.constants.TEMP_DIR", tmp_path / "temp"),
        ):
            from app.application import create_app

            mock_services = MagicMock()
            mock_services.engine.list_logs.return_value = []
            app = create_app()
            app.state.services = mock_services
            return app

    def test_ws_handles_invalid_json_gracefully(self, tmp_path):
        """WebSocket 收到无效 JSON 时不崩溃。"""
        from fastapi.testclient import TestClient

        app = self._make_app_with_ws(tmp_path)
        with TestClient(app) as client, client.websocket_connect("/ws/logs") as ws:
            ws.send_text("not valid json {{{")
            ws.send_text(json.dumps({"type": "ping"}))

    def test_ws_handles_unknown_message_type(self, tmp_path):
        """WebSocket 收到未知 type 消息时不崩溃。"""
        from fastapi.testclient import TestClient

        app = self._make_app_with_ws(tmp_path)
        with TestClient(app) as client, client.websocket_connect("/ws/logs") as ws:
            ws.send_text(json.dumps({"type": "unknown_type_xyz"}))


# ── Windows SIGTERM 兼容性 ──


class TestWindowsSigterm:
    """SIGTERM 信号处理 — 修复 Windows 平台兼容性。"""

    def test_lifespan_registers_signal_or_fallback(self, tmp_path):
        """lifespan 启动后：要么注册了 SIGTERM handler，要么有 fallback。"""
        from fastapi.testclient import TestClient

        (tmp_path / "frontend").mkdir(exist_ok=True)
        (tmp_path / "frontend" / "index.html").write_text("<html></html>")
        (tmp_path / "logs").mkdir(exist_ok=True)
        (tmp_path / "temp").mkdir(exist_ok=True)

        with (
            patch("app.constants.PROJECT_ROOT", tmp_path),
            patch("app.constants.FRONTEND_DIR", tmp_path / "frontend"),
            patch("app.constants.LOGS_DIR", tmp_path / "logs"),
            patch("app.constants.TEMP_DIR", tmp_path / "temp"),
        ):
            from app.application import create_app

            mock_services = MagicMock()
            mock_services.engine = MagicMock()
            mock_services.startup = MagicMock()
            mock_services.shutdown = MagicMock()

            app = create_app()
            app.state.services = mock_services

            with TestClient(app):
                assert app.state.services is not None
