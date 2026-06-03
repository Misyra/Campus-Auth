"""app.py 入口模块测试

覆盖 PID 管理、进程检测、CLI 命令、信号处理、浏览器控制、主入口等。
"""
from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest


# ══════════════════════════════════════════════════════════════════════
#  辅助工具
# ══════════════════════════════════════════════════════════════════════


def _write_raw_pid(pid_dir: Path, content: str) -> Path:
    """直接写入原始 PID 文件内容（绕过 _write_pid 的格式化）。"""
    pid_file = pid_dir / "campus_network_auth.pid"
    pid_file.write_text(content, encoding="utf-8")
    return pid_file


# ══════════════════════════════════════════════════════════════════════
#  TestGetPidFile
# ══════════════════════════════════════════════════════════════════════


class TestGetPidFile:
    """_get_pid_file — 目录创建 + 返回路径。"""

    def test_creates_dir_and_returns_path(self, tmp_pid_dir):
        from app import _get_pid_file

        result = _get_pid_file()
        assert tmp_pid_dir.exists()
        assert result == tmp_pid_dir / "campus_network_auth.pid"


# ══════════════════════════════════════════════════════════════════════
#  TestReadPidFile
# ══════════════════════════════════════════════════════════════════════


class TestReadPidFile:
    """_read_pid_file — 多种文件状态。"""

    def test_file_not_exists(self, tmp_pid_dir):
        from app import _read_pid_file

        assert _read_pid_file() == (None, None, None)

    def test_empty_file(self, tmp_pid_dir):
        from app import _read_pid_file

        _write_raw_pid(tmp_pid_dir, "")
        assert _read_pid_file() == (None, None, None)

    def test_single_line_pid(self, tmp_pid_dir):
        from app import _read_pid_file

        _write_raw_pid(tmp_pid_dir, "1234")
        pid, name, ts = _read_pid_file()
        assert pid == 1234
        assert name is None
        assert ts is None

    def test_two_lines_with_pipe(self, tmp_pid_dir):
        from app import _read_pid_file

        _write_raw_pid(tmp_pid_dir, "5678\npython.exe|2026-01-01 12:00:00")
        pid, name, ts = _read_pid_file()
        assert pid == 5678
        assert name == "python.exe"
        assert ts == "2026-01-01 12:00:00"

    def test_invalid_content(self, tmp_pid_dir):
        from app import _read_pid_file

        _write_raw_pid(tmp_pid_dir, "not_a_number")
        assert _read_pid_file() == (None, None, None)

    def test_negative_pid(self, tmp_pid_dir):
        from app import _read_pid_file

        _write_raw_pid(tmp_pid_dir, "-1")
        assert _read_pid_file() == (None, None, None)


# ══════════════════════════════════════════════════════════════════════
#  TestGetProcessName
# ══════════════════════════════════════════════════════════════════════


class TestGetProcessName:
    """_get_process_name — Windows tasklist CSV 解析。"""

    @patch("subprocess.run")
    def test_valid_csv_output(self, mock_run):
        from app import _get_process_name

        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='"python.exe","1234","Console","1","10,000 K"',
        )
        assert _get_process_name(1234) == "python.exe"

    @patch("subprocess.run")
    def test_no_matching_process(self, mock_run):
        """tasklist 在 PID 不存在时返回本地化消息。"""
        from app import _get_process_name

        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='INFO: No tasks are running which match the specified criteria.',
        )
        assert _get_process_name(9999) is None

    @patch("subprocess.run")
    def test_subprocess_exception(self, mock_run):
        from app import _get_process_name

        mock_run.side_effect = OSError("fail")
        assert _get_process_name(1234) is None


# ══════════════════════════════════════════════════════════════════════
#  TestNormalizeProcName
# ══════════════════════════════════════════════════════════════════════


