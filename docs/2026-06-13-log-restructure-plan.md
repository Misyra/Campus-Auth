# 日志系统重构实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将日志和截图迁移到 `debug/` 目录，用 loguru 原生轮转替代自定义 DateRotatingSink，截图只保留当天。

**Architecture:** 日志从 `logs/YYYY-MM-DD/app.log` 改为 `debug/logs/app.log`（loguru 原生按日期轮转），截图从 `logs/{date}/screenshots/` 改为 `debug/screenshots/{date}/`（启动时清理非当天目录）。

**Tech Stack:** Python, loguru, FastAPI, Vue 3

---

### Task 1: 常量更新

**Files:**
- Modify: `app/constants.py`

- [ ] **Step 1: 更新 constants.py**

```python
# 在 LOGS_DIR 之前添加 DEBUG_DIR
DEBUG_DIR = PROJECT_ROOT / "debug"
LOGS_DIR = DEBUG_DIR / "logs"
SCREENSHOTS_DIR = DEBUG_DIR / "screenshots"
# TEMP_DIR 不变
```

- [ ] **Step 2: 验证导入正常**

Run: `python -c "from app.constants import DEBUG_DIR, LOGS_DIR, SCREENSHOTS_DIR; print(DEBUG_DIR, LOGS_DIR, SCREENSHOTS_DIR)"`
Expected: 三个路径正确输出

- [ ] **Step 3: Commit**

```bash
git add app/constants.py
git commit -m "refactor: 日志目录常量改为 debug/logs，新增 DEBUG_DIR 和 SCREENSHOTS_DIR"
```

---

### Task 2: 日志轮转简化 — 删除 DateRotatingSink

**Files:**
- Modify: `app/utils/logging.py`

- [ ] **Step 1: 删除 DateRotatingSink 类**

删除 `DateRotatingSink` 类（第 179-335 行），保留 `DashboardSink` 和 `LogConfigCenter`。

- [ ] **Step 2: 修改 LogConfigCenter.add_file_handler**

将 `add_file_handler` 方法改为使用 loguru 原生 `logger.add()`：

```python
def add_file_handler(self, log_dir: str, retention_days: int = 7) -> None:
    """添加按日期存储的日志 sink（loguru 原生轮转）"""
    if self._file_sink_id is not None:
        with contextlib.suppress(ValueError):
            logger.remove(self._file_sink_id)
        self._file_sink_id = None

    try:
        log_path = os.path.join(log_dir, "app.log")
        os.makedirs(log_dir, exist_ok=True)

        self._file_sink_id = logger.add(
            log_path,
            rotation="00:00",
            retention=f"{retention_days} days",
            encoding="utf-8",
            format=_file_format,
            level="DEBUG",
            filter=lambda record: record["extra"].get("source") != "frontend",
        )

        logger.info("日志系统启动 | 目录: {} | 保留 {} 天", log_dir, retention_days)
    except Exception as e:
        logger.warning("无法启用文件日志 {}: {}", log_dir, e)
```

- [ ] **Step 3: 更新模块文档字符串**

移除文档字符串中对 `DateRotatingSink` 的描述。

- [ ] **Step 4: Commit**

```bash
git add app/utils/logging.py
git commit -m "refactor: 删除 DateRotatingSink，改用 loguru 原生轮转"
```

---

### Task 3: 截图路径更新

**Files:**
- Modify: `app/tasks/browser_runner.py:410-437`
- Modify: `app/tasks/step_handlers.py:569-606`

- [ ] **Step 1: 更新 browser_runner.py 截图路径**

```python
async def _capture_screenshot(self, page) -> str | None:
    """捕获截图 → 指定目录或 debug/screenshots/{date}/ 目录"""
    from app.utils.files import save_screenshot
    from app.constants import SCREENSHOTS_DIR

    try:
        if self._screenshot_dir:
            out_dir = self._screenshot_dir
            url_prefix = "/temp"
        else:
            date_str = datetime.now().strftime("%Y-%m-%d")
            out_dir = SCREENSHOTS_DIR / date_str
            url_prefix = f"/debug/screenshots/{date_str}"

        task_id = self.config.task_id or self.config.name or "unknown"
        local_path = await asyncio.wait_for(
            save_screenshot(page, out_dir, task_id=task_id),
            timeout=5,
        )
        if local_path:
            filename = Path(local_path).name
            return f"{url_prefix}/{filename}"
        return None
    except TimeoutError:
        logger.warning("截图超时（5s），已跳过")
        return None
    except Exception as e:
        logger.warning("截图失败: {}", e)
        return None
```

