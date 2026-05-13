from __future__ import annotations

import asyncio
import datetime
import json
import logging
import re
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

from .config_service import build_runtime_config, load_runtime_config, load_ui_config
from .profile_service import ProfileService
from .schemas import LogEntry, MonitorConfigPayload, MonitorStatusResponse


class WebSocketManager:
    """WebSocket 管理器 - 实时日志推送"""

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
        """广播消息（直接发送，保证实时性）"""
        async with self._lock:
            connections = self._connections.copy()

        if not connections:
            return

        # 并发发送给所有连接
        tasks = [self._send_safe(ws, message) for ws in connections]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 清理断开连接
        async with self._lock:
            for ws, result in zip(connections, results):
                if isinstance(result, Exception) and ws in self._connections:
                    self._connections.remove(ws)

    async def _send_safe(self, ws: WebSocket, message: str):
        await ws.send_text(message)


ws_manager = WebSocketManager()
service_logger = get_logger("backend.monitor_service", side="BACKEND")


class MonitorService:
    def __init__(
        self, project_root: Path, profile_service: ProfileService | None = None
    ):
        self.project_root = project_root
        self._profile_service = profile_service or ProfileService(project_root)

        self._lock = threading.RLock()  # 可重入锁，避免同一线程内 update_config → _push_log → _push_status 链式获取死锁
        self._logs: deque[LogEntry] = deque(maxlen=1200)

        self._ui_config = load_ui_config(self._profile_service)
        self._runtime_config = build_runtime_config(
            load_runtime_config(self._profile_service),
            self._profile_service.load().system,
        )

        self._monitor_core: NetworkMonitorCore | None = None
        self._monitor_thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self.safe_mode: bool = self._profile_service.load().system.safe_mode

    def set_event_loop(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop

    def _push_status(self) -> None:
        """推送当前监控状态到 WebSocket"""
        if not self._loop or not self._loop.is_running():
            return
        status = self.get_status()
        data = json.dumps(
            {
                "type": "status",
                "data": status.model_dump(),
            }
        )
        asyncio.run_coroutine_threadsafe(ws_manager.broadcast(data), self._loop)

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
        with self._lock:
            self._logs.append(entry)

        # 同步写入 Python 日志系统 → 自动持久化到文件
        log_level = (
            getattr(logging, level_name, logging.INFO)
            if hasattr(logging, level_name)
            else logging.INFO
        )
        record = service_logger.makeRecord(
            service_logger.name,
            log_level,
            "(monitor_service)",
            0,
            "[%s] %s",
            (source_name, message),
            None,
        )
        record.side = "FRONTEND" if source_name == "frontend" else "BACKEND"
        service_logger.handle(record)

        # 监控相关日志触发的状态推送（网络检测、登录尝试等）
        if source_name in ("monitor.core", "monitor", "network"):
            self._push_status()

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

    def reload_config(self) -> None:
        """重新加载配置（从 settings.json），并推送到运行中的监控"""
        with self._lock:
            self._ui_config = load_ui_config(self._profile_service)
            self._runtime_config = build_runtime_config(
                load_runtime_config(self._profile_service),
                self._profile_service.load().system,
            )
            need_update = bool(self._monitor_core and self._monitor_core.monitoring)
            new_config = self._runtime_config.copy() if need_update else None

        # 在锁外执行热更新，避免 update_config → _push_log → 再次获取锁的死锁
        if need_update and new_config is not None:
            self._monitor_core.update_config(new_config)

        service_logger.info("Config reloaded from settings.json")

    def apply_profile(self, profile_name: str) -> None:
        """切换到新方案并重启监控"""
        with self._lock:
            running = self._is_monitoring_unsafe()

        self.reload_config()
        new_url = self._runtime_config.get("auth_url", "")
        new_user = self._runtime_config.get("username", "")
        self._push_log(
            f"切换方案 → {profile_name} (认证={new_url}, 用户={new_user})",
            level="INFO",
            source="backend.monitor_service",
        )

        if running:
            self.stop_monitoring()
            self.start_monitoring()
            self._push_log(
                "监控已按新方案重启", level="INFO", source="backend.monitor_service"
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

            config = self._runtime_config.copy()
            if self.safe_mode:
                config.setdefault("browser_settings", {})["safe_mode"] = True
            core = NetworkMonitorCore(
                config=config,
                log_callback=self._push_log,
            )
            core.set_profile_service(
                self._profile_service, on_switch=self._on_profile_switch
            )
            thread = threading.Thread(target=core.start_monitoring, daemon=True)

            self._monitor_core = core
            self._monitor_thread = thread
            thread.start()

        self._push_log("监控线程已启动", level="INFO", source="backend.monitor_service")
        self._push_status()
        service_logger.info("Monitoring thread started")
        return True, "监控已启动"

    def _on_profile_switch(self, profile_name: str) -> None:
        """自动切换方案时的回调"""
        self.reload_config()
        new_url = self._runtime_config.get("auth_url", "")
        new_user = self._runtime_config.get("username", "")
        self._push_log(
            f"自动切换方案 → {profile_name} (认证={new_url}, 用户={new_user})",
            level="INFO",
            source="backend.monitor_service",
        )
        # 在锁外执行热更新，避免 update_config → _push_log → 再次获取锁的死锁
        new_config = None
        with self._lock:
            if self._monitor_core:
                new_config = self._runtime_config.copy()
        if new_config is not None:
            self._monitor_core.update_config(new_config)

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

        with self._lock:
            self._monitor_core = None
            self._monitor_thread = None

        self._push_log("监控已停止", level="INFO", source="backend.monitor_service")
        self._push_status()
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
        login_attempts = int(snapshot.get("login_attempt_count", 0))
        # network_connected reflects the last verified network check result.
        last_network_ok = bool(snapshot.get("last_network_ok"))

        return MonitorStatusResponse(
            monitoring=running,
            network_check_count=int(snapshot.get("network_check_count", 0)),
            login_attempt_count=login_attempts,
            last_check_time=snapshot.get("last_check_time"),
            runtime_seconds=runtime_seconds,
            network_connected=running and last_network_ok,
        )

    def run_manual_login(self) -> tuple[bool, str]:
        service_logger.info("Manual login requested")
        with self._lock:
            runtime_config = self._runtime_config.copy()
        if self.safe_mode:
            runtime_config.setdefault("browser_settings", {})["safe_mode"] = True

        core = NetworkMonitorCore(config=runtime_config, log_callback=self._push_log)
        success, message = core.attempt_login()
        if success:
            service_logger.info("Manual login succeeded")
            return True, f"手动登录成功：{message}"
        log_msg = re.sub(r"\s*截图[:：]\s*/\S+\.(?:png|jpg|jpeg|webp|gif)", "", message)
        service_logger.warning("Manual login failed: %s", log_msg)
        return False, f"手动登录失败：{message}"

    def test_network(self) -> tuple[bool, str]:
        service_logger.info("手动网络测试")
        with self._lock:
            config = self._runtime_config.copy()
        monitor_cfg = config.get("monitor", {})
        targets = monitor_cfg.get("ping_targets", [])
        strict_mode = monitor_cfg.get("strict_mode", True)
        # 解析 host:port 为 (host, port) 元组列表
        test_sites: list[tuple[str, int]] = []
        for item in targets:
            host = item
            port = 0
            if ":" in str(item):
                host_part, port_part = str(item).rsplit(":", 1)
                if host_part.strip() and port_part.strip().isdigit():
                    host = host_part.strip()
                    port = int(port_part.strip())
            if port <= 0:
                import re
                port = 53 if re.fullmatch(r"\d+\.\d+\.\d+\.\d+", host) else 443
            test_sites.append((host, port))
        self._push_log(
            f"手动网络测试 → 目标={len(test_sites)} 严格模式={'开' if strict_mode else '关'}",
            "INFO", "network",
        )
        try:
            ok = is_network_available(
                test_sites=test_sites if test_sites else None,
                timeout=2,
                require_both=strict_mode,
            )
            if ok:
                self._push_log("手动测试结果: 网络正常", "INFO", "network")
                return True, "网络连接正常"
            else:
                self._push_log("手动测试结果: 网络异常", "WARNING", "network")
                return False, "网络连接异常"
        except Exception as exc:
            service_logger.exception("Network test failed")
            self._push_log(f"手动测试异常: {exc}", "ERROR", "network")
            return False, f"网络测试失败: {exc}"

    def list_logs(self, limit: int = 200) -> list[LogEntry]:
        if limit <= 0:
            return []
        with self._lock:
            snapshot = list(self._logs)
        if len(snapshot) <= limit:
            return snapshot
        return snapshot[-limit:]

    def toggle_safe_mode(self) -> bool:
        """切换安全模式，返回新值"""
        with self._lock:
            new_value = not self.safe_mode
            data = self._profile_service.load()
            data.system.safe_mode = new_value
            self._profile_service.save(data)
            self.safe_mode = new_value
        return new_value
