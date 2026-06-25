# app/services/engine_status.py
"""StatusManager — 状态快照管理，从 ScheduleEngine 提取。"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from app.schemas import MonitorStatusResponse
from app.utils.logging import get_logger

if TYPE_CHECKING:
    from app.services.monitor_service import NetworkMonitorCore
    from app.services.ws_broadcaster import WsBroadcaster
    from app.utils.logging import DashboardSink

logger = get_logger("engine_status", source="backend")


@dataclass
class StatusSnapshot:
    """基于引用替换的监控状态快照，由 API 处理器直接读取。"""

    monitoring: bool = False
    last_network_ok: bool = False
    start_time: float | None = None
    network_check_count: int = 0
    login_attempt_count: int = 0
    last_check_time: str | None = None
    snapshot_time: float = 0.0
    status_detail: str = "正常"
    network_state: str = "unknown"


class StatusManager:
    """状态快照管理与 WS 广播桥接。"""

    def __init__(
        self,
        get_monitor_core: Callable[[], NetworkMonitorCore | None],
        ws_broadcaster: WsBroadcaster | None = None,
    ) -> None:
        self._get_monitor_core = get_monitor_core
        self._ws_broadcaster = ws_broadcaster
        self._status_snapshot = StatusSnapshot()
        self._last_snapshot_time: float = 0
        self._snapshot_min_interval: float = 1.0
        self._dashboard_sink: DashboardSink | None = None

    def set_ws_broadcaster(self, ws_broadcaster: WsBroadcaster) -> None:
        self._ws_broadcaster = ws_broadcaster

    def set_dashboard_sink(self, sink: DashboardSink) -> None:
        self._dashboard_sink = sink

    def update_snapshot(self, force: bool = False) -> None:
        """Read monitor_core state into lock-free StatusSnapshot."""
        now = time.time()
        if not force and now - self._last_snapshot_time < self._snapshot_min_interval:
            return
        self._last_snapshot_time = now

        core = self._get_monitor_core()
        if core is not None:
            try:
                snap = core.snapshot()
                network_state = snap.get("network_state", "unknown")
                network_connected = network_state == "connected"
                self._status_snapshot = StatusSnapshot(
                    monitoring=core.monitoring,
                    last_network_ok=network_connected,
                    start_time=snap.get("start_time"),
                    network_check_count=int(snap.get("network_check_count", 0)),
                    login_attempt_count=int(snap.get("login_attempt_count", 0)),
                    last_check_time=snap.get("last_check_time"),
                    snapshot_time=time.time(),
                    status_detail=snap.get("status_detail", "正常"),
                    network_state=network_state,
                )
            except Exception:
                logger.exception("状态快照更新失败")
        else:
            self._status_snapshot = StatusSnapshot(
                snapshot_time=time.time(), status_detail="已停止"
            )

        self._queue_status_broadcast()

    def _queue_status_broadcast(self) -> None:
        if self._ws_broadcaster is None:
            return
        try:
            status = self.get_status()
            self._ws_broadcaster.enqueue_status(status.model_dump())
        except Exception:
            logger.exception("状态广播队列失败")

    def get_status(self) -> MonitorStatusResponse:
        snap = self._status_snapshot
        runtime_seconds = (
            int(time.time() - snap.start_time)
            if snap.monitoring and snap.start_time
            else 0
        )
        return MonitorStatusResponse(
            monitoring=snap.monitoring,
            network_check_count=snap.network_check_count,
            login_attempt_count=snap.login_attempt_count,
            last_check_time=snap.last_check_time,
            runtime_seconds=runtime_seconds,
            network_connected=snap.monitoring and snap.last_network_ok,
            status_detail=snap.status_detail,
            network_state=snap.network_state,
        )

    def list_logs(self, limit: int = 200) -> list:
        if limit <= 0 or self._dashboard_sink is None:
            return []
        return self._dashboard_sink.list_logs(limit=limit)
