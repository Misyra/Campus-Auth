from __future__ import annotations

import platform
from unittest.mock import patch

from backend.autostart_service import AutoStartService


class TestAutoStartServiceInit:

    def test_platform_name(self, tmp_path):
        svc = AutoStartService(tmp_path)
        assert svc.platform_name == platform.system().lower()

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
        with patch.object(svc, "platform_name", "darwin"):
            path = svc._mac_plist_path()
            assert path.name == "campus-auth.plist"
            assert "LaunchAgents" in str(path)

    def test_linux_service_path(self, tmp_path):
        svc = AutoStartService(tmp_path)
        with patch.object(svc, "platform_name", "linux"):
            path = svc._linux_service_path()
            assert path.name == "campus-auth.service"
            assert "systemd" in str(path)

    def test_windows_startup_vbs(self, tmp_path):
        svc = AutoStartService(tmp_path)
        with patch.object(svc, "platform_name", "windows"):
            with patch("backend.autostart_service.os.getenv", return_value=str(tmp_path)):
                path = svc._windows_startup_vbs()
                assert path.name == "campus-auth.vbs"
                assert "Startup" in str(path)


class TestStatus:

    def test_unsupported_platform(self, tmp_path):
        svc = AutoStartService(tmp_path)
        with patch.object(svc, "platform_name", "freebsd"):
            status = svc.status()
            assert status["enabled"] is False
            assert status["method"] == "unsupported"

    def test_windows_not_enabled(self, tmp_path):
        svc = AutoStartService(tmp_path)
        with patch.object(svc, "platform_name", "windows"):
            with patch.object(svc, "_windows_startup_vbs", return_value=tmp_path / "nonexistent.vbs"):
                status = svc.status()
                assert status["enabled"] is False
                assert status["platform"] == "Windows"


class TestDisable:

    def test_disable_unsupported(self, tmp_path):
        svc = AutoStartService(tmp_path)
        with patch.object(svc, "platform_name", "freebsd"):
            ok, msg = svc.disable()
            assert ok is False
            assert "不支持" in msg

    def test_disable_windows_no_file(self, tmp_path):
        svc = AutoStartService(tmp_path)
        with patch.object(svc, "platform_name", "windows"):
            vbs_path = tmp_path / "nonexistent.vbs"
            with patch.object(svc, "_windows_startup_vbs", return_value=vbs_path):
                ok, msg = svc.disable()
                assert ok is True


class TestHasCjkChars:

    def test_english_path(self):
        assert AutoStartService._has_cjk_chars("D:\\Campus-Auth") is False

    def test_chinese_path(self):
        assert AutoStartService._has_cjk_chars("D:\\校园网\\Campus-Auth") is True
