"""src/utils/config_helpers.py 测试"""
from __future__ import annotations

from src.utils.config_helpers import extract_profile_fields, assign_profile_fields


class TestExtractProfileFields:
    def test_basic(self):
        source = {"a": 1, "b": 2, "c": 3}
        result = extract_profile_fields(source, ["a", "c"])
        assert result == {"a": 1, "c": 3}

    def test_missing_keys_skipped(self):
        source = {"a": 1}
        result = extract_profile_fields(source, ["a", "b", "c"])
        assert result == {"a": 1}

    def test_empty_field_names(self):
        assert extract_profile_fields({"a": 1}, []) == {}

    def test_empty_source(self):
        assert extract_profile_fields({}, ["a", "b"]) == {}

    def test_source_extra_keys_not_copied(self):
        source = {"a": 1, "secret": "leaked"}
        result = extract_profile_fields(source, ["a"])
        assert "secret" not in result

    def test_preserves_value_types(self):
        source = {"num": 42, "flag": True, "nested": {"k": "v"}, "none_val": None}
        result = extract_profile_fields(source, ["num", "flag", "nested", "none_val"])
        assert result["num"] == 42
        assert result["flag"] is True
        assert result["nested"] == {"k": "v"}
        assert result["none_val"] is None


class TestAssignProfileFields:
    def test_basic(self):
        target = {"existing": "old"}
        source = {"a": 1, "b": 2}
        assign_profile_fields(target, source, ["a", "b"])
        assert target == {"existing": "old", "a": 1, "b": 2}

    def test_overwrites_existing(self):
        target = {"a": "old"}
        source = {"a": "new"}
        assign_profile_fields(target, source, ["a"])
        assert target["a"] == "new"

    def test_missing_keys_not_assigned(self):
        target = {}
        source = {"a": 1}
        assign_profile_fields(target, source, ["a", "b"])
        assert target == {"a": 1}
        assert "b" not in target

    def test_source_extra_keys_not_copied(self):
        target = {}
        source = {"a": 1, "secret": "leaked"}
        assign_profile_fields(target, source, ["a"])
        assert "secret" not in target

    def test_empty_field_names(self):
        target = {"a": 1}
        assign_profile_fields(target, {"b": 2}, [])
        assert target == {"a": 1}

    def test_empty_source(self):
        target = {"a": 1}
        assign_profile_fields(target, {}, ["a"])
        assert target == {"a": 1}
