"""_safe_psutil_call 返回类型一致性测试。"""

from __future__ import annotations

import psutil
import pytest

from app.api.system import _safe_psutil_call


class TestSafePsutilCall:
    """_safe_psutil_call 函数测试。"""

    def test_returns_fn_result_on_success(self):
        """正常调用返回 fn() 的结果。"""
        result = _safe_psutil_call(lambda: [1, 2, 3])
        assert result == [1, 2, 3]

    def test_returns_empty_list_on_access_denied(self):
        """AccessDenied 异常时返回空列表。"""

        def raise_access_denied():
            raise psutil.AccessDenied(pid=1)

        result = _safe_psutil_call(raise_access_denied)
        assert result == []
        assert isinstance(result, list)

    def test_returns_empty_list_on_no_such_process(self):
        """NoSuchProcess 异常时返回空列表。"""

        def raise_no_such_process():
            raise psutil.NoSuchProcess(pid=999999)

        result = _safe_psutil_call(raise_no_such_process)
        assert result == []
        assert isinstance(result, list)

    def test_returns_empty_list_on_zombie_process(self):
        """ZombieProcess 异常时返回空列表。"""

        def raise_zombie():
            raise psutil.ZombieProcess(pid=999999)

        result = _safe_psutil_call(raise_zombie)
        assert result == []
        assert isinstance(result, list)

    def test_returns_custom_default_when_provided(self):
        """传入自定义 default 时使用该默认值。"""

        def raise_access_denied():
            raise psutil.AccessDenied(pid=1)

        result = _safe_psutil_call(raise_access_denied, default=-1)
        assert result == -1

    def test_default_none_becomes_empty_list(self):
        """default=None 时内部转换为空列表。"""

        def raise_access_denied():
            raise psutil.AccessDenied(pid=1)

        result = _safe_psutil_call(raise_access_denied, default=None)
        assert result == []
        assert isinstance(result, list)

    def test_other_exceptions_propagate(self):
        """非 psutil 异常正常抛出。"""

        def raise_value_error():
            raise ValueError("unexpected")

        with pytest.raises(ValueError, match="unexpected"):
            _safe_psutil_call(raise_value_error)