class TestNormalizeProcName:
    """_normalize_proc_name — 大小写 + .exe 后缀。"""

    def test_lowercase_with_exe(self):
        from app import _normalize_proc_name

        assert _normalize_proc_name("Python.EXE") == "python"

    def test_no_exe_suffix(self):
        """无 .exe 后缀时原样返回（小写）。"""
        from app import _normalize_proc_name

        result = _normalize_proc_name("node")
        assert result == "node"

    def test_chrome_exe(self):
        """正确去除 .exe 后缀。"""
        from app import _normalize_proc_name

        assert _normalize_proc_name("chrome.exe") == "chrome"

    def test_axe_no_suffix(self):
        """末尾含 e/x 但非 .exe 后缀时不去除。"""
        from app import _normalize_proc_name

        assert _normalize_proc_name("axe") == "axe"

    def test_exe_only(self):
        """仅 .exe 后缀时去除。"""
        from app import _normalize_proc_name

        assert _normalize_proc_name(".exe") == ""


# ══════════════════════════════════════════════════════════════════════
#  TestIsServiceRunning
# ══════════════════════════════════════════════════════════════════════


class TestIsServiceRunning:
    """_is_service_running — 5 种场景。"""

    def test_no_pid_file(self, tmp_pid_dir):
        from app import _is_service_running

        running, pid = _is_service_running()
        assert running is False
        assert pid is None

    def test_pid_file_but_process_dead(self, tmp_pid_dir):
        from app import _is_service_running

        _write_raw_pid(tmp_pid_dir, "1234\npython.exe|2026-01-01")
        with patch("app._get_process_name", return_value=None):
            running, pid = _is_service_running()
        assert running is False
        assert pid is None
        # 残留 PID 文件应被清理
        assert not (tmp_pid_dir / "campus_network_auth.pid").exists()

    def test_process_name_mismatch(self, tmp_pid_dir):
        from app import _is_service_running

        _write_raw_pid(tmp_pid_dir, "1234\npython.exe|2026-01-01")
        with (
            patch("app._get_process_name", return_value="other.exe"),
            patch("app._is_local_port_in_use", return_value=True),
        ):
            running, pid = _is_service_running()
        assert running is False

    def test_port_not_listening(self, tmp_pid_dir):
        from app import _is_service_running

        _write_raw_pid(tmp_pid_dir, "1234\npython.exe|2026-01-01")
        with (
            patch("app._get_process_name", return_value="python.exe"),
            patch("app._is_local_port_in_use", return_value=False),
        ):
            running, pid = _is_service_running()
        assert running is False

    def test_fully_alive(self, tmp_pid_dir):
        from app import _is_service_running

        _write_raw_pid(tmp_pid_dir, "1234\npython.exe|2026-01-01")
        with (
            patch("app._get_process_name", return_value="python.exe"),
            patch("app._is_local_port_in_use", return_value=True),
            patch("os.kill"),
        ):
            running, pid = _is_service_running()
        assert running is True
        assert pid == 1234


# ══════════════════════════════════════════════════════════════════════
#  TestIsLocalPortInUse
# ══════════════════════════════════════════════════════════════════════


class TestIsLocalPortInUse:
    """_is_local_port_in_use — 连接成功/失败。"""

    @patch("socket.socket")
    def test_port_in_use(self, mock_socket_cls):
        from app import _is_local_port_in_use

        mock_sock = MagicMock()
        mock_sock.__enter__ = MagicMock(return_value=mock_sock)
        mock_sock.__exit__ = MagicMock(return_value=False)
        mock_sock.connect_ex.return_value = 0
        mock_socket_cls.return_value = mock_sock

        assert _is_local_port_in_use(8080) is True

    @patch("socket.socket")
    def test_port_free(self, mock_socket_cls):
        from app import _is_local_port_in_use

        mock_sock = MagicMock()
        mock_sock.__enter__ = MagicMock(return_value=mock_sock)
        mock_sock.__exit__ = MagicMock(return_value=False)
        mock_sock.connect_ex.return_value = 111  # ECONNREFUSED
        mock_socket_cls.return_value = mock_sock

        assert _is_local_port_in_use(8080) is False


# ══════════════════════════════════════════════════════════════════════
#  TestWritePid + TestCleanupPid
# ══════════════════════════════════════════════════════════════════════


