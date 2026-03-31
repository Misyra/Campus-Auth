from __future__ import annotations

import asyncio
import datetime
import json
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

from fastapi import WebSocket

from src.monitor_core import NetworkMonitorCore
from src.network_test import is_network_available
from src.utils import ConfigValidator
from src.utils.logging import get_logger

from .config_service import build_runtime_config, load_ui_config, write_env_file
from .schemas import LogEntry, MonitorConfigPayload, MonitorStatusResponse


class WebSocketManager:
    def __init__(self):
        self._connections: list[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        async with self._lock:
            self._connections.append(websocket)

    async def disconnect(self, websocket: WebSocket):
        async with self._lock:
            if websocket in self._connections:
                self._connections.remove(websocket)

    async def broadcast(self, message: str):
        async with self._lock:
            connections = self._connections.copy()

        tasks = []
        for ws in connections:
            tasks.append(self._send_safe(ws, message))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        async with self._lock:
            for ws, result in zip(connections, results):
                if isinstance(result, Exception) and ws in self._connections:
                    self._connections.remove(ws)

    async def _send_safe(self, ws: WebSocket, message: str):
        try:
            await ws.send_text(message)
        except Exception:
            raise


ws_manager = WebSocketManager()
service_logger = get_logger("backend.monitor_service", side="BACKEND")


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
        self._loop: asyncio.AbstractEventLoop | None = None

    def set_event_loop(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop

    def _push_log(
        self, message: str, level: str = "INFO", source: str = "monitor"
    ) -> None:
        stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        level_name = str(level or "INFO").upper()
        source_name = str(source or "monitor")
        entry = LogEntry(
            timestamp=stamp,
            level=level_name,
            source=source_name,
            message=message,
        )
        self._logs.append(entry)

        if self._loop and self._loop.is_running():
            data = json.dumps(
                {
                    "type": "log",
                    "data": {
                        "timestamp": stamp,
                        "level": level_name,
                        "source": source_name,
                        "message": message,
                    },
                }
            )
            asyncio.run_coroutine_threadsafe(ws_manager.broadcast(data), self._loop)

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

        service_logger.info("Saving monitor config")

        write_env_file(payload, self.env_file)

        with self._lock:
            self._ui_config = payload
            self._runtime_config = build_runtime_config(payload)
            running = self._is_monitoring_unsafe()

        self._push_log("配置已保存", level="INFO", source="backend.monitor_service")
        service_logger.info("Monitor config saved")

        if running:
            self.stop_monitoring()
            self.start_monitoring()
            self._push_log(
                "监控已按新配置重启", level="INFO", source="backend.monitor_service"
            )

    def _is_monitoring_unsafe(self) -> bool:
        return bool(
            self._monitor_core
            and self._monitor_core.monitoring
            and self._monitor_thread
            and self._monitor_thread.is_alive()
        )

    def start_monitoring(self) -> tuple[bool, str]:
        service_logger.info("Start monitoring requested")
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

        self._push_log("监控线程已启动", level="INFO", source="backend.monitor_service")
        service_logger.info("Monitoring thread started")
        return True, "监控已启动"

    def stop_monitoring(self) -> tuple[bool, str]:
        service_logger.info("Stop monitoring requested")
        with self._lock:
            if not self._is_monitoring_unsafe():
                return False, "监控未运行"
            core = self._monitor_core
            thread = self._monitor_thread

        if core:
            core.stop_monitoring()

        if thread:
            thread.join(timeout=3)

        self._push_log("监控已停止", level="INFO", source="backend.monitor_service")
        service_logger.info("Monitoring stopped")
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
        service_logger.info("Manual login requested")
        with self._lock:
            runtime_config = self._runtime_config.copy()

        core = NetworkMonitorCore(config=runtime_config, log_callback=self._push_log)
        success, message = core.attempt_login()
        if success:
            service_logger.info("Manual login succeeded")
            return True, f"手动登录成功：{message}"
        service_logger.warning("Manual login failed: %s", message)
        return False, f"手动登录失败：{message}"

    def test_network(self) -> tuple[bool, str]:
        service_logger.debug("Network test requested")
        try:
            ok = is_network_available(timeout=2, require_both=False)
            return (True, "网络连接正常") if ok else (False, "网络连接异常")
        except Exception as exc:
            service_logger.exception("Network test failed")
            return False, f"网络测试失败: {exc}"

    def list_logs(self, limit: int = 200) -> list[LogEntry]:
        if limit <= 0:
            return []
        return list(self._logs)[-limit:]
