"""app.py 入口模块测试

覆盖 PID 管理、进程检测、CLI 命令、信号处理、浏览器控制、主入口等。
"""

from __future__ import annotations

import os
import signal
import threading
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas import LoginCredentials, LoginResult, RetrySettings, RuntimeConfig

_TEST_CREDS = LoginCredentials(username="u", password="p", auth_url="http://x")

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
        from app.utils.process import get_pid_file

        result = get_pid_file()
        assert tmp_pid_dir.exists()
        assert result == tmp_pid_dir / "campus_network_auth.pid"


# ══════════════════════════════════════════════════════════════════════
#  TestReadPidFile
# ══════════════════════════════════════════════════════════════════════


class TestReadPidFile:
    """_read_pid_file — 多种文件状态。"""

    def test_file_not_exists(self, tmp_pid_dir):
        from app.utils.process import read_pid_file

        assert read_pid_file() is None

    def test_empty_file(self, tmp_pid_dir):
        from app.utils.process import read_pid_file

        _write_raw_pid(tmp_pid_dir, "")
        assert read_pid_file() is None

    def test_json_format(self, tmp_pid_dir):
        """JSON 格式。"""
        import json

        from app.utils.process import read_pid_file

        data = {"pid": 1234, "create_time": 1718191234.123, "mode": "lightweight"}
        _write_raw_pid(tmp_pid_dir, json.dumps(data))
        result = read_pid_file()
        assert result is not None
        assert result["pid"] == 1234
        assert result["create_time"] == 1718191234.123
        assert result["mode"] == "lightweight"

    def test_invalid_content(self, tmp_pid_dir):
        from app.utils.process import read_pid_file

        _write_raw_pid(tmp_pid_dir, "not_a_number")
        assert read_pid_file() is None

    def test_negative_pid(self, tmp_pid_dir):
        """负数 PID。"""
        import json

        from app.utils.process import read_pid_file

        data = {"pid": -1, "create_time": 1718191234.123}
        _write_raw_pid(tmp_pid_dir, json.dumps(data))
        assert read_pid_file() is None


# ══════════════════════════════════════════════════════════════════════
#  TestGetProcessName
# ══════════════════════════════════════════════════════════════════════


class TestGetProcessName:
    """get_process_name — psutil 实现。"""

    @patch("app.utils.process.psutil.Process")
    def test_valid_process(self, mock_process_cls):
        """进程存在时返回进程名。"""
        from app.utils.process import get_process_name

        mock_process_cls.return_value.name.return_value = "python.exe"
        assert get_process_name(1234) == "python.exe"

    @patch("app.utils.process.psutil.Process")
    def test_no_such_process(self, mock_process_cls):
        """进程不存在时返回 None。"""
        import psutil

        from app.utils.process import get_process_name

        mock_process_cls.side_effect = psutil.NoSuchProcess(9999)
        assert get_process_name(9999) is None

    @patch("app.utils.process.psutil.Process")
    def test_access_denied(self, mock_process_cls):
        """权限不足时返回 None。"""
        import psutil

        from app.utils.process import get_process_name

        mock_process_cls.side_effect = psutil.AccessDenied(1234)
        assert get_process_name(1234) is None


# ══════════════════════════════════════════════════════════════════════
#  TestNormalizeProcName
# ══════════════════════════════════════════════════════════════════════


class TestNormalizeProcName:
    """_normalize_proc_name — 大小写 + .exe 后缀。"""

    def test_lowercase_with_exe(self):
        from app.utils.process import normalize_proc_name

        assert normalize_proc_name("Python.EXE") == "python"

    def test_no_exe_suffix(self):
        """无 .exe 后缀时原样返回（小写）。"""
        from app.utils.process import normalize_proc_name

        result = normalize_proc_name("node")
        assert result == "node"

    def test_chrome_exe(self):
        """正确去除 .exe 后缀。"""
        from app.utils.process import normalize_proc_name

        assert normalize_proc_name("chrome.exe") == "chrome"

    def test_axe_no_suffix(self):
        """末尾含 e/x 但非 .exe 后缀时不去除。"""
        from app.utils.process import normalize_proc_name

        assert normalize_proc_name("axe") == "axe"

    def test_exe_only(self):
        """仅 .exe 后缀时去除。"""
        from app.utils.process import normalize_proc_name

        assert normalize_proc_name(".exe") == ""


# ══════════════════════════════════════════════════════════════════════
#  TestIsServiceRunning
# ══════════════════════════════════════════════════════════════════════