- [ ] **Step 2: 更新 step_handlers.py ScreenshotHandler**

```python
class ScreenshotHandler(StepHandler):
    """截图处理器 — 运行时截图存入 debug/screenshots/{date}/ 目录"""

    @property
    def step_type(self) -> str:
        return StepType.SCREENSHOT

    async def execute(
        self, page, step: StepConfig, resolver: VariableResolver
    ) -> tuple[bool, str]:
        from app.utils.files import save_screenshot
        from app.constants import SCREENSHOTS_DIR

        params = self.resolve_params(step, resolver)
        path = params.get("path", "")

        date_str = datetime.now().strftime("%Y-%m-%d")
        date_dir = SCREENSHOTS_DIR / date_str
        date_dir.mkdir(parents=True, exist_ok=True)

        if not path:
            task_id = resolver.config.task_id or resolver.config.name or "unknown"
            step_id = step.id or "s0"
            result = await save_screenshot(
                page, date_dir, task_id=task_id, step_id=step_id
            )
        else:
            safe_name = Path(path).name
            result = await save_screenshot(
                page, date_dir, prefix=safe_name.rsplit(".", 1)[0]
            )

        if result:
            filename = Path(result).name
            url = f"/debug/screenshots/{date_str}/{filename}"
            logger.debug("[screenshot] path={}", url)
            return True, url
        return False, "截图失败"
```

- [ ] **Step 3: Commit**

```bash
git add app/tasks/browser_runner.py app/tasks/step_handlers.py
git commit -m "refactor: 截图路径改到 debug/screenshots/{date}/"
```

---

### Task 4: API 更新 — logfiles.py

**Files:**
- Modify: `app/api/logfiles.py`

- [ ] **Step 1: 重写 logfiles.py**

```python
"""日志文件查看路由 — 查看历史日志文件。"""

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

# 文件名校验：当前日志 + loguru 归档格式
_SAFE_FILE_PATTERN = re.compile(r"^app\.log$")
_ARCHIVE_PATTERN = re.compile(
    r"^app\.(\d{4}-\d{2}-\d{2})_\d{2}-\d{2}-\d{2}(?:_\d+)?(?:\.\d+)?\.log$"
)

# 日志行解析正则
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
    file: str
    total_lines: int
    returned_lines: int
    lines: list[LogLine]


def _validate_filename(filename: str) -> None:
    """校验文件名安全性。"""
    if not filename:
        raise HTTPException(400, "文件名不能为空")
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(400, "文件名包含非法字符")
    if not (_SAFE_FILE_PATTERN.match(filename) or _ARCHIVE_PATTERN.match(filename)):
        raise HTTPException(400, "文件名无效，仅允许 app.log 和 loguru 归档格式")


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


def read_tail(filepath: Path, limit: int) -> list[LogLine]:
    """读取日志文件末尾 N 行。"""
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
    """全文扫描日志文件，按级别、来源、关键词过滤。"""
    matched: list[LogLine] = []
    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            for i, raw in enumerate(f):
                if i >= max_scan_lines:
                    logger.warning("扫描行数达到上限 {}，停止扫描文件 {}", max_scan_lines, filepath)
                    break
                line = _parse_log_line(raw.rstrip("\n\r"))
                if level and level.upper() in VALID_LOG_LEVELS and line.level != level.upper():
                    continue
                if source and source.lower() in VALID_SOURCES and line.source != source.lower():
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
                matched.append(line)
    except OSError as err:
        logger.error("扫描日志文件失败: {} — {}", filepath, err)
        return []
    if len(matched) > limit:
        matched = matched[-limit:]
    return matched


@router.get("/api/logfiles/list", response_model=list[LogFileGroup])
def list_log_files() -> list[LogFileGroup]:
    """列出所有日志文件，按日期分组（从文件名提取日期）。"""
    if not LOGS_DIR.exists():
        return []

    groups: dict[str, list[LogFileInfo]] = {}
    for f in sorted(LOGS_DIR.iterdir()):
        if not f.is_file():
            continue
        if f.name == "app.log":
            date = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d")
        elif m := _ARCHIVE_PATTERN.match(f.name):
            date = m.group(1)
        else:
            continue
        stat = f.stat()
        groups.setdefault(date, []).append(
            LogFileInfo(
                name=f.name,
                size=stat.st_size,
                modified=datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            )
        )
    return [LogFileGroup(date=d, files=files) for d in sorted(groups, reverse=True)]


@router.get("/api/logfiles/content", response_model=LogFileContent)
def get_log_file_content(
    file: str = Query(default="app.log", description="文件名"),
    level: str = Query(default="", description="级别过滤"),
    source: str = Query(default="", description="来源过滤"),
    search: str = Query(default="", description="搜索关键词"),
    limit: int = Query(default=2000, ge=1, le=10000),
) -> LogFileContent:
    """获取日志文件内容，支持按级别过滤和关键词搜索。"""
    _validate_filename(file)

    filepath = LOGS_DIR / file
    if not filepath.exists():
        raise HTTPException(404, f"日志文件不存在: {file}")

    is_search_mode = bool(search or level or source)

    if is_search_mode:
        parsed = scan_file(filepath, level, source, search, limit)
        total = len(parsed)
    else:
        parsed = read_tail(filepath, limit)
        total = len(parsed)

    return LogFileContent(
        file=file,
        total_lines=total,
        returned_lines=len(parsed),
        lines=parsed,
    )
```

