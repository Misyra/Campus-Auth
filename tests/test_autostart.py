"""开机自启动服务测试 — 覆盖纯逻辑方法和静态方法。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from app.services.autostart import AutoStartService

# ── _has_cjk_chars ──


class TestHasCjkChars:
    """CJK 字符检测。"""

    def test_pure_ascii(self):
        """纯英文路径不含 CJK。"""
        assert AutoStartService._has_cjk_chars("D:\\Campus-Auth") is False
        assert AutoStartService._has_cjk_chars("/home/user/app") is False

    def test_chinese_chars(self):
        """中文字符被检测。"""
        assert AutoStartService._has_cjk_chars("D:\\校园网认证") is True
        assert AutoStartService._has_cjk_chars("C:\\用户\\test") is True

    def test_japanese_chars(self):
        """日文平假名/片假名不含在 CJK 正则范围内，返回 False。"""
        # 注意：_has_cjk_chars 的正则只覆盖 CJK 统一表意文字，不包含假名
        assert AutoStartService._has_cjk_chars("D:\\テスト") is False

    def test_korean_chars(self):
        """韩文字符不含在 CJK 正则范围内，返回 False。"""
        # 注意：_has_cjk_chars 的正则只覆盖 CJK 统一表意文字，不包含韩文
        assert AutoStartService._has_cjk_chars("D:\\테스트") is False

    def test_empty_string(self):
        """空字符串不含 CJK。"""
        assert AutoStartService._has_cjk_chars("") is False

    def test_mixed_path(self):
        """混合路径含 CJK。"""
        assert AutoStartService._has_cjk_chars("D:\\app\\测试\\bin") is True


# ── _build_vbs_content ──


class TestBuildVbsContent:
    """VBScript 内容生成。"""

    def test_contains_run_command(self):
        """输出包含传入的 run_command。"""
        run_cmd = 'targetCmd = "test.exe"\nWshShell.Run targetCmd, 0, False'
        content = AutoStartService._build_vbs_content(run_cmd)
        assert run_cmd in content

    def test_contains_wshshell(self):
        """输出包含 WshShell 创建。"""
        content = AutoStartService._build_vbs_content("test")
        assert 'CreateObject("WScript.Shell")' in content

    def test_contains_pid_check(self):
        """输出包含 PID 检查逻辑。"""
        content = AutoStartService._build_vbs_content("test")
        assert "campus_network_auth.pid" in content
        assert "Win32_Process" in content

    def test_sets_env_var(self):
        """输出设置环境变量。"""
        content = AutoStartService._build_vbs_content("test")
        assert "CAMPUS_AUTH_AUTO_OPEN_BROWSER" in content
        assert '"false"' in content


# ── _start_command ──


class TestStartCommand:
    """启动命令构建。"""

    def test_env_override(self, tmp_path):
        """环境变量覆盖启动命令。"""
        service = AutoStartService(tmp_path)
        with patch.dict("os.environ", {"CAMPUS_AUTH_START_EXECUTABLE": "C:\\app\\start.exe"}):
            cmd = service._start_command()
            assert cmd == '"C:\\app\\start.exe"'

    def test_env_override_strips_whitespace(self, tmp_path):
        """环境变量去除首尾空格。"""
        service = AutoStartService(tmp_path)
        with patch.dict("os.environ", {"CAMPUS_AUTH_START_EXECUTABLE": "  C:\\app\\start.exe  "}):
            cmd = service._start_command()
            assert cmd == '"C:\\app\\start.exe"'

    def test_fallback_to_python(self, tmp_path):
        """无 venv 时回退到 python。"""
        service = AutoStartService(tmp_path)
        with patch.dict("os.environ", {"CAMPUS_AUTH_START_EXECUTABLE": ""}, clear=False):
            # 确保 venv 不存在
            with patch.object(Path, "exists", return_value=False):
                cmd = service._start_command()
                assert "python" in cmd.lower()
                assert "app.py" in cmd


# ── 路径构建 ──


class TestPathBuilders:
    """平台路径构建。"""

    def test_mac_plist_path(self, tmp_path):
        """macOS plist 路径。"""
        service = AutoStartService(tmp_path)
        with patch("pathlib.Path.home", return_value=Path("/Users/test")):
            path = service._mac_plist_path()
            assert path == Path("/Users/test/Library/LaunchAgents/campus-auth.plist")

    def test_linux_service_path(self, tmp_path):
        """Linux systemd 服务路径。"""
        service = AutoStartService(tmp_path)
        with patch("pathlib.Path.home", return_value=Path("/home/test")):
            path = service._linux_service_path()
            assert path == Path("/home/test/.config/systemd/user/campus-auth.service")

    def test_windows_startup_vbs(self, tmp_path):
        """Windows 启动 VBS 路径。"""
        service = AutoStartService(tmp_path)
        with patch.dict("os.environ", {"APPDATA": "C:\\Users\\test\\AppData\\Roaming"}):
            path = service._windows_startup_vbs()
            assert "Startup" in str(path)
            assert path.name == "campus-auth.vbs"


# ── status ──


class TestStatus:
    """状态查询。"""

    def test_windows_enabled(self, tmp_path):
        """Windows 已启用。"""
        service = AutoStartService(tmp_path)
        with patch("app.services.autostart.is_windows", return_value=True), \
             patch("app.services.autostart.is_macos", return_value=False), \
             patch("app.services.autostart.is_linux", return_value=False), \
             patch.object(service, "_windows_startup_vbs") as mock_path:
            mock_path.return_value = MagicMock(exists=MagicMock(return_value=True))
            mock_path.return_value.__str__ = lambda self: "C:\\test\\campus-auth.vbs"
            result = service.status()
            assert result["platform"] == "Windows"
            assert result["enabled"] is True
            assert result["method"] == "VBScript startup"

    def test_windows_disabled(self, tmp_path):
        """Windows 未启用。"""
        service = AutoStartService(tmp_path)
        with patch("app.services.autostart.is_windows", return_value=True), \
             patch("app.services.autostart.is_macos", return_value=False), \
             patch("app.services.autostart.is_linux", return_value=False), \
             patch.object(service, "_windows_startup_vbs") as mock_path:
            mock_path.return_value = MagicMock(exists=MagicMock(return_value=False))
            mock_path.return_value.__str__ = lambda self: "C:\\test\\campus-auth.vbs"
            result = service.status()
            assert result["enabled"] is False

    def test_macos_enabled(self, tmp_path):
        """macOS 已启用。"""
        service = AutoStartService(tmp_path)
        with patch("app.services.autostart.is_windows", return_value=False), \
             patch("app.services.autostart.is_macos", return_value=True), \
             patch("app.services.autostart.is_linux", return_value=False), \
             patch.object(service, "_mac_plist_path") as mock_path:
            mock_path.return_value = MagicMock(exists=MagicMock(return_value=True))
            mock_path.return_value.__str__ = lambda self: "/test/campus-auth.plist"
            result = service.status()
            assert result["platform"] == "macOS"
            assert result["method"] == "launchd"

    def test_linux_enabled(self, tmp_path):
        """Linux 已启用。"""
        service = AutoStartService(tmp_path)
        with patch("app.services.autostart.is_windows", return_value=False), \
             patch("app.services.autostart.is_macos", return_value=False), \
             patch("app.services.autostart.is_linux", return_value=True), \
             patch.object(service, "_linux_service_path") as mock_path:
            mock_path.return_value = MagicMock(exists=MagicMock(return_value=True))
            mock_path.return_value.__str__ = lambda self: "/test/campus-auth.service"
            result = service.status()
            assert result["platform"] == "Linux"
            assert result["method"] == "systemd --user"


# ── _run ──


class TestRun:
    """_run 命令执行。"""

    def test_success(self, tmp_path):
        """命令成功返回 (True, stdout)。"""
        service = AutoStartService(tmp_path)
        mock_proc = MagicMock(returncode=0, stdout="ok", stderr="")
        with patch("subprocess.run", return_value=mock_proc):
            ok, msg = service._run(["echo", "test"])
            assert ok is True
            assert msg == "ok"

    def test_failure(self, tmp_path):
        """命令失败返回 (False, stderr)。"""
        service = AutoStartService(tmp_path)
        mock_proc = MagicMock(returncode=1, stdout="", stderr="error msg")
        with patch("subprocess.run", return_value=mock_proc):
            ok, msg = service._run(["false"])
            assert ok is False
            assert "error msg" in msg

    def test_timeout(self, tmp_path):
        """命令超时返回 (False, 超时消息)。"""
        service = AutoStartService(tmp_path)
        with patch("subprocess.run", side_effect=TimeoutError()):
            ok, msg = service._run(["slow_cmd"])
            assert ok is False


# ── enable/disable 平台分发 ──


class TestEnableDisable:
    """enable/disable 平台分发。"""

    def test_enable_unsupported_platform(self, tmp_path):
        """不支持的平台返回失败。"""
        service = AutoStartService(tmp_path)
        with patch("app.services.autostart.is_windows", return_value=False), \
             patch("app.services.autostart.is_macos", return_value=False), \
             patch("app.services.autostart.is_linux", return_value=False):
            ok, msg = service.enable()
            assert ok is False
            assert "不支持" in msg

    def test_disable_unsupported_platform(self, tmp_path):
        """不支持的平台返回失败。"""
        service = AutoStartService(tmp_path)
        with patch("app.services.autostart.is_windows", return_value=False), \
             patch("app.services.autostart.is_macos", return_value=False), \
             patch("app.services.autostart.is_linux", return_value=False):
            ok, msg = service.disable()
            assert ok is False
            assert "不支持" in msg

    def test_enable_windows_cjk_rejected(self, tmp_path):
        """Windows 路径含 CJK 字符被拒绝。"""
        cjk_root = tmp_path / "校园网"
        cjk_root.mkdir()
        service = AutoStartService(cjk_root)
        with patch("app.services.autostart.is_windows", return_value=True), \
             patch("app.services.autostart.is_macos", return_value=False), \
             patch("app.services.autostart.is_linux", return_value=False):
            ok, msg = service.enable()
            assert ok is False
            assert "中文" in msg or "CJK" in msg or "字符" in msg
