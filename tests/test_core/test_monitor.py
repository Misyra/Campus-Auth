"""监控与登录模块综合测试

合并原 test_login.py 和 test_monitor_service.py。
覆盖 LoginAttempt、SCREENSHOT_URL_PATTERN、NetworkMonitorCore 等。
"""

from __future__ import annotations

import re
import threading
import time
from datetime import UTC
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas import MonitorSettings, RuntimeConfig
from app.services.monitor_service import (
    NetworkMonitorCore,
    NetworkState,
)
from app.services.login_attempt import SCREENSHOT_URL_PATTERN, LoginAttempt

# ── 第一部分：LoginAttempt（原 test_login.py）──


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
# LoginAttempt 初始化
# =====================================================================


class TestLoginAttemptInit:
    def test_init_defaults(self):
        handler = LoginAttempt(config={})
        assert handler.config == {}
        assert handler.cancel_event is None
        assert handler._browser_ctx is None
        assert handler._task_manager is None

    def test_init_with_cancel_event(self):
        event = threading.Event()
        handler = LoginAttempt(config={}, cancel_event=event)
        assert handler.cancel_event is event


# =====================================================================
# attempt_login
# =====================================================================


class TestAttemptLogin:
    @pytest.mark.asyncio
    async def test_delegates_to_perform(self):
        """attempt_login 直接委托 _perform_login_with_active_task。"""
        handler = LoginAttempt(config={})

        with patch.object(
            handler,
            "_perform_login_with_active_task",
            return_value=(True, "成功"),
        ):
            ok, msg = await handler.attempt_login()

        assert ok is True
        assert "成功" in msg

    @pytest.mark.asyncio
    async def test_exception_returns_error(self):
        """异常应被捕获并返回错误消息"""
        handler = LoginAttempt(config={})

        with patch.object(
            handler,
            "_perform_login_with_active_task",
            side_effect=RuntimeError("test error"),
        ):
            ok, msg = await handler.attempt_login()
            assert ok is False
            assert "test error" in msg


# =====================================================================
# close_browser
# =====================================================================


class TestCloseBrowser:
    @pytest.mark.asyncio
    async def test_close_browser_with_context(self):
        """有浏览器上下文时应释放上下文引用（不销毁浏览器实例）"""
        handler = LoginAttempt(config={})
        mock_ctx = AsyncMock()
        handler._browser_ctx = mock_ctx

        await handler.close_browser()
        # close_browser 只释放上下文引用，不调用 worker.close_browser
        mock_ctx.__aexit__.assert_called_once()
        assert handler._browser_ctx is None

    @pytest.mark.asyncio
    async def test_close_browser_without_context(self):
        """无浏览器上下文时不应抛异常"""
        handler = LoginAttempt(config={})
        handler._browser_ctx = None
        await handler.close_browser()

    @pytest.mark.asyncio
    async def test_close_browser_exception_handled(self):
        """关闭过程中异常应被捕获"""
        handler = LoginAttempt(config={})
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
        core = NetworkMonitorCore(get_config=lambda: RuntimeConfig())
        assert core.monitoring is False
        assert core.network_check_count == 0
        assert core.login_attempt_count == 0
        assert core.start_time is None
        assert core.network_state == NetworkState.UNKNOWN
        assert core.status_detail == "正常"

    def test_custom_config(self):
        config = RuntimeConfig()
        core = NetworkMonitorCore(get_config=lambda: config)
        assert core._get_config() == config

    def test_custom_logger(self):
        logger = MagicMock()
        core = NetworkMonitorCore(get_config=lambda: RuntimeConfig(), logger=logger)
        core.log_message("test message")
        logger.info.assert_called_once_with("{}", "test message")

    def test_default_logger(self):
        """无自定义 logger 时应使用 logger"""
        core = NetworkMonitorCore(get_config=lambda: RuntimeConfig())
        # 不应抛异常
        core.log_message("test message")


class TestMonitorCoreSnapshot:
    def test_snapshot_default(self):
        core = NetworkMonitorCore(get_config=lambda: RuntimeConfig())
        snap = core.snapshot()
        assert snap["monitoring"] is False
        assert snap["network_check_count"] == 0
        assert snap["login_attempt_count"] == 0
        assert snap["network_state"] == "unknown"

    def test_snapshot_with_state(self):
        core = NetworkMonitorCore(get_config=lambda: RuntimeConfig())
        core.monitoring = True
        core.network_check_count = 5
        core.login_attempt_count = 2
        core.start_time = time.time()
        core.network_state = NetworkState.CONNECTED
        snap = core.snapshot()
        assert snap["monitoring"] is True
        assert snap["network_check_count"] == 5
        assert snap["network_state"] == "connected"


