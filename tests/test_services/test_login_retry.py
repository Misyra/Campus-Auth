"""LoginRetryManager 单元测试。"""

from app.services.login_retry import LoginRetryManager


class TestLoginRetryManager:
    def test_initial_state(self):
        mgr = LoginRetryManager()
        assert mgr.count == 0
        assert mgr.config is None
        assert mgr.need_retry(100.0) is False
        assert mgr.next_wakeup() is None

    def test_reset(self):
        mgr = LoginRetryManager(count=3, last_attempt=50.0, config=(5, [1, 2, 3]))
        mgr.reset()
        assert mgr.count == 0
        assert mgr.last_attempt == 0.0
        assert mgr.config is None

    def test_configure(self):
        mgr = LoginRetryManager()
        mgr.configure(3, [5, 10, 15])
        assert mgr.config == (3, [5, 10, 15])

    def test_record_attempt(self):
        mgr = LoginRetryManager()
        mgr.configure(3, [5, 10, 15])
        mgr.record_attempt(100.0)
        assert mgr.count == 1
        assert mgr.last_attempt == 100.0

    def test_need_retry_within_interval(self):
        """间隔内不需要重试。"""
        mgr = LoginRetryManager(count=1, last_attempt=100.0, config=(3, [5, 10, 15]))
        assert mgr.need_retry(104.0) is False

    def test_need_retry_after_interval(self):
        """间隔后需要重试。"""
        mgr = LoginRetryManager(count=1, last_attempt=100.0, config=(3, [5, 10, 15]))
        assert mgr.need_retry(106.0) is True

    def test_need_retry_max_exceeded(self):
        """达到最大重试次数后不需要重试。"""
        mgr = LoginRetryManager(count=3, last_attempt=100.0, config=(3, [5, 10, 15]))
        assert mgr.need_retry(200.0) is False

    def test_need_retry_no_config(self):
        """无配置时不需要重试。"""
        mgr = LoginRetryManager(count=1, last_attempt=100.0)
        assert mgr.need_retry(200.0) is False

    def test_need_retry_zero_count(self):
        """零次计数时不需要重试。"""
        mgr = LoginRetryManager(count=0, config=(3, [5, 10, 15]))
        assert mgr.need_retry(200.0) is False

    def test_next_wakeup(self):
        mgr = LoginRetryManager(count=1, last_attempt=100.0, config=(3, [5, 10, 15]))
        assert mgr.next_wakeup() == 105.0

    def test_next_wakeup_no_config(self):
        mgr = LoginRetryManager(count=1, last_attempt=100.0)
        assert mgr.next_wakeup() is None

    def test_next_wakeup_count_beyond_intervals(self):
        """count 超出 intervals 长度时返回 None。"""
        mgr = LoginRetryManager(count=4, last_attempt=100.0, config=(5, [5, 10, 15]))
        assert mgr.next_wakeup() is None
