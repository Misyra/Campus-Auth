"""监控与登录模块综合测试

合并原 test_login.py 和 test_monitor_service.py。
覆盖 LoginAttemptHandler、SCREENSHOT_URL_PATTERN、NetworkMonitorCore 等。
"""

from __future__ import annotations

import re
import threading
import time
from datetime import UTC
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.monitor_service import (
    NetworkMonitorCore,
    NetworkState,
)
from app.utils.login import SCREENSHOT_URL_PATTERN, LoginAttemptHandler

# ── 第一部分：LoginAttemptHandler（原 test_login.py）──


# =====================================================================
# SCREENSHOT_URL_PATTERN
# =====================================================================


class TestScreenshotUrlPattern:
    def test_matches_chinese_screenshot_label(self):
        msg = "截图: /tmp/test.png"
        assert re.search(SCREENSHOT_URL_PATTERN, msg) is not None

    def test_matches_chinese_colon(self):
        msg = "截图： /tmp/test.jpg"
        assert re.search(SCREENSHOT_URL_PATTERN, msg) is not None

    def test_matches_various_extensions(self):
        for ext in ("png", "jpg", "jpeg", "webp", "gif"):
            msg = f"截图: /tmp/test.{ext}"
            assert re.search(SCREENSHOT_URL_PATTERN, msg) is not None

    def test_no_match_without_screenshot(self):
        msg = "普通日志消息"
        assert re.sub(SCREENSHOT_URL_PATTERN, "", msg) == msg

    def test_removes_screenshot_path(self):
        msg = "登录失败 截图: /tmp/screenshot.png 结束"
        cleaned = re.sub(SCREENSHOT_URL_PATTERN, "", msg)
        assert "截图" not in cleaned
        assert "screenshot" not in cleaned
        assert "登录失败" in cleaned

    def test_removes_absolute_path(self):
        """应移除绝对路径形式的截图引用"""
        msg = "失败 截图: /Users/test/screenshot.png"
        cleaned = re.sub(SCREENSHOT_URL_PATTERN, "", msg)
        assert "screenshot" not in cleaned


# =====================================================================
# LoginAttemptHandler 初始化
# =====================================================================


class TestLoginAttemptHandlerInit:
    def test_init_defaults(self):
        handler = LoginAttemptHandler(config={})
        assert handler.config == {}
        assert handler.cancel_event is None
        assert handler.close_on_failure is True
        assert handler._browser_ctx is None
        assert handler._task_manager is None

    def test_init_with_cancel_event(self):
        event = threading.Event()
        handler = LoginAttemptHandler(config={}, cancel_event=event)
        assert handler.cancel_event is event

    def test_init_close_on_failure_false(self):
        handler = LoginAttemptHandler(config={}, close_on_failure=False)
        assert handler.close_on_failure is False


# =====================================================================
# attempt_login
# =====================================================================


