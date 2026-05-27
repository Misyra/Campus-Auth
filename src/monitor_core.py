from __future__ import annotations

import asyncio
import datetime
import logging
import socket
import threading
import time
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable, Dict, Optional

from .network_test import (
    is_local_network_connected,
    is_network_available,
    set_block_proxy,
)
from .utils import (
    LoginAttemptHandler,
    TimeUtils,
    get_runtime_stats,
    setup_logger,
)
from .utils.network_helpers import parse_host_port
from .utils.notify import send_notification

if TYPE_CHECKING:
    from backend.profile_service import ProfileService


class RecoveryResult(str, Enum):
    LOGIN_OK = "login_ok"
    GIVE_UP = "give_up"
    BREAK = "break"
    NET_DISCONNECT = "net_disconnect"


class NetworkMonitorCore:
    """网络监控核心类"""

    # 类常量：监控配置
    DEFAULT_INTERVAL_SECONDS = 300
    MAX_CONSECUTIVE_LOGIN_FAILURES = 3
    LOGIN_RETRY_INTERVALS = [5, 30, 60]
    PAUSE_CHECK_INTERVAL_SECONDS = 300
    PAUSE_CHECK_STEP_SECONDS = 15
    MIN_WAIT_STEP_SECONDS = 5
    MAX_WAIT_STEP_SECONDS = 20
    LOG_DIVIDER_LENGTH = 50

    # 类常量：网络检测配置
    NETWORK_CHECK_TIMEOUT_SECONDS = 2
    DEFAULT_PING_TARGETS = ["8.8.8.8:53", "114.114.114.114:53", "www.baidu.com:443"]

    # 类常量：自动切换检测冷却
    GATEWAY_CHECK_COOLDOWN_SECONDS = 60

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        log_callback: Optional[Callable[[str, str, str], None]] = None,
        thread_done: Optional[threading.Event] = None,
    ) -> None:
        self.config = config if config is not None else {}
        self.log_callback = log_callback

        # 线程完成事件：由 MonitorService 传入，用于安全等待线程实际结束
        self._thread_done: Optional[threading.Event] = thread_done

        self.monitoring = False
        self.network_check_count = 0
        self.login_attempt_count = 0
        self.start_time: Optional[float] = None
        self.last_check_time: Optional[datetime.datetime] = None
        # Last known connectivity result for UI status.
        self.last_network_ok: Optional[bool] = None

        self._stop_requested = False
        self._cancel_login = threading.Event()
        self._stop_event = threading.Event()
        self._test_sites_cache: Optional[list[tuple[str, int]]] = None
        self.logger = setup_logger("monitor", self.config.get("logging", {}))

        # 持久化登录处理器，重试时复用浏览器
        self._login_handler: Optional[LoginAttemptHandler] = None
        self._reuse_browser = False

        # 自动切换相关
        self._profile_service: Optional[ProfileService] = None
        self._on_profile_switch: Optional[Callable[[str], None]] = None
        self._last_profile_id: Optional[str] = None
        self._last_gateway_check_time: float = 0

    def log_message(self, message: str, level: int = logging.INFO) -> None:
        if self.log_callback:
            self.log_callback(
                message,
                logging.getLevelName(level),
                "monitor.core",
            )
        else:
            self.logger.log(level, message)

    def snapshot(self) -> Dict[str, Any]:
        return {
            "monitoring": self.monitoring,
            "network_check_count": self.network_check_count,
            "login_attempt_count": self.login_attempt_count,
            "last_check_time": self.last_check_time.isoformat()
            if self.last_check_time
            else None,
            "start_time": self.start_time,
            "last_network_ok": self.last_network_ok,
        }

    def set_profile_service(
        self,
        profile_service: ProfileService,
        on_switch: Optional[Callable[[str], None]] = None,
    ) -> None:
        """设置 profile 服务用于自动切换"""
        self._profile_service = profile_service
        self._on_profile_switch = on_switch
        if profile_service:
            self._last_profile_id = profile_service.get_active_profile_id()

    def update_config(self, new_config: Dict[str, Any]) -> None:
        """热更新运行时配置（方案切换时调用）"""
        self.log_message("运行时配置已更新 (热更新)", logging.INFO)
        self.config = new_config
        self._test_sites_cache = None  # 清除测试站点缓存
        # 同步 block_proxy 到 network_test 模块，决定 HTTP 客户端是否信任系统代理
        set_block_proxy(self.config.get("block_proxy", True))

    def start_monitoring(self) -> None:
        try:
            if self.monitoring:
                self.log_message("监控已在运行中", logging.WARNING)
                return

            self.monitoring = True
            self._stop_requested = False
            self._cancel_login.clear()
            self._stop_event.clear()
            self._reuse_browser = True
            self.start_time = time.time()
            self.network_check_count = 0
            self.login_attempt_count = 0
            self.last_network_ok = None
            self._test_sites_cache = None  # 重置缓存

            interval = self.config.get("monitor", {}).get(
                "interval", self.DEFAULT_INTERVAL_SECONDS
            )
            auth_url = self.config.get("auth_url", "未设置")
            username = self.config.get("username", "未设置")
            isp = self.config.get("isp", "无") or "无"
            set_block_proxy(self.config.get("block_proxy", True))
            test_sites_info = self._get_test_sites()
            targets_str = ", ".join(f"{h}:{p}" for h, p in test_sites_info)

            self.log_message("=" * self.LOG_DIVIDER_LENGTH)
            self.log_message("网络监控已启动")
            self.log_message(f"检测间隔: {interval}s | 检测目标: {targets_str}")
            self.log_message(f"认证地址: {auth_url}")
            self.log_message(f"账号: {username}")
            self.log_message(f"运营商: {isp}")
            self.log_message("=" * self.LOG_DIVIDER_LENGTH)

            try:
                self.monitor_network()
            except KeyboardInterrupt:
                self.log_message("收到中断信号，停止监控", logging.WARNING)
            # 注：此处捕获 Exception 后调用 stop_monitoring()，会更新 StatusSnapshot 并推送
            # WebSocket 状态变化，前端可见 monitoring=false。非静默退出。
            except Exception as exc:
                self.log_message(f"监控异常: {exc}", logging.ERROR)
            finally:
                self.stop_monitoring()
        finally:
            if self._thread_done is not None:
                self._thread_done.set()

    def stop_monitoring(self) -> None:
        if not self.monitoring and self._stop_requested:
            return

        self._stop_requested = True
        self._cancel_login.set()
        self._stop_event.set()
        was_monitoring = self.monitoring
        self.monitoring = False

        # 清除登录处理器引用，浏览器会在 attempt_login 返回后被清理
        self._login_handler = None

        if was_monitoring and self.start_time:
            runtime, stats = get_runtime_stats(
                self.start_time, self.network_check_count
            )
            self.log_message("=" * self.LOG_DIVIDER_LENGTH)
            self.log_message(f"监控已停止，运行时长: {runtime}")
            self.log_message(f"检测次数: {self.network_check_count}")
            self.log_message("=" * self.LOG_DIVIDER_LENGTH)

    def _wait_interruptible(self, seconds: int, step: int = 5) -> bool:
        remaining = max(0, seconds)
        while self.monitoring and remaining > 0:
            if self._stop_event.wait(timeout=min(step, remaining)):
                return False
            remaining -= step
        return self.monitoring

    def _get_retry_config(self) -> tuple[int, list[int]]:
        """从配置中读取重试参数，回退到默认值"""
        retry_settings = self.config.get("retry_settings", {})
        max_retries = int(
            retry_settings.get("max_retries", self.MAX_CONSECUTIVE_LOGIN_FAILURES)
        )
        # 限制 1~5 次，避免网络故障时无限重试或退避时间过长
        max_retries = max(1, min(max_retries, 5))
        retry_interval = int(retry_settings.get("retry_interval", 5))
        # 生成递增间隔列表：[retry_interval, retry_interval*2, retry_interval*4, ...]
        intervals = [retry_interval * (2**i) for i in range(max_retries)]
        return max_retries, intervals

    def _login_retry_or_break(self) -> str:
        """登录失败后决定重试还是放弃。

        Returns:
            "retry"   — 短暂等待后应重试（continue）
            "break"   — 监控已停止（break）
            "give_up" — 超过最大重试次数，应等待正常检测间隔（fall through）
        """
        max_retries, intervals = self._get_retry_config()
        idx = self.login_attempt_count - 1
        if idx < len(intervals):
            wait = intervals[idx]
            self.log_message(f"{wait} 秒后重试登录...", logging.DEBUG)
            if not self._wait_interruptible(wait, step=5):
                return RecoveryResult.BREAK
            return "retry"
        # 超过最大重试次数，放弃本次网络检测周期
        self.log_message(
            f"连续登录失败 {self.login_attempt_count} 次，等待下次检测周期",
            logging.WARNING,
        )
        self.login_attempt_count = 0
        return RecoveryResult.GIVE_UP

    def _is_auth_url_reachable(self) -> bool:
        """检查认证地址的 TCP 可达性。

        返回 False 时表示认证地址不可达，应跳过登录尝试。
        无认证地址配置时返回 True（兼容模式）。
        """
        auth_url = self.config.get("auth_url", "")
        if not auth_url:
            return True
        from urllib.parse import urlparse

        try:
            parsed = urlparse(auth_url)
            host = parsed.hostname
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            if not host:
                return True
            sock = socket.create_connection((host, port), timeout=3)
            sock.close()
            return True
        except Exception:
            return False

    def _login_recovery_loop(self) -> str:
        """登录恢复内层循环。

        在外层检测到网络异常后调用，只做登录重试，不做网络检测。
        使用 is_local_network_connected() 做快速物理连接检查（~10ms）。

        Returns:
            "login_ok"         — 登录成功，外层应重置计数器
            "give_up"          — 超过最大重试次数，外层应等待正常检测间隔
            "break"            — 监控已停止
            "net_disconnect"   — 物理网络断开，外层应等待正常检测间隔

        Design rationale:
        方法是独立循环而非内联在 monitor_network() 中的原因：
        原设计是在 monitor_network() 的单层 while 循环中通过 continue 回绕到
        循环顶部，导致每次 retry 都重新执行 is_network_available()（TCP 探测
        耗时 2-8s），使配置的 retry_interval（如 5s）实际被拉长到 12-20s。
        提取为独立方法后，内层只做快速物理连接检查（is_local_network_connected,
        ~10ms）+ 登录重试，不做 is_network_available()，确保 retry 间隔准确。
        """
        while self.monitoring:
            # 1. 快速检查物理网络连接（~10ms，非 TCP 探测）
            if not is_local_network_connected():
                self.log_message(
                    "物理网络未连接，停止重试，等待下次检测周期",
                    logging.WARNING,
                )
                self.login_attempt_count = 0
                self.last_network_ok = False
                return RecoveryResult.NET_DISCONNECT

            # 2. 检查配置方案是否切换（内部有 60s 冷却）
            self._check_profile_switch()

            # 2.5 前置检查认证地址可达性，避免无效的浏览器启动
            if not self._is_auth_url_reachable():
                self.log_message(
                    f"认证地址 {self.config.get('auth_url', '?')} 不可达，跳过登录重试",
                    logging.WARNING,
                )
                self.login_attempt_count = 0
                self.last_network_ok = False
                return RecoveryResult.NET_DISCONNECT

            # 3. 执行登录
            login_ok, login_msg = self.attempt_login()
            time.sleep(2)  # 保持与现有行为一致：等待 2s 后再做重试决策，
            # 避免在 Portal 尚未完全更新会话状态时立即重试

            if login_ok:
                self.login_attempt_count = 0
                self.last_network_ok = True
                return RecoveryResult.LOGIN_OK

            # 4. 登录失败，记录并判断是否重试
            self.login_attempt_count += 1
            self.last_network_ok = False
            max_retries, _ = self._get_retry_config()
            self.log_message(
                f"登录失败 (第{self.login_attempt_count}/{max_retries}次)",
                logging.ERROR,
            )

            if self.login_attempt_count == 2:
                send_notification(
                    "Campus-Auth 登录失败",
                    f"自动登录已失败 {self.login_attempt_count} 次，正在重试...",
                )

            failed_count = self.login_attempt_count
            action = self._login_retry_or_break()
            if action == RecoveryResult.BREAK:
                return RecoveryResult.BREAK
            if action == RecoveryResult.GIVE_UP:
                send_notification(
                    "Campus-Auth 登录失败",
                    f"连续 {failed_count} 次登录失败，等待下次检测周期",
                )
                return RecoveryResult.GIVE_UP
            # action == "retry" → 继续内层循环，不做网络检测

        return RecoveryResult.BREAK

    def monitor_network(self) -> None:
        consecutive_failures = 0

        while self.monitoring:
            # 每次循环重新读取 interval 和 test_sites，支持运行时方案切换
            interval = int(
                self.config.get("monitor", {}).get(
                    "interval", self.DEFAULT_INTERVAL_SECONDS
                )
            )
            pause_config = self.config.get("pause_login", {})
            if TimeUtils.is_in_pause_period(pause_config):
                start_hour = pause_config.get("start_hour", 0)
                end_hour = pause_config.get("end_hour", 6)
                self.log_message(
                    f"暂停时段 ({start_hour}:00-{end_hour}:00)，跳过检测",
                    logging.INFO,
                )
                if not self._wait_interruptible(
                    self.PAUSE_CHECK_INTERVAL_SECONDS,
                    step=self.PAUSE_CHECK_STEP_SECONDS,
                ):
                    break
                continue

            # 重新读取测试站点和探测模式（方案切换后可能已更新）
            test_sites = self._get_test_sites()
            strict_mode = self.config.get("monitor", {}).get("strict_mode", True)

            self.network_check_count += 1
            self.last_check_time = datetime.datetime.now()
            targets_str = ", ".join(f"{h}:{p}" for h, p in test_sites)
            self.log_message(f"[#{self.network_check_count}] 网络检测 → {targets_str}")

            try:
                network_ok = is_network_available(
                    test_sites=test_sites,
                    timeout=self.NETWORK_CHECK_TIMEOUT_SECONDS,
                    require_both=strict_mode,
                )
            except OSError as exc:
                self.log_message(f"网络检测 IO 错误: {exc}", logging.ERROR)
                network_ok = False
            except Exception as exc:
                self.log_message(f"网络检测异常: {exc}", logging.ERROR)
                network_ok = False

            # Update last known connectivity state based on the check result.
            self.last_network_ok = network_ok

            if network_ok:
                consecutive_failures = 0
                self.login_attempt_count = 0
                self.log_message(
                    f"[#{self.network_check_count}] 网络正常，无需登录", logging.INFO
                )
            else:
                consecutive_failures += 1
                self.log_message(
                    f"[#{self.network_check_count}] 网络异常，连续失败 {consecutive_failures} 次",
                    logging.WARNING,
                )

                # ── 网络异常处理路径 ──
                # 当 is_network_available() 返回 False 时，先判断物理连接状态。
                # 如果物理连接正常，则进入 _login_recovery_loop() 内层循环做登录重试；
                # 如果物理断开，则跳过登录，直接等待下次检测周期。

                # 检查物理网络是否连接，未连接则跳过登录恢复
                if not is_local_network_connected():
                    self.log_message(
                        f"[#{self.network_check_count}] 物理网络未连接（WiFi/网线断开），跳过登录，等待下次检测",
                        logging.WARNING,
                    )
                    consecutive_failures = 0
                    self.login_attempt_count = 0
                    self.last_network_ok = False
                else:
                    # 进入登录恢复内层循环
                    # 内层不做 is_network_available()，只做快速物理连接检查 + 登录重试
                    recovery_result = self._login_recovery_loop()
                    if recovery_result == RecoveryResult.LOGIN_OK:
                        consecutive_failures = 0
                        self.login_attempt_count = 0
                        self.last_network_ok = True
                        self.log_message(
                            f"[#{self.network_check_count}] 登录成功，网络已恢复"
                        )
                    elif recovery_result == RecoveryResult.BREAK:
                        break
                    elif recovery_result == RecoveryResult.NET_DISCONNECT:
                        consecutive_failures = 0
                        # fall through to interval wait
                    # RecoveryResult.GIVE_UP → fall through to interval wait

            next_check = datetime.datetime.now() + datetime.timedelta(seconds=interval)
            self.log_message(
                f"等待 {interval} 秒至下次检测周期（{next_check.strftime('%H:%M:%S')}）",
                logging.INFO,
            )
            wait_step = min(
                self.MAX_WAIT_STEP_SECONDS,
                max(self.MIN_WAIT_STEP_SECONDS, interval // 10),
            )
            if not self._wait_interruptible(interval, step=wait_step):
                break

    def _get_test_sites(self) -> list[tuple[str, int]]:
        """获取测试站点列表（带缓存）"""
        if self._test_sites_cache is not None:
            return self._test_sites_cache
        self._test_sites_cache = self._build_test_sites()
        return self._test_sites_cache

    def _build_test_sites(self) -> list[tuple[str, int]]:
        """构建测试站点列表"""
        targets = self.config.get("monitor", {}).get("ping_targets", [])
        if isinstance(targets, str):
            raw_targets = [item.strip() for item in targets.split(",") if item.strip()]
        else:
            raw_targets = [str(item).strip() for item in targets if str(item).strip()]

        if not raw_targets:
            raw_targets = self.DEFAULT_PING_TARGETS.copy()

        # 补全缺少端口的项（IPv4 默认 DNS 53，域名默认 HTTPS 443）
        _targets: list[str] = []
        for item in raw_targets:
            if ":" not in item:
                parts = item.split(".")
                is_ipv4 = len(parts) == 4 and all(p.isdigit() for p in parts)
                _targets.append(f"{item}:{53 if is_ipv4 else 443}")
            else:
                _targets.append(item)
        return parse_host_port(_targets)

    def _check_profile_switch(self) -> None:
        """检测网关 IP 并自动切换方案（带冷却时间）"""
        if not self._profile_service:
            return

        now = time.time()
        if now - self._last_gateway_check_time < self.GATEWAY_CHECK_COOLDOWN_SECONDS:
            return

        self._last_gateway_check_time = now

        data = self._profile_service.load()
        if not data.auto_switch:
            return

        matched_id = self._profile_service.detect_matching_profile()
        if matched_id and matched_id != self._last_profile_id:
            profile = data.profiles.get(matched_id)
            profile_name = profile.name if profile else matched_id

            self.log_message(
                f"检测到网络环境变化，切换方案: {profile_name}",
                logging.INFO,
            )

            self._last_profile_id = matched_id
            ok, msg = self._profile_service.set_active_profile(matched_id)
            if not ok:
                # 方案可能在检测后被删除，回退缓存状态
                self._last_profile_id = self._profile_service.load().active_profile
                self.log_message(f"方案切换失败: {msg}", logging.WARNING)

            if self._on_profile_switch:
                self._on_profile_switch(profile_name)

    def attempt_login(self) -> tuple[bool, str]:
        active_task = self.config.get("active_task", "") or "default"
        auth_url = self.config.get("auth_url", "?")
        username = self.config.get("username", "?")
        isp = self.config.get("isp", "无") or "无"
        self.log_message(
            f"开始登录认证 → URL={auth_url} "
            f"用户={username} "
            f"运营商={isp} "
            f"任务={active_task}"
        )

        if self._stop_event.is_set():
            self.log_message("监控已停止，跳过登录", logging.WARNING)
            return False, "监控已停止"

        try:
            # ── 通过 PlaywrightWorker 派发登录 ──
            # 原实现在此创建独立 asyncio 事件循环（new_event_loop / run_until_complete / loop.close）
            # 并直接管理 LoginAttemptHandler 的生命周期。
            # 重构后改为通过 get_worker().submit(CMD_LOGIN, ...) 将登录任务提交到
            # Worker 线程执行，Worker 内部管理浏览器生命周期和 LoginAttemptHandler。
            from src.playwright_worker import get_worker, CMD_LOGIN

            login_timeout = self.config.get("browser_settings", {}).get("timeout", 120)
            data = {
                "config": self.config,
                "cancel_event": self._cancel_login,
                "reuse_browser": self._reuse_browser,
                "skip_pause_check": True,
            }
            result = get_worker().submit(CMD_LOGIN, data=data, timeout=login_timeout)
            success = result.success
            message = result.data if result.success else result.error
            # 检查是否在登录过程中被取消
            if self._cancel_login.is_set():
                self.log_message("登录已被取消", logging.WARNING)
                return False, "登录已被取消"
            if success:
                self.log_message(f"登录成功 ✓ {message}")
            else:
                self.log_message(f"登录失败 ✗ {message}", logging.ERROR)
                self._reuse_browser = False  # 失败后重置，下次重新创建浏览器实例
            return success, message
        except asyncio.TimeoutError as exc:
            self.log_message(f"登录超时: {exc}", logging.ERROR)
            self._reuse_browser = False  # 失败后重置
            return False, f"登录超时: {exc}"
        except ConnectionError as exc:
            self.log_message(f"登录连接错误: {exc}", logging.ERROR)
            self._reuse_browser = False  # 失败后重置
            return False, f"连接错误: {exc}"
        except RuntimeError as exc:
            self.log_message(f"登录运行时错误: {exc}", logging.ERROR)
            self._reuse_browser = False  # 失败后重置
            return False, f"运行时错误: {exc}"
        except Exception as exc:
            self.log_message(f"登录执行异常: {exc}", logging.ERROR)
            self._reuse_browser = False  # 失败后重置
            return False, str(exc)
