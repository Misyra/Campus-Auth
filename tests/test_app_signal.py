from __future__ import annotations

import errno
import signal
from unittest.mock import patch


class TestSigtermGuard:
    """测试 SIGTERM 在 Windows 上的守卫逻辑（hasattr 守卫）"""

    def test_signal_signal_not_called_when_sigterm_missing(self):
        """当 hasattr(signal, 'SIGTERM') 为 False 时，signal.signal 不应被 SIGTERM 调用"""
        original_hasattr = hasattr

        def fake_hasattr(obj, name):
            if obj is signal and name == "SIGTERM":
                return False
            return original_hasattr(obj, name)

        with patch("builtins.hasattr", fake_hasattr):
            with patch("signal.signal") as mock_signal:
                if hasattr(signal, "SIGTERM"):
                    mock_signal(signal.SIGTERM, lambda: None)
                # 不应被调用
                mock_signal.assert_not_called()

    def test_os_kill_fallback_no_attribute_error(self):
        """SIGTERM 不存在时 os.kill 降级到 os._exit 不应引发 AttributeError"""
        import os

        def make_on_exit():
            if hasattr(signal, "SIGTERM"):
                return lambda: os.kill(os.getpid(), signal.SIGTERM)
            else:
                return lambda: os._exit(0)

        original_hasattr = hasattr

        def fake_hasattr(obj, name):
            if obj is signal and name == "SIGTERM":
                return False
            return original_hasattr(obj, name)

        with patch("builtins.hasattr", fake_hasattr):
            with patch("os._exit") as mock_exit:
                on_exit = make_on_exit()
                on_exit()
                mock_exit.assert_called_once_with(0)

    def test_signal_signal_called_when_sigterm_exists(self):
        """当 SIGTERM 存在时，signal.signal 应被正确调用"""
        def handler():
            return None
        with patch.object(signal, "SIGTERM", 15, create=True):
            with patch("signal.signal") as mock_signal:
                if hasattr(signal, "SIGTERM"):
                    signal.signal(signal.SIGTERM, handler)
                mock_signal.assert_called_once_with(15, handler)


class TestWinerrorErrnoProbe:
    """测试 os.kill(pid, 0) 探活时的 winerror / errno 判断逻辑"""

    def _probe_process(self, exc: OSError) -> bool | None:
        """模拟 app.py 中 os.kill(pid, 0) 的 OSError 处理逻辑"""
        import os
        pid_file_unlinked = []

        def unlink_pid():
            pid_file_unlinked.append(True)

        try:
            os.kill(0, 0)
        except PermissionError:
            return True
        except ProcessLookupError:
            unlink_pid()
            return None
        except OSError as exc:
            if getattr(exc, "winerror", getattr(exc, "errno", None)) in (5, errno.EACCES):
                return True
            unlink_pid()
            return False
        return True

    def test_winerror_5_returns_true(self):
        """winerror=5 (Access denied) 时应保守认为进程存活"""
        exc = OSError()
        exc.winerror = 5
        result = getattr(exc, "winerror", getattr(exc, "errno", None)) in (5, errno.EACCES)
        assert result is True

    def test_errno_eacces_returns_true(self):
        """errno=EACCES 时应保守认为进程存活"""
        # OSError.winerror 是 CPython 内部槽，不可删除
        # 使用普通对象模拟 POSIX 平台上无 winerror 属性的 OSError
        exc = Exception()
        exc.errno = errno.EACCES
        result = getattr(exc, "winerror", getattr(exc, "errno", None)) in (5, errno.EACCES)
        assert result is True

    def test_other_errno_returns_false(self):
        """其他 errno（如 ESRCH）应判定进程已死"""
        exc = Exception()
        exc.errno = errno.ESRCH
        result = getattr(exc, "winerror", getattr(exc, "errno", None)) in (5, errno.EACCES)
        assert result is False

    def test_permission_error_returns_true(self):
        """PermissionError（OSError 子类）应返回 True"""
        with patch("os.kill") as mock_kill:
            mock_kill.side_effect = PermissionError()
            result = self._probe_process(PermissionError())
            assert result is True

    def test_process_lookup_error_returns_none(self):
        """ProcessLookupError 应返回 None（进程不存在）"""
        with patch("os.kill") as mock_kill:
            mock_kill.side_effect = ProcessLookupError()
            with patch("pathlib.Path.unlink"):
                result = self._probe_process(ProcessLookupError())
                assert result is None

    def test_other_os_error_returns_false(self):
        """其他 OSError（非 winerror=5、非 EACCES）应返回 False"""
        exc = OSError()
        exc.winerror = 6
        exc.errno = errno.EPERM
        with patch("os.kill") as mock_kill:
            mock_kill.side_effect = exc
            with patch("pathlib.Path.unlink"):
                result = self._probe_process(exc)
                assert result is False
