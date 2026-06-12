from __future__ import annotations

import datetime
import threading
import time
from collections.abc import Callable
from enum import Enum
from typing import TYPE_CHECKING, Any

from app.constants import DEFAULT_NETWORK_TARGETS
from app.network.decision import (
    NetworkCheckResult,
    check_network_status,
    check_pause,
)
from app.network.probes import set_block_proxy
from app.utils import get_logger
from app.utils.network import parse_ping_targets

if TYPE_CHECKING:
    from app.services.profile_service import ProfileService


class NetworkState(str, Enum):
    """网络状态枚举，用于区分首次检测和已知状态"""

    UNKNOWN = "unknown"  # 首次检测，状态未知
    CONNECTED = "connected"  # 网络正常
    DISCONNECTED = "disconnected"  # 网络异常


class NetworkMonitorCore:
    """网络监控核心类"""

    # 类常量：监控配置
    DEFAULT_INTERVAL_SECONDS = 300
    MAX_CONSECUTIVE_LOGIN_FAILURES = 3

    # 类常量：网络检测配置
    NETWORK_CHECK_TIMEOUT_SECONDS = 2
    DEFAULT_PING_TARGETS = DEFAULT_NETWORK_TARGETS.split(",")

    # 类常量：自动切换检测冷却
    GATEWAY_CHECK_COOLDOWN_SECONDS = 60

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        log_callback: Callable[[str, str, str], None] | None = None,
        login_history: Any = None,
        worker_getter: Callable | None = None,
    ) -> None:
        self.config = config if config is not None else {}
        self.log_callback = log_callback
        self._login_history = login_history
        self._worker_getter = worker_getter

        # 状态锁：保护 snapshot() 读取的状态字段，防止跨线程竞态
        self._state_lock = threading.Lock()

        self.monitoring = False
        self.network_check_count = 0
        self.login_attempt_count = 0
        self.start_time: float | None = None
        self.last_check_time: datetime.datetime | None = None
        # 上次网络连通性检测结果（用于 UI 状态显示）
        self.network_state: NetworkState = NetworkState.UNKNOWN

        self._test_sites_cache: list[tuple[str, int]] | None = None
        self.logger = get_logger("monitor_core", source="network")

        # 状态详情
        self.status_detail: str = "正常"

        # 自动切换相关
        self._profile_service: ProfileService | None = None
        self._last_profile_id: str | None = None
        self._last_gateway_check_time: float = 0

    def log_message(
        self, message: str, level: str = "INFO", exc_info: bool = False
    ) -> None:
        if exc_info:
            import traceback

            tb = traceback.format_exc()
            if tb and tb != "NoneType: None\n":
                message = f"{message}\n{tb}"
        if self.log_callback:
            self.log_callback(
                message,
                level,
                source="network",
                name="monitor_core",
            )
        else:
            log_func = getattr(self.logger, level.lower(), self.logger.info)
            log_func(message)

    def _update_state(self, **kwargs: Any) -> None:
        """线程安全地更新状态字段。

        用法: self._update_state(monitoring=True, status_detail="...")
        """
        with self._state_lock:
            for k, v in kwargs.items():
                setattr(self, k, v)

    def snapshot(self) -> dict[str, Any]:
        """线程安全地获取状态快照。"""
        with self._state_lock:
            return {
                "monitoring": self.monitoring,
                "network_check_count": self.network_check_count,
                "login_attempt_count": self.login_attempt_count,
                "last_check_time": self.last_check_time.isoformat()
                if self.last_check_time
                else None,
                "start_time": self.start_time,
                "network_state": self.network_state.value,
                "status_detail": self.status_detail,
            }

    def set_profile_service(self, profile_service: ProfileService) -> None:
        """设置 profile 服务用于自动切换"""
        self._profile_service = profile_service
        if profile_service:
            self._last_profile_id = profile_service.get_active_profile_id()

    def _get_monitor_interval(self) -> int:
        """获取当前配置的检测间隔（秒）。"""
        return int(
            self.config.get("monitor", {}).get(
                "interval", self.DEFAULT_INTERVAL_SECONDS
            )
        )

    def init_monitoring(self) -> None:
        """初始化监控状态（不启动循环，由引擎驱动检测）。"""
        if self.monitoring:
            self.log_message("监控已在运行中", "WARNING")
            return

        self._test_sites_cache = None
        self._update_state(
            monitoring=True,
            start_time=time.time(),
            network_check_count=0,
            login_attempt_count=0,
            network_state=NetworkState.UNKNOWN,
            status_detail="正在启动监控",
        )

        interval = self._get_monitor_interval()
        auth_url = self.config.get("auth_url", "未设置")
        username = self.config.get("username", "未设置")
        isp = self.config.get("isp", "无") or "无"
        block_proxy = self.config.get("block_proxy", True)
        set_block_proxy(block_proxy if block_proxy is not None else True)
        test_sites_info = self._get_test_sites()

        monitor_cfg = self.config.get("monitor", {})
        modes = []
        if monitor_cfg.get("enable_tcp_check", True):
            modes.append(f"TCP({len(test_sites_info)})")
        if monitor_cfg.get("enable_http_check", True):
            http_urls = monitor_cfg.get("test_urls", [])
            modes.append(f"HTTP({len(http_urls)})")
        url_checks = monitor_cfg.get("url_check_urls")
        if url_checks:
            modes.append(f"网址响应({len(url_checks)})")
        modes_str = " + ".join(modes) if modes else "无"

        self.log_message(
            f"网络监控已启动 | 检测间隔: {interval}s | 方式: {modes_str}\n"
            f"认证地址: {auth_url} | 账号: {username} | 运营商: {isp}"
        )

    def check_once(self) -> dict[str, Any]:
        """执行一次网络检测（不阻塞，不做登录重试）。

        返回:
            dict: {
                "paused": bool,
                "net_ok": bool,
                "net_reason": str,
                "need_login": bool,
                "check_num": int,
                "interval": int,
                "result": NetworkCheckResult,
            }
        """
        interval = self._get_monitor_interval()
        test_sites = self._get_test_sites()

        with self._state_lock:
            self.network_check_count += 1
            self.last_check_time = datetime.datetime.now()
            check_num = self.network_check_count
            if self.network_state == NetworkState.UNKNOWN:
                self.status_detail = "正在检测网络"

        targets_str = ", ".join(f"{h}:{p}" for h, p in test_sites)
        self.log_message(f"[#{check_num}] 网络检测 -> {targets_str}")

        # 1. 暂停时段检查
        is_paused, _ = check_pause(self.config)
        if is_paused:
            pause_config = self.config.get("pause_login", {})
            start_hour = pause_config.get("start_hour", 0)
            end_hour = pause_config.get("end_hour", 6)
            self._update_state(
                status_detail=f"暂停时段（{start_hour}:00-{end_hour}:00），跳过检测"
            )
            self.log_message(
                f"暂停时段 ({start_hour}:00-{end_hour}:00)，跳过检测", "INFO"
            )
            return {
                "paused": True,
                "net_ok": True,
                "net_reason": "",
                "need_login": False,
                "check_num": check_num,
                "interval": interval,
                "result": NetworkCheckResult(
                    available=None,
                    method="paused",
                    latency_ms=0,
                    detail=f"暂停时段（{start_hour}:00-{end_hour}:00）",
                ),
            }

        # 2. 网络状态检测
        net_ok, net_reason = check_network_status(self.config)
        if net_ok:
            self._update_state(
                login_attempt_count=0,
                network_state=NetworkState.CONNECTED,
                status_detail="网络正常",
            )
            self.log_message(f"[#{check_num}] 网络正常，无需登录", "INFO")
        elif net_reason == "all_disabled":
            self.log_message("所有网络检测均未启用，跳过", "WARNING")
        else:
            self._update_state(status_detail="网络异常：待登录")

        # 自动切换检测
        self._check_profile_switch()

        return {
            "paused": False,
            "net_ok": net_ok,
            "net_reason": net_reason,
            "need_login": not net_ok and net_reason != "all_disabled",
            "check_num": check_num,
            "interval": interval,
            "result": NetworkCheckResult(
                available=net_ok,
                method=net_reason
                if net_reason in ("tcp", "http", "url")
                else "local_only",
                latency_ms=0,
                detail="" if net_ok else net_reason,
            ),
        }

    def update_status_after_login(self, success: bool, message: str = "") -> None:
        """登录完成后更新监控状态（由引擎调用）。"""
        if success:
            self._update_state(
                login_attempt_count=0,
                network_state=NetworkState.CONNECTED,
                status_detail="网络正常",
            )
            self.log_message("登录成功，网络已恢复")
        else:
            self._update_state(
                network_state=NetworkState.DISCONNECTED,
                status_detail="网络异常：登录失败",
            )
            self.log_message(f"登录失败: {message}", "WARNING")

    def stop_monitoring(self) -> None:
        """停止监控（状态清理）。"""
        self._update_state(monitoring=False, status_detail="已停止")

    def _close_browser_if_needed(self) -> None:
        """关闭浏览器实例（通过 Worker 命令队列）"""
        try:
            from app.workers.playwright_worker import CMD_BROWSER_CLOSE

            worker = self._worker_getter()
            if worker:
                self.log_message("关闭浏览器实例")
                result = worker.submit(CMD_BROWSER_CLOSE, timeout=5)
                if not result.success:
                    self.log_message(f"关闭浏览器失败: {result.error}", "WARNING")
        except Exception as e:
            self.log_message(f"关闭浏览器时出错: {e}", "WARNING")

    def _get_retry_config(self) -> tuple[int, list[int]]:
        """从配置中读取重试参数，回退到默认值"""
        retry_settings = self.config.get("retry_settings", {})
        max_retries = int(
            retry_settings.get("max_retries", self.MAX_CONSECUTIVE_LOGIN_FAILURES)
        )
        # 限制 1~5 次，避免网络故障时无限重试或退避时间过长
        max_retries = max(1, min(max_retries, 5))
        retry_interval = int(retry_settings.get("retry_interval", 5))
        from app.utils.retry import get_retry_intervals

        intervals = get_retry_intervals(retry_interval, max_retries, exponential=True)
        return max_retries, intervals

    def _get_test_sites(self) -> list[tuple[str, int]]:
        """获取测试站点列表（带缓存，返回副本避免调用方污染缓存）"""
        if self._test_sites_cache is not None:
            return list(self._test_sites_cache)
        self._test_sites_cache = self._build_test_sites()
        return list(self._test_sites_cache)

    def _build_test_sites(self) -> list[tuple[str, int]]:
        """构建测试站点列表"""
        targets = self.config.get("monitor", {}).get("ping_targets", [])
        result = parse_ping_targets(targets)
        if not result:
            result = parse_ping_targets(self.DEFAULT_PING_TARGETS)
        return result

    def _check_profile_switch(self) -> None:
        """检测网关 IP 并自动切换方案（带冷却时间）。

        检测到方案变化时设置标志位并停止监控循环，由外部重启。
        """
        if not self._profile_service:
            return

        try:
            now = time.time()
            if (
                now - self._last_gateway_check_time
                < self.GATEWAY_CHECK_COOLDOWN_SECONDS
            ):
                return

            self._last_gateway_check_time = now

            data = self._profile_service.load()
            if not data.auto_switch:
                return

            matched_id = self._profile_service.detect_matching_profile()
            if matched_id and matched_id != self._last_profile_id:
                profile = data.profiles.get(matched_id)
                profile_name = profile.name if profile else matched_id
                old_profile = data.profiles.get(self._last_profile_id)
                old_name = (
                    old_profile.name if old_profile else (self._last_profile_id or "无")
                )

                self.log_message(
                    f"检测到网络环境变化，方案切换: {old_name} -> {profile_name}",
                    "INFO",
                )

                self._last_profile_id = matched_id
                ok, msg = self._profile_service.set_active_profile(matched_id)
                if not ok:
                    # 方案可能在检测后被删除，回退缓存状态
                    self._last_profile_id = self._profile_service.load().active_profile
                    self.log_message(f"方案切换失败: {msg}", "WARNING")
                else:
                    # 方案切换成功，设置标志位并停止监控循环
                    pass
        except Exception as exc:
            self.log_message(f"方案切换检测异常: {exc}", "WARNING")