class TestAttemptLogin:
    @pytest.mark.asyncio
    async def test_pause_period_skip(self):
        """暂停时段应跳过登录"""
        config = {"pause_login": {"start_hour": 0, "end_hour": 23}}
        handler = LoginAttemptHandler(config=config)

        with patch("app.utils.login.datetime") as mock_dt:
            mock_dt.datetime.now.return_value.hour = 3
            mock_dt.datetime.now.return_value.minute = 0

            with patch(
                "app.network.decision.check_pause",
                return_value=(True, "pause_period"),
            ):
                ok, msg = await handler.attempt_login(skip_pause_check=False)
                assert ok is False
                assert "暂停" in msg

    @pytest.mark.asyncio
    async def test_network_disconnected_skip(self):
        """物理网络未连接时应跳过登录"""
        handler = LoginAttemptHandler(config={})

        with (
            patch(
                "app.network.decision.check_pause",
                return_value=(False, ""),
            ),
            patch(
                "app.network.decision.check_network_status",
                return_value=(False, "network_down"),
            ),
            patch(
                "app.network.decision.check_login_prerequisites",
                return_value=(False, "local_disconnected"),
            ),
        ):
            ok, msg = await handler.attempt_login(skip_pause_check=False)
            assert ok is False
            assert "未连接" in msg

    @pytest.mark.asyncio
    async def test_auth_url_unreachable_skip(self):
        """认证地址不可达时应跳过登录"""
        config = {"auth_url": "http://10.0.0.1"}
        handler = LoginAttemptHandler(config=config)

        with (
            patch(
                "app.network.decision.check_pause",
                return_value=(False, ""),
            ),
            patch(
                "app.network.decision.check_network_status",
                return_value=(False, "network_down"),
            ),
            patch(
                "app.network.decision.check_login_prerequisites",
                return_value=(False, "auth_url_unreachable"),
            ),
        ):
            ok, msg = await handler.attempt_login(skip_pause_check=False)
            assert ok is False
            assert "不可达" in msg

    @pytest.mark.asyncio
    async def test_network_ok_skip(self):
        """网络正常时应跳过登录"""
        handler = LoginAttemptHandler(config={})

        with (
            patch(
                "app.network.decision.check_pause",
                return_value=(False, ""),
            ),
            patch(
                "app.network.decision.check_network_status",
                return_value=(True, "network_ok"),
            ),
        ):
            ok, msg = await handler.attempt_login(skip_pause_check=False)
            assert ok is False
            assert "正常" in msg

    @pytest.mark.asyncio
    async def test_login_cancelled(self):
        """取消事件触发时应返回取消消息"""
        event = threading.Event()
        event.set()
        handler = LoginAttemptHandler(config={}, cancel_event=event)

        with (
            patch(
                "app.network.decision.check_pause",
                return_value=(False, ""),
            ),
            patch(
                "app.network.decision.check_network_status",
                return_value=(False, "network_down"),
            ),
            patch(
                "app.network.decision.check_login_prerequisites",
                return_value=(True, ""),
            ),
        ):
            ok, msg = await handler.attempt_login(skip_pause_check=False)
            # 取消事件已设置，最终会返回取消或失败
            assert ok is False

    @pytest.mark.asyncio
    async def test_skip_pause_check(self):
        """skip_pause_check=True 时应跳过暂停检查"""
        handler = LoginAttemptHandler(config={})

        # 不检查暂停，但没有活动任务，应返回失败
        with patch.object(
            handler,
            "_perform_login_with_auth_class",
            return_value=(False, "未找到可执行的活动任务"),
        ):
            ok, msg = await handler.attempt_login(skip_pause_check=True)
            assert ok is False

    @pytest.mark.asyncio
    async def test_exception_returns_error(self):
        """异常应被捕获并返回错误消息"""
        handler = LoginAttemptHandler(config={})

        with patch(
            "app.network.decision.check_pause",
            side_effect=RuntimeError("test error"),
        ):
            ok, msg = await handler.attempt_login(skip_pause_check=False)
            assert ok is False
            assert "test error" in msg


# =====================================================================
# close_browser
# =====================================================================


class TestCloseBrowser:
    @pytest.mark.asyncio
    async def test_close_browser_with_context(self):
        """有浏览器上下文时应正确关闭"""
        handler = LoginAttemptHandler(config={})
        mock_ctx = AsyncMock()
        handler._browser_ctx = mock_ctx

        with patch("app.workers.playwright_worker.get_worker") as mock_get_worker:
            mock_worker = MagicMock()
            mock_worker.close_browser = AsyncMock()
            mock_get_worker.return_value = mock_worker

            await handler.close_browser()
            mock_worker.close_browser.assert_called_once()
            mock_ctx.__aexit__.assert_called_once()
            assert handler._browser_ctx is None

    @pytest.mark.asyncio
    async def test_close_browser_without_context(self):
        """无浏览器上下文时不应抛异常"""
        handler = LoginAttemptHandler(config={})
        handler._browser_ctx = None
        await handler.close_browser()

    @pytest.mark.asyncio
    async def test_close_browser_exception_handled(self):
        """关闭过程中异常应被捕获"""
        handler = LoginAttemptHandler(config={})
        mock_ctx = AsyncMock()
        mock_ctx.__aexit__ = AsyncMock(side_effect=RuntimeError("close error"))
        handler._browser_ctx = mock_ctx

        with patch("app.workers.playwright_worker.get_worker") as mock_get_worker:
            mock_worker = MagicMock()
            mock_worker.close_browser = AsyncMock(side_effect=RuntimeError("fail"))
            mock_get_worker.return_value = mock_worker

            await handler.close_browser()
            assert handler._browser_ctx is None


# ── 第二部分：NetworkMonitorCore（原 test_monitor_core.py）──


# =====================================================================
# NetworkState 枚举
# =====================================================================


class TestEnums:
    def test_network_state_values(self):
        assert NetworkState.UNKNOWN.value == "unknown"
        assert NetworkState.CONNECTED.value == "connected"
        assert NetworkState.DISCONNECTED.value == "disconnected"


# =====================================================================
# NetworkMonitorCore 初始化与基本方法
# =====================================================================