class TestMonitorCoreGetTestSites:
    def test_default_targets(self):
        core = NetworkMonitorCore(get_config=lambda: RuntimeConfig())
        sites = core._get_test_sites()
        assert len(sites) > 0
        for host, port in sites:
            assert isinstance(host, str)
            assert isinstance(port, int)

    def test_custom_targets(self):
        config = RuntimeConfig(
            monitor=MonitorSettings(ping_targets=["8.8.8.8:53", "1.1.1.1:443"])
        )
        core = NetworkMonitorCore(get_config=lambda: config)
        sites = core._get_test_sites()
        assert ("8.8.8.8", 53) in sites
        assert ("1.1.1.1", 443) in sites

    def test_string_targets(self):
        """字符串格式的目标应被正确解析"""
        config = RuntimeConfig(
            monitor=MonitorSettings(ping_targets=["8.8.8.8:53", "1.1.1.1:443"])
        )
        core = NetworkMonitorCore(get_config=lambda: config)
        sites = core._get_test_sites()
        assert len(sites) == 2

    def test_targets_without_port(self):
        """缺少端口的目标应自动补全"""
        config = RuntimeConfig(
            monitor=MonitorSettings(ping_targets=["8.8.8.8", "www.baidu.com"])
        )
        core = NetworkMonitorCore(get_config=lambda: config)
        sites = core._get_test_sites()
        # IP 默认 53，域名默认 443
        assert ("8.8.8.8", 53) in sites
        assert ("www.baidu.com", 443) in sites

    def test_no_caching_returns_fresh(self):
        """getter 注入后每次重算，返回相同值但非缓存。"""
        core = NetworkMonitorCore(get_config=lambda: RuntimeConfig())
        sites1 = core._get_test_sites()
        sites2 = core._get_test_sites()
        assert sites1 == sites2


class TestMonitorCoreGetMonitorInterval:
    def test_default_interval(self):
        core = NetworkMonitorCore(get_config=lambda: RuntimeConfig())
        assert core._get_monitor_interval() == 300

    def test_custom_interval(self):
        config = RuntimeConfig(monitor=MonitorSettings(check_interval_seconds=600))
        core = NetworkMonitorCore(get_config=lambda: config)
        assert core._get_monitor_interval() == 600


class TestMonitorCoreStopMonitoring:
    def test_stop_clears_state(self):
        core = NetworkMonitorCore(get_config=lambda: RuntimeConfig())
        core.monitoring = True
        core.start_time = time.time()
        core.network_check_count = 10
        core.stop_monitoring()
        assert core.monitoring is False
        assert core.status_detail == "已停止"

    def test_stop_when_not_monitoring(self):
        core = NetworkMonitorCore(get_config=lambda: RuntimeConfig())
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
        logger = MagicMock()
        core = NetworkMonitorCore(get_config=lambda: RuntimeConfig(), logger=logger)
        core.log_message("test", "INFO")
        args = logger.info.call_args[0]
        assert "Traceback" not in args[1]

    def test_exc_info_true_appends_traceback(self):
        """exc_info=True 时应附加堆栈信息"""
        logger = MagicMock()
        core = NetworkMonitorCore(get_config=lambda: RuntimeConfig(), logger=logger)
        try:
            raise ValueError("test error")
        except ValueError:
            core.log_message("出错了", "ERROR", exc_info=True)
        args = logger.error.call_args[0]
        assert "出错了" in args[1]
        assert "ValueError" in args[1]
        assert "test error" in args[1]

    def test_exc_info_without_active_exception(self):
        """无活跃异常时不应附加无意义的堆栈"""
        logger = MagicMock()
        core = NetworkMonitorCore(get_config=lambda: RuntimeConfig(), logger=logger)
        core.log_message("正常消息", "INFO", exc_info=True)
        args = logger.info.call_args[0]
        assert "Traceback" not in args[1]


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

        core = NetworkMonitorCore(get_config=lambda: RuntimeConfig())
        core.last_check_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        snap = core.snapshot()
        assert "2026-01-01" in snap["last_check_time"]


class TestMonitorCoreLogMessage:
    """log_message 分发逻辑。"""

    def test_uses_logger_when_set(self):
        """有自定义 logger 时使用 logger。"""
        logger = MagicMock()
        core = NetworkMonitorCore(get_config=lambda: RuntimeConfig(), logger=logger)
        core.log_message("测试消息", "INFO")
        logger.info.assert_called_once_with("{}", "测试消息")

    def test_uses_default_logger_when_no_custom(self):
        """无自定义 logger 时使用默认 logger。"""
        core = NetworkMonitorCore(get_config=lambda: RuntimeConfig())
        # 不应抛异常
        core.log_message("测试消息", "INFO")
