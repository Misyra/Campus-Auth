"""TaskRegistry + TaskHistoryStore — 定时任务数据中心。

提供任务 CRUD、内存缓存、O(1) 调度索引和独立的执行历史存储。
线程安全，所有公开方法返回副本。
"""

from __future__ import annotations

import json
import threading
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

from app.tasks import is_valid_task_id
from app.utils.file_helpers import atomic_write
from app.utils.logging import get_logger

logger = get_logger("task_registry", source="backend")

# ── 常量 ──
MAX_HISTORY_SIZE = 50


class TaskRegistry:
    """定时任务数据中心 — CRUD + 缓存 + O(1) 调度索引。

    内存常驻所有任务配置，提供调度索引快速查找到期任务。
    所有公开方法通过 RLock 保证线程安全，返回数据副本。
    """

    def __init__(self, tasks_dir: Path) -> None:
        self._tasks_dir = tasks_dir
        self._tasks_dir.mkdir(parents=True, exist_ok=True)

        # 内存缓存：task_id -> task 配置（含 id 字段）
        self._cache: dict[str, dict[str, Any]] = {}

        # 调度索引：(hour, minute, second) -> set[task_id]
        self._schedule_index: dict[tuple[int, int, int], set[str]] = {}

        self._lock = threading.RLock()

        # 从磁盘加载
        self._load_all()

    # ── 公开查询 ──

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        """获取任务配置（副本）。不存在或 ID 无效返回 None。"""
        if not is_valid_task_id(task_id):
            return None
        with self._lock:
            task = self._cache.get(task_id)
            return deepcopy(task) if task is not None else None

    def list_tasks(self) -> list[dict[str, Any]]:
        """列出所有任务（按名称排序，返回副本列表）。"""
        with self._lock:
            tasks = [deepcopy(t) for t in self._cache.values()]
        return sorted(tasks, key=lambda t: t.get("name", ""))

    def has_enabled_tasks(self) -> bool:
        """检查是否存在启用的任务。"""
        with self._lock:
            return any(t.get("enabled", False) for t in self._cache.values())

    # ── CRUD ──

    def save_task(self, task_id: str, config: dict[str, Any]) -> tuple[bool, str]:
        """保存任务（创建或更新）。同步更新缓存和调度索引。"""
        if not is_valid_task_id(task_id):
            return False, "无效的任务 ID"

        task_file = self._tasks_dir / f"{task_id}.json"
        try:
            # 写入磁盘（不含 id 字段）
            data = {k: v for k, v in config.items() if k != "id"}
            atomic_write(
                str(task_file),
                json.dumps(data, ensure_ascii=False, indent=2),
            )

            # 更新缓存
            with self._lock:
                old = self._cache.get(task_id)
                if old is not None:
                    self._remove_from_index(task_id, old)

                stored = deepcopy(config)
                stored["id"] = task_id
                self._cache[task_id] = stored
                self._add_to_index(task_id, stored)

            logger.info("定时任务已保存: {}", task_id)
            return True, "定时任务保存成功"
        except Exception as exc:
            logger.error("保存定时任务失败 {}: {}", task_id, exc)
            return False, f"定时任务保存失败: {exc}"

    def delete_task(self, task_id: str) -> tuple[bool, str]:
        """删除任务。同时清理调度索引。"""
        if not is_valid_task_id(task_id):
            return False, "无效的任务 ID"

        task_file = self._tasks_dir / f"{task_id}.json"
        if not task_file.exists():
            return False, "定时任务不存在"

        try:
            task_file.unlink()

            with self._lock:
                old = self._cache.pop(task_id, None)
                if old is not None:
                    self._remove_from_index(task_id, old)

            logger.info("定时任务已删除: {}", task_id)
            return True, "定时任务删除成功"
        except Exception as exc:
            logger.error("删除定时任务失败 {}: {}", task_id, exc)
            return False, f"定时任务删除失败: {exc}"

    # ── 调度索引 ──

    def get_due_tasks(self, hour: int, minute: int) -> set[str]:
        """返回在指定时刻到期的任务 ID 集合（副本）。"""
        key = (hour, minute, 0)
        with self._lock:
            return set(self._schedule_index.get(key, set()))

    # ── 状态更新 ──

    def update_last_run(
        self, task_id: str, status: str, timestamp: str | None = None
    ) -> None:
        """更新任务的最后执行时间和状态。

        仅更新缓存和磁盘，不触发索引变更。
        """
        with self._lock:
            task = self._cache.get(task_id)
            if task is None:
                return

            task["last_run"] = timestamp or datetime.now().isoformat()
            task["last_status"] = status

            # 写回磁盘
            try:
                data = {k: v for k, v in task.items() if k != "id"}
                atomic_write(
                    str(self._tasks_dir / f"{task_id}.json"),
                    json.dumps(data, ensure_ascii=False, indent=2),
                )
            except Exception as exc:
                logger.error("更新定时任务状态失败 {}: {}", task_id, exc)

    # ── 内部方法 ──

    def _load_all(self) -> None:
        """从磁盘加载所有任务到缓存并构建调度索引。"""
        for file_path in self._tasks_dir.glob("*.json"):
            if file_path.name.startswith("."):
                continue
            task_id = file_path.stem
            if not is_valid_task_id(task_id):
                continue
            try:
                data = json.loads(file_path.read_text(encoding="utf-8"))
                data["id"] = task_id
                self._cache[task_id] = data
                self._add_to_index(task_id, data)
            except Exception as exc:
                logger.error("读取定时任务失败 {}: {}", file_path, exc)

    def _add_to_index(self, task_id: str, config: dict[str, Any]) -> None:
        """将任务添加到调度索引（需要在锁内调用）。"""
        if not config.get("enabled", False):
            return
        schedule = config.get("schedule", {})
        hour = schedule.get("hour", -1)
        minute = schedule.get("minute", -1)
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            key = (hour, minute, 0)
            self._schedule_index.setdefault(key, set()).add(task_id)

    def _remove_from_index(self, task_id: str, config: dict[str, Any]) -> None:
        """将任务从调度索引移除（需要在锁内调用）。"""
        schedule = config.get("schedule", {})
        hour = schedule.get("hour", -1)
        minute = schedule.get("minute", -1)
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            key = (hour, minute, 0)
            task_ids = self._schedule_index.get(key)
            if task_ids is not None:
                task_ids.discard(task_id)
                if not task_ids:
                    del self._schedule_index[key]

    def _update_index(self, task_id: str, config: dict[str, Any]) -> None:
        """先移除旧索引再添加新索引（需要在锁内调用）。

        用于任务配置更新时的索引重建。
        """
        # 查找旧配置并移除旧索引
        old = self._cache.get(task_id)
        if old is not None:
            self._remove_from_index(task_id, old)
        # 添加新索引
        self._add_to_index(task_id, config)


