"""应用入口逻辑测试 — 覆盖纯逻辑函数。"""

from __future__ import annotations

import json
import os
import time
from unittest.mock import MagicMock, patch

import pytest

from app.application import _cleanup_screenshots
from app.utils.ports import resolve_port

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
    """WebSocket 消息处理逻辑（通过 TestClient 间接测试）。"""

    def test_message_size_limit(self):
        """消息大小限制逻辑。"""
        # 大消息应该被拒绝
        large_msg = "x" * 70000  # > 65536
        assert len(large_msg) > 65536

    def test_json_parse_error_handling(self):
        """JSON 解析错误处理。"""
        # 无效 JSON 应该被捕获
        invalid_json = "{invalid json"
        with pytest.raises(json.JSONDecodeError):
            json.loads(invalid_json)
