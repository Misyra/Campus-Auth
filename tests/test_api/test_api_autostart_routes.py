"""自动启动路由 API 测试 — 覆盖 Shell 列表查询、自启动状态/启用/禁用端点，
以及 AutoStartService 纯逻辑方法。"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

from app.services.autostart import AutoStartService, _autostart_cli_args


class TestListShells:
    """测试 GET /api/shells 端点。"""

    @patch("app.api.autostart.get_default_shell", return_value="/bin/bash")
    @patch("app.api.autostart.detect_available_shells")
    def test_list_shells_returns_200(self, mock_detect, mock_default, api_client):
        test_client, _ = api_client
        mock_detect.return_value = [
            {"name": "bash", "path": "/bin/bash", "description": "Bourne Again Shell"}
        ]
        resp = test_client.get("/api/shells")
        assert resp.status_code == 200
        data = resp.json()
        assert "shells" in data
        assert "default" in data
        assert isinstance(data["shells"], list)


class TestAutostartStatus:
    """测试 GET /api/autostart/status 端点。"""

    def test_autostart_status_returns_200(self, api_client):
        test_client, mock_services = api_client
        mock_services.autostart_service.status.return_value = {
            "platform": "windows", "enabled": False, "method": "", "location": "",
        }
        resp = test_client.get("/api/autostart/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "platform" in data
        assert "enabled" in data
        assert "method" in data
        assert "location" in data

    def test_autostart_status_default_disabled(self, api_client):
        test_client, mock_services = api_client
        mock_services.autostart_service.status.return_value = {
            "platform": "windows", "enabled": False, "method": "", "location": "",
        }
        data = test_client.get("/api/autostart/status").json()
        assert data["enabled"] is False


class TestEnableAutostart:
    """测试 POST /api/autostart/enable 端点。"""

    def test_enable_autostart_success(self, api_client):
        test_client, mock_services = api_client
        mock_services.autostart_service.enable.return_value = (True, "自启动已启用")
        resp = test_client.post("/api/autostart/enable")
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert resp.json()["message"] == "自启动已启用"


class TestDisableAutostart:
    """测试 POST /api/autostart/disable 端点。"""

    def test_disable_autostart_success(self, api_client):
        test_client, mock_services = api_client
        mock_services.autostart_service.disable.return_value = (True, "自启动已禁用")
        resp = test_client.post("/api/autostart/disable")
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert resp.json()["message"] == "自启动已禁用"


# ─────────────────────────────────────────────────────────────────────
#  AutoStartService 纯逻辑测试
# ─────────────────────────────────────────────────────────────────────


class TestAutostartCliArgs:
    """_autostart_cli_args 函数。"""

    def test_lightweight_mode(self):
        """轻量模式包含 --runtime-mode lightweight。"""
        result = _autostart_cli_args(lightweight=True)
        assert "--runtime-mode lightweight" in result
        assert "--startup-action monitor" in result
        assert "--no-browser" in result
        assert "--source autostart" in result

    def test_full_mode(self):
        """完整模式不包含 --runtime-mode。"""
        result = _autostart_cli_args(lightweight=False)
        assert "--runtime-mode" not in result
        assert "--startup-action monitor" in result

    def test_no_double_spaces(self):
        """结果中无连续空格。"""
        result = _autostart_cli_args(lightweight=False)
        assert "  " not in result


class TestAutoStartServiceInit:
    """AutoStartService 初始化。"""

    def test_init(self, tmp_path):
        svc = AutoStartService(tmp_path)
        assert svc.project_root == tmp_path
        assert svc.service_name == "campus-auth"


class TestAutoStartServicePaths:
    """路径生成方法。"""

    def test_mac_plist_path(self, tmp_path):
        svc = AutoStartService(tmp_path)
        path = svc._mac_plist_path()
        assert path.name == "campus-auth.plist"
        assert "LaunchAgents" in str(path)

    def test_linux_service_path(self, tmp_path):
        svc = AutoStartService(tmp_path)
        path = svc._linux_service_path()
        assert path.name == "campus-auth.service"
        assert "systemd" in str(path)

    def test_windows_startup_vbs(self, tmp_path):
        svc = AutoStartService(tmp_path)
        path = svc._windows_startup_vbs()
        assert path.name == "campus-auth.vbs"
        assert "Startup" in str(path)


class TestAutoStartServiceRun:
    """_run 方法。"""

    def test_run_success(self, tmp_path):
        svc = AutoStartService(tmp_path)
        with patch("app.services.autostart.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
            success, output = svc._run(["echo", "hello"])
            assert success is True
            assert output == "ok"

    def test_run_failure(self, tmp_path):
        svc = AutoStartService(tmp_path)
        with patch("app.services.autostart.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="error")
            success, output = svc._run(["false"])
            assert success is False
            assert "error" in output

    def test_run_timeout(self, tmp_path):
        import subprocess

        svc = AutoStartService(tmp_path)
        with patch("app.services.autostart.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired("cmd", 30)
            success, output = svc._run(["slow_cmd"])
            assert success is False
            assert "超时" in output

    def test_run_exception(self, tmp_path):
        svc = AutoStartService(tmp_path)
        with patch("app.services.autostart.subprocess.run") as mock_run:
            mock_run.side_effect = OSError("file not found")
            success, output = svc._run(["bad_cmd"])
            assert success is False


class TestAutoStartServiceStatus:
    """status 方法。"""

    @patch("app.services.autostart.is_macos", return_value=True)
    @patch("app.services.autostart.is_linux", return_value=False)
    @patch("app.services.autostart.is_windows", return_value=False)
    def test_status_macos_enabled(self, mock_win, mock_linux, mock_mac, tmp_path):
        svc = AutoStartService(tmp_path)
        with patch.object(svc, "_mac_plist_path") as mock_path:
            mock_path.return_value = MagicMock()
            mock_path.return_value.exists.return_value = True
            mock_path.return_value.__str__ = lambda self: "/path/to/plist"
            result = svc.status()
        assert result["platform"] == "macOS"
        assert result["enabled"] is True
        assert result["method"] == "launchd"

    @patch("app.services.autostart.is_macos", return_value=False)
    @patch("app.services.autostart.is_linux", return_value=True)
    @patch("app.services.autostart.is_windows", return_value=False)
    def test_status_linux_enabled(self, mock_win, mock_linux, mock_mac, tmp_path):
        svc = AutoStartService(tmp_path)
        with patch.object(svc, "_linux_service_path") as mock_path:
            mock_path.return_value = MagicMock()
            mock_path.return_value.exists.return_value = True
            mock_path.return_value.__str__ = lambda self: "/path/to/service"
            result = svc.status()
        assert result["platform"] == "Linux"
        assert result["enabled"] is True
        assert result["method"] == "systemd --user"

    @patch("app.services.autostart.is_macos", return_value=False)
    @patch("app.services.autostart.is_linux", return_value=False)
    @patch("app.services.autostart.is_windows", return_value=True)
    def test_status_windows_enabled(self, mock_win, mock_linux, mock_mac, tmp_path):
        svc = AutoStartService(tmp_path)
        with patch.object(svc, "_windows_startup_vbs") as mock_path:
            mock_path.return_value = MagicMock()
            mock_path.return_value.exists.return_value = True
            mock_path.return_value.__str__ = lambda self: "/path/to/vbs"
            result = svc.status()
        assert result["platform"] == "Windows"
        assert result["enabled"] is True
        assert result["method"] == "VBScript startup"

    @patch("app.services.autostart.is_macos", return_value=False)
    @patch("app.services.autostart.is_linux", return_value=False)
    @patch("app.services.autostart.is_windows", return_value=False)
    @patch("app.services.autostart.get_platform", return_value="FreeBSD")
    def test_status_unsupported(self, mock_gp, mock_win, mock_linux, mock_mac, tmp_path):
        svc = AutoStartService(tmp_path)
        result = svc.status()
        assert result["enabled"] is False
        assert result["method"] == "unsupported"


class TestAutoStartServiceEnableDisable:
    """enable / disable 方法。"""

    @patch("app.services.autostart.is_macos", return_value=False)
    @patch("app.services.autostart.is_linux", return_value=False)
    @patch("app.services.autostart.is_windows", return_value=False)
    @patch("app.services.autostart.get_platform", return_value="FreeBSD")
    def test_enable_unsupported(self, mock_gp, mock_win, mock_linux, mock_mac, tmp_path):
        svc = AutoStartService(tmp_path)
        success, msg = svc.enable()
        assert success is False
        assert "不支持" in msg

    @patch("app.services.autostart.is_macos", return_value=False)
    @patch("app.services.autostart.is_linux", return_value=False)
    @patch("app.services.autostart.is_windows", return_value=False)
    @patch("app.services.autostart.get_platform", return_value="FreeBSD")
    def test_disable_unsupported(self, mock_gp, mock_win, mock_linux, mock_mac, tmp_path):
        svc = AutoStartService(tmp_path)
        success, msg = svc.disable()
        assert success is False
        assert "不支持" in msg

    @patch("app.services.autostart.is_windows", return_value=True)
    @patch("app.services.autostart.is_macos", return_value=False)
    @patch("app.services.autostart.is_linux", return_value=False)
    def test_enable_windows_success(self, mock_linux, mock_mac, mock_win, tmp_path):
        svc = AutoStartService(tmp_path)
        with (
            patch.object(svc, "_has_cjk_chars", return_value=False),
            patch.object(svc, "_start_command", return_value='"python" "app.py"'),
            patch.object(svc, "_windows_startup_vbs") as mock_vbs,
        ):
            mock_vbs_path = tmp_path / "startup.vbs"
            mock_vbs.return_value = mock_vbs_path
            success, msg = svc.enable()
        assert success is True
        assert mock_vbs_path.exists()

    @patch("app.services.autostart.is_windows", return_value=True)
    @patch("app.services.autostart.is_macos", return_value=False)
    @patch("app.services.autostart.is_linux", return_value=False)
    def test_enable_windows_cjk_path(self, mock_linux, mock_mac, mock_win, tmp_path):
        cjk_path = tmp_path / "中文路径"
        svc = AutoStartService(cjk_path)
        success, msg = svc.enable(lightweight=True)
        assert success is False
        assert "中文" in msg or "路径" in msg

    @patch("app.services.autostart.is_windows", return_value=True)
    @patch("app.services.autostart.is_macos", return_value=False)
    @patch("app.services.autostart.is_linux", return_value=False)
    def test_disable_windows(self, mock_linux, mock_mac, mock_win, tmp_path):
        svc = AutoStartService(tmp_path)
        with patch.object(svc, "_windows_startup_vbs") as mock_vbs:
            mock_vbs_path = MagicMock()
            mock_vbs.return_value = mock_vbs_path
            success, msg = svc.disable()
        assert success is True
        mock_vbs_path.unlink.assert_called_once_with(missing_ok=True)


class TestBuildVbsContent:
    """_build_vbs_content 静态方法。"""

    def test_contains_wshshell(self):
        content = AutoStartService._build_vbs_content('WshShell.Run "test", 0, False')
        assert "WScript.Shell" in content
        assert "WshShell.Run" in content

    def test_no_pid_check(self):
        """VBS 不再包含 PID 检测逻辑（去重由 Python 处理）"""
        content = AutoStartService._build_vbs_content("run_cmd")
        assert "campus_network_auth.pid" not in content
        assert "Win32_Process" not in content

    def test_contains_run_command(self):
        run_cmd = 'WshShell.Run "my_app.exe", 0, False'
        content = AutoStartService._build_vbs_content(run_cmd)
        assert run_cmd in content


class TestHasCjkChars:
    """_has_cjk_chars 静态方法。"""

    def test_chinese_chars(self):
        assert AutoStartService._has_cjk_chars("D:\\软件\\Campus-Auth") is True

    def test_mixed_chinese_and_ascii(self):
        assert AutoStartService._has_cjk_chars("D:\\工具\\Campus-Auth") is True

    def test_pure_ascii(self):
        assert AutoStartService._has_cjk_chars("D:\\Campus-Auth") is False

    def test_numbers_only(self):
        assert AutoStartService._has_cjk_chars("C:\\12345") is False

    def test_empty_string(self):
        assert AutoStartService._has_cjk_chars("") is False


class TestStartCommand:
    """_start_command 方法。"""

    def test_packaged_executable(self, tmp_path):
        svc = AutoStartService(tmp_path)
        with patch.dict(os.environ, {"CAMPUS_AUTH_START_EXECUTABLE": "C:\\app.exe"}):
            cmd = svc._start_command()
        assert "C:\\app.exe" in cmd

    def test_fallback_to_python(self, tmp_path):
        svc = AutoStartService(tmp_path)
        with (
            patch.dict(os.environ, {"CAMPUS_AUTH_START_EXECUTABLE": ""}),
            patch("app.services.autostart.is_windows", return_value=True),
        ):
            # .venv 不存在时回退
            cmd = svc._start_command()
        assert "app.py" in cmd

    def test_venv_python_windows(self, tmp_path):
        svc = AutoStartService(tmp_path)
        venv_dir = tmp_path / ".venv" / "Scripts"
        venv_dir.mkdir(parents=True)
        (venv_dir / "python.exe").touch()
        with patch.dict(os.environ, {"CAMPUS_AUTH_START_EXECUTABLE": ""}):
            with patch("app.services.autostart.is_windows", return_value=True):
                cmd = svc._start_command()
        assert ".venv" in cmd
        assert "python.exe" in cmd


class TestDisableMacos:
    """_disable_macos 方法。"""

    def test_disable_when_plist_exists(self, tmp_path):
        svc = AutoStartService(tmp_path)
        mock_plist = MagicMock()
        mock_plist.exists.return_value = True
        mock_plist.__str__ = lambda self: "/path/to/plist"

        # Windows 上没有 os.getuid，需要 mock os 模块
        mock_os = MagicMock()
        mock_os.getuid.return_value = 501

        with (
            patch.object(svc, "_mac_plist_path", return_value=mock_plist),
            patch.object(svc, "_run", return_value=(True, "")),
            patch.dict("sys.modules", {"os": mock_os}),
            patch("app.services.autostart.os", mock_os),
        ):
            success, msg = svc._disable_macos()

        assert success is True
        mock_plist.unlink.assert_called_once_with(missing_ok=True)

    def test_disable_when_plist_not_exists(self, tmp_path):
        svc = AutoStartService(tmp_path)
        mock_plist = MagicMock()
        mock_plist.exists.return_value = False

        with patch.object(svc, "_mac_plist_path", return_value=mock_plist):
            success, msg = svc._disable_macos()

        assert success is True


class TestDisableLinux:
    """_disable_linux 方法。"""

    def test_disable_linux(self, tmp_path):
        svc = AutoStartService(tmp_path)
        mock_service = MagicMock()

        with (
            patch.object(svc, "_linux_service_path", return_value=mock_service),
            patch.object(svc, "_run", return_value=(True, "")),
        ):
            success, msg = svc._disable_linux()

        assert success is True
        mock_service.unlink.assert_called_once_with(missing_ok=True)
