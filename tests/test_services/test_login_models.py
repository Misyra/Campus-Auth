"""login_models 单元测试 — AttemptOutcomeType / AttemptOutcome。"""

from __future__ import annotations

import dataclasses

import pytest

from app.services.login_models import AttemptOutcome, AttemptOutcomeType


class TestAttemptOutcomeType:
    def test_is_strenum(self):
        """AttemptOutcomeType 是 StrEnum，可直接与字符串比较。"""
        assert AttemptOutcomeType.SUCCESS == "success"
        assert AttemptOutcomeType.RETRYABLE == "retryable"
        assert AttemptOutcomeType.INVALID_CREDENTIAL == "invalid"
        assert AttemptOutcomeType.CANCELLED == "cancelled"
        assert AttemptOutcomeType.EXHAUSTED == "exhausted"

    def test_all_members_distinct(self):
        members = list(AttemptOutcomeType)
        assert len(members) == 5
        assert len({m.value for m in members}) == 5


class TestAttemptOutcome:
    def test_default_message_empty(self):
        outcome = AttemptOutcome(AttemptOutcomeType.SUCCESS)
        assert outcome.message == ""

    def test_should_retry_true_only_for_retryable(self):
        assert AttemptOutcome(AttemptOutcomeType.RETRYABLE).should_retry is True
        assert AttemptOutcome(AttemptOutcomeType.SUCCESS).should_retry is False
        assert AttemptOutcome(AttemptOutcomeType.INVALID_CREDENTIAL).should_retry is False
        assert AttemptOutcome(AttemptOutcomeType.CANCELLED).should_retry is False
        assert AttemptOutcome(AttemptOutcomeType.EXHAUSTED).should_retry is False

    def test_frozen_and_slots(self):
        """AttemptOutcome 不可变，且无法新增属性。"""
        outcome = AttemptOutcome(AttemptOutcomeType.SUCCESS, "ok")
        with pytest.raises(dataclasses.FrozenInstanceError):
            outcome.type = AttemptOutcomeType.RETRYABLE
        with pytest.raises(dataclasses.FrozenInstanceError):
            outcome.message = "changed"
        with pytest.raises((AttributeError, TypeError)):
            outcome.extra = "nope"
