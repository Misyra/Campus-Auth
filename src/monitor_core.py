from __future__ import annotations

import asyncio
import datetime
import logging
import re
import threading
import time
from typing import TYPE_CHECKING, Any, Callable, Dict, Optional

from .network_test import is_local_network_connected, is_network_available
from .utils import (
    ConfigLoader,
    LoginAttemptHandler,
    TimeUtils,
    get_runtime_stats,
    setup_logger,
)
from .utils.notify import send_notification

if TYPE_CHECKING:
    from backend.profile_service import ProfileService


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
    ) -> None:
        self.config = config or ConfigLoader.load_config_from_env()
        self.log_callback = log_callback

        self.monitoring = False
        self.network_check_count = 0
        self.login_attempt_count = 0
        self.start_time: Optional[float] = None
        self.last_check_time: Optional[datetime.datetime] = None
        # Last known connectivity result for UI status.
        self.last_network_ok: Optional[bool] = None

        self._stop_requested = False
        self._cancel_login = threading.Event()
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

    def start_monitoring(self) -> None:
        if self.monitoring:
            self.log_message("监控已在运行中", logging.WARNING)
            return

        self.monitoring = True
        self._stop_requested = False
        self._cancel_login.clear()
        self._reuse_browser = True
        self.start_time = time.time()
        self.network_check_count = 0
        self.login_attempt_count = 0
        self.last_network_ok = None
        self._test_sites_cache = None  # 重置缓存

        interval = self.config.get("monitor", {}).get(
            "interval", self.DEFAULT_INTERVAL_SECONDS
        )
        test_sites_info = self._get_test_sites()
        targets_str = ", ".join(f"{h}:{p}" for h, p in test_sites_info)

        self.log_message("=" * self.LOG_DIVIDER_LENGTH)
        self.log_message("网络监控已启动")
        self.log_message(f"检测间隔: {interval}s | 检测目标: {targets_str}")
        self.log_message(f"认证地址: {self.config.get('auth_url', '未设置')}")
        self.log_message(f"账号: {self.config.get('username', '未设置')}")
        self.log_message(f"运营商: {self.config.get('isp', '无') or '无'}")
        self.log_message("=" * self.LOG_DIVIDER_LENGTH)

        try:
            self.monitor_network()
        except KeyboardInterrupt:
            self.log_message("收到中断信号，停止监控", logging.WARNING)
        except Exception as exc:
            self.log_message(f"监控异常: {exc}", logging.ERROR)
        finally:
            self.stop_monitoring()

    def stop_monitoring(self) -> None:
        if not self.monitoring and self._stop_requested:
            return

        self._stop_requested = True
        self._cancel_login.set()
        was_monitoring = self.monitoring
        self.monitoring = False

        # 关闭登录浏览器
        if self._login_handler:
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(self._login_handler.close_browser())
            finally:
                loop.close()
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
            time.sleep(min(step, remaining))
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
                return "break"
            return "retry"
        # 超过最大重试次数，放弃本次网络检测周期
        self.log_message(
            f"连续登录失败 {self.login_attempt_count} 次，等待下次检测周期",
            logging.WARNING,
        )
        self.login_attempt_count = 0
        return "give_up"

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

            # 自动切换方案检测
            self._check_profile_switch()

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

                # 检查物理网络是否连接，未连接则跳过登录
                if not is_local_network_connected():
                    self.log_message(
                        f"[#{self.network_check_count}] 物理网络未连接（WiFi/网线断开），跳过登录，等待下次检测",
                        logging.WARNING,
                    )
                    consecutive_failures = 0
                    self.login_attempt_count = 0
                    self.last_network_ok = False
                    next_check = datetime.datetime.now() + datetime.timedelta(
                        seconds=interval
                    )
                    self.log_message(
                        f"下次检测: {next_check.strftime('%H:%M:%S')}", logging.DEBUG
                    )
                    wait_step = min(
                        self.MAX_WAIT_STEP_SECONDS,
                        max(self.MIN_WAIT_STEP_SECONDS, interval // 10),
                    )
                    if not self._wait_interruptible(interval, step=wait_step):
                        break
                    continue

                login_ok, login_msg = self.attempt_login()
                if login_ok:
                    # 网络检测已移至 task_executor 内部，登录成功即表示网络已恢复
                    consecutive_failures = 0
                    self.login_attempt_count = 0
                    self.last_network_ok = True
                    self.log_message(
                        f"[#{self.network_check_count}] 登录成功，网络已恢复"
                    )
                else:
                    self.login_attempt_count += 1
                    self.last_network_ok = False
                    max_retries, _ = self._get_retry_config()
                    self.log_message(
                        f"[#{self.network_check_count}] 登录失败 "
                        f"(第{self.login_attempt_count}/{max_retries}次)",
                        logging.ERROR,
                    )
                    # 第2次失败时发送桌面通知提醒
                    if self.login_attempt_count == 2:
                        send_notification(
                            "Campus-Auth 登录失败",
                            f"自动登录已失败 {self.login_attempt_count} 次，正在重试...",
                        )
                    failed_count = self.login_attempt_count
                    action = self._login_retry_or_break()
                    if action == "break":
                        break
                    if action == "retry":
                        continue
                    # "give_up" → fall through to normal interval wait
                    send_notification(
                        "Campus-Auth 登录失败",
                        f"连续 {failed_count} 次登录失败，等待下次检测周期",
                    )

            next_check = datetime.datetime.now() + datetime.timedelta(seconds=interval)
            self.log_message(
                f"下次检测: {next_check.strftime('%H:%M:%S')}", logging.DEBUG
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

        parsed: list[tuple[str, int]] = []
        for item in raw_targets:
            host = item
            port = 0
            if ":" in item:
                host_part, port_part = item.rsplit(":", 1)
                if host_part.strip() and port_part.strip().isdigit():
                    host = host_part.strip()
                    port = int(port_part.strip())
            if port <= 0:
                is_ipv4 = bool(re.fullmatch(r"\d+\.\d+\.\d+\.\d+", host))
                port = 53 if is_ipv4 else 443
            parsed.append((host, port))
        return parsed

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
        self.log_message(
            f"开始登录认证 → URL={self.config.get('auth_url', '?')} "
            f"用户={self.config.get('username', '?')} "
            f"运营商={self.config.get('isp', '无') or '无'} "
            f"任务={active_task}"
        )
        try:
            # 复用持久化 handler，重试时保留浏览器
            if self._login_handler is None:
                self._login_handler = LoginAttemptHandler(
                    self.config, cancel_event=self._cancel_login
                )
            else:
                self._login_handler.config = self.config

            handler = self._login_handler
            loop = asyncio.new_event_loop()
            try:
                success, message = loop.run_until_complete(
                    handler.attempt_login(
                        skip_pause_check=True, reuse_browser=self._reuse_browser
                    )
                )
            finally:
                pending = asyncio.all_tasks(loop)
                if pending:
                    loop.run_until_complete(asyncio.gather(*pending))
                loop.close()
            # 检查是否在登录过程中被取消
            if self._cancel_login.is_set():
                self.log_message("登录已被取消", logging.WARNING)
                return False, "登录已被取消"
            if success:
                self.log_message(f"登录成功 ✓ {message}")
            else:
                self.log_message(f"登录失败 ✗ {message}", logging.ERROR)
            return success, message
        except asyncio.TimeoutError as exc:
            self.log_message(f"登录超时: {exc}", logging.ERROR)
            return False, f"登录超时: {exc}"
        except ConnectionError as exc:
            self.log_message(f"登录连接错误: {exc}", logging.ERROR)
            return False, f"连接错误: {exc}"
        except RuntimeError as exc:
            self.log_message(f"登录运行时错误: {exc}", logging.ERROR)
            return False, f"运行时错误: {exc}"
        except Exception as exc:
            self.log_message(f"登录执行异常: {exc}", logging.ERROR)
            return False, str(exc)