class TaskHistoryStore:
    """定时任务执行历史存储。

    独立于 TaskRegistry，负责历史记录的 CRUD。
    线程安全，所有公开方法返回副本。
    """

    def __init__(self, history_dir: Path) -> None:
        self._history_dir = history_dir
        self._history_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def get_history(self, task_id: str) -> list[dict[str, Any]]:
        """获取任务执行历史（副本列表，按时间倒序）。"""
        if not is_valid_task_id(task_id):
            return []
        history_file = self._history_dir / f"{task_id}.json"
        if not history_file.exists():
            return []
        try:
            data = json.loads(history_file.read_text(encoding="utf-8"))
            return list(data.get("runs", []))
        except Exception as exc:
            logger.error("读取执行历史失败 {}: {}", task_id, exc)
            return []

    def add_record(
        self, task_id: str, status: str, message: str, duration: float
    ) -> None:
        """添加执行历史记录（线程安全，自动裁剪到 MAX_HISTORY_SIZE）。"""
        if not is_valid_task_id(task_id):
            return

        with self._lock:
            history_file = self._history_dir / f"{task_id}.json"
            try:
                if history_file.exists():
                    data = json.loads(history_file.read_text(encoding="utf-8"))
                else:
                    data = {"runs": []}

                data["runs"].insert(
                    0,
                    {
                        "timestamp": datetime.now().isoformat(),
                        "status": status,
                        "message": message[:500],
                        "duration": round(duration, 2),
                    },
                )

                # 裁剪到上限
                data["runs"] = data["runs"][:MAX_HISTORY_SIZE]

                atomic_write(
                    str(history_file),
                    json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except Exception as exc:
                logger.error("保存执行历史失败 {}: {}", task_id, exc)

    def delete_history(self, task_id: str) -> None:
        """删除指定任务的全部历史记录。"""
        if not is_valid_task_id(task_id):
            return
        history_file = self._history_dir / f"{task_id}.json"
        try:
            if history_file.exists():
                history_file.unlink()
                logger.info("已删除执行历史: {}", task_id)
        except Exception as exc:
            logger.error("删除执行历史失败 {}: {}", task_id, exc)