- [ ] **Step 2: Commit**

```bash
git add app/api/logfiles.py
git commit -m "refactor: logfiles API 适配新目录结构，content 去掉 date 参数"
```

---

### Task 5: 应用入口更新 — application.py

**Files:**
- Modify: `app/application.py`

- [ ] **Step 1: 更新 imports 和常量**

```python
from app.constants import DEBUG_DIR, FRONTEND_DIR, LOGS_DIR, PROJECT_ROOT, TEMP_DIR, SCREENSHOTS_DIR
```

- [ ] **Step 2: 添加截图清理函数**

```python
def _cleanup_old_screenshots() -> None:
    """启动时清理非当天的截图子目录。"""
    try:
        if not SCREENSHOTS_DIR.exists():
            return
        today = datetime.now().strftime("%Y-%m-%d")
        removed = 0
        for d in SCREENSHOTS_DIR.iterdir():
            if d.is_dir() and d.name != today:
                import shutil
                shutil.rmtree(d, ignore_errors=True)
                removed += 1
        if removed:
            startup_logger.info("启动时清理旧截图: 删除 {} 个日期目录", removed)
    except Exception as exc:
        startup_logger.warning("清理旧截图失败: {}", exc)
```

- [ ] **Step 3: 在 lifespan 中调用截图清理**

在 `_cleanup_temp_screenshots()` 调用后添加：
```python
_cleanup_old_screenshots()
```

- [ ] **Step 4: 更新静态文件挂载**

```python
# 确保挂载目录存在
for _dir in (DEBUG_DIR, TEMP_DIR):
    _dir.mkdir(parents=True, exist_ok=True)

_app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
_app.mount("/debug", StaticFiles(directory=DEBUG_DIR), name="debug")
_app.mount("/temp", StaticFiles(directory=TEMP_DIR), name="temp")
# 移除 _app.mount("/logs", ...)
```

- [ ] **Step 5: 更新 run() 中的日志路径提示**

```python
log_dir = LOGS_DIR
try:
    log_center.add_file_handler(str(log_dir), retention_days=log_retention)
    startup_logger.info("日志文件: {}", log_dir / "app.log")
    # 删除旧日志清理逻辑（不再需要按日期目录清理）
except Exception:
    startup_logger.warning("日志系统初始化失败", exc_info=True)
```

- [ ] **Step 6: Commit**

```bash
git add app/application.py
git commit -m "refactor: 静态挂载改为 /debug，添加截图清理逻辑"
```

---

### Task 6: 前端更新

**Files:**
- Modify: `frontend/js/methods/logfiles.js`
- Modify: `frontend/js/methods/formatters.js`

- [ ] **Step 1: 更新 logfiles.js — fetchLogFileContent 去掉 date 参数**

```javascript
async fetchLogFileContent() {
    if (!this.logViewer.file) return;
    this.logViewer.loading = true;
    try {
      const params = {
        file: this.logViewer.file,
        limit: 5000,
      };
      if (this.logViewer.level) params.level = this.logViewer.level;
      if (this.logViewer.source) params.source = this.logViewer.source;
      if (this.logViewer.search) params.search = this.logViewer.search;
      const { data } = await this.$api.get('/api/logfiles/content', { params });
      this.logViewer.lines = data.lines;
      this.logViewer.totalLines = data.total_lines;
      this.$nextTick(() => {
        const viewer = this.$refs?.logFileViewer;
        if (viewer) viewer.scrollTop = viewer.scrollHeight;
      });
    } catch (error) {
      this.frontendLogger.error('logfiles', '获取日志内容失败', error);
      this.logViewer.lines = [];
    } finally {
      this.logViewer.loading = false;
    }
  },
```

