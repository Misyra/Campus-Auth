"""登录历史服务 — 记录每次登录尝试的时间、结果、耗时。"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel

from app.utils.file_helpers import atomic_write
from app.utils.logging import get_logger

if TYPE_CHECKING:
    from app.services.profile import ProfileService
    from app.tasks.manager import TaskManager

logger = get_logger("backend.login_history", source="BACKEND")


class LoginHistoryEntry(BaseModel):
    """单条登录历史记录"""

    id: str
    timestamp: str
    success: bool
    duration_ms: int = 0
    profile_name: str = ""
    task_name: str = ""
    error: str = ""


class LoginHistoryService:
    """登录历史存储服务 — JSONL 文件追加写入。"""

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._history_path = data_dir / "login_history.jsonl"
        self._lock = threading.Lock()
        self._cleanup_lock = threading.Lock()
        self._write_count = 0

    def record(
        self,
        success: bool,
        duration_ms: int,
        profile_service: ProfileService | None = None,
        task_manager: TaskManager | None = None,
        error: str = "",
    ) -> None:
        """记录登录历史，自动从服务对象提取 profile/task 名称。"""
        profile_name = ""
        if profile_service is not None:
            try:
                active = profile_service.get_active_profile()
                if active:
                    profile_name = getattr(active, "name", "")
            except Exception:
                logger.debug("获取当前方案名称失败", exc_info=True)

        task_name = ""
        if task_manager is not None:
            try:
                task_id = task_manager.get_active_task()
                task = task_manager.load_task(task_id)
                if task:
                    task_name = getattr(task, "name", task_id)
            except Exception:
                logger.debug("获取当前任务名称失败", exc_info=True)

        self.add(
            success=success,
            duration_ms=duration_ms,
            profile_name=profile_name,
            task_name=task_name,
            error=error,
        )

    def add(
        self,
        success: bool,
        duration_ms: int = 0,
        profile_name: str = "",
        task_name: str = "",
        error: str = "",
    ) -> None:
        """追加一条登录记录。"""
        now = datetime.now()
        entry = LoginHistoryEntry(
            id=f"{now.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}",
            timestamp=now.strftime("%Y-%m-%d %H:%M:%S"),
            success=success,
            duration_ms=duration_ms,
            profile_name=profile_name,
            task_name=task_name,
            error=error[:200] if error else "",
        )
        need_cleanup = False
        with self._lock:
            try:
                with open(self._history_path, "a", encoding="utf-8") as f:
                    f.write(entry.model_dump_json() + "\n")
                    f.flush()
                self._write_count += 1
                # 每 50 次写入概率性清理旧记录
                if self._write_count % 50 == 0:
                    need_cleanup = True
            except Exception:
                logger.warning("写入登录历史失败", exc_info=True)
        # 锁外使用独立锁序列化清理，不阻塞新写入
        if need_cleanup:
            with self._cleanup_lock:
                self._cleanup_old(max_age_days=30)

    def list_recent(self, limit: int = 50) -> list[LoginHistoryEntry]:
        """读取最近 N 条登录记录（从新到旧）。"""
        if not self._history_path.exists():
            return []
        try:
            lines: list[str] = []
            with open(self._history_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        lines.append(line)
            # 取最后 limit 条并反转（最新在前）
            recent = lines[-limit:]
            recent.reverse()
            result: list[LoginHistoryEntry] = []
            for line in recent:
                try:
                    result.append(LoginHistoryEntry.model_validate_json(line))
                except Exception:
                    logger.debug("解析登录历史条目失败，跳过", exc_info=True)
                    continue
            return result
        except Exception:
            logger.warning("读取登录历史失败", exc_info=True)
            return []

    def clear(self) -> int:
        """清空所有登录历史记录，返回删除的记录数。"""
        with self._lock:
            if not self._history_path.exists():
                return 0
            try:
                count = 0
                with open(self._history_path, encoding="utf-8") as f:
                    for line in f:
                        if line.strip():
                            count += 1
                atomic_write(str(self._history_path), "", encoding="utf-8")
                logger.info("登录历史已清空，共删除 {} 条记录", count)
                return count
            except Exception:
                logger.warning("清空登录历史失败", exc_info=True)
                return 0

    def _cleanup_old(self, max_age_days: int = 30) -> None:
        """清理超过 max_age_days 天的旧记录。"""
        if not self._history_path.exists():
            return
        cutoff = datetime.now() - timedelta(days=max_age_days)
        cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M:%S")
        try:
            kept: list[str] = []
            with open(self._history_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        if data.get("timestamp", "") >= cutoff_str:
                            kept.append(line)
                    except Exception:
                        kept.append(line)
            content = "\n".join(kept)
            if kept:
                content += "\n"
            atomic_write(str(self._history_path), content, encoding="utf-8")
            kept_count = len(kept)
            if kept_count > 0:
                logger.debug("登录历史清理完成，保留 {} 条记录", kept_count)
        except Exception:
            logger.warning("清理登录历史失败", exc_info=True)
