"""异常类测试 — 覆盖自定义异常。"""

from __future__ import annotations

import pytest

from app.utils.exceptions import DecryptionError, LoginCancelledError

# ── LoginCancelledError ──


class TestLoginCancelledError:
    """登录取消异常。"""

    def test_is_exception(self):
        """是 Exception 子类。"""
        assert issubclass(LoginCancelledError, Exception)

    def test_can_raise(self):
        """可以抛出。"""
        with pytest.raises(LoginCancelledError):
            raise LoginCancelledError("cancelled")

    def test_message(self):
        """消息可读取。"""
        try:
            raise LoginCancelledError("test message")
        except LoginCancelledError as e:
            assert str(e) == "test message"


# ── DecryptionError ──


class TestDecryptionError:
    """解密异常。"""

    def test_is_exception(self):
        """是 Exception 子类。"""
        assert issubclass(DecryptionError, Exception)

    def test_can_raise(self):
        """可以抛出。"""
        with pytest.raises(DecryptionError):
            raise DecryptionError("decryption failed")

    def test_message(self):
        """消息可读取。"""
        try:
            raise DecryptionError("test message")
        except DecryptionError as e:
            assert str(e) == "test message"
