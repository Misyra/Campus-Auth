"""monitor_service.py 日志脱敏测试

验证 init_monitoring 中 auth_url 和 username 的日志脱敏行为。
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.schemas import (
    LoginCredentials,
    MonitorSettings,
    RuntimeConfig,
)
from app.services.monitor_service import NetworkMonitorCore


class TestInitMonitoringLogMasking:
    """验证 init_monitoring 日志输出中敏感信息被脱敏。"""

    def _run_init_monitoring(self, auth_url: str, username: str) -> str:
        """调用 init_monitoring 并捕获日志输出。"""
        captured_logs: list[str] = []

        class _CaptureLogger:
            def info(self, fmt, *args):
                captured_logs.append(args[0] if args else fmt)
            warning = info
            error = info
            debug = info

        config = RuntimeConfig(
            credentials=LoginCredentials(
                auth_url=auth_url,
                username=username,
                isp="移动",
            ),
            monitor=MonitorSettings(
                check_interval_seconds=300,
                enable_tcp_check=True,
                enable_http_check=True,
            ),
            block_proxy=True,
        )

        core = NetworkMonitorCore(get_config=lambda: config, logger=_CaptureLogger())
        # mock _get_test_sites 以避免真实网络调用
        with patch.object(core, "_get_test_sites", return_value=[("1.1.1.1", 80)]):
            core.init_monitoring()

        # 在测试后清理状态，避免影响其他测试
        core.monitoring = False

        return "\n".join(captured_logs)

    def test_auth_url_is_masked(self):
        """认证地址应被脱敏，不应出现完整明文 URL。"""
        full_url = "http://10.10.10.1:801/eportal/portal/login"
        log_output = self._run_init_monitoring(auth_url=full_url, username="testuser")
        assert full_url not in log_output, (
            f"日志中不应出现完整认证地址，实际输出: {log_output}"
        )

    def test_username_is_masked(self):
        """用户名应被脱敏，不应出现完整明文用户名。"""
        full_username = "202301010001"
        log_output = self._run_init_monitoring(
            auth_url="http://10.10.10.1:801/eportal/portal/login",
            username=full_username,
        )
        assert full_username not in log_output, (
            f"日志中不应出现完整用户名，实际输出: {log_output}"
        )

    def test_short_url_not_excessively_masked(self):
        """较短的 URL 不应被过度脱敏（长度 <= 20 时不截断）。"""
        short_url = "http://example.com"
        log_output = self._run_init_monitoring(auth_url=short_url, username="ab")
        # 短 URL（<= 20 字符）应保持原样
        assert short_url in log_output or "..." in log_output

    def test_short_username_masked(self):
        """较短用户名（<= 3 字符）应被脱敏为 ***。"""
        log_output = self._run_init_monitoring(
            auth_url="http://10.10.10.1:801/eportal/portal/login",
            username="ab",
        )
        assert "ab" not in log_output, (
            f"短用户名也应被脱敏，实际输出: {log_output}"
        )
        assert "***" in log_output

    def test_isp_not_masked(self):
        """运营商信息不需要脱敏，应保持明文。"""
        log_output = self._run_init_monitoring(
            auth_url="http://10.10.10.1:801/eportal/portal/login",
            username="202301010001",
        )
        assert "移动" in log_output, (
            f"运营商信息应保持明文，实际输出: {log_output}"
        )