class TestWritePid:
    """_write_pid — 原子写入。"""

    def test_writes_pid_file(self, tmp_pid_dir):
        from app import _write_pid, _get_pid_file

        _write_pid()
        pid_file = _get_pid_file()
        assert pid_file.exists()
        content = pid_file.read_text(encoding="utf-8")
        lines = content.splitlines()
        assert int(lines[0]) == os.getpid()
        assert len(lines) == 2
        assert "|" in lines[1]


class TestCleanupPid:
    """_cleanup_pid — missing_ok 行为。"""

    def test_removes_existing_file(self, tmp_pid_dir):
        from app import _cleanup_pid, _get_pid_file

        pid_file = _get_pid_file()
        pid_file.write_text("test", encoding="utf-8")
        _cleanup_pid()
        assert not pid_file.exists()

    def test_no_error_when_missing(self, tmp_pid_dir):
        from app import _cleanup_pid

        # 文件不存在时不应抛异常
        _cleanup_pid()


# ══════════════════════════════════════════════════════════════════════
#  TestCmdStatus
# ══════════════════════════════════════════════════════════════════════


class TestCmdStatus:
    """_cmd_status — 4 种输出场景。"""

    def test_running(self, tmp_pid_dir, capsys):
        from app import _cmd_status

        _write_raw_pid(tmp_pid_dir, "1234\npython.exe|2026-01-01")
        with (
            patch("app._is_service_running", return_value=(True, 1234)),
            patch("app._is_local_port_in_use", return_value=True),
        ):
            _cmd_status()
        assert "正在运行" in capsys.readouterr().out

    def test_port_in_use_not_running(self, tmp_pid_dir, capsys):
        from app import _cmd_status

        with (
            patch("app._is_service_running", return_value=(False, None)),
            patch("app._is_local_port_in_use", return_value=True),
        ):
            _cmd_status()
        assert "疑似正在运行" in capsys.readouterr().out

    def test_stale_pid_file(self, tmp_pid_dir, capsys):
        """有残留 PID 文件但进程已死。"""
        from app import _cmd_status, _get_pid_file

        _write_raw_pid(tmp_pid_dir, "1234\npython.exe|2026-01-01")

        def fake_is_service_running():
            _get_pid_file().unlink(missing_ok=True)
            return False, None

        with (
            patch("app._is_service_running", side_effect=fake_is_service_running),
            patch("app._is_local_port_in_use", return_value=False),
        ):
            _cmd_status()
        out = capsys.readouterr().out
        assert "残留 PID 文件已清理" in out

    def test_not_running_no_pid(self, tmp_pid_dir, capsys):
        from app import _cmd_status

        with (
            patch("app._is_service_running", return_value=(False, None)),
            patch("app._is_local_port_in_use", return_value=False),
        ):
            _cmd_status()
        out = capsys.readouterr().out
        assert "服务未运行" in out
        assert "残留" not in out


# ══════════════════════════════════════════════════════════════════════
#  TestCmdStop
# ══════════════════════════════════════════════════════════════════════


