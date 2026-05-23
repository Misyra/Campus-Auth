from __future__ import annotations

from unittest.mock import MagicMock, patch

from backend.autostart_service import AutoStartService


class TestAutoStartServiceInit:

    def test_platform(self, tmp_path):
        svc = AutoStartService(tmp_path)
        assert svc.platform in ("windows", "darwin", "linux")

    def test_service_name(self, tmp_path):
        svc = AutoStartService(tmp_path)
        assert svc.service_name == "campus-auth"


class TestStartCommand:

    def test_no_embedded_python_no_env(self, tmp_path):
        svc = AutoStartService(tmp_path)
        with patch("backend.autostart_service.sys.executable", "/usr/bin/python3"):
            cmd = svc._start_command()
            assert "app.py" in cmd


class TestPaths:

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
        with patch("backend.autostart_service.os.getenv", return_value=str(tmp_path)):
            path = svc._windows_startup_vbs()
            assert path.name == "campus-auth.vbs"
            assert "Startup" in str(path)


class TestStatus:

    def test_unsupported_platform(self, tmp_path):
        svc = AutoStartService(tmp_path)
        with patch("backend.autostart_service.is_windows", return_value=False):
            with patch("backend.autostart_service.is_macos", return_value=False):
                with patch("backend.autostart_service.is_linux", return_value=False):
                    status = svc.status()
                    assert status["enabled"] is False
                    assert status["method"] == "unsupported"

    def test_windows_not_enabled(self, tmp_path):
        svc = AutoStartService(tmp_path)
        with patch("backend.autostart_service.is_windows", return_value=True):
            with patch("backend.autostart_service.is_macos", return_value=False):
                with patch("backend.autostart_service.is_linux", return_value=False):
                    with patch.object(svc, "_windows_startup_vbs", return_value=tmp_path / "nonexistent.vbs"):
                        status = svc.status()
                        assert status["enabled"] is False
                        assert status["platform"] == "Windows"


class TestDisable:

    def test_disable_unsupported(self, tmp_path):
        svc = AutoStartService(tmp_path)
        with patch("backend.autostart_service.is_windows", return_value=False):
            with patch("backend.autostart_service.is_macos", return_value=False):
                with patch("backend.autostart_service.is_linux", return_value=False):
                    ok, msg = svc.disable()
                    assert ok is False
                    assert "不支持" in msg

    def test_disable_windows_no_file(self, tmp_path):
        svc = AutoStartService(tmp_path)
        with patch("backend.autostart_service.is_windows", return_value=True):
            with patch("backend.autostart_service.is_macos", return_value=False):
                with patch("backend.autostart_service.is_linux", return_value=False):
                    vbs_path = tmp_path / "nonexistent.vbs"
                    with patch.object(svc, "_windows_startup_vbs", return_value=vbs_path):
                        ok, msg = svc.disable()
                        assert ok is True


class TestStartCommandNonWindows:
    """测试非 Windows 平台 _start_command 使用 sys.executable"""

    def test_linux_uses_sys_executable(self, tmp_path):
        """Linux 平台 _start_command 应使用 sys.executable（无 python.exe）"""
        svc = AutoStartService(tmp_path)
        with patch("backend.autostart_service.sys.executable", "/usr/bin/python3"):
            with patch("backend.autostart_service.is_windows", return_value=False):
                with patch("pathlib.Path.exists", return_value=True):
                    cmd = svc._start_command()
                    assert "python3" in cmd
                    assert "python.exe" not in cmd

    def test_macos_uses_sys_executable(self, tmp_path):
        """macOS 平台 _start_command 应使用 sys.executable"""
        svc = AutoStartService(tmp_path)
        with patch("backend.autostart_service.sys.executable", "/opt/homebrew/bin/python3"):
            with patch("backend.autostart_service.is_windows", return_value=False):
                with patch("pathlib.Path.exists", return_value=True):
                    cmd = svc._start_command()
                    assert "python3" in cmd
                    assert "python.exe" not in cmd


class TestEnableLinux:
    """测试 Linux 自启动服务文件生成"""

    def test_service_file_uses_bin_sh(self, tmp_path):
        """_enable_linux 生成的 service 文件应使用 /bin/sh 而非 /bin/bash"""
        svc = AutoStartService(tmp_path)
        service_path = tmp_path / ".config" / "systemd" / "user" / "campus-auth.service"

        with patch.object(svc, "_linux_service_path", return_value=service_path):
            with patch("backend.autostart_service.is_linux", return_value=True):
                with patch("backend.autostart_service.is_windows", return_value=False):
                    with patch("backend.autostart_service.is_macos", return_value=False):
                        with patch("backend.autostart_service.subprocess.run") as mock_run:
                            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
                            with patch("src.utils.logging.get_logger"):
                                ok, msg = svc._enable_linux()

        assert service_path.exists()
        content = service_path.read_text(encoding="utf-8")
        assert "/bin/sh" in content
        assert "/bin/bash" not in content

    def test_service_file_contains_start_command(self, tmp_path):
        """_enable_linux 生成的 service 文件应包含正确的启动命令"""
        svc = AutoStartService(tmp_path)
        service_path = tmp_path / ".config" / "systemd" / "user" / "campus-auth.service"

        with patch.object(svc, "_linux_service_path", return_value=service_path):
            with patch("backend.autostart_service.is_linux", return_value=True):
                with patch("backend.autostart_service.is_windows", return_value=False):
                    with patch("backend.autostart_service.is_macos", return_value=False):
                        with patch("backend.autostart_service.subprocess.run") as mock_run:
                            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
                            with patch("src.utils.logging.get_logger"):
                                ok, msg = svc._enable_linux()

        content = service_path.read_text(encoding="utf-8")
        assert "ExecStart=" in content
        assert "WorkingDirectory=" in content
        assert "Campus-Auth" in content or "campus" in content.lower()


class TestHasCjkChars:

    def test_english_path(self):
        assert AutoStartService._has_cjk_chars("D:\\Campus-Auth") is False

    def test_chinese_path(self):
        assert AutoStartService._has_cjk_chars("D:\\校园网\\Campus-Auth") is True
