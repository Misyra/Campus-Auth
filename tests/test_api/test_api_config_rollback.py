"""测试 config.py 回滚语义 — 确保回滚后 data 仍是合法的 Pydantic 对象。"""

from __future__ import annotations

import pytest

from app.schemas import Profile, ProfilesData


class TestDictUpdateBreaksPydantic:
    """测试 __dict__.update 对 Pydantic 模型的影响。

    Pydantic v2 模型的 __dict__ 包含实例属性，但模型内部还维护了
    __pydantic_fields_set__ 等状态。直接 __dict__.update 会导致
    这些内部状态不一致。
    """

    def test_dict_update_preserves_field_values(self):
        """__dict__.update 能正确替换字段值。"""
        data = ProfilesData(
            profiles={"default": Profile(name="当前方案", username="current")},
        )
        backup = ProfilesData(
            profiles={"default": Profile(name="备份方案", username="backup")},
        )

        # 当前的回滚方式
        data.__dict__.update(backup.__dict__)

        # 字段值确实被替换了
        assert data.profiles["default"].username == "backup"

    def test_dict_update_corrupts_pydantic_fields_set(self):
        """__dict__.update 会破坏 __pydantic_fields_set__，导致 model_dump 行为异常。

        这个测试记录了旧代码（__dict__.update）的已知问题：
        fields_set 不会被正确更新，导致 Pydantic 内部状态不一致。
        """
        # data 只设置了部分字段
        data = ProfilesData(
            profiles={"default": Profile(username="current")},
        )
        # backup 设置了所有字段
        backup = ProfilesData(
            auto_switch=True,
            active_profile="custom",
            profiles={"default": Profile(name="备份方案", username="backup")},
        )

        # 记录 backup 的 fields_set
        backup_fields_set = backup.model_fields_set.copy()

        # __dict__.update 后，data 的 fields_set 不会被更新
        data.__dict__.update(backup.__dict__)

        # 验证：fields_set 没有被正确更新（这是已知的 bug）
        assert data.model_fields_set != backup_fields_set, (
            "__dict__.update 应该不会更新 fields_set"
        )

    def test_dict_update_noop_when_backup_is_same_type(self):
        """当 backup 和 data 是同一类型时，__dict__.update 看起来能工作。

        但这只是巧合——如果 Pydantic 内部结构变化，这种方式就会出问题。
        这个测试记录了当前行为，但不保证未来兼容性。
        """
        data = ProfilesData(
            profiles={"default": Profile(name="当前方案", username="current")},
        )
        backup = ProfilesData(
            profiles={"default": Profile(name="备份方案", username="backup")},
        )

        backup_dump = backup.model_dump()

        # __dict__.update
        data.__dict__.update(backup.__dict__)

        # 当前能工作，但这是实现细节
        assert data.model_dump() == backup_dump

    def test_proper_rollback_via_model_copy(self):
        """正确的回滚方式：使用 model_copy(deep=True)，保持 Pydantic 内部状态一致。"""
        backup = ProfilesData(
            auto_switch=True,
            active_profile="custom",
            profiles={"default": Profile(name="备份方案", username="backup")},
        )

        # 正确的回滚方式（frozen 模型使用 model_copy）
        result = backup.model_copy(deep=True)

        # 字段值正确
        assert result.profiles["default"].username == "backup"
        assert result.auto_switch is True
        assert result.active_profile == "custom"

        # model_dump 也正确
        assert result.model_dump() == backup.model_dump()