class TestIsServiceRunning:
    """_is_service_running — 5 种场景。"""

    def test_no_pid_file(self, tmp_pid_dir):
        from app.utils.process import is_service_running

        running, pid = is_service_running()
        assert running is False
        assert pid is None

    def test_pid_file_but_process_dead(self, tmp_pid_dir):
        """PID 文件存在但进程已死。"""
        import json

        from app.utils.process import is_service_running

        data = {"pid": 1234, "create_time": 1718191234.123, "mode": "full"}
        _write_raw_pid(tmp_pid_dir, json.dumps(data))
        with patch("app.utils.process.verify_process_identity", return_value=False):
            running, pid = is_service_running()
        assert running is False
        assert pid is None
        # 残留 PID 文件应被清理
        assert not (tmp_pid_dir / "campus_network_auth.pid").exists()

    def test_process_identity_mismatch(self, tmp_pid_dir):
        """进程身份不匹配（create_time 不同）。"""
        import json

        from app.utils.process import is_service_running

        data = {"pid": 1234, "create_time": 1718191234.123, "mode": "full"}
        _write_raw_pid(tmp_pid_dir, json.dumps(data))
        with patch("app.utils.process.verify_process_identity", return_value=False):
            running, pid = is_service_running()
        assert running is False

    def test_port_not_listening(self, tmp_pid_dir):
        """完整模式下端口未监听。"""
        import json

        from app.utils.process import is_service_running

        data = {"pid": 1234, "create_time": 1718191234.123, "mode": "full"}
        _write_raw_pid(tmp_pid_dir, json.dumps(data))
        with (
            patch("app.utils.process.verify_process_identity", return_value=True),
            patch("app.utils.process.is_local_port_in_use", return_value=False),
        ):
            running, pid = is_service_running()
        assert running is False

    def test_fully_alive(self, tmp_pid_dir):
        """进程完全存活。"""
        import json

        from app.utils.process import is_service_running

        data = {"pid": 1234, "create_time": 1718191234.123, "mode": "full"}
        _write_raw_pid(tmp_pid_dir, json.dumps(data))
        with (
            patch("app.utils.process.verify_process_identity", return_value=True),
            patch("app.utils.process.is_local_port_in_use", return_value=True),
        ):
            running, pid = is_service_running()
        assert running is True
        assert pid == 1234


# ══════════════════════════════════════════════════════════════════════
#  TestIsLocalPortInUse
# ══════════════════════════════════════════════════════════════════════


class TestIsLocalPortInUse:
    """_is_local_port_in_use — 连接成功/失败。"""

    @patch("socket.socket")
    def test_port_in_use(self, mock_socket_cls):
        from app.utils.process import is_local_port_in_use

        mock_sock = MagicMock()
        mock_sock.__enter__ = MagicMock(return_value=mock_sock)
        mock_sock.__exit__ = MagicMock(return_value=False)
        mock_sock.connect_ex.return_value = 0
        mock_socket_cls.return_value = mock_sock

        assert is_local_port_in_use(8080) is True

    @patch("socket.socket")
    def test_port_free(self, mock_socket_cls):
        from app.utils.process import is_local_port_in_use

        mock_sock = MagicMock()
        mock_sock.__enter__ = MagicMock(return_value=mock_sock)
        mock_sock.__exit__ = MagicMock(return_value=False)
        mock_sock.connect_ex.return_value = 111  # ECONNREFUSED
        mock_socket_cls.return_value = mock_sock

        assert is_local_port_in_use(8080) is False


# ══════════════════════════════════════════════════════════════════════
#  TestWritePid + TestCleanupPid
# ══════════════════════════════════════════════════════════════════════


class TestWritePid:
    """_write_pid — 原子写入。"""

    def test_writes_pid_file(self, tmp_pid_dir):
        import json

        from app.utils.process import get_pid_file, write_pid

        write_pid()
        pid_file = get_pid_file()
        assert pid_file.exists()
        data = json.loads(pid_file.read_text(encoding="utf-8"))
        assert data["pid"] == os.getpid()
        assert "create_time" in data
        assert "proc_name" in data


class TestCleanupPid:
    """_cleanup_pid — missing_ok 行为。"""

    def test_removes_existing_file(self, tmp_pid_dir):
        from app.utils.process import cleanup_pid, get_pid_file

        pid_file = get_pid_file()
        pid_file.write_text("test", encoding="utf-8")
        cleanup_pid()
        assert not pid_file.exists()

    def test_no_error_when_missing(self, tmp_pid_dir):
        from app.utils.process import cleanup_pid

        # 文件不存在时不应抛异常
        cleanup_pid()


# ══════════════════════════════════════════════════════════════════════
#  TestCmdStatus
# ══════════════════════════════════════════════════════════════════════


