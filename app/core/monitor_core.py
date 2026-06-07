from __future__ import annotations

import datetime
import threading
import time
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable, Dict, Optional

from app.constants import DEFAULT_NETWORK_TARGETS
from app.network.decision import check_login_prerequisites, check_network_status, check_pause
from app.network.probes import set_block_proxy
from app.utils import (
    get_runtime_stats,
    get_logger,
)
from app.utils.network_helpers import parse_host_port
from app.utils.notify import send_notification

if TYPE_CHECKING:
    from app.services.profile import ProfileService


class RecoveryResult(str, Enum):
    LOGIN_OK = "login_ok"
    GIVE_UP = "give_up"
    BREAK = "break"
    NET_DISCONNECT = "net_disconnect"
    PAUSED = "paused"


class NetworkState(str, Enum):
    """网络状态枚举，用于区分首次检测和已知状态"""
    UNKNOWN = "unknown"          # 首次检测，状态未知
    CONNECTED = "connected"      # 网络正常
    DISCONNECTED = "disconnected"  # 网络异常


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

    # 类常量：网络检测配置
    NETWORK_CHECK_TIMEOUT_SECONDS = 2
    DEFAULT_PING_TARGETS = DEFAULT_NETWORK_TARGETS.split(",")

    # 类常量：自动切换检测冷却
    GATEWAY_CHECK_COOLDOWN_SECONDS = 60

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        log_callback: Optional[Callable[[str, str, str], None]] = None,
        thread_done: Optional[threading.Event] = None,
        login_history: Any = None,
    ) -> None:
        self.config = config if config is not None else {}
        self.log_callback = log_callback
        self._login_history = login_history

        # 线程完成事件：由 MonitorService 传入，用于安全等待线程实际结束
        self._thread_done: Optional[threading.Event] = thread_done

        self.monitoring = False
        self.network_check_count = 0
        self.login_attempt_count = 0
        self.start_time: Optional[float] = None
        self.last_check_time: Optional[datetime.datetime] = None
        # 上次网络连通性检测结果（用于 UI 状态显示）
        self.network_state: NetworkState = NetworkState.UNKNOWN

        self._stop_requested = False
        self._cancel_login = threading.Event()
        self._stop_event = threading.Event()
        # 登录恢复进行中标志（供定时任务等待）
        self._login_recovery_in_progress = threading.Event()
        self._test_sites_cache: Optional[list[tuple[str, int]]] = None
        self.logger = get_logger("monitor")

        # 状态详情
        self.status_detail: str = "正常"

        # 自动切换相关
        self._profile_service: Optional[ProfileService] = None
        self._on_profile_switch: Optional[Callable[[str], None]] = None
        self._last_profile_id: Optional[str] = None
        self._last_gateway_check_time: float = 0

    def log_message(self, message: str, level: str = "INFO", exc_info: bool = False) -> None:
        if exc_info:
            import traceback
            tb = traceback.format_exc()
            if tb and tb != "NoneType: None\n":
                message = f"{message}\n{tb}"
        if self.log_callback:
            self.log_callback(
                message,
                level,
                "monitor.core",
            )
        else:
            log_func = getattr(self.logger, level.lower(), self.logger.info)
            log_func(message)

    def snapshot(self) -> Dict[str, Any]:
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
        self.log_message("运行时配置已更新 (热更新)", "INFO")
        self.config = new_config
        self._test_sites_cache = None  # 清除测试站点缓存
        # 同步 block_proxy 到 network_test 模块，决定 HTTP 客户端是否信任系统代理
        set_block_proxy(self.config.get("block_proxy", True))

    def _get_monitor_interval(self) -> int:
        """获取当前配置的检测间隔（秒）。"""
        return int(
            self.config.get("monitor", {}).get(
                "interval", self.DEFAULT_INTERVAL_SECONDS
            )
        )

    def start_monitoring(self) -> None:
        try:
            if self.monitoring:
                self.log_message("监控已在运行中", "WARNING")
                return

            self.monitoring = True
            self._stop_requested = False
            self._cancel_login.clear()
            self._stop_event.clear()
            self.start_time = time.time()
            self.network_check_count = 0
            self.login_attempt_count = 0
            self.network_state = NetworkState.UNKNOWN
            self.status_detail = "正在启动监控"
            self._test_sites_cache = None  # 重置缓存

            interval = self._get_monitor_interval()
            auth_url = self.config.get("auth_url", "未设置")
            username = self.config.get("username", "未设置")
            isp = self.config.get("isp", "无") or "无"
            set_block_proxy(self.config.get("block_proxy", True))
            test_sites_info = self._get_test_sites()

            # 构建检测方式摘要
            monitor_cfg = self.config.get("monitor", {})
            modes = []
            if monitor_cfg.get("enable_tcp_check", True):
                modes.append(f"TCP({len(test_sites_info)})")
            if monitor_cfg.get("enable_http_check", True):
                http_urls = monitor_cfg.get("test_urls", [])
                modes.append(f"HTTP({len(http_urls)})")
            portal_checks = monitor_cfg.get("portal_check_urls")
            if portal_checks:
                modes.append(f"Portal({len(portal_checks)})")
            modes_str = " + ".join(modes) if modes else "无"

            self.log_message(
                f"网络监控已启动 | 检测间隔: {interval}s | 方式: {modes_str}\n"
                f"认证地址: {auth_url} | 账号: {username} | 运营商: {isp}"
            )

            try:
                self.monitor_network()
            except KeyboardInterrupt:
                self.log_message("收到中断信号，停止监控", "WARNING")
            # 注：此处捕获 Exception 后调用 stop_monitoring()，会更新 StatusSnapshot 并推送
            # WebSocket 状态变化，前端可见 monitoring=false。非静默退出。
            except Exception as exc:
                self.log_message(f"监控异常: {exc}", "ERROR", exc_info=True)
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
        self.status_detail = "已停止"

        if was_monitoring and self.start_time:
            runtime, stats = get_runtime_stats(
                self.start_time, self.network_check_count
            )
            self.log_message(f"监控已停止 | 运行时长: {runtime} | 检测次数: {self.network_check_count}")

    def _close_browser_if_needed(self) -> None:
        """关闭浏览器实例（通过 Worker 命令队列）"""
        try:
            from app.workers.playwright_worker import get_worker, CMD_BROWSER_CLOSE

            worker = get_worker()
            if worker:
                self.log_message("关闭浏览器实例")
                result = worker.submit(CMD_BROWSER_CLOSE, timeout=5)
                if not result.success:
                    self.log_message(
                        f"关闭浏览器失败: {result.error}", "WARNING"
                    )
        except Exception as e:
            self.log_message(f"关闭浏览器时出错: {e}", "WARNING")

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

    def _login_retry_or_break(
        self, max_retries: int | None = None, intervals: list[int] | None = None
    ) -> str:
        """登录失败后决定重试还是放弃。

        Args:
            max_retries: 缓存的最大重试次数（避免重复调用 _get_retry_config）
            intervals: 缓存的重试间隔列表

        Returns:
            "retry"   — 短暂等待后应重试（continue）
            "break"   — 监控已停止（break）
            "give_up" — 超过最大重试次数，应等待正常检测间隔（fall through）
        """
        if max_retries is None or intervals is None:
            max_retries, intervals = self._get_retry_config()
        idx = self.login_attempt_count - 1
        if idx < len(intervals):
            wait = intervals[idx]
            self.status_detail = f"网络异常：等待重试（{wait}秒后）"
            self.log_message(f"{wait} 秒后重试登录...", "INFO")
            if not self._wait_interruptible(wait, step=5):
                return RecoveryResult.BREAK
            return "retry"
        # 超过最大重试次数，放弃本次网络检测周期
        self.log_message(
            f"连续登录失败 {self.login_attempt_count} 次，等待下次检测周期",
            "WARNING",
        )
        self.login_attempt_count = 0
        return RecoveryResult.GIVE_UP

    def _login_recovery_loop(self) -> str:
        """登录恢复内层循环。

        在外层检测到网络异常后调用，执行登录前置检查 + 登录重试。
        不做网络状态检测（TCP/HTTP/Portal），确保 retry 间隔准确。

        Returns:
            "login_ok"         — 登录成功，外层应重置计数器
            "give_up"          — 超过最大重试次数，外层应等待正常检测间隔
            "break"            — 监控已停止
            "net_disconnect"   — 物理网络断开，外层应等待正常检测间隔
        """
        self._login_recovery_in_progress.set()
        try:
            return self._login_recovery_inner()
        finally:
            self._login_recovery_in_progress.clear()

    def _login_recovery_inner(self) -> str:
        """登录恢复实际逻辑（由 _login_recovery_loop 包装，管理标志位）。"""
        # 暂停时段检查：重试期间跨越暂停时段边界时停止
        is_paused, _ = check_pause(self.config)
        if is_paused:
            self.log_message("当前处于暂停时段，停止登录重试", "INFO")
            return RecoveryResult.PAUSED

        while self.monitoring:
            # 缓存本轮迭代的重试配置（避免循环内重复调用 _get_retry_config）
            max_retries, retry_intervals = self._get_retry_config()

            # 1. 登录前置检查（物理网络 + 认证地址）
            prereq_ok, prereq_reason = check_login_prerequisites(self.config)
            if not prereq_ok:
                if prereq_reason == "local_disconnected":
                    self.log_message(
                        "物理网络未连接，停止重试，等待下次检测周期",
                        "WARNING",
                    )
                    self.login_attempt_count = 0
                    self.network_state = NetworkState.DISCONNECTED
                    return RecoveryResult.NET_DISCONNECT
                elif prereq_reason == "auth_url_unreachable":
                    self.log_message(
                        f"认证地址 {self.config.get('auth_url', '?')} 不可达，等待下次检测周期",
                        "WARNING",
                    )
                    self.status_detail = "网络异常：认证地址不可达"
                    return RecoveryResult.GIVE_UP

            # 2. 检查配置方案是否切换（内部有 60s 冷却）
            self._check_profile_switch()

            # 2.6 检查是否还有重试机会（登录前检查，避免多执行一次）
            if self.login_attempt_count >= max_retries:
                self.status_detail = f"网络异常：已达到最大重试次数（{max_retries}次）"
                self.log_message(
                    f"已达到最大重试次数 ({max_retries})，等待下次检测周期",
                    "WARNING",
                )
                interval = self._get_monitor_interval()
                next_check = datetime.datetime.now() + datetime.timedelta(
                    seconds=interval
                )
                send_notification(
                    "Campus-Auth 登录失败",
                    f"连续 {self.login_attempt_count} 次登录失败，"
                    f"{interval}秒后重试（{next_check.strftime('%H:%M:%S')}）",
                )
                self.login_attempt_count = 0
                return RecoveryResult.GIVE_UP

            # 3. 执行登录
            self.status_detail = "网络异常：正在登录"
            login_ok, login_msg = self.attempt_login()
            # 等待 2s 后再做重试决策，避免 Portal 尚未完全更新会话状态时立即重试
            self._stop_event.wait(timeout=2)

            if login_ok:
                self.login_attempt_count = 0
                self.network_state = NetworkState.CONNECTED
                self.status_detail = "网络正常"
                return RecoveryResult.LOGIN_OK

            # 4. 登录失败，记录并判断是否重试
            self.login_attempt_count += 1
            self.network_state = NetworkState.DISCONNECTED
            self.log_message(
                f"登录失败 (第{self.login_attempt_count}/{max_retries}次)",
                "ERROR",
            )
            self.status_detail = f"网络异常：登录失败（第{self.login_attempt_count}/{max_retries}次）"

            # 浏览器已由 login.py 在失败时关闭，下次重试 ensure_browser 自动重建

            if self.login_attempt_count == 2:
                send_notification(
                    "Campus-Auth 登录失败",
                    f"自动登录已失败 {self.login_attempt_count} 次，正在重试...",
                )

            failed_count = self.login_attempt_count
            action = self._login_retry_or_break(max_retries, retry_intervals)
            if action == RecoveryResult.BREAK:
                return RecoveryResult.BREAK
            if action == RecoveryResult.GIVE_UP:
                interval = self._get_monitor_interval()
                next_check = datetime.datetime.now() + datetime.timedelta(
                    seconds=interval
                )
                send_notification(
                    "Campus-Auth 登录失败",
                    f"连续 {failed_count} 次登录失败，"
                    f"{interval}秒后重试（{next_check.strftime('%H:%M:%S')}）",
                )
                return RecoveryResult.GIVE_UP
            # action == "retry" → 继续内层循环，不做网络检测

        return RecoveryResult.BREAK

    def monitor_network(self) -> None:
        while self.monitoring:
            # 每次循环重新读取 interval 和 test_sites，支持运行时方案切换
            interval = self._get_monitor_interval()
            # 重新读取测试站点（方案切换后可能已更新）
            test_sites = self._get_test_sites()

            self.network_check_count += 1
            self.last_check_time = datetime.datetime.now()
            # 首次检测显示"正在检测网络"，后续检测根据上次结果显示
            if self.network_state == NetworkState.UNKNOWN:
                self.status_detail = "正在检测网络"
            targets_str = ", ".join(f"{h}:{p}" for h, p in test_sites)
            self.log_message(f"[#{self.network_check_count}] 网络检测 -> {targets_str}")

            # 1. 暂停时段检查
            is_paused, _ = check_pause(self.config)
            if is_paused:
                pause_config = self.config.get("pause_login", {})
                start_hour = pause_config.get("start_hour", 0)
                end_hour = pause_config.get("end_hour", 6)
                self.status_detail = f"网络异常：暂停时段（{start_hour}:00-{end_hour}:00）"
                self.log_message(
                    f"暂停时段 ({start_hour}:00-{end_hour}:00)，跳过检测",
                    "INFO",
                )
                if not self._wait_interruptible(
                    self.PAUSE_CHECK_INTERVAL_SECONDS,
                    step=self.PAUSE_CHECK_STEP_SECONDS,
                ):
                    break
                continue

            # 2. 网络状态检测 (TCP/HTTP/Portal)
            net_ok, net_reason = check_network_status(self.config)
            if net_ok:
                self.login_attempt_count = 0
                self.network_state = NetworkState.CONNECTED
                self.status_detail = "网络正常"
                self.log_message(
                    f"[#{self.network_check_count}] 网络正常，无需登录", "INFO"
                )
            elif net_reason == "all_disabled":
                self.log_message("所有网络检测均未启用，跳过", "WARNING")
            else:
                # 3. 网络异常，进入登录恢复
                self.status_detail = "网络异常：正在登录"
                recovery_result = self._login_recovery_loop()
                if recovery_result == RecoveryResult.LOGIN_OK:
                    self.login_attempt_count = 0
                    self.network_state = NetworkState.CONNECTED
                    self.status_detail = "网络正常"
                    self.log_message(
                        f"[#{self.network_check_count}] 登录成功，网络已恢复"
                    )
                elif recovery_result == RecoveryResult.BREAK:
                    break
                elif recovery_result == RecoveryResult.NET_DISCONNECT:
                    self.status_detail = "网络异常：物理网络断开"
                    self.network_state = NetworkState.DISCONNECTED
                elif recovery_result == RecoveryResult.GIVE_UP:
                    self.status_detail = "网络异常：登录失败，等待下次检测"
                    self.network_state = NetworkState.DISCONNECTED
                # RecoveryResult.GIVE_UP → 跳出，进入正常检测间隔等待

            next_check = datetime.datetime.now() + datetime.timedelta(seconds=interval)
            # 根据网络状态设置等待文案
            if self.network_state == NetworkState.CONNECTED:
                self.status_detail = f"网络正常：等待下次检测（{next_check.strftime('%H:%M:%S')}）"
                self.log_message(
                    f"等待 {interval} 秒至下次检测周期（{next_check.strftime('%H:%M:%S')}）",
                    "DEBUG",
                )
            else:
                self.status_detail = f"网络异常：等待下次检测（{next_check.strftime('%H:%M:%S')}）"
                self.log_message(
                    f"等待 {interval} 秒至下次检测周期（{next_check.strftime('%H:%M:%S')}）",
                    "INFO",
                )
            wait_step = min(
                self.MAX_WAIT_STEP_SECONDS,
                max(self.MIN_WAIT_STEP_SECONDS, interval // 10),
            )
            if not self._wait_interruptible(interval, step=wait_step):
                break

    def _get_test_sites(self) -> list[tuple[str, int]]:
        """获取测试站点列表（带缓存，返回副本避免调用方污染缓存）"""
        if self._test_sites_cache is not None:
            return list(self._test_sites_cache)
        self._test_sites_cache = self._build_test_sites()
        return list(self._test_sites_cache)

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

        try:
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
                old_profile = data.profiles.get(self._last_profile_id)
                old_name = old_profile.name if old_profile else (self._last_profile_id or "无")

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
                elif self._on_profile_switch:
                    self._on_profile_switch(profile_name)
        except Exception as exc:
            self.log_message(f"方案切换检测异常: {exc}", "WARNING")

    def attempt_login(self) -> tuple[bool, str]:
        active_task = self.config.get("active_task", "") or "default"
        auth_url = self.config.get("auth_url", "?")
        username = self.config.get("username", "?")
        isp = self.config.get("isp", "无") or "无"
        self.log_message(
            f"开始登录认证 -> URL={auth_url} "
            f"用户={username} "
            f"运营商={isp} "
            f"任务={active_task}"
        )

        if self._stop_event.is_set():
            self.log_message("监控已停止，跳过登录", "WARNING")
            return False, "监控已停止"

        from app.utils.crypto import has_decryption_error
        if has_decryption_error():
            self.log_message("密码解密失败，跳过登录（请在设置页面重新输入密码）", "ERROR")
            return False, "密码解密失败，请在设置页面重新输入密码"

        try:
            # ── 通过 PlaywrightWorker 派发登录 ──
            from app.workers.playwright_worker import get_worker, CMD_LOGIN

            login_timeout = self.config.get("browser_settings", {}).get("timeout", 120)
            data = {
                "config": self.config,
                "cancel_event": self._cancel_login,
                "skip_pause_check": True,
                "close_on_failure": False,  # 自动监控重试时复用浏览器
            }
            start_time = time.perf_counter()
            result = get_worker().submit(CMD_LOGIN, data=data, timeout=login_timeout)
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            success = result.success
            message = result.data if result.success else result.error
            # 检查是否在登录过程中被取消
            if self._cancel_login.is_set():
                self.log_message("登录已被取消", "WARNING")
                return False, "登录已被取消"
            if success:
                self.log_message(f"登录成功 {message}")
            else:
                self.log_message(f"登录失败 {message}", "ERROR")
            # 记录登录历史
            self._record_login_history(success, duration_ms, str(message) if not success else "")
            return success, message
        except ConnectionError as exc:
            self.log_message(f"登录连接错误: {exc}", "WARNING")
            self._record_login_history(False, 0, f"连接错误: {exc}")
            return False, f"连接错误: {exc}"
        except RuntimeError as exc:
            self.log_message(f"登录运行时错误: {exc}", "ERROR", exc_info=True)
            self._record_login_history(False, 0, f"运行时错误: {exc}")
            return False, f"运行时错误: {exc}"
        except Exception as exc:
            self.log_message(f"登录执行异常: {exc}", "ERROR", exc_info=True)
            self._record_login_history(False, 0, str(exc))
            return False, str(exc)

    def _record_login_history(
        self, success: bool, duration_ms: int, error: str = ""
    ) -> None:
        """记录登录历史（如果 login_history 服务可用）。"""
        if self._login_history is None:
            return
        try:
            self._login_history.add(
                success=success,
                duration_ms=duration_ms,
                profile_name=self.config.get("profile_name", ""),
                task_name=self.config.get("active_task", ""),
                error=error,
            )
        except Exception:
            self.log_message("记录登录历史失败", "WARNING", exc_info=True)