class TestCmdStop:
    """_cmd_stop — 未运行/优雅停止/强制停止/进程名不匹配。"""

    def test_not_running(self, tmp_pid_dir, capsys):
        from app import _cmd_stop

        with patch("app._is_service_running", return_value=(False, None)):
            _cmd_stop()
        assert "未运行" in capsys.readouterr().out

    def test_graceful_stop(self, tmp_pid_dir, capsys):
        """优雅停止：os.kill(pid, 0) 抛 OSError 表示进程已退出。"""
        from app import _cmd_stop

        with (
            patch("app._is_service_running", return_value=(True, 1234)),
            patch("app._read_pid_file", return_value=(1234, "python.exe", "2026-01-01")),
            patch("app._get_process_name", return_value="python.exe"),
            patch("app._normalize_proc_name", side_effect=lambda n: n.lower().rstrip(".exe")),
            patch("app.is_windows", return_value=False),
            patch("os.kill", side_effect=[None, OSError("process gone")]),
            patch("time.sleep"),
        ):
            _cmd_stop()
        out = capsys.readouterr().out
        assert "已停止" in out

    def test_force_stop(self, tmp_pid_dir, capsys):
        """优雅停止超时后强制停止（Windows 路径：taskkill）。"""
        from app import _cmd_stop

        # os.kill(pid, 0) 始终成功 → 优雅停止超时 → taskkill /F
        with (
            patch("app._is_service_running", return_value=(True, 1234)),
            patch("app._read_pid_file", return_value=(1234, "python.exe", "2026-01-01")),
            patch("app._get_process_name", return_value="python.exe"),
            patch("app._normalize_proc_name", side_effect=lambda n: n.lower().rstrip(".exe")),
            patch("app.is_windows", return_value=True),
            patch("os.kill", return_value=None),
            patch("time.sleep"),
            patch("subprocess.run"),
        ):
            _cmd_stop()
        assert "强制停止" in capsys.readouterr().out

    def test_process_name_mismatch(self, tmp_pid_dir, capsys):
        from app import _cmd_stop

        with (
            patch("app._is_service_running", return_value=(True, 1234)),
            patch("app._read_pid_file", return_value=(1234, "python.exe", "2026-01-01")),
            patch("app._get_process_name", return_value="other.exe"),
            patch("app._normalize_proc_name", side_effect=lambda n: n.lower().rstrip(".exe")),
        ):
            _cmd_stop()
        out = capsys.readouterr().out
        assert "不匹配" in out


# ══════════════════════════════════════════════════════════════════════
#  TestCmdAutostart
# ══════════════════════════════════════════════════════════════════════


class TestCmdAutostart:
    """_cmd_autostart — status/enable/disable。"""

    @patch("backend.autostart_service.AutoStartService")
    def test_status(self, mock_cls, capsys):
        from app import _cmd_autostart

        mock_instance = MagicMock()
        mock_instance.status.return_value = {
            "platform": "windows",
            "enabled": True,
            "method": "registry",
            "location": "HKCU\\...",
        }
        mock_cls.return_value = mock_instance

        _cmd_autostart("status")
        out = capsys.readouterr().out
        assert "已启用" in out
        assert "windows" in out

    @patch("backend.autostart_service.AutoStartService")
    def test_enable(self, mock_cls, capsys):
        from app import _cmd_autostart

        mock_instance = MagicMock()
        mock_instance.enable.return_value = (True, "已启用开机自启动")
        mock_cls.return_value = mock_instance

        with pytest.raises(SystemExit) as exc_info:
            _cmd_autostart("enable")
        assert exc_info.value.code == 0

    @patch("backend.autostart_service.AutoStartService")
    def test_disable(self, mock_cls, capsys):
        from app import _cmd_autostart

        mock_instance = MagicMock()
        mock_instance.disable.return_value = (True, "已禁用开机自启动")
        mock_cls.return_value = mock_instance

        with pytest.raises(SystemExit) as exc_info:
            _cmd_autostart("disable")
        assert exc_info.value.code == 0


# ══════════════════════════════════════════════════════════════════════
#  TestRunLoginThenExit
# ══════════════════════════════════════════════════════════════════════


