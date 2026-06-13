#!/usr/bin/env python3
"""
测试 config_utils.py 中常量类型问题的修复。

验证 PROFILE_FIELDS 应为 tuple 而非 list，确保不可变性。
"""

from app.utils.config_utils import PROFILE_FIELDS


def test_profile_fields_is_tuple():
    """验证 PROFILE_FIELDS 是 tuple 类型"""
    assert isinstance(PROFILE_FIELDS, tuple), \
        f"PROFILE_FIELDS 应为 tuple 类型，实际为 {type(PROFILE_FIELDS)}"


def test_profile_fields_is_not_list():
    """验证 PROFILE_FIELDS 不是 list 类型"""
    assert not isinstance(PROFILE_FIELDS, list), \
        "PROFILE_FIELDS 不应为 list 类型"


def test_profile_fields_not_empty():
    """验证 PROFILE_FIELDS 不为空"""
    assert len(PROFILE_FIELDS) > 0, "PROFILE_FIELDS 不应为空"


def test_profile_fields_contains_expected_fields():
    """验证 PROFILE_FIELDS 包含预期的字段"""
    expected_fields = [
        "username",
        "password",
        "auth_url",
        "active_task",
        "carrier",
        "check_interval_seconds",
        "headless",
    ]
    for field in expected_fields:
        assert field in PROFILE_FIELDS, f"PROFILE_FIELDS 缺少字段: {field}"


def test_profile_fields_is_frozen():
    """验证 PROFILE_FIELDS 不可修改（tuple 的不可变性）"""
    try:
        # tuple 不支持 item assignment
        PROFILE_FIELDS[0] = "modified"
        assert False, "PROFILE_FIELDS 应该是不可变的"
    except TypeError:
        # 预期抛出 TypeError
        pass
