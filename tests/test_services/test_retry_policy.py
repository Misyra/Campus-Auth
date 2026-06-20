"""RetryPolicy 框架单元测试。"""

from app.services.retry_policy import ImmediatePolicy, MonitoredPolicy, RetryPolicy


class TestRetryPolicyBase:
    """RetryPolicy 抽象基类测试。"""

    def test_cannot_instantiate_directly(self):
        """不能直接实例化抽象基类。"""
        import pytest

        with pytest.raises(TypeError):
            RetryPolicy()  # type: ignore[abstract]


class TestImmediatePolicy:
    """ImmediatePolicy 测试。"""

    def test_default_params(self):
        policy = ImmediatePolicy()
        assert policy.max_retries == 3
        assert policy.interval == 5

    def test_attempts_yields_1_to_max(self):
        policy = ImmediatePolicy(max_retries=4)
        assert list(policy.attempts()) == [1, 2, 3, 4]

    def test_delay_before_first_attempt_is_zero(self):
        policy = ImmediatePolicy()
        assert policy.delay_before(1) == 0.0

    def test_delay_before_subsequent_returns_interval(self):
        policy = ImmediatePolicy(interval=7)
        assert policy.delay_before(2) == 7.0
        assert policy.delay_before(3) == 7.0
        assert policy.delay_before(100) == 7.0  # 无论 attempt 多大

    def test_max_retries_clamped_low(self):
        """max_retries 下限为 1。"""
        policy = ImmediatePolicy(max_retries=0)
        assert policy.max_retries == 1

        policy = ImmediatePolicy(max_retries=-5)
        assert policy.max_retries == 1

    def test_max_retries_clamped_high(self):
        """max_retries 上限为 10。"""
        policy = ImmediatePolicy(max_retries=20)
        assert policy.max_retries == 10

    def test_interval_min_clamped(self):
        """interval 最小值为 1。"""
        policy = ImmediatePolicy(interval=0)
        assert policy.interval == 1

        policy = ImmediatePolicy(interval=-3)
        assert policy.interval == 1

    def test_single_retry(self):
        """max_retries=1 时只产生一次重试。"""
        policy = ImmediatePolicy(max_retries=1)
        assert list(policy.attempts()) == [1]
        assert policy.delay_before(1) == 0.0