class TestCmdStatus:
    """_cmd_status — 4 种输出场景。"""

    def test_running(self, tmp_pid_dir, capsys):
        from main import _cmd_status

        _write_raw_pid(tmp_pid_dir, "1234\npython.exe|2026-01-01")
        with (
            patch("main.is_service_running", return_value=(True, 1234)),
            patch("main.is_local_port_in_use", return_value=True),
        ):
            _cmd_status()
        assert "正在运行" in capsys.readouterr().out

    def test_port_in_use_not_running(self, tmp_pid_dir, capsys):
        from main import _cmd_status

        with (
            patch("main.is_service_running", return_value=(False, None)),
            patch("main.is_local_port_in_use", return_value=True),
        ):
            _cmd_status()
        assert "疑似正在运行" in capsys.readouterr().out

    def test_stale_pid_file(self, tmp_pid_dir, capsys):
        """有残留 PID 文件但进程已死。"""
        from app.utils.process import get_pid_file
        from main import _cmd_status

        _write_raw_pid(tmp_pid_dir, "1234\npython.exe|2026-01-01")

        def fake_is_service_running():
            get_pid_file().unlink(missing_ok=True)
            return False, None

        with (
            patch("main.is_service_running", side_effect=fake_is_service_running),
            patch("main.is_local_port_in_use", return_value=False),
        ):
            _cmd_status()
        out = capsys.readouterr().out
        assert "残留 PID 文件已清理" in out

    def test_not_running_no_pid(self, tmp_pid_dir, capsys):
        from main import _cmd_status

        with (
            patch("main.is_service_running", return_value=(False, None)),
            patch("main.is_local_port_in_use", return_value=False),
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
        from main import _cmd_stop

        with patch("main.is_service_running", return_value=(False, None)):
            _cmd_stop()
        assert "未运行" in capsys.readouterr().out

    def test_graceful_stop(self, tmp_pid_dir, capsys):
        """优雅停止：先 SIGTERM，等待后进程退出。"""
        from main import _cmd_stop

        with (
            patch("main.is_service_running", return_value=(True, 1234)),
            patch("main._terminate_process") as mock_terminate,
        ):
            _cmd_stop()
        mock_terminate.assert_called_once_with(1234)
        out = capsys.readouterr().out
        assert "已停止" in out

    def test_force_stop(self, tmp_pid_dir, capsys):
        """优雅停止超时后强制停止（Windows 路径：taskkill）。"""
        from main import _cmd_stop

        with (
            patch("main.is_service_running", return_value=(True, 1234)),
            patch("main._terminate_process") as mock_terminate,
        ):
            _cmd_stop()
        mock_terminate.assert_called_once_with(1234)
        assert "服务已停止" in capsys.readouterr().out


# ══════════════════════════════════════════════════════════════════════
#  TestCmdAutostart
# ══════════════════════════════════════════════════════════════════════


class TestCmdAutostart:
    """_cmd_autostart — status/enable/disable。"""

    @patch("app.services.autostart.AutoStartService")
    def test_status(self, mock_cls, capsys):
        from main import _cmd_autostart

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

    @patch("app.services.autostart.AutoStartService")
    def test_enable(self, mock_cls, capsys):
        from main import _cmd_autostart

        mock_instance = MagicMock()
        mock_instance.enable.return_value = (True, "已启用开机自启动")
        mock_cls.return_value = mock_instance

        with pytest.raises(SystemExit) as exc_info:
            _cmd_autostart("enable")
        assert exc_info.value.code == 0

    @patch("app.services.autostart.AutoStartService")
    def test_disable(self, mock_cls, capsys):
        from main import _cmd_autostart

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
        """首次登录成功应返回 SUCCESS。"""
        from main import _run_login_then_exit

        mock_worker, mock_ps, mock_data = self._make_mocks()
        success_result = MagicMock(success=True, data="ok")
        mock_worker.submit.return_value = success_result

        # 所有 local import 需要 patch 到源模块
        mock_ps.get_runtime_config.return_value = RuntimeConfig(credentials=_TEST_CREDS, retry=RetrySettings(max_retries=3))
        with (
            patch("app.workers.playwright_worker.get_worker", return_value=mock_worker),
            patch("app.workers.playwright_worker.CMD_LOGIN", "login"),
            patch("main.create_profile_service", return_value=mock_ps),
            patch("main.cleanup_orphan_browsers"),
            patch("time.sleep"),
        ):
            mock_ps.load.return_value = mock_data
            mock_ctx = MagicMock()
            result = _run_login_then_exit(mock_ctx, MagicMock())
            assert result == LoginResult.SUCCESS

    def test_retry_then_succeed(self, tmp_pid_dir):
        """第一次失败、第二次成功。返回 SUCCESS。"""
        from main import _run_login_then_exit

        mock_worker, mock_ps, mock_data = self._make_mocks()
        fail_result = MagicMock(success=False, error="timeout")
        success_result = MagicMock(success=True, data="ok")
        mock_worker.submit.side_effect = [fail_result, success_result]

        mock_ps.get_runtime_config.return_value = RuntimeConfig(credentials=_TEST_CREDS, retry=RetrySettings(max_retries=3, retry_interval=1))
        with (
            patch("app.workers.playwright_worker.get_worker", return_value=mock_worker),
            patch("app.workers.playwright_worker.CMD_LOGIN", "login"),
            patch("main.create_profile_service", return_value=mock_ps),
            patch("main.cleanup_orphan_browsers"),
            patch("time.sleep"),
        ):
            mock_ps.load.return_value = mock_data
            mock_ctx = MagicMock()
            result = _run_login_then_exit(mock_ctx, MagicMock())
            assert result == LoginResult.SUCCESS

    def test_retries_exhausted(self, tmp_pid_dir):
        """所有重试均失败，返回 TEMPORARY_FAILURE。"""
        from main import _run_login_then_exit

        mock_worker, mock_ps, mock_data = self._make_mocks()
        fail_result = MagicMock(success=False, error="timeout")
        mock_worker.submit.return_value = fail_result

        mock_ps.get_runtime_config.return_value = RuntimeConfig(credentials=_TEST_CREDS, retry=RetrySettings(max_retries=2, retry_interval=1))
        with (
            patch("app.workers.playwright_worker.get_worker", return_value=mock_worker),
            patch("app.workers.playwright_worker.CMD_LOGIN", "login"),
            patch("main.create_profile_service", return_value=mock_ps),
            patch(
                "app.network.decision.check_network_status",
                return_value=(False, "network_down", "none"),
            ),
            patch("main.cleanup_orphan_browsers"),
            patch("time.sleep"),
        ):
            mock_ps.load.return_value = mock_data
            mock_ctx = MagicMock()
            mock_logger = MagicMock()
            result = _run_login_then_exit(mock_ctx, mock_logger)
            assert result == LoginResult.TEMPORARY_FAILURE
            mock_logger.warning.assert_called_once()

    def test_network_already_connected_exits(self, tmp_pid_dir):
        """网络已连接时应返回 SUCCESS，不启动浏览器登录。"""
        from main import _run_login_then_exit

        mock_worker, mock_ps, mock_data = self._make_mocks()

        mock_ps.get_runtime_config.return_value = RuntimeConfig(credentials=_TEST_CREDS, retry=RetrySettings(max_retries=3))
        with (
            patch("app.workers.playwright_worker.get_worker", return_value=mock_worker),
            patch("app.workers.playwright_worker.CMD_LOGIN", "login"),
            patch("main.create_profile_service", return_value=mock_ps),
            patch(
                "app.network.decision.check_network_status",
                return_value=(True, "network_ok", "tcp"),
            ),
        ):
            mock_ps.load.return_value = mock_data
            mock_ctx = MagicMock()
            result = _run_login_then_exit(mock_ctx, MagicMock())
            assert result == LoginResult.SUCCESS
            # 不应调用登录
            mock_worker.submit.assert_not_called()

    def test_network_down_proceeds_with_login(self, tmp_pid_dir):
        """网络未连接时应继续尝试登录，返回 SUCCESS。"""
        from main import _run_login_then_exit

        mock_worker, mock_ps, mock_data = self._make_mocks()
        success_result = MagicMock(success=True, data="ok")
        mock_worker.submit.return_value = success_result

        mock_ps.get_runtime_config.return_value = RuntimeConfig(credentials=_TEST_CREDS, retry=RetrySettings(max_retries=3))
        with (
            patch("app.workers.playwright_worker.get_worker", return_value=mock_worker),
            patch("app.workers.playwright_worker.CMD_LOGIN", "login"),
            patch("main.create_profile_service", return_value=mock_ps),
            patch(
                "app.network.decision.check_network_status",
                return_value=(False, "network_down", "none"),
            ),
            patch("main.cleanup_orphan_browsers"),
            patch("time.sleep"),
        ):
            mock_ps.load.return_value = mock_data
            mock_ctx = MagicMock()
            result = _run_login_then_exit(mock_ctx, MagicMock())
            assert result == LoginResult.SUCCESS
            mock_worker.submit.assert_called_once()

    def test_network_check_exception_proceeds(self, tmp_pid_dir):
        """网络检测异常时应降级继续尝试登录，返回 SUCCESS。"""
        from main import _run_login_then_exit

        mock_worker, mock_ps, mock_data = self._make_mocks()
        success_result = MagicMock(success=True, data="ok")
        mock_worker.submit.return_value = success_result

        mock_ps.get_runtime_config.return_value = RuntimeConfig(credentials=_TEST_CREDS, retry=RetrySettings(max_retries=3))
        with (
            patch("app.workers.playwright_worker.get_worker", return_value=mock_worker),
            patch("app.workers.playwright_worker.CMD_LOGIN", "login"),
            patch("main.create_profile_service", return_value=mock_ps),
            patch(
                "app.network.decision.check_network_status",
                side_effect=RuntimeError("probe failed"),
            ),
            patch("main.cleanup_orphan_browsers"),
            patch("time.sleep"),
        ):
            mock_ps.load.return_value = mock_data
            mock_ctx = MagicMock()
            result = _run_login_then_exit(mock_ctx, MagicMock())
            assert result == LoginResult.SUCCESS
            mock_worker.submit.assert_called_once()


class TestLoginOnceRetryInterval:
    """login_once 固定间隔重试 + login_timeout 统一。"""

    def test_fixed_retry_interval(self, tmp_pid_dir):
        """重试间隔应为固定值，不使用指数退避。"""
        from main import _execute_login_with_retries

        mock_worker = MagicMock()
        fail_result = MagicMock(success=False, error="timeout")
        success_result = MagicMock(success=True, data="ok")
        mock_worker.submit.side_effect = [fail_result, fail_result, success_result]

        runtime_config = RuntimeConfig(credentials=_TEST_CREDS, retry=RetrySettings(max_retries=3, retry_interval=5))

        with (
            patch("app.workers.playwright_worker.get_worker", return_value=mock_worker),
            patch("app.workers.playwright_worker.CMD_LOGIN", "login"),
            patch("app.services.profile_service.ProfileService"),
            patch("app.services.login_history_service.LoginHistoryService"),
            patch("main.AUTH_DATA_DIR", tmp_pid_dir),
            patch("main.cleanup_orphan_browsers"),
            patch("time.sleep") as mock_sleep,
        ):
            result = _execute_login_with_retries(runtime_config, MagicMock())
            assert result == LoginResult.SUCCESS
            # 两次重试都应 sleep(retry_interval=5)，而非指数递增
            assert mock_sleep.call_count == 2
            for call in mock_sleep.call_args_list:
                assert call.args == (5,)

    def test_login_timeout_passed_to_worker(self, tmp_pid_dir):
        """login_timeout 应从配置读取并传递给 worker。"""
        from main import _execute_login_with_retries

        mock_worker = MagicMock()
        success_result = MagicMock(success=True, data="ok")
        mock_worker.submit.return_value = success_result

        from app.schemas import BrowserSettings
        runtime_config = RuntimeConfig(
            credentials=_TEST_CREDS,
            retry=RetrySettings(max_retries=1),
            browser=BrowserSettings(login_timeout=200),
        )

        with (
            patch("app.workers.playwright_worker.get_worker", return_value=mock_worker),
            patch("app.workers.playwright_worker.CMD_LOGIN", "login"),
            patch("app.services.profile_service.ProfileService"),
            patch("app.services.login_history_service.LoginHistoryService"),
            patch("main.AUTH_DATA_DIR", tmp_pid_dir),
            patch("main.cleanup_orphan_browsers"),
            patch("time.sleep"),
        ):
            _execute_login_with_retries(runtime_config, MagicMock())
            mock_worker.submit.assert_called_once()
            call_kwargs = mock_worker.submit.call_args
            assert call_kwargs.kwargs["timeout"] == 200

    def test_login_timeout_default(self, tmp_pid_dir):
        """配置中无 login_timeout 时由 Orchestrator 兜底（resolve_worker_timeout fallback=300）。"""
        from main import _execute_login_with_retries

        mock_worker = MagicMock()
        success_result = MagicMock(success=True, data="ok")
        mock_worker.submit.return_value = success_result

        runtime_config = RuntimeConfig(credentials=_TEST_CREDS, retry=RetrySettings(max_retries=1))

        with (
            patch("app.workers.playwright_worker.get_worker", return_value=mock_worker),
            patch("app.workers.playwright_worker.CMD_LOGIN", "login"),
            patch("app.services.profile_service.ProfileService"),
            patch("app.services.login_history_service.LoginHistoryService"),
            patch("main.AUTH_DATA_DIR", tmp_pid_dir),
            patch("main.cleanup_orphan_browsers"),
            patch("time.sleep"),
        ):
            result = _execute_login_with_retries(runtime_config, MagicMock())
            assert result == LoginResult.SUCCESS


# ══════════════════════════════════════════════════════════════════════
#  TestRunServer
# ══════════════════════════════════════════════════════════════════════


class TestRunServer:
    """_run_server — 已运行/PID 写入+atexit/托盘降级。"""

    def test_already_running(self, tmp_pid_dir, patched_webbrowser):
        """检测到已运行时打开浏览器并退出。"""
        from app.schemas import (
            AppConfig,
            ApplicationContext,
            LaunchContext,
            LaunchSource,
            RuntimeMode,
        )
        from main import _run_server

        mock_ctx = MagicMock(spec=ApplicationContext)
        mock_ctx.config = MagicMock(spec=AppConfig)
        mock_ctx.config.runtime_mode = RuntimeMode.FULL
        mock_ctx.launch = MagicMock(spec=LaunchContext)
        mock_ctx.launch.source = LaunchSource.MANUAL

        with (
            patch("main.is_service_running", return_value=(True, 1234)),
            patch("main.is_local_port_in_use", return_value=True),
            patch("app.utils.ports.resolve_port", return_value=50721),
        ):
            with pytest.raises(SystemExit) as exc_info:
                _run_server(mock_ctx)
            assert exc_info.value.code == 0
        patched_webbrowser.assert_called_once()

    def test_writes_pid_and_registers_atexit(self, tmp_pid_dir):
        """正常启动时写入 PID 文件并注册 atexit 清理。"""
        from app.schemas import (
            AppConfig,
            ApplicationContext,
            LaunchContext,
            LaunchSource,
            RuntimeMode,
            StartupAction,
        )
        from main import _run_server

        mock_ctx = MagicMock(spec=ApplicationContext)
        mock_ctx.config = MagicMock(spec=AppConfig)
        mock_ctx.config.startup_action = StartupAction.NONE
        mock_ctx.config.runtime_mode = RuntimeMode.FULL
        mock_ctx.config.minimize_to_tray = False
        mock_ctx.config.auto_open_browser = True
        mock_ctx.launch = MagicMock(spec=LaunchContext)
        mock_ctx.launch.source = LaunchSource.MANUAL

        with (
            patch("main.is_service_running", return_value=(False, None)),
            patch("main.is_local_port_in_use", return_value=False),
            patch("main.ensure_playwright_ready"),
            patch("app.utils.ports.resolve_port", return_value=50721),
            patch("app.services.profile_service.ProfileService") as mock_ps_cls,
            patch("app.container.ServiceContainer") as mock_container_cls,
            patch("app.application.create_app") as mock_create_app,
            patch("app.application.run"),
            patch("main._open_browser"),
            patch("main.atexit.register") as mock_atexit,
            patch("main.signal.signal"),
            patch("main.os._exit"),
            patch.object(time, "sleep", side_effect=[None, KeyboardInterrupt]),
        ):
            mock_ps = MagicMock()
            mock_ps.load.return_value.system = MagicMock(
                access_log=False,
                log_retention_days=7,
            )
            mock_ps_cls.return_value = mock_ps
            mock_create_app.return_value = MagicMock()
            mock_container_cls.return_value.stop_web_services = AsyncMock()
            mock_container_cls.return_value.shutdown = AsyncMock()

            _run_server(mock_ctx)
            mock_atexit.assert_called()

    def test_tray_failure_graceful(self, tmp_pid_dir, caplog):
        """系统托盘启动失败时降级，不阻塞主流程。"""
        from app.schemas import (
            AppConfig,
            ApplicationContext,
            LaunchContext,
            LaunchSource,
            RuntimeMode,
            StartupAction,
        )
        from main import _run_server

        mock_ctx = MagicMock(spec=ApplicationContext)
        mock_ctx.config = MagicMock(spec=AppConfig)
        mock_ctx.config.startup_action = StartupAction.NONE
        mock_ctx.config.runtime_mode = RuntimeMode.FULL
        mock_ctx.config.minimize_to_tray = True
        mock_ctx.config.auto_open_browser = False
        mock_ctx.launch = MagicMock(spec=LaunchContext)
        mock_ctx.launch.source = LaunchSource.MANUAL

        with (
            patch("main.is_service_running", return_value=(False, None)),
            patch("main.is_local_port_in_use", return_value=False),
            patch("main.ensure_playwright_ready"),
            patch("app.utils.ports.resolve_port", return_value=50721),
            patch("app.services.profile_service.ProfileService") as mock_ps_cls,
            patch("app.container.ServiceContainer") as mock_container_cls,
            patch("app.application.create_app") as mock_create_app,
            patch("app.application.run"),
            patch("main._open_browser"),
            patch("main.atexit.register"),
            patch("main.signal.signal"),
            patch("main.os._exit"),
            patch.object(time, "sleep", side_effect=[None, KeyboardInterrupt]),
            patch("app.ui.system_tray.SystemTray", side_effect=ImportError("no tray")),
        ):
            mock_ps = MagicMock()
            mock_ps.load.return_value.system = MagicMock(
                access_log=False,
                log_retention_days=7,
            )
            mock_ps_cls.return_value = mock_ps
            mock_create_app.return_value = MagicMock()
            mock_container_cls.return_value.stop_web_services = AsyncMock()
            mock_container_cls.return_value.shutdown = AsyncMock()
            _run_server(mock_ctx)

        assert "启动系统托盘失败" in caplog.text

    def test_login_then_exit_without_autostart_skipped(self, tmp_pid_dir):
        """startup_action=LOGIN_ONCE 时调用 handle_startup_action。"""
        from app.schemas import (
            AppConfig,
            ApplicationContext,
            LaunchContext,
            LaunchSource,
            RuntimeMode,
            StartupAction,
        )
        from main import _run_server

        mock_ctx = MagicMock(spec=ApplicationContext)
        mock_ctx.config = MagicMock(spec=AppConfig)
        mock_ctx.config.startup_action = StartupAction.LOGIN_ONCE
        mock_ctx.config.runtime_mode = RuntimeMode.FULL
        mock_ctx.config.minimize_to_tray = False
        mock_ctx.config.auto_open_browser = True
        mock_ctx.launch = MagicMock(spec=LaunchContext)
        mock_ctx.launch.source = LaunchSource.MANUAL

        with (
            patch("main.is_service_running", return_value=(False, None)),
            patch("main.is_local_port_in_use", return_value=False),
            patch("main.ensure_playwright_ready"),
            patch("app.utils.ports.resolve_port", return_value=50721),
            patch("app.services.profile_service.ProfileService") as mock_ps_cls,
            patch("app.container.ServiceContainer") as mock_container_cls,
            patch("app.application.create_app") as mock_create_app,
            patch("app.application.run"),
            patch("main._open_browser"),
            patch("main.atexit.register"),
            patch("main.signal.signal"),
            patch("main.os._exit"),
            patch.object(time, "sleep", side_effect=[None, KeyboardInterrupt]),
            patch(
                "main.handle_startup_action", return_value=(MagicMock(), False)
            ) as mock_handle,
        ):
            mock_ps = MagicMock()
            mock_ps.load.return_value.system = MagicMock(
                access_log=False,
                log_retention_days=7,
            )
            mock_ps_cls.return_value = mock_ps
            mock_create_app.return_value = MagicMock()
            mock_container_cls.return_value.stop_web_services = AsyncMock()
            mock_container_cls.return_value.shutdown = AsyncMock()

            _run_server(mock_ctx)
            mock_handle.assert_called_once()


# ══════════════════════════════════════════════════════════════════════
#  TestSignalHandler
# ══════════════════════════════════════════════════════════════════════


class TestSignalHandler:
    """_run_server 内的信号处理器。"""

    def _make_ctx(self):
        """创建测试用 ApplicationContext。"""
        from app.schemas import (
            AppConfig,
            ApplicationContext,
            LaunchContext,
            LaunchSource,
            RuntimeMode,
            StartupAction,
        )

        mock_ctx = MagicMock(spec=ApplicationContext)
        mock_ctx.config = MagicMock(spec=AppConfig)
        mock_ctx.config.startup_action = StartupAction.NONE
        mock_ctx.config.runtime_mode = RuntimeMode.FULL
        mock_ctx.config.minimize_to_tray = False
        mock_ctx.config.auto_open_browser = False
        mock_ctx.launch = MagicMock(spec=LaunchContext)
        mock_ctx.launch.source = LaunchSource.MANUAL
        return mock_ctx

    def test_sigint_triggers_cleanup(self, tmp_pid_dir):
        """SIGINT 触发 cleanup 和 os._exit(0)。"""
        from main import _run_server

        registered = {}

        def fake_signal(signum, handler):
            registered[signum] = handler
            return handler

        with (
            patch("main.is_service_running", return_value=(False, None)),
            patch("main.is_local_port_in_use", return_value=False),
            patch("main.ensure_playwright_ready"),
            patch("app.utils.ports.resolve_port", return_value=50721),
            patch("app.services.profile_service.ProfileService") as mock_ps_cls,
            patch("app.container.ServiceContainer") as mock_container_cls,
            patch("app.application.create_app") as mock_create_app,
            patch("app.application.run"),
            patch("main._open_browser"),
            patch("main.atexit.register"),
            patch("os._exit") as mock_exit,
            patch.object(time, "sleep", side_effect=[None, KeyboardInterrupt]),
            patch("signal.signal", side_effect=fake_signal),
            patch("asyncio.run"),  # 防止 Runner 注册自己的 SIGINT handler
        ):
            mock_ps = MagicMock()
            mock_ps.load.return_value.system = MagicMock(
                access_log=False,
                log_retention_days=7,
            )
            mock_ps_cls.return_value = mock_ps
            mock_create_app.return_value = MagicMock()
            mock_container_cls.return_value.stop_web_services = AsyncMock()
            mock_container_cls.return_value.shutdown = AsyncMock()
            _run_server(self._make_ctx())

            # 模拟 SIGINT 触发（仍在 os._exit mock 范围内）
            assert signal.SIGINT in registered
            with (
                patch("main.cleanup_pid"),
                patch(
                    "app.workers.playwright_worker.get_worker",
                    side_effect=Exception("not init"),
                ),
                patch("app.workers.playwright_worker.cleanup_orphan_browsers"),
            ):
                registered[signal.SIGINT](signal.SIGINT, None)
            mock_exit.assert_called_with(0)

    def test_sigterm_guard_on_windows(self, tmp_pid_dir):
        """_run_server 使用 hasattr(signal, 'SIGTERM') 守卫。"""
        from main import _run_server

        registered = {}

        def fake_signal(signum, handler):
            registered[signum] = handler
            return handler

        with (
            patch("main.is_service_running", return_value=(False, None)),
            patch("main.is_local_port_in_use", return_value=False),
            patch("main.ensure_playwright_ready"),
            patch("app.utils.ports.resolve_port", return_value=50721),
            patch("app.services.profile_service.ProfileService") as mock_ps_cls,
            patch("app.container.ServiceContainer") as mock_container_cls,
            patch("app.application.create_app") as mock_create_app,
            patch("app.application.run"),
            patch("main._open_browser"),
            patch("main.atexit.register"),
            patch("signal.signal", side_effect=fake_signal),
            patch("main.os._exit"),
            patch.object(time, "sleep", side_effect=[None, KeyboardInterrupt]),
            patch("asyncio.run"),  # 防止 Runner 注册自己的 SIGINT handler
        ):
            mock_ps = MagicMock()
            mock_ps.load.return_value.system = MagicMock(
                access_log=False,
                log_retention_days=7,
            )
            mock_ps_cls.return_value = mock_ps
            mock_create_app.return_value = MagicMock()
            mock_container_cls.return_value.stop_web_services = AsyncMock()
            mock_container_cls.return_value.shutdown = AsyncMock()
            _run_server(self._make_ctx())

        # SIGINT 一定被注册
        assert signal.SIGINT in registered
        # SIGTERM 如果存在也会被注册
        if hasattr(signal, "SIGTERM"):
            assert signal.SIGTERM in registered


# ══════════════════════════════════════════════════════════════════════
#  TestOpenBrowser
# ══════════════════════════════════════════════════════════════════════


class TestOpenBrowser:
    """_open_browser — 显式 True/False/环境变量。"""

    def test_setting_true(self, patched_webbrowser):
        """setting=True 时应启动后台线程。"""
        from main import _open_browser

        threads = []
        original_thread = threading.Thread

        def capture_thread(*args, **kwargs):
            t = original_thread(*args, **kwargs)
            threads.append(t)
            return t

        with patch("time.sleep"), patch("threading.Thread", side_effect=capture_thread):
            _open_browser(8080, setting=True)
        # 等待后台线程完成（time.sleep 已被 mock，线程会立即执行）
        for t in threads:
            t.join(timeout=2)

    def test_setting_false(self, patched_webbrowser):
        """setting=False 时不打开浏览器。"""
        from main import _open_browser

        _open_browser(8080, setting=False)
        patched_webbrowser.assert_not_called()

    def test_setting_none_not_open(self, patched_webbrowser):
        """setting=None 时不打开浏览器。"""
        from main import _open_browser

        _open_browser(8080, setting=None)
        patched_webbrowser.assert_not_called()


# ══════════════════════════════════════════════════════════════════════
#  TestSetupExceptionHooks
# ══════════════════════════════════════════════════════════════════════


class TestSetupExceptionHooks:
    """_setup_exception_hooks — threading.excepthook 已注册。"""

    def test_registers_hook(self):
        from main import _setup_exception_hooks

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
        from main import main

        with (
            patch("sys.argv", ["app.py", "--status"]),
            patch("main._setup_exception_hooks"),
            patch("main._cmd_status") as mock_status,
        ):
            main()
        mock_status.assert_called_once()

    def test_stop_flag(self, tmp_pid_dir):
        """--stop 应调用 _cmd_stop。"""
        from main import main

        with (
            patch("sys.argv", ["app.py", "--stop"]),
            patch("main._setup_exception_hooks"),
            patch("main._cmd_stop") as mock_stop,
        ):
            main()
        mock_stop.assert_called_once()

    def test_help_text(self, capsys):
        """--help 应输出包含示例的帮助文本。"""
        from main import main

        with (
            patch("sys.argv", ["app.py", "--help"]),
            patch("main._setup_exception_hooks"),
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 0
        out = capsys.readouterr().out
        assert "Campus-Auth" in out
        assert "--no-browser" in out
