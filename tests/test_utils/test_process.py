"""进程管理工具测试 — 覆盖纯逻辑函数。"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import psutil

from app.utils.process import (
    cleanup_pid,
    get_pid_file,
    get_process_create_time,
    get_process_name,
    is_local_port_in_use,
    is_service_running,
    read_pid_file,
    read_pid_mode,
    verify_process_identity,
    write_pid,
)

# ── read_pid_file ──


class TestReadPidFile:
    """PID 文件读取。"""

    def test_valid_json(self, tmp_path):
        """有效 JSON 格式。"""
        pid_file = tmp_path / "test.pid"
        data = {
            "pid": 12345,
            "create_time": 1718191234.123,
            "mode": "lightweight",
            "proc_name": "python.exe",
        }
        pid_file.write_text(json.dumps(data), encoding="utf-8")

        with patch("app.utils.process.get_pid_file", return_value=pid_file):
            result = read_pid_file()
            assert result is not None
            assert result["pid"] == 12345
            assert result["create_time"] == 1718191234.123
            assert result["mode"] == "lightweight"
            assert result["proc_name"] == "python.exe"

    def test_empty_file(self, tmp_path):
        """空文件。"""
        pid_file = tmp_path / "test.pid"
        pid_file.write_text("", encoding="utf-8")

        with patch("app.utils.process.get_pid_file", return_value=pid_file):
            result = read_pid_file()
            assert result is None

    def test_nonexistent_file(self, tmp_path):
        """文件不存在。"""
        pid_file = tmp_path / "nonexistent.pid"

        with patch("app.utils.process.get_pid_file", return_value=pid_file):
            result = read_pid_file()
            assert result is None

    def test_invalid_json(self, tmp_path):
        """无效 JSON。"""
        pid_file = tmp_path / "test.pid"
        pid_file.write_text("not json", encoding="utf-8")

        with patch("app.utils.process.get_pid_file", return_value=pid_file):
            result = read_pid_file()
            # 旧格式解析失败返回 None
            assert result is None

    def test_invalid_pid(self, tmp_path):
        """无效 PID。"""
        pid_file = tmp_path / "test.pid"
        pid_file.write_text("not_a_number", encoding="utf-8")

        with patch("app.utils.process.get_pid_file", return_value=pid_file):
            result = read_pid_file()
            assert result is None

    def test_negative_pid(self, tmp_path):
        """负数 PID。"""
        pid_file = tmp_path / "test.pid"
        data = {"pid": -1, "create_time": 1718191234.123}
        pid_file.write_text(json.dumps(data), encoding="utf-8")

        with patch("app.utils.process.get_pid_file", return_value=pid_file):
            result = read_pid_file()
            assert result is None

    def test_zero_pid(self, tmp_path):
        """零 PID。"""
        pid_file = tmp_path / "test.pid"
        data = {"pid": 0, "create_time": 1718191234.123}
        pid_file.write_text(json.dumps(data), encoding="utf-8")

        with patch("app.utils.process.get_pid_file", return_value=pid_file):
            result = read_pid_file()
            assert result is None

    def test_missing_create_time(self, tmp_path):
        """缺失 create_time 字段 → None（防止 PID 复用误判）。"""
        pid_file = tmp_path / "test.pid"
        data = {"pid": 12345, "mode": "lightweight"}
        pid_file.write_text(json.dumps(data), encoding="utf-8")

        with patch("app.utils.process.get_pid_file", return_value=pid_file):
            result = read_pid_file()
            assert result is None


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

    def test_ipv6_localhost(self):
        """IPv6 localhost (::1) 端口检测。"""
        result = is_local_port_in_use(59998, host="::1")
        assert isinstance(result, bool)

    def test_ipv6_auto_detect(self):
        """包含 ':' 的 host 自动使用 AF_INET6。"""
        import socket

        # 绑定一个 IPv6 端口
        with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as s:
            s.bind(("::1", 0))
            port = s.getsockname()[1]
            s.listen(1)
            assert is_local_port_in_use(port, host="::1") is True

    def test_ipv4_default_host(self):
        """默认 host 为 127.0.0.1（IPv4）。"""
        import socket

        # 绑定一个 IPv4 端口
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
            s.listen(1)
            assert is_local_port_in_use(port) is True


# ── get_process_name ──


class TestGetProcessName:
    """进程名获取。"""

    def test_current_process(self):
        """当前进程应有名称。"""
        name = get_process_name(os.getpid())
        assert name is not None
        assert isinstance(name, str)

    def test_nonexistent_pid(self):
        """不存在的 PID 返回 None。"""
        assert get_process_name(999999999) is None


# ── get_process_create_time ──


class TestGetProcessCreateTime:
    """进程创建时间获取。覆盖 76-79 行。"""

    def test_current_process(self):
        """当前进程应有创建时间。"""
        result = get_process_create_time(os.getpid())
        assert result is not None
        assert isinstance(result, float)
        assert result > 0

    def test_nonexistent_pid(self):
        """不存在的 PID 返回 None。"""
        assert get_process_create_time(999999999) is None

    def test_no_such_process(self):
        """NoSuchProcess 异常时返回 None。"""
        with patch(
            "app.utils.process.psutil.Process", side_effect=psutil.NoSuchProcess(123)
        ):
            assert get_process_create_time(123) is None

    def test_access_denied(self):
        """AccessDenied 异常时返回 None。"""
        with patch(
            "app.utils.process.psutil.Process", side_effect=psutil.AccessDenied(123)
        ):
            assert get_process_create_time(123) is None

    def test_zombie_process(self):
        """ZombieProcess 异常时返回 None。"""
        with patch(
            "app.utils.process.psutil.Process", side_effect=psutil.ZombieProcess(123)
        ):
            assert get_process_create_time(123) is None


# ── verify_process_identity ──


class TestVerifyProcessIdentity:
    """进程身份验证。覆盖 97-109 行。"""

    def test_process_alive_no_create_time(self):
        """进程存活且不检查 create_time → True。"""
        assert verify_process_identity(os.getpid()) is True

    def test_process_alive_matching_create_time(self):
        """进程存活且 create_time 匹配 → True。"""
        pid = os.getpid()
        ct = psutil.Process(pid).create_time()
        assert verify_process_identity(pid, ct) is True

    def test_process_not_found(self):
        """进程不存在 → False（覆盖 98-99 行）。"""
        assert verify_process_identity(999999999) is False

    def test_create_time_not_available(self):
        """进程存在但无法获取 create_time → False（覆盖 103-104 行）。"""
        pid = os.getpid()
        with patch("app.utils.process.get_process_create_time", return_value=None):
            assert verify_process_identity(pid, 12345.0) is False

    def test_create_time_mismatch(self):
        """进程存在但 create_time 不匹配 → False（覆盖 106-107 行）。"""
        pid = os.getpid()
        assert verify_process_identity(pid, 0.0) is False

    def test_create_time_within_tolerance(self):
        """create_time 在 1 秒误差内 → True。"""
        pid = os.getpid()
        ct = psutil.Process(pid).create_time()
        assert verify_process_identity(pid, ct + 0.5) is True


# ── is_service_running ──


class TestIsServiceRunning:
    """服务运行状态检查。覆盖 120-121, 140 行。"""

    def test_no_pid_file(self, tmp_path):
        """无 PID 文件 → (False, None)。"""
        pid_file = tmp_path / "test.pid"
        with patch("app.utils.process.get_pid_file", return_value=pid_file):
            running, pid = is_service_running()
            assert running is False
            assert pid is None

    def test_invalid_pid_file_cleans_up(self, tmp_path):
        """PID 文件内容无效时清理文件（覆盖 120-121 行）。"""
        pid_file = tmp_path / "test.pid"
        pid_file.write_text("invalid", encoding="utf-8")
        with patch("app.utils.process.get_pid_file", return_value=pid_file):
            running, pid = is_service_running()
            assert running is False
            assert pid is None
            assert not pid_file.exists()

    def test_process_identity_mismatch_cleans_up(self, tmp_path):
        """进程身份不匹配时清理 PID 文件。"""
        pid_file = tmp_path / "test.pid"
        data = {"pid": 999999999, "create_time": 0.0, "mode": "full"}
        pid_file.write_text(json.dumps(data), encoding="utf-8")
        with patch("app.utils.process.get_pid_file", return_value=pid_file):
            running, pid = is_service_running()
            assert running is False
            assert pid is None
            assert not pid_file.exists()

    def test_grace_period_skips_port_check(self, tmp_path):
        """刚启动 30 秒内跳过端口检查（覆盖 140 行）。"""
        pid = os.getpid()
        ct = psutil.Process(pid).create_time()
        pid_file = tmp_path / "test.pid"
        data = {"pid": pid, "create_time": ct, "mode": "full"}
        pid_file.write_text(json.dumps(data), encoding="utf-8")
        with (
            patch("app.utils.process.get_pid_file", return_value=pid_file),
            patch("app.utils.process.is_local_port_in_use", return_value=False),
            patch("app.utils.process.time") as mock_time,
        ):
            mock_time.time.return_value = ct + 10  # 10 秒前启动，在 30 秒宽限期内
            running, result_pid = is_service_running()
            assert running is True
            assert result_pid == pid

    def test_full_mode_port_not_used_cleans_up(self, tmp_path):
        """完整模式下端口未监听且超过宽限期 → 清理。"""
        pid = os.getpid()
        ct = psutil.Process(pid).create_time()
        pid_file = tmp_path / "test.pid"
        data = {"pid": pid, "create_time": ct, "mode": "full"}
        pid_file.write_text(json.dumps(data), encoding="utf-8")
        with (
            patch("app.utils.process.get_pid_file", return_value=pid_file),
            patch("app.utils.process.is_local_port_in_use", return_value=False),
            patch("app.utils.process.time") as mock_time,
        ):
            mock_time.time.return_value = ct + 60  # 超过 30 秒宽限期
            running, result_pid = is_service_running()
            assert running is False
            assert result_pid is None
            assert not pid_file.exists()

    def test_full_mode_port_in_use(self, tmp_path):
        """完整模式下端口已监听 → 运行中。"""
        pid = os.getpid()
        ct = psutil.Process(pid).create_time()
        pid_file = tmp_path / "test.pid"
        data = {"pid": pid, "create_time": ct, "mode": "full"}
        pid_file.write_text(json.dumps(data), encoding="utf-8")
        with (
            patch("app.utils.process.get_pid_file", return_value=pid_file),
            patch("app.utils.process.is_local_port_in_use", return_value=True),
        ):
            running, result_pid = is_service_running()
            assert running is True
            assert result_pid == pid

    def test_lightweight_mode_skips_port_check(self, tmp_path):
        """轻量模式跳过端口检查。"""
        pid = os.getpid()
        ct = psutil.Process(pid).create_time()
        pid_file = tmp_path / "test.pid"
        data = {"pid": pid, "create_time": ct, "mode": "lightweight"}
        pid_file.write_text(json.dumps(data), encoding="utf-8")
        with patch("app.utils.process.get_pid_file", return_value=pid_file):
            running, result_pid = is_service_running()
            assert running is True
            assert result_pid == pid

    def test_missing_create_time_cleans_up(self, tmp_path):
        """PID 文件缺失 create_time → 清理并返回未运行。"""
        pid_file = tmp_path / "test.pid"
        data = {"pid": os.getpid(), "mode": "lightweight"}
        pid_file.write_text(json.dumps(data), encoding="utf-8")
        with patch("app.utils.process.get_pid_file", return_value=pid_file):
            running, pid = is_service_running()
            assert running is False
            assert pid is None
            assert not pid_file.exists()


# ── read_pid_mode ──


class TestReadPidMode:
    """读取运行模式。覆盖 181 行。"""

    def test_valid_mode(self, tmp_path):
        """有效模式。"""
        pid_file = tmp_path / "test.pid"
        data = {"pid": 1234, "create_time": 1718191234.0, "mode": "lightweight"}
        pid_file.write_text(json.dumps(data), encoding="utf-8")
        with patch("app.utils.process.get_pid_file", return_value=pid_file):
            assert read_pid_mode() == "lightweight"

    def test_no_pid_file(self, tmp_path):
        """无 PID 文件 → None。"""
        pid_file = tmp_path / "test.pid"
        with patch("app.utils.process.get_pid_file", return_value=pid_file):
            assert read_pid_mode() is None

    def test_mode_is_none(self, tmp_path):
        """mode 字段为 None → None（覆盖 181 行 falsy 分支）。"""
        pid_file = tmp_path / "test.pid"
        data = {"pid": 1234, "create_time": 1718191234.0, "mode": None}
        pid_file.write_text(json.dumps(data), encoding="utf-8")
        with patch("app.utils.process.get_pid_file", return_value=pid_file):
            assert read_pid_mode() is None

    def test_mode_is_empty_string(self, tmp_path):
        """mode 字段为空字符串 → None。"""
        pid_file = tmp_path / "test.pid"
        data = {"pid": 1234, "create_time": 1718191234.0, "mode": ""}
        pid_file.write_text(json.dumps(data), encoding="utf-8")
        with patch("app.utils.process.get_pid_file", return_value=pid_file):
            assert read_pid_mode() is None


# ── write_pid / cleanup_pid ──


class TestWritePidAndCleanup:
    """PID 写入和清理。"""

    def test_write_and_cleanup(self, tmp_path):
        """写入后清理。"""
        pid_file = tmp_path / "test.pid"
        with (
            patch("app.utils.process.AUTH_DATA_DIR", tmp_path),
            patch("app.utils.process.get_pid_file", return_value=pid_file),
            patch("app.utils.files.atomic_write") as mock_write,
        ):
            write_pid(mode="lightweight")
            mock_write.assert_called_once()
            written_data = json.loads(mock_write.call_args[0][1])
            assert written_data["mode"] == "lightweight"
            assert written_data["pid"] > 0
            assert "create_time" in written_data
            assert written_data["create_time"] > 0

    def test_cleanup_nonexistent(self, tmp_path):
        """清理不存在的文件不报错。"""
        pid_file = tmp_path / "test.pid"
        with patch("app.utils.process.get_pid_file", return_value=pid_file):
            cleanup_pid()  # missing_ok=True，不应抛异常
