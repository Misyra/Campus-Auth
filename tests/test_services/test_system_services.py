"""系统服务模块综合测试

合并原 test_autostart_service.py 和 test_uninstall_service.py。
覆盖 AutoStartService（自启动）和卸载清理服务。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.services.autostart import AutoStartService
from app.services.uninstall import (
    CleanupItem,
    CleanupResult,
    _check_autostart,
    detect,
    perform,
)
from app.utils.files import dir_size_mb as _dir_size_mb
from app.utils.platform import get_playwright_cache_dir as _playwright_cache_dir

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
        assert svc._platform in ("windows", "darwin", "linux")


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
            assert "main.py" in cmd


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
    @patch("app.services.autostart.is_macos", return_value=True)
    @patch("app.services.autostart.is_linux", return_value=False)
    @patch("app.services.autostart.is_windows", return_value=False)
    def test_macos_status(self, mock_win, mock_linux, mock_mac, tmp_path):
        svc = AutoStartService(tmp_path)
        status = svc.status()
        assert status["platform"] == "macOS"
        assert "enabled" in status
        assert status["method"] == "launchd"

    @patch("app.services.autostart.is_macos", return_value=False)
    @patch("app.services.autostart.is_linux", return_value=True)
    @patch("app.services.autostart.is_windows", return_value=False)
    def test_linux_status(self, mock_win, mock_linux, mock_mac, tmp_path):
        svc = AutoStartService(tmp_path)
        status = svc.status()
        assert status["platform"] == "Linux"
        assert status["method"] == "systemd --user"

    @patch("app.services.autostart.is_macos", return_value=False)
    @patch("app.services.autostart.is_linux", return_value=False)
    @patch("app.services.autostart.is_windows", return_value=True)
    def test_windows_status(self, mock_win, mock_linux, mock_mac, tmp_path):
        svc = AutoStartService(tmp_path)
        status = svc.status()
        assert status["platform"] == "Windows"
        assert status["method"] == "VBScript startup"


class TestAutoStartEnableDisable:
    @patch("app.services.autostart.is_macos", return_value=False)
    @patch("app.services.autostart.is_linux", return_value=False)
    @patch("app.services.autostart.is_windows", return_value=False)
    def test_unsupported_platform_enable(
        self, mock_win, mock_linux, mock_mac, tmp_path
    ):
        svc = AutoStartService(tmp_path)
        ok, msg = svc.enable()
        assert ok is False
        assert "不支持" in msg

    @patch("app.services.autostart.is_macos", return_value=False)
    @patch("app.services.autostart.is_linux", return_value=False)
    @patch("app.services.autostart.is_windows", return_value=False)
    def test_unsupported_platform_disable(
        self, mock_win, mock_linux, mock_mac, tmp_path
    ):
        svc = AutoStartService(tmp_path)
        ok, msg = svc.disable()
        assert ok is False
        assert "不支持" in msg

    @patch("app.services.autostart.is_macos", return_value=False)
    @patch("app.services.autostart.is_linux", return_value=False)
    @patch("app.services.autostart.is_windows", return_value=True)
    def test_windows_enable_cjk_path(self, mock_win, mock_linux, mock_mac, tmp_path):
        cjk_path = tmp_path / "中文目录"
        cjk_path.mkdir()
        svc = AutoStartService(cjk_path)
        ok, msg = svc.enable()
        assert ok is False
        assert "中文" in msg or "路径" in msg

    @patch("app.services.autostart.is_macos", return_value=False)
    @patch("app.services.autostart.is_linux", return_value=False)
    @patch("app.services.autostart.is_windows", return_value=True)
    def test_windows_disable(self, mock_win, mock_linux, mock_mac, tmp_path):
        svc = AutoStartService(tmp_path)
        ok, msg = svc.disable()
        assert ok is True

    @patch("app.services.autostart.is_macos", return_value=True)
    @patch("app.services.autostart.is_linux", return_value=False)
    @patch("app.services.autostart.is_windows", return_value=False)
    def test_macos_disable_no_plist(self, mock_win, mock_linux, mock_mac, tmp_path):
        svc = AutoStartService(tmp_path)
        ok, msg = svc.disable()
        assert ok is True

    @patch("app.services.autostart.is_macos", return_value=False)
    @patch("app.services.autostart.is_linux", return_value=True)
    @patch("app.services.autostart.is_windows", return_value=False)
    def test_linux_disable(self, mock_win, mock_linux, mock_mac, tmp_path):
        svc = AutoStartService(tmp_path)
        ok, msg = svc.disable()
        assert ok is True


class TestAutoStartRun:
    def test_success(self, tmp_path):
        svc = AutoStartService(tmp_path)
        ok, msg = svc._run([sys.executable, "-c", "print('hello')"])
        assert ok is True
        assert "hello" in msg

    def test_failure(self, tmp_path):
        svc = AutoStartService(tmp_path)
        ok, msg = svc._run([sys.executable, "-c", "import sys; sys.exit(1)"])
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
        item = CleanupItem(
            key="test", label="测试", exists=True, path="/tmp/test", size_mb=1.5
        )
        assert item.path == "/tmp/test"
        assert item.size_mb == 1.5


class TestCleanupResult:
    def test_basic(self):
        result = CleanupResult(key="test", label="测试", success=True, message="成功")
        assert result.key == "test"
        assert result.success is True
        assert result.message == "成功"


class TestPlaywrightCacheDir:
    @patch("app.utils.platform.get_platform", return_value="windows")
    def test_windows(self, _mock):
        path = _playwright_cache_dir()
        assert path is not None
        assert "ms-playwright" in str(path)

    @patch("app.utils.platform.get_platform", return_value="darwin")
    def test_macos(self, _mock):
        path = _playwright_cache_dir()
        assert path is not None
        assert "ms-playwright" in str(path)

    @patch("app.utils.platform.get_platform", return_value="linux")
    def test_linux(self, _mock):
        path = _playwright_cache_dir()
        assert path is not None
        assert "ms-playwright" in str(path)

    @patch("app.utils.platform.get_platform", return_value="unknown")
    def test_unknown(self, _mock):
        path = _playwright_cache_dir()
        assert path is None


class TestDirSizeMb:
    def test_empty_dir(self, tmp_path):
        result = _dir_size_mb(tmp_path)
        assert result.size_mb == 0.0
        assert result.complete is True

    def test_with_files(self, tmp_path):
        # 写入超过 1MB 以确保 round(..., 1) 不为 0
        (tmp_path / "test.txt").write_bytes(b"x" * (1024 * 1024 + 1))
        result = _dir_size_mb(tmp_path)
        assert result.size_mb > 0
        assert result.complete is True

    def test_nonexistent_dir(self, tmp_path):
        result = _dir_size_mb(tmp_path / "nonexistent")
        assert result.size_mb == 0.0
        assert result.complete is True


class TestUninstallCheckAutostart:
    def setup_method(self):
        import app.services.uninstall as _um

        _um._autostart_service = None

    @patch("app.services.autostart.AutoStartService")
    def test_enabled(self, mock_svc_class):
        mock_svc = MagicMock()
        mock_svc.status.return_value = {"enabled": True, "location": "/test/path"}
        mock_svc_class.return_value = mock_svc
        result = _check_autostart()
        assert result["enabled"] is True

    @patch("app.services.autostart.AutoStartService")
    def test_disabled(self, mock_svc_class):
        mock_svc = MagicMock()
        mock_svc.status.return_value = {"enabled": False}
        mock_svc_class.return_value = mock_svc
        result = _check_autostart()
        assert result["enabled"] is False

    @patch("app.services.autostart.AutoStartService", side_effect=Exception("fail"))
    def test_exception_returns_disabled(self, mock_svc_class):
        result = _check_autostart()
        assert result["enabled"] is False


class TestDetect:
    @patch("app.services.uninstall._check_autostart", return_value={"enabled": False})
    def test_returns_list(self, mock_autostart):
        items = detect()
        assert isinstance(items, list)
        assert len(items) >= 2

    @patch(
        "app.services.uninstall._check_autostart",
        return_value={"enabled": True, "location": "/test"},
    )
    def test_autostart_enabled(self, mock_autostart):
        items = detect()
        autostart_items = [i for i in items if i.key == "autostart"]
        assert len(autostart_items) == 1
        assert autostart_items[0].exists is True


class TestPerform:
    @patch("app.services.uninstall._remove_autostart", return_value=(True, "已移除"))
    def test_perform_autostart(self, mock_remove):
        results = perform(["autostart"])
        assert len(results) == 1
        assert results[0].success is True

    def test_perform_empty(self):
        results = perform([])
        assert len(results) == 0

    @patch("app.services.uninstall._remove_user_data", return_value=(True, "已删除"))
    def test_perform_userdata(self, mock_remove):
        results = perform(["userdata"])
        assert len(results) == 1
        assert results[0].key == "userdata"


# ─────────────────────────────────────────────────────────────────────
#  _build_vbs_content (autostart_service.py)
# ─────────────────────────────────────────────────────────────────────


class TestBuildVbsContent:
    def test_minimal_output_structure(self):
        """VBS 输出应为最小结构：On Error + WshShell + 命令"""
        svc = AutoStartService(project_root=Path("/test"))
        run_cmd = 'WshShell.Run "test.exe", 0, False'
        content = svc._build_vbs_content(run_cmd)
        expected = (
            'Set WshShell = CreateObject("WScript.Shell")\n'
            "\n"
            'WshShell.Run "test.exe", 0, False'
        )
        assert content == expected

    def test_no_pid_parsing(self):
        """VBS 不应包含 PID 检测逻辑（去重由 Python 处理）"""
        svc = AutoStartService(project_root=Path("/test"))
        content = svc._build_vbs_content('WshShell.Run "test.exe"')
        assert "campus_network_auth.pid" not in content
        assert "Win32_Process" not in content
        assert "WMI" not in content.upper()

    def test_contains_run_command(self):
        """生成的 VBScript 应包含传入的运行命令"""
        svc = AutoStartService(project_root=Path("/test"))
        run_cmd = 'WshShell.Run "C:\\test\\app.exe" --no-browser'
        content = svc._build_vbs_content(run_cmd)
        assert run_cmd in content

    def test_different_commands_produce_different_content(self):
        """不同命令应产生不同的 VBScript 内容"""
        svc = AutoStartService(project_root=Path("/test"))
        content1 = svc._build_vbs_content('WshShell.Run "a.exe"')
        content2 = svc._build_vbs_content('WshShell.Run "b.exe"')
        assert content1 != content2


# ─────────────────────────────────────────────────────────────────────
#  macOS launchctl 新版 API
# ─────────────────────────────────────────────────────────────────────


class TestMacosLaunchctl:
    def test_enable_macos_uses_bootstrap(self, tmp_path, monkeypatch):
        """启用 macOS 自启动应使用 launchctl bootstrap"""
        if not hasattr(os, "getuid"):
            monkeypatch.setattr(os, "getuid", lambda: 501, raising=False)
        svc = AutoStartService(project_root=tmp_path)
        with (
            patch.object(svc, "_run", return_value=(True, "")) as mock_run,
            patch.object(svc, "_mac_plist_path", return_value=tmp_path / "test.plist"),
            patch("app.services.autostart.is_macos", return_value=True),
            patch("app.services.autostart.get_platform", return_value="darwin"),
        ):
            svc._enable_macos()
            calls = [str(c) for c in mock_run.call_args_list]
            assert any("bootstrap" in str(c) for c in calls)

    def test_disable_macos_uses_bootout(self, tmp_path, monkeypatch):
        """禁用 macOS 自启动应使用 launchctl bootout"""
        if not hasattr(os, "getuid"):
            monkeypatch.setattr(os, "getuid", lambda: 501, raising=False)
        svc = AutoStartService(project_root=tmp_path)
        plist = tmp_path / "test.plist"
        plist.write_text("test", encoding="utf-8")
        with (
            patch.object(svc, "_run", return_value=(True, "")) as mock_run,
            patch.object(svc, "_mac_plist_path", return_value=plist),
            patch("app.services.autostart.is_macos", return_value=True),
            patch("app.services.autostart.get_platform", return_value="darwin"),
        ):
            svc._disable_macos()
            calls = [str(c) for c in mock_run.call_args_list]
            assert any("bootout" in str(c) for c in calls)
