"""登录历史服务 — 记录每次登录尝试的时间、结果、耗时。"""

from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from pydantic import BaseModel

from app.utils.files import atomic_write
from app.utils.logging import get_logger

logger = get_logger("login_history", source="backend")

MAX_HISTORY_SIZE = 200


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
                    os.fsync(f.fileno())
                self._write_count += 1
                # 每 50 次写入概率性清理旧记录
                if self._write_count % 50 == 0:
                    need_cleanup = True
            except Exception as exc:
                logger.warning(
                    "写入登录历史失败: {}", exc, exc_info=True
                )
        # 清理在主写入锁外执行，避免长时间持有 _lock 阻塞并发写入
        if need_cleanup:
            self._cleanup_old(max_age_days=30)

    def list_recent(self, limit: int = 50) -> list[LoginHistoryEntry]:
        """读取最近 N 条登录记录（从新到旧）。"""
        if not self._history_path.exists():
            return []
        try:
            with self._lock:
                file_size = self._history_path.stat().st_size
                # 大文件（>5MB）只读取末尾部分
                if file_size > 5 * 1024 * 1024:
                    approx_bytes = limit * 500  # 估算每行约 500 字节
                    read_size = min(approx_bytes, file_size)
                    with open(self._history_path, encoding="utf-8") as f:
                        f.seek(max(0, file_size - read_size))
                        f.readline()  # 跳过可能截断的第一行
                        lines = [line.strip() for line in f if line.strip()]
                else:
                    with open(self._history_path, encoding="utf-8") as f:
                        lines = [line.strip() for line in f if line.strip()]
            # 取最后 limit 条并反转（最新在前）
            recent = lines[-limit:]
            recent.reverse()
            result: list[LoginHistoryEntry] = []
            for line in recent:
                try:
                    result.append(LoginHistoryEntry.model_validate_json(line))
                except Exception:
                    logger.warning("解析登录历史条目失败，跳过", exc_info=True)
                    continue
            return result
        except Exception as exc:
            logger.warning("读取登录历史失败: {}", exc, exc_info=True)
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
                logger.info("清空登录历史成功: 删除 {} 条记录", count)
                return count
            except Exception:
                logger.warning(
                    "清空登录历史失败: {}", self._history_path, exc_info=True
                )
                return 0

    def _cleanup_old(self, max_age_days: int = 30) -> None:
        """清理超过 max_age_days 天的旧记录，最多保留 MAX_HISTORY_SIZE 条。

        使用独立的 _cleanup_lock 防止并发清理，且不持有主写入锁 _lock，
        避免清理期间阻塞并发写入。
        """
        with self._cleanup_lock:
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
                # 最多保留 MAX_HISTORY_SIZE 条（保留末尾，即最新记录）
                if len(kept) > MAX_HISTORY_SIZE:
                    kept = kept[-MAX_HISTORY_SIZE:]
                content = "\n".join(kept)
                if kept:
                    content += "\n"
                atomic_write(str(self._history_path), content, encoding="utf-8")
                kept_count = len(kept)
                if kept_count > 0:
                    logger.debug("登录历史清理完成，保留 {} 条记录", kept_count)
            except Exception:
                logger.warning("清理登录历史失败: {}", self._history_path, exc_info=True)
