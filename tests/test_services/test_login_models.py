"""login_models 单元测试 — AttemptOutcomeType / AttemptOutcome / LoginRetryPolicy。"""

from __future__ import annotations

import dataclasses

import pytest

from app.schemas import RetrySettings
from app.services.login_models import (
    AttemptOutcome,
    AttemptOutcomeType,
    LoginRetryPolicy,
)


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
        assert (
            AttemptOutcome(AttemptOutcomeType.INVALID_CREDENTIAL).should_retry is False
        )
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


class TestLoginRetryPolicy:
    def test_next_delay_within_range_returns_interval(self):
        policy = LoginRetryPolicy(max_retries=3, interval_seconds=5.0)
        assert policy.next_delay(0) == 5.0
        assert policy.next_delay(1) == 5.0
        assert policy.next_delay(2) == 5.0

    def test_next_delay_at_max_retries_returns_none(self):
        policy = LoginRetryPolicy(max_retries=3, interval_seconds=5.0)
        assert policy.next_delay(3) is None
        assert policy.next_delay(99) is None

    def test_max_retries_clamped_to_min_1(self):
        policy = LoginRetryPolicy(max_retries=0, interval_seconds=5.0)
        assert policy.max_retries == 1

    def test_max_retries_clamped_to_max_10(self):
        policy = LoginRetryPolicy(max_retries=99, interval_seconds=5.0)
        assert policy.max_retries == 10

    def test_interval_seconds_clamped_to_min_1(self):
        policy = LoginRetryPolicy(max_retries=3, interval_seconds=0.0)
        assert policy.interval_seconds == 1.0

    def test_interval_seconds_negative_clamped(self):
        policy = LoginRetryPolicy(max_retries=3, interval_seconds=-5.0)
        assert policy.interval_seconds == 1.0

    def test_from_runtime_config(self):
        settings = RetrySettings(max_retries=4, retry_interval=10)
        policy = LoginRetryPolicy.from_runtime_config(settings)
        assert policy.max_retries == 4
        assert policy.interval_seconds == 10.0

    def test_from_runtime_config_default(self):
        settings = RetrySettings()
        policy = LoginRetryPolicy.from_runtime_config(settings)
        assert policy.max_retries == 3
        assert policy.interval_seconds == 5.0

    def test_from_runtime_config_max_retries_zero_clamped(self):
        """RetrySettings 允许 max_retries=0，但 LoginRetryPolicy 至少 1 次。"""
        settings = RetrySettings(max_retries=0)
        policy = LoginRetryPolicy.from_runtime_config(settings)
        assert policy.max_retries == 1
