"""登录历史服务 — 记录每次登录尝试的时间、结果、耗时。"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from src.utils.file_helpers import atomic_write

from pydantic import BaseModel

from src.utils.logging import get_logger

logger = get_logger("backend.login_history", side="BACKEND")


class LoginHistoryEntry(BaseModel):
    """单条登录历史记录"""

    id: str
    timestamp: str
    success: bool
    duration_ms: int = 0
    profile_name: str = ""
    error: str = ""


class LoginHistoryService:
    """登录历史存储服务 — JSONL 文件追加写入。"""

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._history_path = data_dir / "login_history.jsonl"
        self._lock = threading.Lock()
        self._write_count = 0

    def add(
        self,
        success: bool,
        duration_ms: int = 0,
        profile_name: str = "",
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
            error=error[:200] if error else "",
        )
        with self._lock:
            try:
                with open(self._history_path, "a", encoding="utf-8") as f:
                    f.write(entry.model_dump_json() + "\n")
                    f.flush()
                self._write_count += 1
                # 每 50 次写入概率性清理旧记录
                if self._write_count % 50 == 0:
                    self._cleanup_old(max_age_days=30)
            except Exception:
                logger.warning("写入登录历史失败", exc_info=True)

    def list_recent(self, limit: int = 50) -> list[LoginHistoryEntry]:
        """读取最近 N 条登录记录（从新到旧）。"""
        if not self._history_path.exists():
            return []
        try:
            lines: list[str] = []
            with open(self._history_path, "r", encoding="utf-8") as f:
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
                    continue
            return result
        except Exception:
            logger.warning("读取登录历史失败", exc_info=True)
            return []

    def _cleanup_old(self, max_age_days: int = 30) -> None:
        """清理超过 max_age_days 天的旧记录。"""
        if not self._history_path.exists():
            return
        cutoff = datetime.now() - timedelta(days=max_age_days)
        cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M:%S")
        try:
            kept: list[str] = []
            with open(self._history_path, "r", encoding="utf-8") as f:
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
            removed = len(kept)
            if removed > 0:
                logger.debug("登录历史清理完成，保留 %d 条记录", removed)
        except Exception:
            logger.warning("清理登录历史失败", exc_info=True)