class TestRunLoginThenExit:
    """_run_login_then_exit — 成功/重试/耗尽。"""

    def _make_mocks(self):
        """创建通用 mock 对象。"""
        mock_worker = MagicMock()
        mock_ps = MagicMock()
        mock_data = MagicMock()
        mock_data.system = MagicMock()
        return mock_worker, mock_ps, mock_data

    def test_success_first_try(self, tmp_pid_dir):
        """首次登录成功应 sys.exit(0)。"""
        from app import _run_login_then_exit

        mock_worker, mock_ps, mock_data = self._make_mocks()
        success_result = MagicMock(success=True, data="ok")
        mock_worker.submit.return_value = success_result

        # 所有 local import 需要 patch 到源模块
        with (
            patch("src.playwright_worker.get_worker", return_value=mock_worker),
            patch("src.playwright_worker.CMD_LOGIN", "login"),
            patch("backend.profile_service.ProfileService", return_value=mock_ps),
            patch("backend.config_service.build_runtime_config", return_value={"retry_settings": {"max_retries": 3}}),
            patch("backend.config_service.load_runtime_config", return_value=(MagicMock(), False)),
            patch("app.cleanup_orphan_browsers"),
            patch("time.sleep"),
        ):
            mock_ps.load.return_value = mock_data
            with pytest.raises(SystemExit) as exc_info:
                _run_login_then_exit(MagicMock())
            assert exc_info.value.code == 0

    def test_retry_then_succeed(self, tmp_pid_dir):
        """第一次失败、第二次成功。"""
        from app import _run_login_then_exit

        mock_worker, mock_ps, mock_data = self._make_mocks()
        fail_result = MagicMock(success=False, error="timeout")
        success_result = MagicMock(success=True, data="ok")
        mock_worker.submit.side_effect = [fail_result, success_result]

        with (
            patch("src.playwright_worker.get_worker", return_value=mock_worker),
            patch("src.playwright_worker.CMD_LOGIN", "login"),
            patch("backend.profile_service.ProfileService", return_value=mock_ps),
            patch("backend.config_service.build_runtime_config", return_value={
                "retry_settings": {"max_retries": 3, "retry_interval": 1}
            }),
            patch("backend.config_service.load_runtime_config", return_value=(MagicMock(), False)),
            patch("app.cleanup_orphan_browsers"),
            patch("time.sleep"),
        ):
            mock_ps.load.return_value = mock_data
            with pytest.raises(SystemExit) as exc_info:
                _run_login_then_exit(MagicMock())
            assert exc_info.value.code == 0

    def test_retries_exhausted(self, tmp_pid_dir):
        """所有重试均失败，回退到正常模式。"""
        from app import _run_login_then_exit

        mock_worker, mock_ps, mock_data = self._make_mocks()
        fail_result = MagicMock(success=False, error="timeout")
        mock_worker.submit.return_value = fail_result

        with (
            patch("src.playwright_worker.get_worker", return_value=mock_worker),
            patch("src.playwright_worker.CMD_LOGIN", "login"),
            patch("backend.profile_service.ProfileService", return_value=mock_ps),
            patch("backend.config_service.build_runtime_config", return_value={
                "retry_settings": {"max_retries": 2, "retry_interval": 0}
            }),
            patch("backend.config_service.load_runtime_config", return_value=(MagicMock(), False)),
            patch("app.cleanup_orphan_browsers"),
            patch("time.sleep"),
        ):
            mock_ps.load.return_value = mock_data
            mock_logger = MagicMock()
            _run_login_then_exit(mock_logger)
            mock_logger.warning.assert_called_once()


# ══════════════════════════════════════════════════════════════════════
#  TestRunServer
# ══════════════════════════════════════════════════════════════════════


