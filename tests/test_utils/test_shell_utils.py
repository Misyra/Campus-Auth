"""Shell 工具测试 — 覆盖 detect_shells、detect_binaries、get_default_shell。"""

from __future__ import annotations

import sys
from unittest.mock import patch

from app.utils.shell_utils import detect_binaries, detect_shells, get_default_shell

# ── detect_shells ──


class TestDetectShells:
    """Shell 检测。"""

    def test_returns_list(self):
        """返回列表。"""
        result = detect_shells()
        assert isinstance(result, list)

    def test_each_entry_has_required_keys(self):
        """每个条目包含必需键。"""
        result = detect_shells()
        for entry in result:
            assert "name" in entry
            assert "path" in entry
            assert "description" in entry

    def test_windows_candidates(self):
        """Windows 平台候选。"""
        if sys.platform == "win32":
            result = detect_shells()
            names = {e["name"] for e in result}
            # 至少应该有 cmd
            assert "cmd" in names or len(result) > 0

    def test_mocked_shell_found(self):
        """模拟找到 shell。"""
        with (
            patch("app.utils.shell_utils.shutil.which", return_value="/bin/bash"),
            patch("app.utils.shell_utils.sys") as mock_sys,
        ):
            mock_sys.platform = "linux"
            result = detect_shells()
            assert len(result) > 0
            assert any(e["path"] == "/bin/bash" for e in result)

    def test_mocked_no_shell(self):
        """模拟未找到 shell。"""
        with patch("app.utils.shell_utils.shutil.which", return_value=None):
            result = detect_shells()
            assert result == []


# ── detect_binaries ──


class TestDetectBinaries:
    """二进制检测。"""

    def test_returns_list(self):
        """返回列表。"""
        result = detect_binaries()
        assert isinstance(result, list)

    def test_includes_python(self):
        """包含 Python。"""
        result = detect_binaries()
        names = {e["name"] for e in result}
        assert "Python" in names

    def test_includes_shells(self):
        """包含 Shell。"""
        with patch(
            "app.utils.shell_utils.detect_shells",
            return_value=[{"name": "bash", "path": "/bin/bash", "description": "test"}],
        ):
            result = detect_binaries()
            names = {e["name"] for e in result}
            assert "bash" in names


# ── get_default_shell ──


class TestGetDefaultShell:
    """默认 Shell 获取。"""

    def test_returns_string(self):
        """返回字符串。"""
        result = get_default_shell()
        assert isinstance(result, str)

    def test_windows_returns_cmd(self):
        """Windows 返回 cmd.exe 或 powershell。"""
        if sys.platform == "win32":
            result = get_default_shell()
            assert (
                "cmd" in result.lower()
                or "powershell" in result.lower()
                or "pwsh" in result.lower()
            )

    def test_unix_returns_shell(self):
        """Unix 返回 shell 路径。"""
        if sys.platform != "win32":
            result = get_default_shell()
            assert "/" in result  # 路径格式

    def test_mocked_pwsh(self):
        """模拟找到 pwsh。"""
        with (
            patch(
                "app.utils.shell_utils.shutil.which",
                side_effect=lambda x: "/usr/bin/pwsh" if x == "pwsh.exe" else None,
            ),
            patch("app.utils.shell_utils.sys") as mock_sys,
        ):
            mock_sys.platform = "win32"
            result = get_default_shell()
            assert result == "/usr/bin/pwsh"

    def test_mocked_powershell(self):
        """模拟找到 powershell。"""

        def which_side_effect(x):
            if x == "pwsh.exe":
                return None
            if x == "powershell.exe":
                return "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe"
            return None

        with (
            patch("app.utils.shell_utils.shutil.which", side_effect=which_side_effect),
            patch("app.utils.shell_utils.sys") as mock_sys,
        ):
            mock_sys.platform = "win32"
            result = get_default_shell()
            assert "powershell" in result.lower()

    def test_mocked_cmd_fallback(self):
        """模拟回退到 cmd。"""
        with (
            patch("app.utils.shell_utils.shutil.which", return_value=None),
            patch("app.utils.shell_utils.sys") as mock_sys,
        ):
            mock_sys.platform = "win32"
            result = get_default_shell()
            assert result == "cmd.exe"

    def test_mocked_unix_shell_env(self):
        """模拟 Unix SHELL 环境变量。"""
        with patch("app.utils.shell_utils.sys") as mock_sys:
            mock_sys.platform = "linux"
            with (
                patch("app.utils.shell_utils.os.environ", {"SHELL": "/bin/zsh"}),
                patch(
                    "app.utils.shell_utils.shutil.which",
                    side_effect=lambda x: x if x == "/bin/zsh" else None,
                ),
            ):
                result = get_default_shell()
                assert result == "/bin/zsh"

    def test_mocked_unix_no_shell_env(self):
        """模拟 Unix 无 SHELL 环境变量。"""
        with patch("app.utils.shell_utils.sys") as mock_sys:
            mock_sys.platform = "linux"
            with patch("app.utils.shell_utils.os.environ", {}):
                result = get_default_shell()
                assert result == "/bin/bash"
