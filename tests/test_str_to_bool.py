"""src/utils/__init__.py — str_to_bool 测试"""
from __future__ import annotations

import pytest
from src.utils import str_to_bool


class TestStrToBool:
    @pytest.mark.parametrize("value", ["true", "True", "TRUE", " true ", "1", "yes", "YES", "on", "ON"])
    def test_truthy(self, value):
        assert str_to_bool(value) is True

    @pytest.mark.parametrize("value", ["false", "False", "0", "no", "off", "", "anything", "  "])
    def test_falsy(self, value):
        assert str_to_bool(value) is False

    def test_non_string_int_1(self):
        assert str_to_bool(1) is True

    def test_non_string_int_0(self):
        assert str_to_bool(0) is False

    def test_none(self):
        assert str_to_bool(None) is False