class TestRunServer:
    """_run_server — 已运行/PID 写入+atexit/托盘降级。"""

    def test_already_running(self, tmp_pid_dir, patched_webbrowser):
        """检测到已运行时打开浏览器并退出。"""
        from app import _run_server

        with (
            patch("app._is_service_running", return_value=(True, 1234)),
            patch("app._is_local_port_in_use", return_value=True),
        ):
            with pytest.raises(SystemExit) as exc_info:
                _run_server()
            assert exc_info.value.code == 0
        patched_webbrowser.assert_called_once()

    def test_writes_pid_and_registers_atexit(self, tmp_pid_dir):
        """正常启动时写入 PID 文件并注册 atexit 清理。"""
        from app import _run_server

        with (
            patch("app._is_service_running", return_value=(False, None)),
            patch("app._is_local_port_in_use", return_value=False),
            patch("app.ensure_playwright_ready"),
            patch("backend.profile_service.ProfileService") as mock_ps_cls,
            patch("backend.main.run"),
            patch("app._open_browser"),
            patch("app.atexit.register") as mock_atexit,
            patch("app.signal.signal"),
            patch("app.os._exit"),
            patch.object(time, "sleep"),
        ):
            mock_ps = MagicMock()
            mock_ps.load.return_value.system = MagicMock(
                minimize_to_tray=False,
                login_then_exit=False,
                auto_open_browser=True,
            )
            mock_ps_cls.return_value = mock_ps

            _run_server()
            mock_atexit.assert_called()

    def test_tray_failure_graceful(self, tmp_pid_dir, capsys):
        """系统托盘启动失败时降级，不阻塞主流程。"""
        from app import _run_server

        with (
            patch("app._is_service_running", return_value=(False, None)),
            patch("app._is_local_port_in_use", return_value=False),
            patch("app.ensure_playwright_ready"),
            patch("backend.profile_service.ProfileService") as mock_ps_cls,
            patch("backend.main.run"),
            patch("app._open_browser"),
            patch("app.atexit.register"),
            patch("app.signal.signal"),
            patch("app.os._exit"),
            patch.object(time, "sleep"),
            patch("src.system_tray.SystemTray", side_effect=ImportError("no tray")),
        ):
            mock_ps = MagicMock()
            mock_ps.load.return_value.system = MagicMock(
                minimize_to_tray=True,
                login_then_exit=False,
                auto_open_browser=False,
            )
            mock_ps_cls.return_value = mock_ps
            _run_server()

        out = capsys.readouterr().out
        assert "启动系统托盘失败" in out


# ══════════════════════════════════════════════════════════════════════
#  TestSignalHandler
# ══════════════════════════════════════════════════════════════════════


class TestSignalHandler:
    """_run_server 内的信号处理器。"""

    def test_sigint_triggers_cleanup(self, tmp_pid_dir):
        """SIGINT 触发 cleanup 和 os._exit(0)。"""
        from app import _run_server

        registered = {}

        def fake_signal(signum, handler):
            registered[signum] = handler
            return handler

        with (
            patch("app._is_service_running", return_value=(False, None)),
            patch("app._is_local_port_in_use", return_value=False),
            patch("app.ensure_playwright_ready"),
            patch("backend.profile_service.ProfileService") as mock_ps_cls,
            patch("backend.main.run"),
            patch("app._open_browser"),
            patch("app.atexit.register"),
            patch("os._exit") as mock_exit,
            patch.object(time, "sleep"),
            patch("signal.signal", side_effect=fake_signal),
        ):
            mock_ps = MagicMock()
            mock_ps.load.return_value.system = MagicMock(
                minimize_to_tray=False,
                login_then_exit=False,
                auto_open_browser=False,
            )
            mock_ps_cls.return_value = mock_ps
            _run_server()

            # 模拟 SIGINT 触发（仍在 os._exit mock 范围内）
            assert signal.SIGINT in registered
            with (
                patch("app._cleanup_pid"),
                patch("src.playwright_worker.get_worker", side_effect=Exception("not init")),
                patch("src.playwright_worker.cleanup_orphan_browsers"),
            ):
                registered[signal.SIGINT](signal.SIGINT, None)
            mock_exit.assert_called_with(0)

    def test_sigterm_guard_on_windows(self, tmp_pid_dir):
        """_run_server 使用 hasattr(signal, 'SIGTERM') 守卫。"""
        from app import _run_server

        registered = {}

        def fake_signal(signum, handler):
            registered[signum] = handler
            return handler

        with (
            patch("app._is_service_running", return_value=(False, None)),
            patch("app._is_local_port_in_use", return_value=False),
            patch("app.ensure_playwright_ready"),
            patch("backend.profile_service.ProfileService") as mock_ps_cls,
            patch("backend.main.run"),
            patch("app._open_browser"),
            patch("app.atexit.register"),
            patch("signal.signal", side_effect=fake_signal),
            patch("app.os._exit"),
            patch.object(time, "sleep"),
        ):
            mock_ps = MagicMock()
            mock_ps.load.return_value.system = MagicMock(
                minimize_to_tray=False,
                login_then_exit=False,
                auto_open_browser=False,
            )
            mock_ps_cls.return_value = mock_ps
            _run_server()

        # SIGINT 一定被注册
        assert signal.SIGINT in registered
        # SIGTERM 如果存在也会被注册
        if hasattr(signal, "SIGTERM"):
            assert signal.SIGTERM in registered