- [ ] **Step 2: 验证 formatters.js 截图正则已兼容**

当前正则已经匹配 `/debug/` 路径，无需修改：
```javascript
const match = text.match(/截图[:：]\s*(\/(?:logs|debug|temp)\/\S+\.(?:png|jpg|jpeg|webp|gif))/i);
```

- [ ] **Step 3: Commit**

```bash
git add frontend/js/methods/logfiles.js
git commit -m "refactor: fetchLogFileContent 去掉 date 参数"
```

---

### Task 7: 测试更新

**Files:**
- Modify: `tests/test_api/test_api_logfiles_routes.py`
- Modify: `tests/test_utils/test_logging_fix.py`
- Modify: `tests/test_utils/test_utils.py`
- Modify: `tests/test_core/test_step_handlers.py`
- 其他测试文件中 `LOGS_DIR` patch 路径

- [ ] **Step 1: 更新 logfiles 测试**

- 删除 `_validate_date` 相关测试（函数已移除）
- 更新 `_validate_filename` 测试用例（适配新正则）
- `TestListLogFiles` 测试改为在 tmp_path 下直接创建文件（不再用日期目录）
- `TestGetLogFileContent` 去掉 `date` 参数
- `TestBrowseVsSearchMode` 同上

- [ ] **Step 2: 更新 logging 测试**

- 删除 `TestDateRotatingSinkRotation` 相关测试
- 更新 `test_logging_fix.py` 中对 `DateRotatingSink` 的引用

- [ ] **Step 3: 更新 step_handlers 测试**

更新截图 URL 断言：`/logs/{date}/screenshots/` → `/debug/screenshots/{date}/`

- [ ] **Step 4: 更新其他测试中的 LOGS_DIR patch**

将 `patch("app.constants.LOGS_DIR", tmp_path / "logs")` 改为 `patch("app.constants.LOGS_DIR", tmp_path / "debug" / "logs")`

- [ ] **Step 5: 运行全部测试**

Run: `uv run pytest -x -q`
Expected: 全部通过

- [ ] **Step 6: Commit**

```bash
git add tests/
git commit -m "test: 适配日志系统重构后的路径和 API 签名"
```

---

### Task 8: 向后迁移

**Files:**
- Modify: `app/application.py`

- [ ] **Step 1: 添加迁移函数**

```python
def _migrate_old_logs() -> None:
    """启动时将旧 logs/ 目录内容迁移到 debug/。"""
    old_logs_dir = PROJECT_ROOT / "logs"
    if not old_logs_dir.exists():
        return

    import shutil

    try:
        migrated_logs = 0
        migrated_screenshots = 0

        for date_dir in old_logs_dir.iterdir():
            if not date_dir.is_dir():
                continue
            date_name = date_dir.name  # YYYY-MM-DD

            # 迁移日志文件
            for f in date_dir.iterdir():
                if f.is_file() and (f.name == "app.log" or f.name.startswith("app.log.")):
                    dest = LOGS_DIR / f.name
                    if not dest.exists():
                        shutil.move(str(f), str(dest))
                        migrated_logs += 1

            # 迁移截图
            screenshots_dir = date_dir / "screenshots"
            if screenshots_dir.is_dir():
                dest = SCREENSHOTS_DIR / date_name
                if not dest.exists():
                    shutil.move(str(screenshots_dir), str(dest))
                    migrated_screenshots += 1

        # 清理空目录
        for date_dir in old_logs_dir.iterdir():
            if date_dir.is_dir():
                try:
                    date_dir.rmdir()
                except OSError:
                    pass
        try:
            old_logs_dir.rmdir()
        except OSError:
            pass

        if migrated_logs or migrated_screenshots:
            startup_logger.info(
                "旧日志迁移完成: {} 个日志文件, {} 个截图目录",
                migrated_logs, migrated_screenshots,
            )
    except Exception as exc:
        startup_logger.warning("旧日志迁移失败: {}", exc)
```

- [ ] **Step 2: 在 lifespan 中调用迁移**

在 `_cleanup_old_screenshots()` 之前调用：
```python
_migrate_old_logs()
```

- [ ] **Step 3: Commit**

```bash
git add app/application.py
git commit -m "feat: 启动时自动迁移旧 logs/ 目录到 debug/"
```
