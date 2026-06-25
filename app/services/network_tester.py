"""NetworkTester — 手动网络测试封装。

从 ScheduleEngine 提取，负责：
- 手动网络测试（test_network）
- 结果日志记录
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.network.decision import is_network_available
from app.utils.logging import get_logger
from app.utils.network import parse_ping_targets

if TYPE_CHECKING:
    from app.schemas import RuntimeConfig

logger = get_logger("network_tester", source="backend")


class NetworkTester:
    """手动网络测试封装。"""

    def test_network(self, config: RuntimeConfig) -> tuple[bool, str]:
        """执行手动网络测试。

        Args:
            config: 当前运行时配置。

        Returns:
            (success, message) 元组。
        """
        monitor = config.monitor
        targets = monitor.ping_targets
        enable_tcp = monitor.enable_tcp_check
        enable_http = monitor.enable_http_check

        from app.utils.network import parse_url_checks

        url_checks = parse_url_checks(monitor.url_check_urls)
        test_sites = parse_ping_targets(targets)

        mode_desc = []
        if enable_tcp:
            mode_desc.append(f"TCP({len(test_sites) if test_sites else 2})")
        if enable_http:
            mode_desc.append("HTTP(2)")
        if url_checks:
            mode_desc.append(f"网址响应({len(url_checks)})")

        logger.debug("手动网络测试: {}", "+".join(mode_desc) or "无")

        try:
            timeout = monitor.network_check_timeout
            is_available = is_network_available(
                test_sites=test_sites if test_sites else None,
                test_urls=monitor.test_urls or None,
                timeout=timeout,
                enable_tcp=enable_tcp,
                enable_http=enable_http,
                url_checks=url_checks if url_checks else None,
            )
            if is_available:
                logger.info("手动测试结果: 网络正常")
                return True, "网络连接正常"
            else:
                logger.warning("手动测试结果: 网络异常")
                return False, "网络连接异常"
        except Exception as exc:
            logger.exception("网络测试失败")
            return False, f"网络测试失败: {exc}"
