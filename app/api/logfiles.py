"""日志文件查看路由 — 按日期/级别查看历史日志文件。"""

from __future__ import annotations

import re
from collections import deque
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.constants import LOGS_DIR

router = APIRouter()

# 安全校验：只允许 app.log 和 app.log.N（N=1,2,3,...）
_SAFE_FILE_PATTERN = re.compile(r"^app\.log(?:\.\d+)?$")
_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# 日志行解析正则
# 格式: [2026-06-01 00:04:44][INFO][backend][module] message
_LOG_LINE_PATTERN = re.compile(
    r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\[(\w+)\]\[(\w+)\]\[([\w.]+)\] (.+)$"
)

_VALID_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
_VALID_SOURCES = {"backend", "network", "task", "frontend", "debug"}


class LogFileInfo(BaseModel):
    name: str
    size: int
    modified: str


class LogFileGroup(BaseModel):
    date: str
    files: list[LogFileInfo]


class LogLine(BaseModel):
    timestamp: str = ""
    level: str = ""
    source: str = ""
    name: str = ""
    message: str = ""


class LogFileContent(BaseModel):
    date: str
    file: str
    total_lines: int
    returned_lines: int
    lines: list[LogLine]


def _validate_date(date: str) -> None:
    """校验日期格式 YYYY-MM-DD。"""
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError as err:
        raise HTTPException(400, "日期格式无效，须为 YYYY-MM-DD") from err


def _validate_filename(filename: str) -> None:
    """校验文件名安全性。"""
    if not _SAFE_FILE_PATTERN.match(filename):
        raise HTTPException(400, "文件名无效，仅允许 app.log 和 app.log.N")


def _parse_log_line(raw: str) -> LogLine:
    """解析单行日志。"""
    m = _LOG_LINE_PATTERN.match(raw)
    if m:
        return LogLine(
            timestamp=m.group(1),
            level=m.group(2),
            source=m.group(3),
            name=m.group(4),
            message=m.group(5),
        )
    return LogLine(message=raw)


@router.get("/api/logfiles/list", response_model=list[LogFileGroup])
def list_log_files() -> list[LogFileGroup]:
    """列出所有日志文件，按日期分组（最新在前）。"""
    if not LOGS_DIR.exists():
        return []

    groups: list[LogFileGroup] = []

    for item in sorted(LOGS_DIR.iterdir(), reverse=True):
        if not item.is_dir() or not _DATE_PATTERN.match(item.name):
            continue
        files: list[LogFileInfo] = []
        for f in sorted(item.iterdir()):
            if f.is_file() and _SAFE_FILE_PATTERN.match(f.name):
                stat = f.stat()
                files.append(
                    LogFileInfo(
                        name=f.name,
                        size=stat.st_size,
                        modified=datetime.fromtimestamp(stat.st_mtime).strftime(
                            "%Y-%m-%d %H:%M:%S"
                        ),
                    )
                )
        if files:
            groups.append(LogFileGroup(date=item.name, files=files))

    return groups


@router.get("/api/logfiles/content", response_model=LogFileContent)
def get_log_file_content(
    date: str = Query(..., description="日期 YYYY-MM-DD"),
    file: str = Query(default="app.log", description="文件名"),
    level: str = Query(default="", description="级别过滤"),
    source: str = Query(default="", description="来源过滤"),
    search: str = Query(default="", description="搜索关键词"),
    limit: int = Query(default=2000, ge=1, le=10000),
) -> LogFileContent:
    """获取日志文件内容，支持按级别过滤和关键词搜索。"""
    _validate_date(date)
    _validate_filename(file)

    date_dir = LOGS_DIR / date
    filepath = date_dir / file

    if not date_dir.is_dir() or not filepath.exists():
        raise HTTPException(404, f"日志文件不存在: {date}/{file}")

    try:
        max_lines = max(limit * 2, 5000)
        file_size = filepath.stat().st_size
        # 大文件（>50MB）只读取末尾部分，避免全量加载到内存
        if file_size > 50 * 1024 * 1024:
            # 估算每行平均长度（约 200 字节），读取末尾足够行数
            approx_bytes = max_lines * 200
            read_size = min(approx_bytes, file_size)
            with open(filepath, encoding="utf-8", errors="replace") as f:
                f.seek(max(0, file_size - read_size))
                # 跳过第一行（可能是截断的）
                f.readline()
                lines = list(deque(f, maxlen=max_lines))
        else:
            with open(filepath, encoding="utf-8", errors="replace") as f:
                lines = list(deque(f, maxlen=max_lines))
    except OSError as err:
        raise HTTPException(404, f"日志文件不存在: {date}/{file}") from err

    # 解析并过滤
    parsed: list[LogLine] = []
    for raw in lines:
        line = _parse_log_line(raw.rstrip("\n\r"))

        if level and level.upper() in _VALID_LEVELS and line.level != level.upper():
            continue

        if (
            source
            and source.lower() in _VALID_SOURCES
            and line.source != source.lower()
        ):
            continue

        if search:
            search_lower = search.lower()
            if (
                search_lower not in line.message.lower()
                and search_lower not in line.name.lower()
                and search_lower not in line.source.lower()
                and search_lower not in raw.lower()
            ):
                continue

        parsed.append(line)

    total = len(parsed)
    if total > limit:
        parsed = parsed[-limit:]

    return LogFileContent(
        date=date,
        file=file,
        total_lines=total,
        returned_lines=len(parsed),
        lines=parsed,
    )
