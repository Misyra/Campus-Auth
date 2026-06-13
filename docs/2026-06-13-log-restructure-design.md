# 日志系统重构设计

## 背景

当前日志按日期目录存储（`logs/YYYY-MM-DD/app.log`），截图混在日期目录下的 `screenshots/` 子目录中。日志和截图的清理逻辑不同（日志按文件删除、截图保留目录），结构不直观，维护成本高。

## 目标

1. 日志和截图职责分离，目录结构清晰
2. 清理逻辑统一、直观
3. 利用 loguru 原生轮转能力，减少自定义代码

## 目录结构

```
debug/
  logs/                         # 日志文件（loguru 原生轮转）
    app.log                     # 当前日志
    app.log.2026-06-12          # 按日期归档（loguru rotation="00:00" 自动生成）
    app.log.2026-06-11
  screenshots/                  # 截图，只保留当天
    2026-06-13/
      taskid_stepid_20260613_120000_123456.png
temp/                           # 不动，调试模式临时文件
```

## 常量变更

```python
# constants.py
DEBUG_DIR = PROJECT_ROOT / "debug"
LOGS_DIR = DEBUG_DIR / "logs"          # 替代原 LOGS_DIR
SCREENSHOTS_DIR = DEBUG_DIR / "screenshots"
TEMP_DIR = PROJECT_ROOT / "temp"       # 不变
```

## 日志轮转

用 loguru 原生能力替代自定义 `DateRotatingSink` 的轮转和清理逻辑：

```python
logger.add(
    str(LOGS_DIR / "app.log"),
    rotation="00:00",           # 每天午夜轮转
    retention=f"{retention_days} days",  # 自动清理过期归档
    encoding="utf-8",
    format=_file_format,
    level="DEBUG",
)
```

loguru 轮转后归档文件命名格式为 `app.log.2026-06-12_00-00-00`（YYYY-MM-DD_HH-MM-SS），非简单的 `.N` 后缀。

- `DateRotatingSink` 中的 `_rotate_file()`、`_cleanup_old_dirs()`、文件大小检查等自定义逻辑全部移除
- 保留 `_get_log_path()` 的日期目录逻辑（不再需要，但 loguru 直接写单文件）
- 保留 `DashboardSink` 不动（实时日志 + WebSocket 广播）
- 保留 `LogConfigCenter` 不动（运行时级别控制）

## 截图存储与清理

### 保存路径

截图统一保存到 `debug/screenshots/{YYYY-MM-DD}/`：

- `browser_runner.py` `_capture_screenshot`：路径从 `LOGS_DIR / date / "screenshots"` 改为 `SCREENSHOTS_DIR / date`
- `step_handlers.py` `ScreenshotHandler`：同上
- `files.py` `save_screenshot`：接收的 `output_dir` 参数由调用方传入新路径
- 截图 URL 格式：`/debug/screenshots/{date}/{filename}`（替代 `/logs/{date}/screenshots/{filename}`）

### 清理机制

启动时 + 每小时检查，删除非当天的 `screenshots/YYYY-MM-DD/` 子目录：

```python
def cleanup_old_screenshots():
    """删除非当天的截图子目录。"""
    today = datetime.now().strftime("%Y-%m-%d")
    if not SCREENSHOTS_DIR.exists():
        return
    for d in SCREENSHOTS_DIR.iterdir():
        if d.is_dir() and d.name != today:
            shutil.rmtree(d, ignore_errors=True)
```

## API 变更

### GET /api/logfiles/list

去掉日期分组，直接返回日志文件列表：

```python
# 文件名校验正则更新（适配 loguru 归档命名）
_SAFE_FILE_PATTERN = re.compile(r"^app\.log(?:\.\d{4}-\d{2}-\d{2}(?:_\d{2}-\d{2}-\d{2})?)?$")
```

```python
# 响应格式变更
# 旧：list[LogFileGroup]（按日期分组）
# 新：list[LogFileInfo]（平铺列表）

@router.get("/api/logfiles/list", response_model=list[LogFileInfo])
def list_log_files() -> list[LogFileInfo]:
    """列出 debug/logs/ 下所有日志文件。"""
    files = []
    for f in sorted(LOGS_DIR.iterdir()):
        if f.is_file() and _SAFE_FILE_PATTERN.match(f.name):
            stat = f.stat()
            files.append(LogFileInfo(name=f.name, size=stat.st_size, modified=...))
    return files
```

### GET /api/logfiles/content

去掉 `date` 参数，`file` 参数直接定位文件：

```python
@router.get("/api/logfiles/content", response_model=LogFileContent)
def get_log_file_content(
    file: str = Query(default="app.log", description="文件名"),
    level: str = Query(default=""),
    source: str = Query(default=""),
    search: str = Query(default=""),
    limit: int = Query(default=2000, ge=1, le=10000),
) -> LogFileContent:
    filepath = LOGS_DIR / file
    # ...
```

## 前端变更

### 日志查看器（logfiles 页面）

- 去掉日期 Tab 选择器
- 文件列表从平铺的文件名列表中选择
- 级别、来源、搜索过滤保持不变

### 截图 URL

前端 `extractScreenshotUrl` 正则适配新路径：

```javascript
// 旧：/logs/{date}/screenshots/{filename}
// 新：/debug/screenshots/{date}/{filename}
const match = text.match(/截图[:：]\s*(\/debug\/screenshots\/\S+\.(?:png|jpg|jpeg|webp|gif))/i);
```

## 静态文件挂载

```python
# application.py
_app.mount("/debug", StaticFiles(directory=DEBUG_DIR), name="debug")
_app.mount("/temp", StaticFiles(directory=TEMP_DIR), name="temp")
# 移除 _app.mount("/logs", ...)
```

## 改动文件清单

| 文件 | 改动内容 |
|------|---------|
| `app/constants.py` | `LOGS_DIR` → `DEBUG_DIR / "logs"`，新增 `SCREENSHOTS_DIR` |
| `app/utils/logging.py` | `DateRotatingSink` 简化为 loguru 原生 `logger.add()` |
| `app/api/logfiles.py` | API 去掉 `date` 参数，`list` 返回平铺列表 |
| `app/tasks/browser_runner.py` | 截图路径改到 `SCREENSHOTS_DIR / date` |
| `app/tasks/step_handlers.py` | 截图路径同上 |
| `app/utils/files.py` | `save_screenshot` 调用方传入新路径 |
| `app/application.py` | 静态挂载改为 `/debug`，截图清理逻辑迁移 |
| `app/container.py` | 日志初始化适配新路径 |
| `app/schemas.py` | `log_retention_days` 描述更新 |
| `frontend/js/methods/logfiles.js` | 去掉日期选择逻辑 |
| `frontend/js/methods/formatters.js` | 截图 URL 正则适配 |
| `frontend/partials/pages/logfiles.html` | 去掉日期 Tab |
| `frontend/styles/pages/logfiles.css` | 去掉日期 Tab 样式 |
| 相关测试文件 | 适配新路径和 API 签名 |

## 向后迁移

启动时检测旧 `logs/` 目录是否存在，如果存在：
1. 将 `logs/YYYY-MM-DD/app.log*` 移动到 `debug/logs/`（保留最近 N 天）
2. 将 `logs/YYYY-MM-DD/screenshots/` 移动到 `debug/screenshots/`
3. 迁移完成后删除空的 `logs/` 目录