class TestMonitorCoreInit:
    def test_default_state(self):
        core = NetworkMonitorCore()
        assert core.monitoring is False
        assert core.network_check_count == 0
        assert core.login_attempt_count == 0
        assert core.start_time is None
        assert core.network_state == NetworkState.UNKNOWN
        assert core.status_detail == "正常"

    def test_custom_config(self):
        config = {"auth_url": "http://test.com", "username": "admin"}
        core = NetworkMonitorCore(config=config)
        assert core.config == config

    def test_custom_log_callback(self):
        callback = MagicMock()
        core = NetworkMonitorCore(log_callback=callback)
        core.log_message("test message")
        callback.assert_called_once()

    def test_default_log_callback(self):
        """无回调时应使用 logger"""
        core = NetworkMonitorCore()
        # 不应抛异常
        core.log_message("test message")


class TestMonitorCoreSnapshot:
    def test_snapshot_default(self):
        core = NetworkMonitorCore()
        snap = core.snapshot()
        assert snap["monitoring"] is False
        assert snap["network_check_count"] == 0
        assert snap["login_attempt_count"] == 0
        assert snap["network_state"] == "unknown"

    def test_snapshot_with_state(self):
        core = NetworkMonitorCore()
        core.monitoring = True
        core.network_check_count = 5
        core.login_attempt_count = 2
        core.start_time = time.time()
        core.network_state = NetworkState.CONNECTED
        snap = core.snapshot()
        assert snap["monitoring"] is True
        assert snap["network_check_count"] == 5
        assert snap["network_state"] == "connected"


class TestMonitorCoreGetRetryConfig:
    def test_default_config(self):
        core = NetworkMonitorCore()
        max_retries, intervals = core._get_retry_config()
        assert max_retries == core.MAX_CONSECUTIVE_LOGIN_FAILURES
        assert len(intervals) == max_retries

    def test_custom_config(self):
        config = {"retry_settings": {"max_retries": 2, "retry_interval": 10}}
        core = NetworkMonitorCore(config=config)
        max_retries, intervals = core._get_retry_config()
        assert max_retries == 2
        assert intervals[0] == 10

    def test_max_retries_clamped(self):
        """最大重试次数应被限制在 1~5"""
        config = {"retry_settings": {"max_retries": 100}}
        core = NetworkMonitorCore(config=config)
        max_retries, _ = core._get_retry_config()
        assert max_retries == 5

        config = {"retry_settings": {"max_retries": 0}}
        core = NetworkMonitorCore(config=config)
        max_retries, _ = core._get_retry_config()
        assert max_retries == 1


class TestMonitorCoreGetTestSites:
    def test_default_targets(self):
        core = NetworkMonitorCore()
        sites = core._get_test_sites()
        assert len(sites) > 0
        for host, port in sites:
            assert isinstance(host, str)
            assert isinstance(port, int)

    def test_custom_targets(self):
        config = {"monitor": {"ping_targets": ["8.8.8.8:53", "1.1.1.1:443"]}}
        core = NetworkMonitorCore(config=config)
        sites = core._get_test_sites()
        assert ("8.8.8.8", 53) in sites
        assert ("1.1.1.1", 443) in sites

    def test_string_targets(self):
        """字符串格式的目标应被正确解析"""
        config = {"monitor": {"ping_targets": "8.8.8.8:53,1.1.1.1:443"}}
        core = NetworkMonitorCore(config=config)
        sites = core._get_test_sites()
        assert len(sites) == 2

    def test_targets_without_port(self):
        """缺少端口的目标应自动补全"""
        config = {"monitor": {"ping_targets": ["8.8.8.8", "www.baidu.com"]}}
        core = NetworkMonitorCore(config=config)
        sites = core._get_test_sites()
        # IP 默认 53，域名默认 443
        assert ("8.8.8.8", 53) in sites
        assert ("www.baidu.com", 443) in sites

    def test_caching(self):
        core = NetworkMonitorCore()
        sites1 = core._get_test_sites()
        sites2 = core._get_test_sites()
        # 每次返回副本，值相同但不是同一对象
        assert sites1 == sites2
        assert sites1 is not sites2
        # 修改副本不影响缓存
        sites1.clear()
        sites3 = core._get_test_sites()
        assert len(sites3) > 0


class TestMonitorCoreGetMonitorInterval:
    def test_default_interval(self):
        core = NetworkMonitorCore()
        assert core._get_monitor_interval() == core.DEFAULT_INTERVAL_SECONDS

    def test_custom_interval(self):
        config = {"monitor": {"interval": 600}}
        core = NetworkMonitorCore(config=config)
        assert core._get_monitor_interval() == 600


