"""MonitoredPolicy 重试策略单元测试。"""

from app.services.retry_policy import MonitoredPolicy


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

    def test_delay_first_attempt(self):
        policy = MonitoredPolicy()
        assert policy.delay_before(1) == 5.0

    def test_delay_within_table(self):
        """每次失败使用固定延迟表。"""
        policy = MonitoredPolicy()
        assert policy.delay_before(1) == 5.0
        assert policy.delay_before(2) == 10.0
        assert policy.delay_before(3) == 20.0

    def test_delay_fixed_table(self):
        """延迟表 [5, 10, 20, 60, 100]，超出后取最后一个值。"""
        policy = MonitoredPolicy()
        assert policy.delay_before(1) == 5.0
        assert policy.delay_before(2) == 10.0
        assert policy.delay_before(3) == 20.0
        assert policy.delay_before(4) == 60.0
        assert policy.delay_before(5) == 100.0
        # 超出表长，取最后一个
        assert policy.delay_before(100) == 100.0

    def test_delay_table_max(self):
        """超出延迟表范围时取最后一个值。"""
        policy = MonitoredPolicy()
        assert policy.delay_before(100) == 100.0
        assert policy.delay_before(1000) == 100.0

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
        # 第一次失败 → _attempt=1，delay_before(1)=5.0
        result = policy.on_login_done(success=False)
        assert result == 5.0

    def test_login_failure_subsequent_delays(self):
        """多次登录失败 → 按延迟表递增。"""
        policy = MonitoredPolicy()
        # 第 1 次失败: _attempt=1 → delay_before(1)=5.0
        assert policy.on_login_done(success=False) == 5.0
        # 第 2 次失败: _attempt=2 → delay_before(2)=10.0
        assert policy.on_login_done(success=False) == 10.0
        # 第 3 次失败: _attempt=3 → delay_before(3)=20.0
        assert policy.on_login_done(success=False) == 20.0
        # 第 4 次失败: _attempt=4 → delay_before(4)=60.0
        assert policy.on_login_done(success=False) == 60.0
        # 第 5 次失败: _attempt=5 → delay_before(5)=100.0
        assert policy.on_login_done(success=False) == 100.0

    def test_login_failure_exceeds_max_returns_none(self):
        """超过最大重试次数 → 返回 None。"""
        policy = MonitoredPolicy(max_retries=3)
        assert policy.on_login_done(success=False) == 5.0   # attempt=1
        assert policy.on_login_done(success=False) == 10.0  # attempt=2
        assert policy.on_login_done(success=False) == 20.0  # attempt=3
        result = policy.on_login_done(success=False)         # attempt=4 > max_retries
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
        assert policy.on_login_done(success=False) == 5.0  # delay_before(1)=5

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
