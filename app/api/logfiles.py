"""日志文件查看路由 — 按日期/级别查看历史日志文件。"""

from __future__ import annotations

import re
from collections import deque
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from loguru import logger
from pydantic import BaseModel

from app.constants import LOGS_DIR
from app.utils.logging import VALID_LOG_LEVELS, VALID_SOURCES

router = APIRouter()

# 安全校验：只允许 app.log 和 app.log.N（N=1,2,3,...）
_SAFE_FILE_PATTERN = re.compile(r"^app\.log(?:\.\d+)?$")
_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# 日志行解析正则
# 格式: [2026-06-01 00:04:44][INFO][source][name] message
_LOG_LINE_PATTERN = re.compile(
    r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\[(\w+)\]\[([\w.-]+)\]\[([\w.-]+)\] (.+)$"
)


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


def read_tail(
    filepath: Path,
    limit: int,
) -> list[LogLine]:
    """读取日志文件末尾 N 行（浏览模式）。"""
    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            lines = list(deque(f, maxlen=limit))
    except OSError as err:
        logger.error("读取日志文件失败: {} — {}", filepath, err)
        return []

    return [_parse_log_line(raw.rstrip("\n\r")) for raw in lines]


def scan_file(
    filepath: Path,
    level: str,
    source: str,
    search: str,
    limit: int,
    max_scan_lines: int = 500_000,
) -> list[LogLine]:
    """全文扫描日志文件，按级别、来源、关键词过滤，返回匹配的行。

    超过 limit 时返回最后 N 条匹配结果。
    """
    matched: list[LogLine] = []

    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            for i, raw in enumerate(f):
                if i >= max_scan_lines:
                    logger.warning(
                        "扫描行数达到上限 {}，停止扫描文件 {}",
                        max_scan_lines,
                        filepath,
                    )
                    break

                line = _parse_log_line(raw.rstrip("\n\r"))

                # 级别过滤
                if level and level.upper() in VALID_LOG_LEVELS and line.level != level.upper():
                    continue

                # 来源过滤
                if (
                    source
                    and source.lower() in VALID_SOURCES
                    and line.source != source.lower()
                ):
                    continue

                # 关键词搜索（大小写不敏感）
                if search:
                    search_lower = search.lower()
                    if (
                        search_lower not in line.message.lower()
                        and search_lower not in line.name.lower()
                        and search_lower not in line.source.lower()
                        and search_lower not in raw.lower()
                    ):
                        continue

                matched.append(line)
    except OSError as err:
        logger.error("扫描日志文件失败: {} — {}", filepath, err)
        return []

    # 超过 limit 时返回最后 N 条
    if len(matched) > limit:
        matched = matched[-limit:]

    return matched


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

    # 判断是否为搜索模式
    is_search_mode = bool(search or level or source)

    if is_search_mode:
        # 搜索模式：全文扫描
        parsed = scan_file(filepath, level, source, search, limit)
        total = len(parsed)
    else:
        # 浏览模式：读取末尾 N 行
        parsed = read_tail(filepath, limit)
        total = len(parsed)

    return LogFileContent(
        date=date,
        file=file,
        total_lines=total,
        returned_lines=len(parsed),
        lines=parsed,
    )
