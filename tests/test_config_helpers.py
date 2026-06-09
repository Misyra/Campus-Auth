"""配置辅助工具测试 — 覆盖 extract_profile_fields 和 assign_profile_fields。"""

from __future__ import annotations

from app.utils.config_helpers import (
    PROFILE_FIELDS,
    assign_profile_fields,
    extract_profile_fields,
)

# ── PROFILE_FIELDS ──


class TestProfileFields:
    """字段列表。"""

    def test_not_empty(self):
        """非空。"""
        assert len(PROFILE_FIELDS) > 0

    def test_contains_essential_fields(self):
        """包含必需字段。"""
        assert "username" in PROFILE_FIELDS
        assert "password" in PROFILE_FIELDS
        assert "auth_url" in PROFILE_FIELDS

    def test_no_duplicates(self):
        """无重复。"""
        assert len(PROFILE_FIELDS) == len(set(PROFILE_FIELDS))


# ── extract_profile_fields ──


class TestExtractProfileFields:
    """字段提取。"""

    def test_basic_extraction(self):
        """基本提取。"""
        source = {"username": "admin", "password": "pass", "other": "ignored"}
        result = extract_profile_fields(source, ["username", "password"])
        assert result == {"username": "admin", "password": "pass"}

    def test_missing_field_skipped(self):
        """缺失字段被跳过。"""
        source = {"username": "admin"}
        result = extract_profile_fields(source, ["username", "password"])
        assert result == {"username": "admin"}

    def test_empty_source(self):
        """空源字典。"""
        result = extract_profile_fields({}, ["username"])
        assert result == {}

    def test_empty_field_names(self):
        """空字段列表。"""
        source = {"username": "admin"}
        result = extract_profile_fields(source, [])
        assert result == {}

    def test_extra_fields_ignored(self):
        """额外字段被忽略。"""
        source = {"username": "admin", "extra": "value"}
        result = extract_profile_fields(source, ["username"])
        assert "extra" not in result


# ── assign_profile_fields ──


class TestAssignProfileFields:
    """字段赋值。"""

    def test_basic_assignment(self):
        """基本赋值。"""
        target = {"existing": "keep"}
        source = {"username": "admin", "password": "pass"}
        assign_profile_fields(target, source, ["username", "password"])
        assert target["username"] == "admin"
        assert target["password"] == "pass"
        assert target["existing"] == "keep"

    def test_overwrites_existing(self):
        """覆盖已有字段。"""
        target = {"username": "old"}
        source = {"username": "new"}
        assign_profile_fields(target, source, ["username"])
        assert target["username"] == "new"

    def test_missing_source_field_skipped(self):
        """源中缺失字段被跳过。"""
        target = {"username": "old"}
        source = {}
        assign_profile_fields(target, source, ["username"])
        assert target["username"] == "old"

    def test_empty_field_names(self):
        """空字段列表不修改 target。"""
        target = {"username": "old"}
        source = {"username": "new"}
        assign_profile_fields(target, source, [])
        assert target["username"] == "old"

    def test_empty_source(self):
        """空源不修改 target。"""
        target = {"username": "old"}
        assign_profile_fields(target, {}, ["username"])
        assert target["username"] == "old"

    def test_target_not_modified_for_missing(self):
        """target 中不存在的字段不被添加。"""
        target = {}
        source = {"username": "admin"}
        assign_profile_fields(target, source, ["username"])
        assert target == {"username": "admin"}
