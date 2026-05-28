"""系统服务模块综合测试

合并原 test_autostart_service.py 和 test_uninstall_service.py。
覆盖 AutoStartService（自启动）和卸载清理服务。
"""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from backend.autostart_service import AutoStartService
from backend.uninstall_service import (
    CleanupItem,
    CleanupResult,
    detect,
    perform,
    _playwright_cache_dir,
    _dir_size_mb,
    _check_autostart,
)


# ─────────────────────────────────────────────────────────────────────
#  AutoStartService (backend/autostart_service.py)
# ─────────────────────────────────────────────────────────────────────


class TestAutoStartServiceInit:
    def test_init(self, tmp_path):
        svc = AutoStartService(tmp_path)
        assert svc.project_root == tmp_path
        assert svc.service_name == "campus-auth"

    def test_platform_set(self, tmp_path):
        svc = AutoStartService(tmp_path)
        assert svc.platform in ("windows", "darwin", "linux")


class TestStartCommand:
    def test_with_env_executable(self, tmp_path):
        with patch.dict(os.environ, {"CAMPUS_AUTH_START_EXECUTABLE": "/path/to/exe"}):
            svc = AutoStartService(tmp_path)
            cmd = svc._start_command()
            assert "/path/to/exe" in cmd

    def test_fallback_to_sys_executable(self, tmp_path):
        with patch.dict(os.environ, {}, clear=True):
            svc = AutoStartService(tmp_path)
            cmd = svc._start_command()
            assert "app.py" in cmd


class TestHasCjkChars:
    def test_chinese_chars(self):
        assert AutoStartService._has_cjk_chars("C:\\用户\\test") is True

    def test_no_cjk_chars(self):
        assert AutoStartService._has_cjk_chars("C:\\Users\\test") is False

    def test_japanese_kanji_chars(self):
        assert AutoStartService._has_cjk_chars("C:\\東京\\test") is True

    def test_empty_string(self):
        assert AutoStartService._has_cjk_chars("") is False


class TestAutoStartStatus:
    @patch("backend.autostart_service.is_macos", return_value=True)
    @patch("backend.autostart_service.is_linux", return_value=False)
    @patch("backend.autostart_service.is_windows", return_value=False)
    def test_macos_status(self, mock_win, mock_linux, mock_mac, tmp_path):
        svc = AutoStartService(tmp_path)
        status = svc.status()
        assert status["platform"] == "macOS"
        assert "enabled" in status
        assert status["method"] == "launchd"

    @patch("backend.autostart_service.is_macos", return_value=False)
    @patch("backend.autostart_service.is_linux", return_value=True)
    @patch("backend.autostart_service.is_windows", return_value=False)
    def test_linux_status(self, mock_win, mock_linux, mock_mac, tmp_path):
        svc = AutoStartService(tmp_path)
        status = svc.status()
        assert status["platform"] == "Linux"
        assert status["method"] == "systemd --user"

    @patch("backend.autostart_service.is_macos", return_value=False)
    @patch("backend.autostart_service.is_linux", return_value=False)
    @patch("backend.autostart_service.is_windows", return_value=True)
    def test_windows_status(self, mock_win, mock_linux, mock_mac, tmp_path):
        svc = AutoStartService(tmp_path)
        status = svc.status()
        assert status["platform"] == "Windows"
        assert status["method"] == "VBScript startup"


class TestAutoStartEnableDisable:
    @patch("backend.autostart_service.is_macos", return_value=False)
    @patch("backend.autostart_service.is_linux", return_value=False)
    @patch("backend.autostart_service.is_windows", return_value=False)
    def test_unsupported_platform_enable(self, mock_win, mock_linux, mock_mac, tmp_path):
        svc = AutoStartService(tmp_path)
        ok, msg = svc.enable()
        assert ok is False
        assert "不支持" in msg

    @patch("backend.autostart_service.is_macos", return_value=False)
    @patch("backend.autostart_service.is_linux", return_value=False)
    @patch("backend.autostart_service.is_windows", return_value=False)
    def test_unsupported_platform_disable(self, mock_win, mock_linux, mock_mac, tmp_path):
        svc = AutoStartService(tmp_path)
        ok, msg = svc.disable()
        assert ok is False
        assert "不支持" in msg

    @patch("backend.autostart_service.is_macos", return_value=False)
    @patch("backend.autostart_service.is_linux", return_value=False)
    @patch("backend.autostart_service.is_windows", return_value=True)
    def test_windows_enable_cjk_path(self, mock_win, mock_linux, mock_mac, tmp_path):
        cjk_path = tmp_path / "中文目录"
        cjk_path.mkdir()
        svc = AutoStartService(cjk_path)
        ok, msg = svc.enable()
        assert ok is False
        assert "中文" in msg or "路径" in msg

    @patch("backend.autostart_service.is_macos", return_value=False)
    @patch("backend.autostart_service.is_linux", return_value=False)
    @patch("backend.autostart_service.is_windows", return_value=True)
    def test_windows_disable(self, mock_win, mock_linux, mock_mac, tmp_path):
        svc = AutoStartService(tmp_path)
        ok, msg = svc.disable()
        assert ok is True

    @patch("backend.autostart_service.is_macos", return_value=True)
    @patch("backend.autostart_service.is_linux", return_value=False)
    @patch("backend.autostart_service.is_windows", return_value=False)
    def test_macos_disable_no_plist(self, mock_win, mock_linux, mock_mac, tmp_path):
        svc = AutoStartService(tmp_path)
        ok, msg = svc.disable()
        assert ok is True

    @patch("backend.autostart_service.is_macos", return_value=False)
    @patch("backend.autostart_service.is_linux", return_value=True)
    @patch("backend.autostart_service.is_windows", return_value=False)
    def test_linux_disable(self, mock_win, mock_linux, mock_mac, tmp_path):
        svc = AutoStartService(tmp_path)
        ok, msg = svc.disable()
        assert ok is True


