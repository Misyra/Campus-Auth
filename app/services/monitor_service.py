from __future__ import annotations

import asyncio
import datetime
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

from app.constants import DEFAULT_NETWORK_TARGETS
from app.network.decision import (
    NetworkCheckResult,
    check_network_status,
    check_pause,
)
from app.network.parsers import parse_ping_targets
from app.network.probes import set_block_proxy
from app.schemas import RuntimeConfig
from app.utils import get_logger

if TYPE_CHECKING:
    from app.services.profile_service import ProfileService


@dataclass(frozen=True, slots=True)
class CheckOnceResult:
    """check_once() 的返回值。"""

    paused: bool
    net_ok: bool
    net_reason: str
    need_login: bool
    check_num: int
    interval: int
    result: NetworkCheckResult


class NetworkState(str, Enum):
    """网络状态枚举，用于区分首次检测和已知状态"""

    UNKNOWN = "unknown"  # 首次检测，状态未知
    CONNECTED = "connected"  # 网络正常
    DISCONNECTED = "disconnected"  # 网络异常


class NetworkMonitorCore:
    """网络监控核心类"""

    # 类常量：网络检测配置
    DEFAULT_PING_TARGETS = DEFAULT_NETWORK_TARGETS.split(",")

    def __init__(
        self,
        get_config: Callable[[], RuntimeConfig],
        logger=None,
        login_history: Any = None,
    ) -> None:
        self._get_config = get_config
        self._log_callback_logger = logger
        self._login_history = login_history

        # 状态锁：保护 snapshot() 读取的状态字段，防止跨线程竞态
        self._state_lock = threading.Lock()

        self.monitoring = False
        self.network_check_count = 0
        self.login_attempt_count = 0
        self.start_time: float | None = None
        self.last_check_time: datetime.datetime | None = None
        # 上次网络连通性检测结果（用于 UI 状态显示）
        self.network_state: NetworkState = NetworkState.UNKNOWN

        self.logger = get_logger("monitor_core", source="backend")

        # 状态详情
        self.status_detail: str = "正常"

        # 自动切换相关
        self._profile_service: ProfileService | None = None
        self._last_profile_id: str | None = None
        self._profile_switch_needed: bool = False

        # 一次性告警去重：所有网络检测均未启用时仅首次告警 WARNING
        self._detection_disabled_warned: bool = False

        # bind_interface_name 指纹：变化时需重建 SOCKS5 Forwarder
        self._last_bind_interface: str = ""

        # 绑定代理 URL（由 _start_bind_proxy 设置）
        self._bind_proxy_url: str | None = None

    def log_message(
        self, message: str, level: str = "INFO", exc_info: bool = False
    ) -> None:
        if exc_info:
            import traceback

            tb = traceback.format_exc()
            if tb and tb != "NoneType: None\n":
                message = f"{message}\n{tb}"
        target_logger = self._log_callback_logger or self.logger
        log_func = getattr(target_logger, level.lower(), target_logger.info)
        log_func("{}", message)

    def _update_state(
        self,
        *,
        monitoring: bool | None = None,
        network_check_count: int | None = None,
        login_attempt_count: int | None = None,
        start_time: float | None = None,
        last_check_time: datetime.datetime | None = None,
        network_state: NetworkState | None = None,
        status_detail: str | None = None,
    ) -> None:
        """线程安全地更新状态字段。仅更新非 None 的字段。"""
        with self._state_lock:
            if monitoring is not None:
                self.monitoring = monitoring
            if network_check_count is not None:
                self.network_check_count = network_check_count
            if login_attempt_count is not None:
                self.login_attempt_count = login_attempt_count
            if start_time is not None:
                self.start_time = start_time
            if last_check_time is not None:
                self.last_check_time = last_check_time
            if network_state is not None:
                self.network_state = network_state
            if status_detail is not None:
                self.status_detail = status_detail

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
        return self._get_config().monitor.check_interval_seconds

    def init_monitoring(self) -> None:
        """初始化监控状态（不启动循环，由引擎驱动检测）。"""
        if self.monitoring:
            self.log_message("监控已在运行中", "WARNING")
            return

        self._update_state(
            monitoring=True,
            start_time=time.time(),
            network_check_count=0,
            login_attempt_count=0,
            network_state=NetworkState.UNKNOWN,
            status_detail="正在启动监控",
        )

        interval = self._get_monitor_interval()
        config = self._get_config()
        auth_url = config.credentials.auth_url or "未设置"
        username = config.credentials.username or "未设置"
        isp = config.credentials.isp or "无"
        block_proxy = config.app_settings.block_proxy
        set_block_proxy(block_proxy if block_proxy is not None else True)
        test_sites_info = self._get_test_sites()

        monitor_cfg = config.monitor
        modes = []
        if monitor_cfg.enable_tcp_check:
            modes.append(f"TCP({len(test_sites_info)})")
        if monitor_cfg.enable_http_check:
            http_urls = monitor_cfg.test_urls
            modes.append(f"HTTP({len(http_urls)})")
        url_checks = monitor_cfg.url_check_urls
        if url_checks:
            modes.append(f"网址响应({len(url_checks)})")
        modes_str = " + ".join(modes) if modes else "无"

        # 脱敏处理：截断认证地址，隐藏用户名明文
        masked_url = auth_url[:20] + "..." if len(auth_url) > 20 else auth_url
        masked_username = username[:3] + "***" if len(username) > 3 else "***"

        self.log_message(
            f"网络监控已启动: 间隔={interval}s, 方式={modes_str}, "
            f"认证地址={masked_url}, 账号={masked_username}, 运营商={isp}"
        )

        # 绑定网卡：启动 SOCKS5 Forwarder
        self._start_bind_proxy()

    async def check_once(self) -> CheckOnceResult:
        """执行一次网络检测（async，不阻塞，不做登录重试）。"""
        interval = self._get_monitor_interval()
        test_sites = self._get_test_sites()

        with self._state_lock:
            self.network_check_count += 1
            self.last_check_time = datetime.datetime.now()
            check_num = self.network_check_count
            if self.network_state == NetworkState.UNKNOWN:
                self.status_detail = "正在检测网络"

        monitor_cfg = self._get_config().monitor
        targets_parts = []
        if monitor_cfg.enable_tcp_check:
            targets_parts.append(f"TCP: {', '.join(f'{h}:{p}' for h, p in test_sites)}")
        if monitor_cfg.enable_http_check:
            targets_parts.append(f"HTTP: {', '.join(monitor_cfg.test_urls)}")
        if monitor_cfg.url_check_urls:
            targets_parts.append(f"网址响应: {', '.join(monitor_cfg.url_check_urls)}")
        targets_str = " | ".join(targets_parts) if targets_parts else "无检测目标"
        self.log_message(f"网络检测 #{check_num}: {targets_str}", "DEBUG")

        # 1. 暂停时段检查
        config = self._get_config()
        is_paused, _ = check_pause(config.pause)
        if is_paused:
            start_hour = config.pause.start_hour
            end_hour = config.pause.end_hour
            self._update_state(
                status_detail=f"暂停时段（{start_hour}:00-{end_hour}:00），跳过检测"
            )
            self.log_message(
                f"暂停时段 ({start_hour}:00-{end_hour}:00)，跳过检测", "INFO"
            )
            return CheckOnceResult(
                paused=True,
                net_ok=True,
                net_reason="",
                need_login=False,
                check_num=check_num,
                interval=interval,
                result=NetworkCheckResult(
                    available=None,
                    method="paused",
                    latency_ms=0,
                    detail=f"暂停时段（{start_hour}:00-{end_hour}:00）",
                ),
            )

        # 2. IP 变化检测（网卡绑定场景下 DHCP 续租可能导致 IP 变化）
        self._check_bind_ip_change()

        # 3. 网络状态检测
        net_ok, net_reason, net_method = await check_network_status(
            self._get_config().monitor
        )
        if net_ok:
            self._update_state(
                network_state=NetworkState.CONNECTED,
                status_detail="网络正常",
            )
            self.log_message(f"网络检测 #{check_num}: 正常", "DEBUG")
        elif net_reason == "all_disabled":
            if not self._detection_disabled_warned:
                self.log_message("所有网络检测均未启用，跳过", "WARNING")
                self._detection_disabled_warned = True
            else:
                self.log_message("所有网络检测均未启用，跳过", "DEBUG")
            # 所有网络检测均未启用时更新状态，避免 UI 显示与实际不符
            self._update_state(
                network_state=NetworkState.UNKNOWN,
                status_detail="网络检测已禁用",
            )
        else:
            self._update_state(
                network_state=NetworkState.DISCONNECTED,
                status_detail="网络异常：待登录",
            )

        # 自动切换检测
        await self._check_profile_switch()

        return CheckOnceResult(
            paused=False,
            net_ok=net_ok,
            net_reason=net_reason,
            need_login=not net_ok and net_reason != "all_disabled",
            check_num=check_num,
            interval=interval,
            result=NetworkCheckResult(
                available=net_ok,
                method=net_method,
                latency_ms=0,
                detail="" if net_ok else net_reason,
            ),
        )

    def stop_monitoring(self) -> None:
        """停止监控（状态清理）。"""
        self._stop_bind_proxy()
        self._update_state(monitoring=False, status_detail="已停止")

    @property
    def bind_proxy_url(self) -> str | None:
        """当前绑定代理 URL（供引擎传递给 Worker）。"""
        return self._bind_proxy_url

    def _start_bind_proxy(self) -> None:
        """根据 bind_interface_name 启动 SOCKS5 Forwarder。"""
        config = self._get_config()
        bind_name = config.monitor.bind_interface_name
        self._last_bind_interface = bind_name
        self._bind_proxy_url: str | None = None
        self._interface_mgr = None
        self._socks5_server = None
        self._last_bind_ip: str | None = None

        if not bind_name:
            return

        from app.network.interfaces import InterfaceManager

        self._interface_mgr = InterfaceManager()

        # 检查网卡是否可用于绑定
        bindable, reason = self._interface_mgr.is_interface_bindable(bind_name)
        if not bindable:
            self.log_message(f"{reason}，回退系统路由", "ERROR")
            return

        bind_ip = self._interface_mgr.resolve_ip(bind_name)
        if not bind_ip:
            self.log_message(f"绑定网卡 {bind_name} 不可用，回退系统路由", "ERROR")
            return

        from app.network.proxy import Socks5Server

        # 传 interface_name（接口索引绑定）+ fallback_source_ip（Linux 降级用）
        self._socks5_server = Socks5Server(bind_name, bind_ip)
        try:
            self._socks5_server.start()
            self._bind_proxy_url = self._socks5_server.proxy_url
            self._last_bind_ip = bind_ip
            self.log_message(
                f"网卡绑定已启用: {bind_name} ({bind_ip}) -> {self._bind_proxy_url}"
            )
        except Exception as exc:
            self.log_message(f"SOCKS5 Forwarder 启动失败，关闭绑定功能: {exc}", "ERROR")
            self._socks5_server = None
            self._bind_proxy_url = None

    def _stop_bind_proxy(self) -> None:
        """停止 SOCKS5 Forwarder。"""
        if hasattr(self, "_socks5_server") and self._socks5_server:
            self._socks5_server.stop()
            self._socks5_server = None
            self._bind_proxy_url = None

    def _needs_bind_proxy_rebuild(self) -> bool:
        """bind_interface_name 变化时需重建 SOCKS5 Forwarder。"""
        current = self._get_config().monitor.bind_interface_name
        return current != self._last_bind_interface

    def _check_bind_ip_change(self) -> None:
        """检测绑定网卡的 IP 变化。

        接口索引绑定模式下，DHCP IP 变化不影响绑定（接口索引不变）。
        fallback_source_ip 仅 Linux 无 CAP_NET_RAW 时使用，变化影响有限。
        此处仅记录日志，不重建代理；接口名变化走 _needs_bind_proxy_rebuild 路径。
        """
        bind_name = self._get_config().monitor.bind_interface_name
        if (
            not bind_name
            or not hasattr(self, "_interface_mgr")
            or not self._interface_mgr
        ):
            return

        new_ip = self._interface_mgr.resolve_ip(bind_name)
        old_ip = getattr(self, "_last_bind_ip", None)
        if new_ip == old_ip:
            return

        self._last_bind_ip = new_ip
        if new_ip:
            self.log_message(
                f"绑定网卡 DHCP IP 变化: {old_ip} -> {new_ip}（接口索引绑定不受影响）"
            )

    def _get_test_sites(self) -> list[tuple[str, int]]:
        """获取测试站点列表（每次重算，targets 量小无需缓存）。"""
        targets = self._get_config().monitor.ping_targets
        result = parse_ping_targets(targets)
        if not result:
            result = parse_ping_targets(self.DEFAULT_PING_TARGETS)
        return result

    async def _check_profile_switch(self) -> None:
        """检测网关 IP 并自动切换方案。

        检测到方案变化时设置标志位并停止监控循环，由外部重启。
        内部同步磁盘 IO 通过 asyncio.to_thread() 包装，避免阻塞事件循环。
        """
        if not self._profile_service:
            return

        try:
            data = await asyncio.to_thread(self._profile_service.load)
            if not data.auto_switch:
                return

            matched_id = await asyncio.to_thread(
                self._profile_service.detect_matching_profile, data
            )
            if matched_id and matched_id != self._last_profile_id:
                profile = data.profiles.get(matched_id)
                profile_name = profile.name if profile else matched_id
                old_profile = data.profiles.get(self._last_profile_id)
                old_name = (
                    old_profile.name if old_profile else (self._last_profile_id or "无")
                )

                self.log_message(
                    f"方案切换: {old_name} 至 {profile_name}",
                    "INFO",
                )

                self._last_profile_id = matched_id
                ok, msg = await asyncio.to_thread(
                    self._profile_service.set_active_profile, matched_id
                )
                if not ok:
                    # 方案可能在检测后被删除，回退缓存状态
                    reloaded = await asyncio.to_thread(self._profile_service.load)
                    self._last_profile_id = reloaded.active_profile
                    self.log_message(f"方案切换失败: {matched_id}, {msg}", "WARNING")
                else:
                    # 方案切换成功，设置标志位
                    self._profile_switch_needed = True
        except Exception as exc:
            self.log_message(f"方案切换检测失败: {exc}", "WARNING")

    def consume_profile_switch_flag(self) -> bool:
        """消费重启标志位（由引擎线程串行调用，无需额外同步）。"""
        if self._profile_switch_needed:
            self._profile_switch_needed = False
            return True
        return False
