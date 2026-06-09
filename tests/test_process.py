"""进程管理工具测试 — 覆盖纯逻辑函数。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from app.utils.process import (
    get_pid_file,
    is_local_port_in_use,
    normalize_proc_name,
    read_pid_file,
)

# ── normalize_proc_name ──


class TestNormalizeProcName:
    """进程名标准化。"""

    def test_lowercase(self):
        """转小写。"""
        assert normalize_proc_name("Python.exe") == "python"

    def test_remove_exe_suffix(self):
        """移除 .exe 后缀。"""
        assert normalize_proc_name("python.exe") == "python"

    def test_no_suffix(self):
        """无后缀。"""
        assert normalize_proc_name("python") == "python"

    def test_uppercase_with_exe(self):
        """大写带 .exe。"""
        assert normalize_proc_name("PYTHON.EXE") == "python"

    def test_empty_string(self):
        """空字符串。"""
        assert normalize_proc_name("") == ""

    def test_exe_only(self):
        """仅 .exe。"""
        assert normalize_proc_name(".exe") == ""

    def test_multiple_exe(self):
        """多个 .exe。"""
        assert normalize_proc_name("test.exe.exe") == "test.exe"


# ── read_pid_file ──


class TestReadPidFile:
    """PID 文件读取。"""

    def test_valid_pid(self, tmp_path):
        """有效 PID。"""
        pid_file = tmp_path / "test.pid"
        pid_file.write_text("12345", encoding="utf-8")

        with patch("app.utils.process.get_pid_file", return_value=pid_file):
            pid, name, timestamp = read_pid_file()
            assert pid == 12345
            assert name is None
            assert timestamp is None

    def test_valid_pid_with_name(self, tmp_path):
        """带进程名的 PID。"""
        pid_file = tmp_path / "test.pid"
        pid_file.write_text("12345\npython.exe|2026-06-01 12:00:00", encoding="utf-8")

        with patch("app.utils.process.get_pid_file", return_value=pid_file):
            pid, name, timestamp = read_pid_file()
            assert pid == 12345
            assert name == "python.exe"
            assert timestamp == "2026-06-01 12:00:00"

    def test_empty_file(self, tmp_path):
        """空文件。"""
        pid_file = tmp_path / "test.pid"
        pid_file.write_text("", encoding="utf-8")

        with patch("app.utils.process.get_pid_file", return_value=pid_file):
            pid, name, timestamp = read_pid_file()
            assert pid is None

    def test_nonexistent_file(self, tmp_path):
        """文件不存在。"""
        pid_file = tmp_path / "nonexistent.pid"

        with patch("app.utils.process.get_pid_file", return_value=pid_file):
            pid, name, timestamp = read_pid_file()
            assert pid is None

    def test_invalid_pid(self, tmp_path):
        """无效 PID。"""
        pid_file = tmp_path / "test.pid"
        pid_file.write_text("not_a_number", encoding="utf-8")

        with patch("app.utils.process.get_pid_file", return_value=pid_file):
            pid, name, timestamp = read_pid_file()
            assert pid is None

    def test_negative_pid(self, tmp_path):
        """负数 PID。"""
        pid_file = tmp_path / "test.pid"
        pid_file.write_text("-1", encoding="utf-8")

        with patch("app.utils.process.get_pid_file", return_value=pid_file):
            pid, name, timestamp = read_pid_file()
            assert pid is None

    def test_zero_pid(self, tmp_path):
        """零 PID。"""
        pid_file = tmp_path / "test.pid"
        pid_file.write_text("0", encoding="utf-8")

        with patch("app.utils.process.get_pid_file", return_value=pid_file):
            pid, name, timestamp = read_pid_file()
            assert pid is None

    def test_pid_only_no_name(self, tmp_path):
        """仅有 PID 无进程名。"""
        pid_file = tmp_path / "test.pid"
        pid_file.write_text("12345\n", encoding="utf-8")

        with patch("app.utils.process.get_pid_file", return_value=pid_file):
            pid, name, timestamp = read_pid_file()
            assert pid == 12345
            assert name is None

    def test_name_without_timestamp(self, tmp_path):
        """有进程名无时间戳。"""
        pid_file = tmp_path / "test.pid"
        pid_file.write_text("12345\npython.exe", encoding="utf-8")

        with patch("app.utils.process.get_pid_file", return_value=pid_file):
            pid, name, timestamp = read_pid_file()
            assert pid == 12345
            assert name == "python.exe"
            assert timestamp is None


# ── get_pid_file ──


class TestGetPidFile:
    """PID 文件路径。"""

    def test_returns_path(self):
        """返回 Path 对象。"""
        result = get_pid_file()
        assert isinstance(result, Path)
        assert result.name == "campus_network_auth.pid"


# ── is_local_port_in_use ──


class TestIsLocalPortInUse:
    """端口占用检查。"""

    def test_returns_bool(self):
        """返回布尔值。"""
        result = is_local_port_in_use(50721)
        assert isinstance(result, bool)

    def test_closed_port_returns_false(self):
        """关闭的端口返回 False。"""
        # 使用一个不太可能被占用的高位端口
        result = is_local_port_in_use(59999)
        assert result is False