class TestAutoStartRun:
    def test_success(self, tmp_path):
        svc = AutoStartService(tmp_path)
        ok, msg = svc._run(["echo", "hello"])
        assert ok is True
        assert "hello" in msg

    def test_failure(self, tmp_path):
        svc = AutoStartService(tmp_path)
        ok, msg = svc._run(["python", "-c", "import sys; sys.exit(1)"])
        assert ok is False

    def test_exception(self, tmp_path):
        svc = AutoStartService(tmp_path)
        ok, msg = svc._run(["nonexistent_command_12345"])
        assert ok is False


# ─────────────────────────────────────────────────────────────────────
#  卸载清理服务 (backend/uninstall_service.py)
# ─────────────────────────────────────────────────────────────────────


class TestCleanupItem:
    def test_basic(self):
        item = CleanupItem(key="test", label="测试", exists=True)
        assert item.key == "test"
        assert item.label == "测试"
        assert item.exists is True
        assert item.path == ""
        assert item.size_mb == 0.0

    def test_with_path(self):
        item = CleanupItem(key="test", label="测试", exists=True, path="/tmp/test", size_mb=1.5)
        assert item.path == "/tmp/test"
        assert item.size_mb == 1.5


class TestCleanupResult:
    def test_basic(self):
        result = CleanupResult(key="test", label="测试", success=True, message="成功")
        assert result.key == "test"
        assert result.success is True
        assert result.message == "成功"


class TestPlaywrightCacheDir:
    @patch("backend.uninstall_service.PLATFORM", "windows")
    def test_windows(self):
        path = _playwright_cache_dir()
        assert path is not None
        assert "ms-playwright" in str(path)

    @patch("backend.uninstall_service.PLATFORM", "darwin")
    def test_macos(self):
        path = _playwright_cache_dir()
        assert path is not None
        assert "ms-playwright" in str(path)

    @patch("backend.uninstall_service.PLATFORM", "linux")
    def test_linux(self):
        path = _playwright_cache_dir()
        assert path is not None
        assert "ms-playwright" in str(path)

    @patch("backend.uninstall_service.PLATFORM", "unknown")
    def test_unknown(self):
        path = _playwright_cache_dir()
        assert path is None


class TestDirSizeMb:
    def test_empty_dir(self, tmp_path):
        assert _dir_size_mb(tmp_path) == 0.0

    def test_with_files(self, tmp_path):
        (tmp_path / "test.txt").write_text("hello world")
        size = _dir_size_mb(tmp_path)
        assert size > 0

    def test_nonexistent_dir(self, tmp_path):
        assert _dir_size_mb(tmp_path / "nonexistent") == 0.0


class TestUninstallCheckAutostart:
    @patch("backend.autostart_service.AutoStartService")
    def test_enabled(self, mock_svc_class):
        mock_svc = MagicMock()
        mock_svc.status.return_value = {"enabled": True, "location": "/test/path"}
        mock_svc_class.return_value = mock_svc
        result = _check_autostart()
        assert result["enabled"] is True

    @patch("backend.autostart_service.AutoStartService")
    def test_disabled(self, mock_svc_class):
        mock_svc = MagicMock()
        mock_svc.status.return_value = {"enabled": False}
        mock_svc_class.return_value = mock_svc
        result = _check_autostart()
        assert result["enabled"] is False

    @patch("backend.autostart_service.AutoStartService", side_effect=Exception("fail"))
    def test_exception_returns_disabled(self, mock_svc_class):
        result = _check_autostart()
        assert result["enabled"] is False


class TestDetect:
    @patch("backend.uninstall_service._check_autostart", return_value={"enabled": False})
    def test_returns_list(self, mock_autostart):
        items = detect()
        assert isinstance(items, list)
        assert len(items) >= 2

    @patch("backend.uninstall_service._check_autostart", return_value={"enabled": True, "location": "/test"})
    def test_autostart_enabled(self, mock_autostart):
        items = detect()
        autostart_items = [i for i in items if i.key == "autostart"]
        assert len(autostart_items) == 1
        assert autostart_items[0].exists is True


class TestPerform:
    @patch("backend.uninstall_service._remove_autostart", return_value=(True, "已移除"))
    def test_perform_autostart(self, mock_remove):
        results = perform(["autostart"])
        assert len(results) == 1
        assert results[0].success is True

    def test_perform_empty(self):
        results = perform([])
        assert len(results) == 0

    @patch("backend.uninstall_service._remove_user_data", return_value=(True, "已删除"))
    def test_perform_userdata(self, mock_remove):
        results = perform(["userdata"])
        assert len(results) == 1
        assert results[0].key == "userdata"
