"""核心网络监控服务，供 CLI 与 API 复用。"""

from __future__ import annotations

import asyncio
import datetime
import time
from typing import Any, Callable, Dict, Optional

from .network_test import is_network_available
from .utils import ConfigLoader, LoginAttemptHandler, LoggerSetup, TimeUtils, get_runtime_stats


class NetworkMonitorCore:
    """校园网监控核心逻辑。"""

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        log_callback: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.config = config or ConfigLoader.load_config_from_env()
        self.log_callback = log_callback

        self.monitoring = False
        self.network_check_count = 0
        self.login_attempt_count = 0
        self.start_time: Optional[float] = None
        self.last_check_time: Optional[datetime.datetime] = None

        self._stop_requested = False
        self.logger = LoggerSetup.setup_logger(
            f"{__name__}_core", self.config.get("logging", {})
        )

    def _now(self) -> str:
        return datetime.datetime.now().strftime("%H:%M:%S")

    def log_message(self, message: str) -> None:
        self.logger.info("[%s] %s", self._now(), message)
        if self.log_callback:
            self.log_callback(message)

    def snapshot(self) -> Dict[str, Any]:
        return {
            "monitoring": self.monitoring,
            "network_check_count": self.network_check_count,
            "login_attempt_count": self.login_attempt_count,
            "last_check_time": self.last_check_time.isoformat() if self.last_check_time else None,
            "start_time": self.start_time,
        }

    def start_monitoring(self) -> None:
        if self.monitoring:
            self.log_message("监控已在运行中")
            return

        self.monitoring = True
        self._stop_requested = False
        self.start_time = time.time()
        self.network_check_count = 0
        self.login_attempt_count = 0

        self.log_message("开始网络监控")
        try:
            self.monitor_network()
        except KeyboardInterrupt:
            self.log_message("收到中断信号，停止监控")
        except Exception as exc:
            self.log_message(f"监控异常: {exc}")
        finally:
            self.stop_monitoring()

    def stop_monitoring(self) -> None:
        if not self.monitoring and self._stop_requested:
            return

        self._stop_requested = True
        was_monitoring = self.monitoring
        self.monitoring = False

        if was_monitoring and self.start_time:
            runtime, stats = get_runtime_stats(self.start_time, self.network_check_count)
            self.log_message(f"监控已停止，运行时长: {runtime}")
            self.log_message(f"监控统计: {stats}")

    def _wait_interruptible(self, seconds: int, step: int = 5) -> bool:
        """等待期间支持停止信号。返回值表示是否继续监控。"""
        remaining = max(0, seconds)
        while self.monitoring and remaining > 0:
            time.sleep(min(step, remaining))
            remaining -= step
        return self.monitoring

    def monitor_network(self) -> None:
        consecutive_failures = 0
        interval = int(self.config.get("monitor", {}).get("interval", 240))

        while self.monitoring:
            pause_config = self.config.get("pause_login", {})
            if TimeUtils.is_in_pause_period(pause_config):
                now_hour = datetime.datetime.now().hour
                start_hour = pause_config.get("start_hour", 0)
                end_hour = pause_config.get("end_hour", 6)
                self.log_message(
                    f"当前 {now_hour}:xx 在暂停时段({start_hour}-{end_hour})，跳过登录检测"
                )
                if not self._wait_interruptible(300, step=15):
                    break
                continue

            self.network_check_count += 1
            self.last_check_time = datetime.datetime.now()
            self.log_message(f"执行第 {self.network_check_count} 次网络检测")

            try:
                network_ok = is_network_available(timeout=2, verbose=False, require_both=False)
            except Exception as exc:
                self.log_message(f"网络检测失败: {exc}")
                network_ok = False

            if network_ok:
                consecutive_failures = 0
                self.login_attempt_count = 0
                self.log_message("网络连接正常")
            else:
                consecutive_failures += 1
                self.log_message(f"网络异常，连续失败 {consecutive_failures} 次")

                login_ok = self.attempt_login()
                if login_ok:
                    consecutive_failures = 0
                    self.login_attempt_count = 0
                    self.log_message("自动登录成功")
                else:
                    self.login_attempt_count += 1
                    self.log_message(f"自动登录失败，第 {self.login_attempt_count} 次")
                    if self.login_attempt_count >= 3:
                        self.log_message("连续登录失败达到 3 次，冷却 120 秒")
                        self.login_attempt_count = 0
                        if not self._wait_interruptible(120, step=10):
                            break
                        continue

            next_check = datetime.datetime.now() + datetime.timedelta(seconds=interval)
            self.log_message(f"下次检测时间: {next_check.strftime('%H:%M:%S')}")
            if not self._wait_interruptible(interval, step=min(20, max(5, interval // 10))):
                break

    def attempt_login(self) -> bool:
        """执行一次登录尝试（手动触发和自动触发共用）。"""
        try:
            handler = LoginAttemptHandler(self.config)
            return asyncio.run(handler.attempt_login(skip_pause_check=True))
        except Exception as exc:
            self.log_message(f"登录执行失败: {exc}")
            return False
