"""日志文件查看路由 — 按日期/级别查看历史日志文件（支持 zip 归档）。"""

from __future__ import annotations

import re
import zipfile
from collections import deque
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.constants import LOGS_DIR

router = APIRouter()

# 安全校验：只允许 app.log 和 app.log.N（N=1-3）
_SAFE_FILE_PATTERN = re.compile(r"^app\.log(?:\.\d)?$")
_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# 日志行解析正则
# 格式: 2026-06-01 00:04:44 | INFO | BACKEND | backend.module | message
_LOG_LINE_PATTERN = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \| (\w+) \| (\w+) \| ([\w.]+) \| (.+)$"
)

_VALID_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


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
    side: str = ""
    logger: str = ""
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
    except ValueError:
        raise HTTPException(400, "日期格式无效，须为 YYYY-MM-DD")


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
            side=m.group(3),
            logger=m.group(4),
            message=m.group(5),
        )
    return LogLine(message=raw)


def _list_dir_files(date_dir: Path) -> list[LogFileInfo]:
    """列出目录中的日志文件。"""
    files: list[LogFileInfo] = []
    for f in sorted(date_dir.iterdir()):
        if f.is_file() and _SAFE_FILE_PATTERN.match(f.name):
            stat = f.stat()
            files.append(LogFileInfo(
                name=f.name,
                size=stat.st_size,
                modified=datetime.fromtimestamp(stat.st_mtime).strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
            ))
    return files


def _list_zip_files(zip_path: Path) -> list[LogFileInfo]:
    """列出 zip 中的日志文件。"""
    files: list[LogFileInfo] = []
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            for info in sorted(zf.infolist(), key=lambda i: i.filename):
                # 路径格式: 2026-06-06/app.log 或 2026-06-06/screenshots/xxx.png
                parts = info.filename.split("/")
                if len(parts) == 2 and _SAFE_FILE_PATTERN.match(parts[1]):
                    files.append(LogFileInfo(
                        name=parts[1],
                        size=info.file_size,
                        modified=datetime(*info.date_time).strftime(
                            "%Y-%m-%d %H:%M:%S"
                        ),
                    ))
    except (zipfile.BadZipFile, OSError):
        pass
    return files


def _read_from_zip(zip_path: Path, date: str, filename: str) -> list[str]:
    """从 zip 中读取日志文件内容。"""
    arcname = f"{date}/{filename}"
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            with zf.open(arcname) as f:
                return f.read().decode("utf-8", errors="replace").splitlines()
    except (KeyError, zipfile.BadZipFile, OSError):
        return []


@router.get("/api/logfiles/list", response_model=list[LogFileGroup])
def list_log_files() -> list[LogFileGroup]:
    """列出所有日志文件（含 zip 归档），按日期分组（最新在前）。"""
    if not LOGS_DIR.exists():
        return []

    groups: list[LogFileGroup] = []
    seen_dates: set[str] = set()

    for item in sorted(LOGS_DIR.iterdir(), reverse=True):
        # 日期目录
        if item.is_dir() and _DATE_PATTERN.match(item.name):
            files = _list_dir_files(item)
            if files:
                groups.append(LogFileGroup(date=item.name, files=files))
                seen_dates.add(item.name)

        # zip 归档
        elif item.suffix == ".zip" and _DATE_PATTERN.match(item.stem):
            if item.stem in seen_dates:
                continue
            files = _list_zip_files(item)
            if files:
                groups.append(LogFileGroup(date=item.stem, files=files))
                seen_dates.add(item.stem)

    return groups


@router.get("/api/logfiles/content", response_model=LogFileContent)
def get_log_file_content(
    date: str = Query(..., description="日期 YYYY-MM-DD"),
    file: str = Query(default="app.log", description="文件名"),
    level: str = Query(default="", description="级别过滤"),
    search: str = Query(default="", description="搜索关键词"),
    limit: int = Query(default=2000, ge=1, le=10000),
) -> LogFileContent:
    """获取日志文件内容，支持按级别过滤和关键词搜索（自动从目录或 zip 读取）。"""
    _validate_date(date)
    _validate_filename(file)

    # 优先从目录读取，其次从 zip 读取
    date_dir = LOGS_DIR / date
    lines: list[str] = []

    if date_dir.is_dir():
        filepath = date_dir / file
        if filepath.exists():
            try:
                with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                    lines = list(deque(f, maxlen=max(limit * 2, 5000)))
            except (FileNotFoundError, OSError):
                pass

    if not lines:
        zip_path = LOGS_DIR / f"{date}.zip"
        if zip_path.exists():
            lines = _read_from_zip(zip_path, date, file)

    if not lines:
        raise HTTPException(404, f"日志文件不存在: {date}/{file}")

    # 解析并过滤
    parsed: list[LogLine] = []
    for raw in lines:
        line = _parse_log_line(raw.rstrip("\n\r"))

        if level and level.upper() in _VALID_LEVELS:
            if line.level != level.upper():
                continue

        if search:
            search_lower = search.lower()
            if (
                search_lower not in line.message.lower()
                and search_lower not in line.logger.lower()
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
