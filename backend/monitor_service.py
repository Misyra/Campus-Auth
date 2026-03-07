from __future__ import annotations

import datetime
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

from src.monitor_core import NetworkMonitorCore
from src.network_test import is_network_available
from src.utils import ConfigValidator

from .config_service import build_runtime_config, load_ui_config, write_env_file
from .schemas import LogEntry, MonitorConfigPayload, MonitorStatusResponse


class MonitorService:
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.env_file = project_root / ".env"

        self._lock = threading.Lock()
        self._logs: deque[LogEntry] = deque(maxlen=1200)

        self._ui_config = load_ui_config()
        self._runtime_config = build_runtime_config(self._ui_config)

        self._monitor_core: NetworkMonitorCore | None = None
        self._monitor_thread: threading.Thread | None = None

    def _push_log(self, message: str) -> None:
        stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._logs.append(LogEntry(timestamp=stamp, message=message))

    def boot(self) -> None:
        if self._ui_config.auto_start:
            self.start_monitoring()

    def get_config(self) -> MonitorConfigPayload:
        with self._lock:
            return self._ui_config.model_copy(deep=True)

    def save_config(self, payload: MonitorConfigPayload) -> None:
        ok, error = ConfigValidator.validate_gui_config(
            payload.username,
            payload.password,
            str(payload.check_interval_minutes),
        )
        if not ok:
            raise ValueError(error)

        write_env_file(payload, self.env_file)

        with self._lock:
            self._ui_config = payload
            self._runtime_config = build_runtime_config(payload)
            running = self._is_monitoring_unsafe()

        self._push_log("配置已保存")

        if running:
            self.stop_monitoring()
            self.start_monitoring()
            self._push_log("监控已按新配置重启")

    def _is_monitoring_unsafe(self) -> bool:
        return bool(
            self._monitor_core
            and self._monitor_core.monitoring
            and self._monitor_thread
            and self._monitor_thread.is_alive()
        )

    def start_monitoring(self) -> tuple[bool, str]:
        with self._lock:
            if self._is_monitoring_unsafe():
                return False, "监控已在运行中"

            valid, error = ConfigValidator.validate_env_config(self._runtime_config)
            if not valid:
                return False, f"配置无效: {error}"

            core = NetworkMonitorCore(
                config=self._runtime_config.copy(),
                log_callback=self._push_log,
            )
            thread = threading.Thread(target=core.start_monitoring, daemon=True)

            self._monitor_core = core
            self._monitor_thread = thread
            thread.start()

        self._push_log("监控线程已启动")
        return True, "监控已启动"

    def stop_monitoring(self) -> tuple[bool, str]:
        with self._lock:
            if not self._is_monitoring_unsafe():
                return False, "监控未运行"
            core = self._monitor_core
            thread = self._monitor_thread

        if core:
            core.stop_monitoring()

        if thread:
            thread.join(timeout=3)

        self._push_log("监控已停止")
        return True, "监控已停止"

    def get_status(self) -> MonitorStatusResponse:
        with self._lock:
            running = self._is_monitoring_unsafe()
            snapshot: dict[str, Any] = (
                self._monitor_core.snapshot() if self._monitor_core else {}
            )

        start_time = snapshot.get("start_time")
        runtime_seconds = int(time.time() - start_time) if running and start_time else 0

        return MonitorStatusResponse(
            monitoring=running,
            network_check_count=int(snapshot.get("network_check_count", 0)),
            login_attempt_count=int(snapshot.get("login_attempt_count", 0)),
            last_check_time=snapshot.get("last_check_time"),
            runtime_seconds=runtime_seconds,
        )

    def run_manual_login(self) -> tuple[bool, str]:
        with self._lock:
            runtime_config = self._runtime_config.copy()

        core = NetworkMonitorCore(config=runtime_config, log_callback=self._push_log)
        success = core.attempt_login()
        return (True, "手动登录成功") if success else (False, "手动登录失败")

    def test_network(self) -> tuple[bool, str]:
        try:
            ok = is_network_available(timeout=2, verbose=False, require_both=False)
            return (True, "网络连接正常") if ok else (False, "网络连接异常")
        except Exception as exc:
            return False, f"网络测试失败: {exc}"

    def list_logs(self, limit: int = 200) -> list[LogEntry]:
        if limit <= 0:
            return []
        return list(self._logs)[-limit:]