class TestMonitorCoreStopMonitoring:
    def test_stop_clears_state(self):
        core = NetworkMonitorCore()
        core.monitoring = True
        core.start_time = time.time()
        core.network_check_count = 10
        core.stop_monitoring()
        assert core.monitoring is False
        assert core.status_detail == "已停止"

    def test_stop_when_not_monitoring(self):
        core = NetworkMonitorCore()
        core.monitoring = False
        # 不应抛异常
        core.stop_monitoring()


# ── 第三部分：新增测试 ──


# =====================================================================
# log_message exc_info 测试
# =====================================================================


class TestLogMessageExcInfo:
    def test_exc_info_false_by_default(self):
        """默认不附加堆栈"""
        callback = MagicMock()
        core = NetworkMonitorCore(log_callback=callback)
        core.log_message("test", "INFO")
        args = callback.call_args[0]
        assert "Traceback" not in args[0]

    def test_exc_info_true_appends_traceback(self):
        """exc_info=True 时应附加堆栈信息"""
        callback = MagicMock()
        core = NetworkMonitorCore(log_callback=callback)
        try:
            raise ValueError("test error")
        except ValueError:
            core.log_message("出错了", "ERROR", exc_info=True)
        args = callback.call_args[0]
        assert "出错了" in args[0]
        assert "ValueError" in args[0]
        assert "test error" in args[0]

    def test_exc_info_without_active_exception(self):
        """无活跃异常时不应附加无意义的堆栈"""
        callback = MagicMock()
        core = NetworkMonitorCore(log_callback=callback)
        core.log_message("正常消息", "INFO", exc_info=True)
        args = callback.call_args[0]
        assert "Traceback" not in args[0]


# =====================================================================
# DEFAULT_PING_TARGETS 引用常量测试
# =====================================================================


class TestDefaultPingTargets:
    def test_uses_shared_constant(self):
        """DEFAULT_PING_TARGETS 应与 constants.DEFAULT_NETWORK_TARGETS 一致"""
        from app.constants import DEFAULT_NETWORK_TARGETS

        assert (
            DEFAULT_NETWORK_TARGETS.split(",")
            == NetworkMonitorCore.DEFAULT_PING_TARGETS
        )


# ── NetworkMonitorCore 详细逻辑测试 ──


class TestMonitorCoreDetailedSnapshot:
    """snapshot 详细测试。"""

    def test_last_check_time_isoformat(self):
        """last_check_time 序列化为 ISO 格式。"""
        from datetime import datetime

        core = NetworkMonitorCore(config={})
        core.last_check_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        snap = core.snapshot()
        assert "2026-01-01" in snap["last_check_time"]


class TestMonitorCoreDetailedRetryConfig:
    """retry_config 详细测试。"""

    def test_negative_retries_clamped(self):
        """负数重试次数被钳制为最小值 1。"""
        core = NetworkMonitorCore(config={"retry_settings": {"max_retries": -1}})
        max_retries, _ = core._get_retry_config()
        assert max_retries >= 1

    def test_exponential_backoff(self):
        """间隔呈指数增长。"""
        core = NetworkMonitorCore(
            config={"retry_settings": {"max_retries": 4, "retry_interval": 5}}
        )
        _, intervals = core._get_retry_config()
        assert intervals == [5, 10, 20, 40]


class TestMonitorCoreLogMessage:
    """log_message 分发逻辑。"""

    def test_uses_callback_when_set(self):
        """有 callback 时使用 callback。"""
        core = NetworkMonitorCore(config={})
        callback = MagicMock()
        core.log_callback = callback
        core.log_message("测试消息", "INFO")
        callback.assert_called_once()

    def test_uses_logger_when_no_callback(self):
        """无 callback 时使用 logger。"""
        core = NetworkMonitorCore(config={})
        core.log_callback = None
        # 不应抛异常
        core.log_message("测试消息", "INFO")


# ── LoginAttemptHandler 详细检查 ──


class TestAttemptLoginDetailedChecks:
    """attempt_login 前置检查详细测试。"""

    @pytest.mark.asyncio
    async def test_skip_pause_check(self):
        """skip_pause_check=True 时跳过前置检查直接执行登录。"""
        handler = LoginAttemptHandler(config={})

        with patch.object(
            handler,
            "_perform_login_with_auth_class",
            return_value=(True, "成功"),
        ):
            ok, msg = await handler.attempt_login(skip_pause_check=True)

        assert ok is True
        assert "成功" in msg