# ══════════════════════════════════════════════════════════════════════
#  TestIsPackaged
# ══════════════════════════════════════════════════════════════════════


class TestIsPackaged:
    """_is_packaged — sys.frozen / 未打包。"""

    def test_frozen(self):
        from app import _is_packaged

        with patch.object(sys, "frozen", True, create=True):
            assert _is_packaged() is True

    def test_not_packaged(self):
        """当前运行环境非打包状态。"""
        from app import _is_packaged

        # 正常 Python 环境无 frozen 属性，__compiled__ 也不存在
        result = _is_packaged()
        assert result is False


# ══════════════════════════════════════════════════════════════════════
#  TestOpenBrowser
# ══════════════════════════════════════════════════════════════════════


class TestOpenBrowser:
    """_open_browser — 显式 True/False/环境变量。"""

    def test_setting_true(self, patched_webbrowser):
        """setting=True 时应启动后台线程。"""
        from app import _open_browser

        with patch("time.sleep"):
            _open_browser(8080, setting=True)
        # 后台线程在 sleep 后调用 webbrowser.open
        # 给线程足够时间执行
        time.sleep(0.2)

    def test_setting_false(self, patched_webbrowser):
        """setting=False 时不打开浏览器。"""
        from app import _open_browser

        _open_browser(8080, setting=False)
        time.sleep(0.1)
        patched_webbrowser.assert_not_called()

    def test_env_variable_false(self, patched_webbrowser):
        """环境变量 CAMPUS_AUTH_AUTO_OPEN_BROWSER=false 时不打开。"""
        from app import _open_browser

        with patch.dict(os.environ, {"CAMPUS_AUTH_AUTO_OPEN_BROWSER": "false"}):
            _open_browser(8080, setting=None)
        time.sleep(0.1)
        patched_webbrowser.assert_not_called()


# ══════════════════════════════════════════════════════════════════════
#  TestSetupExceptionHooks
# ══════════════════════════════════════════════════════════════════════


class TestSetupExceptionHooks:
    """_setup_exception_hooks — threading.excepthook 已注册。"""

    def test_registers_hook(self):
        from app import _setup_exception_hooks

        original = threading.excepthook
        try:
            _setup_exception_hooks()
            assert threading.excepthook is not original
            assert callable(threading.excepthook)
        finally:
            threading.excepthook = original


# ══════════════════════════════════════════════════════════════════════
#  TestMainArgparse
# ══════════════════════════════════════════════════════════════════════


class TestMainArgparse:
    """main() — 互斥 flags / help 文本。"""

    def test_status_flag(self, tmp_pid_dir):
        """--status 应调用 _cmd_status。"""
        from app import main

        with (
            patch("sys.argv", ["app.py", "--status"]),
            patch("app._setup_exception_hooks"),
            patch("app._cmd_status") as mock_status,
            patch("app._setup_packaged_env"),
        ):
            main()
        mock_status.assert_called_once()

    def test_stop_flag(self, tmp_pid_dir):
        """--stop 应调用 _cmd_stop。"""
        from app import main

        with (
            patch("sys.argv", ["app.py", "--stop"]),
            patch("app._setup_exception_hooks"),
            patch("app._cmd_stop") as mock_stop,
            patch("app._setup_packaged_env"),
        ):
            main()
        mock_stop.assert_called_once()

    def test_help_text(self, capsys):
        """--help 应输出包含示例的帮助文本。"""
        from app import main

        with (
            patch("sys.argv", ["app.py", "--help"]),
            patch("app._setup_exception_hooks"),
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 0
        out = capsys.readouterr().out
        assert "Campus-Auth" in out
        assert "--no-browser" in out