class TestMonitoredPolicy:
    """MonitoredPolicy 测试。"""

    # -- 构造与基本行为 -------------------------------------------------

    def test_default_params(self):
        policy = MonitoredPolicy()
        assert policy.max_retries == 5

    def test_attempts_yields_1_to_max(self):
        policy = MonitoredPolicy(max_retries=5)
        assert list(policy.attempts()) == [1, 2, 3, 4, 5]

    # -- delay_before ---------------------------------------------------

    def test_delay_first_attempt_zero(self):
        policy = MonitoredPolicy()
        assert policy.delay_before(1) == 0.0

    def test_delay_within_table(self):
        """前几次重试使用固定延迟表。"""
        policy = MonitoredPolicy()
        assert policy.delay_before(2) == 0.0
        assert policy.delay_before(3) == 30.0

    def test_delay_fixed_table(self):
        """延迟表 [0, 0, 30, 60, 120]，超出后取最后一个值。"""
        policy = MonitoredPolicy()
        assert policy.delay_before(1) == 0.0
        assert policy.delay_before(2) == 0.0
        assert policy.delay_before(3) == 30.0
        assert policy.delay_before(4) == 60.0
        assert policy.delay_before(5) == 120.0
        # 超出表长，取最后一个
        assert policy.delay_before(100) == 120.0

    def test_delay_table_max(self):
        """超出延迟表范围时取最后一个值。"""
        policy = MonitoredPolicy()
        assert policy.delay_before(100) == 120.0
        assert policy.delay_before(1000) == 120.0

    # -- on_network_check -----------------------------------------------

    def test_initial_state_no_transition(self):
        """初始状态（unknown）→ need_login=False，不算 down->up 转换。"""
        policy = MonitoredPolicy()
        result = policy.on_network_check(need_login=False)
        assert result is False

    def test_down_to_up_transition_resets(self):
        """网络断开后恢复 → 返回 True 并重置。"""
        policy = MonitoredPolicy()
        # 先标记为断开
        policy.on_network_check(need_login=True)
        # 恢复
        result = policy.on_network_check(need_login=False)
        assert result is True
        assert policy._attempt == 0

    def test_stay_down_no_reset(self):
        """持续断开 → 不重置。"""
        policy = MonitoredPolicy()
        policy.on_network_check(need_login=True)
        result = policy.on_network_check(need_login=True)
        assert result is False

    def test_stay_up_no_reset(self):
        """持续连通 → 不触发重置。"""
        policy = MonitoredPolicy()
        policy.on_network_check(need_login=False)
        result = policy.on_network_check(need_login=False)
        assert result is False

    def test_up_to_down_no_reset(self):
        """连通→断开 → 不重置。"""
        policy = MonitoredPolicy()
        policy.on_network_check(need_login=False)
        result = policy.on_network_check(need_login=True)
        assert result is False

    def test_multiple_down_up_cycles(self):
        """多次 down->up 循环都能正确重置。"""
        policy = MonitoredPolicy()
        for _ in range(3):
            policy.on_network_check(need_login=True)
            policy._attempt = 5  # 模拟有退避状态
            result = policy.on_network_check(need_login=False)
            assert result is True
            assert policy._attempt == 0

    # -- on_login_done --------------------------------------------------

    def test_login_success_resets(self):
        """登录成功 → 重置并返回 None。"""
        policy = MonitoredPolicy()
        policy._attempt = 5
        result = policy.on_login_done(success=True)
        assert result is None
        assert policy._attempt == 0

    def test_login_failure_returns_delay(self):
        """登录失败 → 返回下次延迟（查表）。"""
        policy = MonitoredPolicy()
        # 第一次失败 → _attempt=1，delay_before(1)=0.0
        result = policy.on_login_done(success=False)
        assert result == 0.0

    def test_login_failure_subsequent_delays(self):
        """多次登录失败 → 按延迟表递增。"""
        policy = MonitoredPolicy()
        # 第 1 次失败: _attempt=1 → delay_before(1)=0.0
        assert policy.on_login_done(success=False) == 0.0
        # 第 2 次失败: _attempt=2 → delay_before(2)=0.0
        assert policy.on_login_done(success=False) == 0.0
        # 第 3 次失败: _attempt=3 → delay_before(3)=30.0
        assert policy.on_login_done(success=False) == 30.0
        # 第 4 次失败: _attempt=4 → delay_before(4)=60.0
        assert policy.on_login_done(success=False) == 60.0

    def test_login_failure_exceeds_max_returns_none(self):
        """超过最大重试次数 → 返回 None。"""
        policy = MonitoredPolicy(max_retries=3)
        policy.on_login_done(success=False)  # attempt=1
        policy.on_login_done(success=False)  # attempt=2
        result = policy.on_login_done(success=False)  # attempt=3 >= max_retries
        assert result is None

    def test_login_success_after_failures_resets(self):
        """登录失败后再成功 → 重置状态。"""
        policy = MonitoredPolicy()
        policy.on_login_done(success=False)  # attempt=1
        policy.on_login_done(success=False)  # attempt=2
        result = policy.on_login_done(success=True)
        assert result is None
        assert policy._attempt == 0
        # 再次失败应该从头开始
        assert policy.on_login_done(success=False) == 0.0  # delay_before(1)=0

    # -- 参数 clamping --------------------------------------------------

    def test_max_retries_min_clamped(self):
        policy = MonitoredPolicy(max_retries=0)
        assert policy.max_retries == 1

    def test_max_retries_clamped_to_one(self):
        """max_retries 下限为 1。"""
        policy = MonitoredPolicy(max_retries=0)
        assert policy.max_retries == 1

        policy = MonitoredPolicy(max_retries=-5)
        assert policy.max_retries == 1
