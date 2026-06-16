# 代码审查问题修复实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复代码审查报告中确认的 43 个问题（8 Critical + 23 Major + 12 Minor）

**Architecture:** 按模块分 11 组修复，每组独立可提交。修复原则：最小改动、保持风格、测试验证。

**Tech Stack:** Python 3.10+, FastAPI, Playwright, threading, asyncio

---

## 文件变更总览

| 文件 | 变更类型 | 涉及问题 |
|------|----------|----------|
| `app/workers/playwright_worker.py` | Modify | [11][12][13][14] |
| `app/utils/browser_registry.py` | Modify | [4][17][18] |
| `app/workers/playwright_bootstrap.py` | Modify | [4][16][52] |
| `app/api/install_playwright.py` | Modify | [5] |
| `app/services/engine.py` | Modify | [19][21][54][55][56] |
| `app/services/task_executor.py` | Modify | [2][22][24] |
| `app/services/config_service.py` | Modify | [26][28] |
| `app/services/runtime_config.py` | Modify | [27] |
| `app/tasks/variable_resolver.py` | Modify | [6][7] |
| `app/tasks/step_handlers.py` | Modify | [33][34] |
| `app/container.py` | Modify | [3] |
| `main.py` | Modify | [29][30][64] |
| `app/services/debug_service.py` | Modify | [9][10][44][45][75] |
| `app/network/probes.py` | Modify | [35] |
| `frontend/js/methods/ui.js` | Modify | [47][48] |
| `app/utils/browser.py` | Modify | [50] |
| `app/utils/shell_utils.py` | Modify | [57] |
| `app/services/monitor_service.py` | Modify | [53] |
| `app/utils/crypto.py` | Modify | [60] |
| `app/schemas.py` | Modify | [61] |
| `app/tasks/manager.py` | Modify | [66] |
| `tests/` | Create/Modify | 各 Task 对应测试 |

---

## Task 1: 浏览器自动化核心修复（`playwright_worker.py`）

**Files:**
- Modify: `app/workers/playwright_worker.py:295-297`（[11] submit_nowait）
- Modify: `app/workers/playwright_worker.py:1008-1037`（[12] cleanup_orphan_browsers）
- Modify: `app/workers/playwright_worker.py:975-993`（[13] get_worker）
- Modify: `app/workers/playwright_worker.py:586-593`（[14] _handle_debug_stop）
- Test: `tests/test_utils/test_src_utils.py`

### [11] `submit_nowait` 添加异常处理和事件循环唤醒

- [ ] **Step 1: 修改 `submit_nowait` 方法**

```python
# app/workers/playwright_worker.py:295-297
# 替换原方法
def submit_nowait(self, cmd_type: str, data: dict | None = None) -> None:
    """提交命令但不等待响应（fire-and-forget）。"""
    try:
        self._cmd_queue.put_nowait(WorkerCommand(type=cmd_type, data=data or {}))
    except queue.Full:
        logger.warning("命令队列已满，丢弃命令: {}", cmd_type)
        return
    # 唤醒 Worker 事件循环
    loop = self._loop
    if loop is not None:
        with contextlib.suppress(RuntimeError):
            asyncio.run_coroutine_threadsafe(self._wake_async(), loop)
```

- [ ] **Step 2: 运行测试验证**

Run: `pytest tests/test_utils/test_src_utils.py -v -k "submit_nowait" 2>$null`

### [12] `cleanup_orphan_browsers` 扩展清理 Firefox

- [ ] **Step 1: 修改过滤条件**

```python
# app/workers/playwright_worker.py:1023-1025
# 替换原条件
if ("ms-playwright" in exe or "ms-playwright" in cmdline) and (
    "chrom" in exe or "chrom" in cmdline
    or "firefox" in exe or "firefox" in cmdline
):
```

- [ ] **Step 2: 更新日志消息**

```python
# app/workers/playwright_worker.py:1028
logger.debug("已终止孤儿浏览器 PID={}", info["pid"])
```

```python
# app/workers/playwright_worker.py:1035
logger.info("已终止 {} 个孤儿浏览器进程", killed)
```

```python
# app/workers/playwright_worker.py:1037
logger.debug("未发现孤儿 Playwright 浏览器进程")
```

- [ ] **Step 3: 运行测试验证**

Run: `pytest tests/test_utils/test_src_utils.py -v -k "cleanup" 2>$null`

### [13] `get_worker()` 将赋值移到 `start()` 成功之后

- [ ] **Step 1: 修改 `get_worker` 函数**

```python
# app/workers/playwright_worker.py:975-993
def get_worker() -> PlaywrightWorker:
    """获取全局 PlaywrightWorker 单例。

    首次调用时创建实例并自动 start()。
    后续调用返回已有实例；若实例已停止则自动重建。
    """
    global _worker
    if _worker is None or not _worker.is_alive():
        with _worker_lock:
            if _worker is None or not _worker.is_alive():
                if _worker is not None:
                    try:
                        _worker.stop()
                    except Exception:
                        logger.debug("停止旧 Worker 失败", exc_info=True)
                cleanup_orphan_browsers()
                new_worker = PlaywrightWorker()
                new_worker.start()
                _worker = new_worker
    return _worker
```

- [ ] **Step 2: 运行测试验证**

Run: `pytest tests/test_utils/test_src_utils.py -v -k "get_worker" 2>$null`

### [14] `_handle_debug_stop` 使用与 `_start_browser` 一致的反检测逻辑

- [ ] **Step 1: 修改 `_handle_debug_stop` 中的反检测调用**

```python
# app/workers/playwright_worker.py:586-593
# 替换原代码
if self._page is not None:
    # 使用与 _start_browser 一致的判断逻辑
    settings = self._last_browser_settings or {}
    if not self._pure_mode or settings.get("stealth_mode", False):
        await self._apply_stealth_and_routes({"browser_settings": settings})
```

- [ ] **Step 2: 运行测试验证**

Run: `pytest tests/test_utils/test_src_utils.py -v -k "debug" 2>$null`

- [ ] **Step 3: 提交**

```bash
git add app/workers/playwright_worker.py tests/test_utils/test_src_utils.py
git commit -m "fix: 修复浏览器自动化核心 4 个问题

- submit_nowait 添加 queue.Full 处理和 _wake_async 唤醒
- cleanup_orphan_browsers 扩展清理 Firefox 进程
- get_worker 将 _worker 赋值移到 start() 成功之后
- _handle_debug_stop 使用与 _start_browser 一致的反检测逻辑"
```

---

## Task 2: 浏览器注册与安装修复（`browser_registry.py`、`playwright_bootstrap.py`、`install_playwright.py`）

**Files:**
- Modify: `app/utils/browser_registry.py`（[4] Chromium 检测去重、[17] Firefox LOCALAPPDATA、[18] 缓存）
- Modify: `app/workers/playwright_bootstrap.py`（[4] 复用公共函数、[16] 环境变量回滚、[52] 移除 sync_playwright 回退）
- Modify: `app/api/install_playwright.py`（[5] asyncio.Lock）
- Test: `tests/test_utils/test_browser_registry.py`

### [4] 提取 Chromium 检测到公共函数

- [ ] **Step 1: 在 `browser_registry.py` 中添加公共函数 `has_playwright_chromium()`**

在 `_has_playwright_chromium()` 函数之前添加：

```python
# app/utils/browser_registry.py
def has_playwright_chromium() -> bool:
    """检查 Playwright Chromium 是否已下载（公共接口）。

    扫描 ms-playwright 缓存目录和包内 .local-browsers 路径。
    供 browser_registry 和 playwright_bootstrap 复用。
    """
    if PLATFORM == "windows":
        cache_dir = Path.home() / "AppData" / "Local" / "ms-playwright"
    elif PLATFORM == "darwin":
        cache_dir = Path.home() / "Library" / "Caches" / "ms-playwright"
    else:
        cache_dir = Path.home() / ".cache" / "ms-playwright"

    search_dirs = [cache_dir]

    # 添加包内 .local-browsers 备用路径
    try:
        import importlib.util as _ilu
        _spec = _ilu.find_spec("playwright")
        if _spec and _spec.submodule_search_locations:
            search_dirs.append(
                Path(_spec.submodule_search_locations[0]) / "driver" / "package" / ".local-browsers"
            )
    except Exception:
        pass

    for base_dir in search_dirs:
        if not base_dir.is_dir():
            continue
        for d in base_dir.glob("chromium-*"):
            if not d.is_dir():
                continue
            for candidate in [
                d / "chrome-win64" / "chrome.exe",
                d / "chrome-win" / "chrome.exe",
                d / "chrome-linux" / "chrome",
                d / "chrome-mac" / "Chromium.app" / "Contents" / "MacOS" / "Chromium",
            ]:
                if candidate.exists():
                    return True
    return False
```

- [ ] **Step 2: 修改 `_has_playwright_chromium()` 复用公共函数**

```python
# app/utils/browser_registry.py
def _has_playwright_chromium() -> bool:
    """检查 Playwright Chromium 是否已下载。"""
    return has_playwright_chromium()
```

- [ ] **Step 3: 修改 `playwright_bootstrap.py` 复用公共函数**

```python
# app/workers/playwright_bootstrap.py:92-141
# 替换整个 _has_chromium 函数
def _has_chromium() -> bool:
    """检查 Playwright Chromium 是否已下载。"""
    from app.utils.browser_registry import has_playwright_chromium
    return has_playwright_chromium()
```

### [5] `install_playwright` 改用 `asyncio.Lock()`

- [ ] **Step 1: 修改并发保护**

```python
# app/api/install_playwright.py:16
# 替换原变量
_installing_lock = asyncio.Lock()

# app/api/install_playwright.py:19-26
# 替换原端点函数开头
@router.post("/api/browsers/install-playwright")
async def install_playwright_chromium():
    """安装 Playwright Chromium 浏览器（异步执行）。"""
    if _installing_lock.locked():
        return {"success": False, "message": "安装正在进行中，请稍后再试"}

    async with _installing_lock:
        # ... 原 try/finally 块内容（移除 finally 中的 _installing = False）
```

- [ ] **Step 2: 移除 `finally` 块中的 `_installing = False`**

删除 `app/api/install_playwright.py:69` 的 `_installing = False`。

### [16] `ensure_playwright_ready` 环境变量回滚

- [ ] **Step 1: 添加环境变量保存/恢复**

```python
# app/workers/playwright_bootstrap.py:216 之前插入
original_host = os.environ.get("PLAYWRIGHT_DOWNLOAD_HOST")

# app/workers/playwright_bootstrap.py:229 之后（for 循环结束后）插入
# 恢复原始环境变量
if original_host is not None:
    os.environ["PLAYWRIGHT_DOWNLOAD_HOST"] = original_host
else:
    os.environ.pop("PLAYWRIGHT_DOWNLOAD_HOST", None)
```

### [17] Firefox 检测补充 `LOCALAPPDATA` 路径

- [ ] **Step 1: 添加 `LOCALAPPDATA` 检测**

```python
# app/utils/browser_registry.py:117-126
# 替换原代码
elif PLATFORM == "windows":
    # 检查 Windows 标准安装路径
    program_files = [
        Path(os.environ.get("PROGRAMFILES", "C:\\Program Files")),
        Path(os.environ.get("PROGRAMFILES(X86)", "C:\\Program Files (x86)")),
    ]
    # 用户级安装路径
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        program_files.append(Path(local_app_data))

    for base in program_files:
        firefox_path = base / "Mozilla Firefox" / "firefox.exe"
        if firefox_path.exists():
            installed = True
            break
```

### [18] `detect_browsers()` 添加 TTL 缓存

- [ ] **Step 1: 添加缓存机制**

```python
# app/utils/browser_registry.py:38 之前插入
import time

_detect_cache: list[BrowserInfo] | None = None
_detect_cache_time: float = 0
_DETECT_CACHE_TTL = 30.0  # 30 秒缓存

# app/utils/browser_registry.py:38-50
# 替换原函数
def detect_browsers() -> list[BrowserInfo]:
    """检测系统已安装的浏览器。

    仅在向导和设置页面调用，启动时直接使用配置的 channel。
    结果缓存 30 秒，避免短时间内重复扫描。
    """
    global _detect_cache, _detect_cache_time
    now = time.monotonic()
    if _detect_cache is not None and now - _detect_cache_time < _DETECT_CACHE_TTL:
        return _detect_cache

    browsers = [
        _detect_playwright_chromium(),
        _detect_edge(),
        _detect_chrome(),
        _detect_firefox(),
        _detect_custom(),
    ]
    _detect_cache = browsers
    _detect_cache_time = now
    return browsers
```

### [52] 移除 `_has_chromium()` 的 `sync_playwright` 回退

此步骤已在 [4] 中完成（`_has_chromium` 整体替换为调用 `has_playwright_chromium()`）。

- [ ] **Step 1: 运行测试验证**

Run: `pytest tests/test_utils/test_browser_registry.py -v 2>$null`

- [ ] **Step 2: 提交**

```bash
git add app/utils/browser_registry.py app/workers/playwright_bootstrap.py app/api/install_playwright.py
git commit -m "fix: 修复浏览器注册与安装 5 个问题

- 提取 Chromium 检测到公共函数 has_playwright_chromium()
- playwright_bootstrap 复用公共函数，移除 sync_playwright 回退
- install_playwright 改用 asyncio.Lock 替代布尔变量
- ensure_playwright_ready 环境变量失败后回滚
- Firefox 检测补充 LOCALAPPDATA 路径
- detect_browsers 添加 30 秒 TTL 缓存"
```

---

## Task 3: 调度引擎修复（`engine.py`）

**Files:**
- Modify: `app/services/engine.py:311-338`（[19] 手动登录污染重试计数）
- Modify: `app/services/engine.py:267-289`（[21] shutdown 绕过 Actor、[54] profile switch 失败跳过）
- Modify: `app/services/engine.py:529-543`（[55] ws_drain_loop 空检查）
- Modify: `app/services/engine.py:141-144`（[56] 重复 IO）
- Test: `tests/test_services/test_engine.py`

### [19] 手动登录路径不递增重试计数

- [ ] **Step 1: 添加 `is_manual` 参数**

```python
# app/services/engine.py:311
# 替换原方法签名
def _do_async_login(self, skip_pause_check: bool = False, is_manual: bool = False) -> bool:
    """提交登录到 executor 的 login_pool。返回 True 表示已提交。"""
    if self._login_in_progress.is_set():
        return False
    self._login_in_progress.set()
    self._login_retry.last_attempt = time.time()
    if not is_manual:
        self._login_retry.count += 1
    # ... 其余不变
```

- [ ] **Step 2: 手动登录路径传递 `is_manual=True`**

```python
# app/services/engine.py:421
# 替换原调用
if self._do_async_login(skip_pause_check=skip_pause_check, is_manual=True):
```

### [21] `_do_network_check` 获取 `_monitor_core` 本地引用

- [ ] **Step 1: 添加本地引用**

```python
# app/services/engine.py:267-289
# 在方法开头添加本地引用
def _do_network_check(self) -> None:
    """执行一次网络检测。"""
    core = self._monitor_core
    if core is None:
        return

    try:
        result = core.check_once()
        # ... 使用 core 替代 self._monitor_core
        if result.get("need_login", False):
            self._login_retry.config = self._get_retry_config()
            self._login_retry.count = 0
            self._do_async_login()
        else:
            self._login_retry.count = 0

        # 检查是否需要重启（自动切换方案）
        if core and core.consume_profile_switch_flag():
```

### [54] `_reload_config_internal` 失败时跳过 `_handle_start`

- [ ] **Step 1: 检查重载结果**

```python
# app/services/engine.py:284-289
# 替换原代码
        # 检查是否需要重启（自动切换方案）
        if core and core.consume_profile_switch_flag():
            logger.info("检测到方案切换，重启监控")
            self._handle_stop()
            if self._reload_config_internal():
                self._handle_start(EngineCommand(type=EngineCmdType.START))
            else:
                logger.warning("配置重载失败，跳过重启监控")
```

### [55] `ws_drain_loop` 入口检查 `_ws_manager`

- [ ] **Step 1: 添加空值检查**

```python
# app/services/engine.py:545-556
# 在 drain_ws_queue 开头添加检查
async def drain_ws_queue(self) -> None:
    """Flush pending WS broadcast messages to WebSocket clients."""
    if self._ws_manager is None:
        return
    broadcast_queue = self.ws_broadcast_queue
    # ... 其余不变
```

### [56] `_reload_config_internal` 中同时更新 `_pure_mode`

- [ ] **Step 1: 读取 `_pure_mode` 配置**

需要确认 `_reload_config_internal` 的实现。如果它调用 `_profile_service.load()`，则在其中同时更新 `self._pure_mode`。

```python
# 在 _reload_config_internal 方法中，配置加载后添加
self._pure_mode = self._profile_service.load().global_settings.pure_mode
```

- [ ] **Step 2: 运行测试验证**

Run: `pytest tests/test_services/test_engine.py -v 2>$null`

- [ ] **Step 3: 提交**

```bash
git add app/services/engine.py
git commit -m "fix: 修复调度引擎 5 个问题

- 手动登录路径不递增自动重试计数
- _do_network_check 获取 _monitor_core 本地引用避免竞态
- _reload_config_internal 失败时跳过重启监控
- ws_drain_loop 入口检查 _ws_manager 非空
- _reload_config_internal 中同时更新 _pure_mode"
```

---

## Task 4: 任务执行中心修复（`task_executor.py`）

**Files:**
- Modify: `app/services/task_executor.py:147-151`（[2] _ensure_task_pool 无锁）
- Modify: `app/services/task_executor.py:210-227`（[22] 去重返回旧 Future）
- Modify: `app/services/task_executor.py:495-520`（[24] _get_script_path 脆弱）
- Test: `tests/test_services/test_task_executor_fix.py`

### [2] `_ensure_task_pool` 添加双检锁

- [ ] **Step 1: 添加锁和修改方法**

```python
# app/services/task_executor.py:147-151
# 替换原方法
_task_pool_lock = threading.Lock()

def _ensure_task_pool(self) -> BoundedExecutor:
    """确保定时任务线程池存在（懒初始化）。"""
    if self._task_pool is None:
        with self._task_pool_lock:
            if self._task_pool is None:
                self._task_pool = BoundedExecutor(max_workers=2, queue_size=10)
    return self._task_pool
```

注意：需要在 `__init__` 中初始化 `self._task_pool_lock = threading.Lock()`，或使用模块级锁。

### [22] `execute_login_async` 去重时合并 cancel_event

- [ ] **Step 1: 去重时设置已有 cancel_event**

```python
# app/services/task_executor.py:214-217
# 替换原去重逻辑
if self._login_future is not None and not self._login_future.done():
    # 去重：将新调用方的 cancel_event 合并到已有任务
    if cancel_event is not None and self._login_cancel_event is not None:
        # 创建一个组合事件：任一事件被设置都触发取消
        original = self._login_cancel_event
        combined = cancel_event
        # 通过回调联动
        def _sync_cancel(evt):
            if evt.is_set():
                original.set()
        combined.add_callback(_sync_cancel) if hasattr(combined, 'add_callback') else None
    logger.debug("登录任务已在执行中，跳过重复提交")
    return self._login_future
```

实际上更简单的方案是：在去重时记录新的 cancel_event，让取消检查逻辑同时检查两个事件。但这需要修改 `execute_login` 的取消检查逻辑。最简方案：

```python
# app/services/task_executor.py:214-217
if self._login_future is not None and not self._login_future.done():
    # 去重：如果新调用方有 cancel_event，联动到已有任务的 cancel_event
    if cancel_event is not None and self._login_cancel_event is not None:
        # 在后台线程监控新 cancel_event，设置时联动到已有事件
        def _watch_cancel():
            cancel_event.wait()
            if not self._login_future.done():
                self._login_cancel_event.set()
        threading.Thread(target=_watch_cancel, daemon=True).start()
    logger.debug("登录任务已在执行中，跳过重复提交")
    return self._login_future
```

需要确认 `self._login_cancel_event` 是否存在。如果不存在，需要在提交时保存 cancel_event 引用。

### [24] `_get_script_path` 在 TaskRegistry 上添加方法

- [ ] **Step 1: 在 TaskRegistry 添加 `get_script_path` 方法**

需要先读取 `app/services/task_registry.py` 确认结构，然后添加方法。

```python
# app/services/task_registry.py
def get_script_path(self, script_id: str) -> Path | None:
    """获取脚本任务的文件路径。"""
    project_root = self._tasks_dir.parent.parent
    scripts_dir = project_root / "tasks" / "scripts"
    for ext in (".json", ".py"):
        candidate = scripts_dir / f"{script_id}{ext}"
        if candidate.exists():
            return candidate
    return None
```

- [ ] **Step 2: 运行测试验证**

Run: `pytest tests/test_services/test_task_executor_fix.py -v 2>$null`

- [ ] **Step 3: 提交**

```bash
git add app/services/task_executor.py app/services/task_registry.py
git commit -m "fix: 修复任务执行中心 3 个问题

- _ensure_task_pool 添加 threading.Lock 双检锁
- execute_login_async 去重时联动 cancel_event
- TaskRegistry 添加 get_script_path 方法替代脆弱的路径推断"
```

---

## Task 5: 配置服务修复（`config_service.py`、`runtime_config.py`）

**Files:**
- Modify: `app/services/config_service.py:20-79`（[26] 遗漏 lightweight_tray）
- Modify: `app/services/runtime_config.py:90-141`（[27] 遗漏 lightweight_tray）
- Modify: `app/services/config_service.py:104-111`（[28] 密码处理绕过）
- Test: `tests/test_services/test_config_service.py`

### [26] `_update_global_settings` 补充 `lightweight_tray`

- [ ] **Step 1: 添加字段赋值**

```python
# app/services/config_service.py:32 之后插入
global_settings.lightweight_tray = payload.lightweight_tray
```

### [27] `_build_config_payload` 补充 `lightweight_tray`

- [ ] **Step 1: 添加字段到 payload_dict**

```python
# app/services/runtime_config.py:98 之后插入
"lightweight_tray": data.global_settings.lightweight_tray,
```

### [28] 密码处理委托给 `save_password_field`

- [ ] **Step 1: 简化密码处理逻辑**

```python
# app/services/config_service.py:104-111
# 替换原代码
from app.utils.crypto import save_password_field
profile.username = payload.username.strip()
profile.password = save_password_field(payload.password.strip(), profile.password)
profile.auth_url = payload.auth_url.strip()
```

`save_password_field` 已经处理了掩码值（`startswith("•")`）、空字符串（清空密码）、`ENC:` 前缀等所有情况。

- [ ] **Step 2: 运行测试验证**

Run: `pytest tests/test_services/test_config_service.py -v 2>$null`

- [ ] **Step 3: 提交**

```bash
git add app/services/config_service.py app/services/runtime_config.py
git commit -m "fix: 修复配置服务 3 个问题

- _update_global_settings 补充 lightweight_tray 字段同步
- _build_config_payload 补充 lightweight_tray 字段
- save_config_combined 密码处理完全委托给 save_password_field"
```

---

## Task 6: 任务系统修复（`variable_resolver.py`、`step_handlers.py`）

**Files:**
- Modify: `app/tasks/variable_resolver.py:99-117`（[6] resolve_for_js 双重编码）
- Modify: `app/tasks/variable_resolver.py:30-97`（[7] 缓存版本号）
- Modify: `app/tasks/step_handlers.py:640-692`（[33] OCR Timer 竞态）
- Modify: `app/tasks/step_handlers.py:609-634`（[34] SleepHandler 校验）
- Test: `tests/test_integration/test_scheduled_task.py`

### [6] `resolve_for_js` 统一 `str()` 转换

- [ ] **Step 1: 修改 replacer 函数**

```python
# app/tasks/variable_resolver.py:109-115
# 替换原 replacer
def replacer(match: re.Match) -> str:
    resolved = self.resolve(match.group(0))
    # If variable not found, resolve returns the original pattern
    if resolved == match.group(0):
        logger.warning("[var] 未解析的变量: {}", match.group(0))
        return json.dumps(match.group(0))
    # 统一转为字符串后再 JSON 编码，确保输出始终是带引号的 JS 字符串字面量
    return json.dumps(str(resolved))
```

### [7] 变量解析添加版本号机制

- [ ] **Step 1: 添加版本号字段**

```python
# app/tasks/variable_resolver.py:30
# 在 __init__ 中添加
self._cache_version = 0

# app/tasks/variable_resolver.py:96-97
# 修改 set_runtime_var
def set_runtime_var(self, name: str, value: Any) -> None:
    """设置运行时变量"""
    self.runtime_vars[name] = value
    self._cache_version += 1
    self._cache.clear()
```

- [ ] **Step 2: 在 resolve 中检查版本号**

缓存 key 需要包含版本号，或者在检查缓存时验证版本号。最简方案：将版本号嵌入缓存 key。

```python
# app/tasks/variable_resolver.py:42-44
# 替换缓存检查
cache_key = (self._cache_version, value)
if depth == 0 and cache_key in self._cache:
    return self._cache[cache_key]

# app/tasks/variable_resolver.py:89-90
# 替换缓存存储
if depth == 0:
    self._cache[cache_key] = result
```

注意：还需要在 `template_vars` 或 `config.variables` 被外部修改时递增版本号。但这些是构造时传入的引用，外部修改难以追踪。可以通过在 `resolve` 中检测变化来处理，但这会增加复杂度。当前方案（版本号 + `set_runtime_var` 清缓存）已覆盖主要场景。

### [33] OCR Timer 操作纳入锁保护

- [ ] **Step 1: 修改 `_cancel_cleanup` 和 `schedule_cleanup` 使用锁**

```python
# app/tasks/step_handlers.py:665-678
# 替换原方法
@classmethod
def schedule_cleanup(cls, old: bool = False):
    """OCR 使用完毕后调用，启动定时清理"""
    with cls._ocr_lock:
        cls._cancel_cleanup_locked(old)
        timer = threading.Timer(cls._IDLE_TIMEOUT, cls._do_cleanup, args=[old])
        timer.daemon = True
        timer.start()
        cls._cleanup_timers[old] = timer

@classmethod
def _cancel_cleanup(cls, old: bool):
    with cls._ocr_lock:
        cls._cancel_cleanup_locked(old)

@classmethod
def _cancel_cleanup_locked(cls, old: bool):
    """内部方法，调用时必须已持有 _ocr_lock。"""
    timer = cls._cleanup_timers.pop(old, None)
    if timer is not None:
        timer.cancel()
```

- [ ] **Step 2: 修改 `_do_cleanup` 使用锁**

```python
# app/tasks/step_handlers.py:680-692
# 替换原方法
@classmethod
def _do_cleanup(cls, old: bool):
    """定时器回调：卸载 OCR 模型释放内存"""
    with cls._ocr_lock:
        if old in cls._ocr_instances:
            del cls._ocr_instances[old]
            logger.info(
                "[ocr] 模型已卸载 (old={})，空闲超过 {}s", old, cls._IDLE_TIMEOUT
            )
        cls._cleanup_timers.pop(old, None)
    import gc
    gc.collect()
```

- [ ] **Step 3: 修改 `_get_ocr` 中的 `_cancel_cleanup` 调用**

```python
# app/tasks/step_handlers.py:646-663
# _get_ocr 中的 _cancel_cleanup 调用已在锁外，需要调整
@classmethod
def _get_ocr(cls, old: bool = False):
    with cls._ocr_lock:
        # 取消已有的清理定时器（还在用，不需要清理了）
        cls._cancel_cleanup_locked(old)

        if old in cls._ocr_instances:
            return cls._ocr_instances[old]

        try:
            import ddddocr
            instance = ddddocr.DdddOcr(old=old, show_ad=False)
        except ImportError as err:
            raise StepError(
                "ddddocr 未安装，请在「设置 → 系统与日志」中安装 OCR 依赖"
            ) from err
        cls._ocr_instances[old] = instance
        return instance
```

### [34] `SleepHandler` 添加校验

- [ ] **Step 1: 添加 try/except 和负值检查**

```python
# app/tasks/step_handlers.py:621-630
# 替换原代码
params = self.resolve_params(step, resolver)
try:
    duration = int(params.get("duration", 1000))
except (ValueError, TypeError):
    logger.warning("[sleep] duration 值无效: {}", params.get("duration"))
    duration = 1000

if duration < 0:
    logger.warning("[sleep] duration={}ms 为负数，使用默认值 1000ms", duration)
    duration = 1000
elif duration > self.MAX_SLEEP_MS:
```

- [ ] **Step 2: 运行测试验证**

Run: `pytest tests/test_integration/test_scheduled_task.py -v -k "sleep" 2>$null`

- [ ] **Step 3: 提交**

```bash
git add app/tasks/variable_resolver.py app/tasks/step_handlers.py
git commit -m "fix: 修复任务系统 4 个问题

- resolve_for_js 统一 str() 转换后再 json.dumps 避免双重编码
- 变量解析缓存添加版本号机制避免过期结果
- OCR Timer 操作全部纳入 _ocr_lock 保护
- SleepHandler 添加 try/except 和负值校验"
```

---

## Task 7: 应用入口修复（`main.py`、`container.py`）

**Files:**
- Modify: `app/container.py:54-60`（[3] 轻量模式 TaskExecutor）
- Modify: `main.py:416-428`（[29] event loop 竞态）
- Modify: `main.py:359-378`（[30] Web 服务竞态）
- Modify: `main.py:103-133`（[64] 终止进程后未验证）
- Test: `tests/test_integration/test_app_startup.py`

### [3] 轻量模式创建 NullTaskExecutor

- [ ] **Step 1: 修改 container.py**

```python
# app/container.py:53-60
# 替换原代码
# 任务执行器（双线程池）
if self._is_lightweight:
    self.task_executor = NullTaskExecutor()
else:
    self.task_executor = TaskExecutor(
        registry=self.task_registry,
        history_store=self.task_history_store,
        worker_getter=_get_worker,
        login_history=self.login_history_service,
        profile_service=self.profile_service,
    )
```

- [ ] **Step 2: 确认 `NullTaskExecutor` 已导入**

检查 `app/container.py` 的导入列表，确保 `NullTaskExecutor` 已导入。

### [29] 轻量模式关闭改为同步分离

- [ ] **Step 1: 修改 finally 块**

```python
# main.py:424-428
# 替换原代码
if not _web_server_state["started"]:
    # 轻量模式下不创建新 event loop，直接同步关闭
    import asyncio as _asyncio
    try:
        loop = _asyncio.get_event_loop()
        if loop.is_running():
            # 无法在运行中的 loop 内 run_until_complete，跳过
            logger.debug("轻量模式：跳过异步 shutdown（事件循环运行中）")
        else:
            loop.run_until_complete(container.shutdown())
    except RuntimeError:
        # 没有事件循环，跳过异步 shutdown
        logger.debug("轻量模式：无事件循环，跳过异步 shutdown")
```

### [30] `_start_web_server` 使用锁保护

- [ ] **Step 1: 添加锁**

```python
# main.py:359 之前插入
_web_server_lock = threading.Lock()

# main.py:361-378
# 替换原函数
def _start_web_server():
    """按需启动 Web 服务（在子线程中运行）。"""
    with _web_server_lock:
        if _web_server_state["started"]:
            return
        _web_server_state["started"] = True

    def _worker():
        try:
            from app.application import run
            run(
                existing_container=container,
                server_ref=_web_server_state["server_ref"],
            )
        except Exception as e:
            logger.error("Web 服务启动失败: {}", e)
            with _web_server_lock:
                _web_server_state["started"] = False

    threading.Thread(target=_worker, daemon=True).start()
```

### [64] 终止进程后验证退出

- [ ] **Step 1: 添加退出验证**

需要读取 `main.py:103-133` 确认具体实现后添加验证逻辑。

- [ ] **Step 2: 运行测试验证**

Run: `pytest tests/test_integration/test_app_startup.py -v 2>$null`

- [ ] **Step 3: 提交**

```bash
git add app/container.py main.py
git commit -m "fix: 修复应用入口 4 个问题

- 轻量模式创建 NullTaskExecutor 替代真正的 TaskExecutor
- 轻量模式关闭不再创建新 event loop
- _start_web_server 使用 threading.Lock 保护
- 终止进程后验证退出状态"
```

---

## Task 8: 调试会话管理修复（`debug_service.py`）

**Files:**
- Modify: `app/services/debug_service.py:252-253`（[9] run_all 锁外访问）
- Modify: `app/services/debug_service.py:70-94`（[10] 超时监控器无锁读取）
- Modify: `app/services/debug_service.py:223-284`（[44] run_all 并发保护）
- Modify: `app/services/debug_service.py:96-178`（[45] start 锁内耗时）
- Modify: `app/services/debug_service.py:308-314`（[75] close 未取消定时器）
- Test: `tests/test_services/test_debug_service.py`

### [9] + [44] `run_all` 会话检查移入锁内 + 一次性持有信号量

- [ ] **Step 1: 修改 `run_all` 方法**

```python
# app/services/debug_service.py:223-284
# 替换原方法
async def run_all(self) -> dict:
    """执行所有步骤。"""
    from app.workers.playwright_worker import CMD_DEBUG_STEP, get_worker

    async with self._lock:
        self._require_debug_session()
        session = self._session
        from_idx = session.current_step

        if from_idx >= len(session.steps):
            return {**self._debug_response(), "message": "所有步骤已执行完毕"}

    worker = get_worker()
    results: list[dict] = []
    all_success = True

    # 一次性持有信号量直到批量完成
    async with self._exec_sem:
        for i in range(from_idx, len(session.steps)):
            async with self._lock:
                if self._session is not session or not session.running:
                    all_success = False
                    break

            response = await asyncio.to_thread(
                lambda idx=i: worker.submit(
                    CMD_DEBUG_STEP, data={"step_index": idx}
                )
            )

            async with self._lock:
                if self._session is not session or not session.running:
                    all_success = False
                    break

            if not response.success:
                results.append(
                    {
                        "step_index": i,
                        "success": False,
                        "message": response.error or "步骤执行异常",
                        "screenshot_url": None,
                    }
                )
                all_success = False
                break

            step_result = response.data
            results.append(step_result)
            if not step_result.get("success", False):
                all_success = False
                break

    async with self._lock:
        if self._session is not session:
            return self._debug_response()
        session.results.extend(results)
        session.current_step = (
            len(session.steps) if all_success else from_idx + len(results)
        )
        session._last_activity = time.monotonic()
        if results:
            session.screenshot_url = results[-1].get("screenshot_url")
        return self._debug_response()
```

### [10] 超时监控器 `_last_activity` 读取移入锁内

- [ ] **Step 1: 修改 `_debug_timeout_watcher`**

```python
# app/services/debug_service.py:76-80
# 替换原循环体
while True:
    await asyncio.sleep(check_interval)
    if gen != _current_gen:
        return
    async with self._lock:
        if gen != _current_gen:
            return
        if time.monotonic() - self._session._last_activity > timeout_seconds:
            debug_logger.info(
                "调试会话超时（{}s 无操作），正在关闭浏览器",
                timeout_seconds,
            )
            try:
                if self._session._browser_active:
                    await self._close_debug_browser()
            finally:
                self._session = empty_debug_session()
```

### [45] `start` 将 Worker 启动移到锁外

- [ ] **Step 1: 重构 start 方法**

```python
# app/services/debug_service.py:138-174
# 在锁内准备数据，锁外调用 Worker
async with self._lock:
    if self._session._browser_active:
        await self._close_debug_browser()
    await self._cancel_debug_timer()

    # ... 构建 worker_data 和 steps_info ...

    self._session = empty_debug_session()
    self._session._browser_active = True
    self._session.task_id = task_id
    self._session.steps = steps_info
    self._session.running = True
    self._session._last_activity = time.monotonic()
    self._session._timer_task = asyncio.create_task(
        self._debug_timeout_watcher(gen)
    )
    self._session.executor = None

# 锁外调用 Worker（耗时操作）
response = await asyncio.to_thread(
    lambda: get_worker().submit(CMD_DEBUG_START, data=worker_data)
)

async with self._lock:
    if not response.success:
        await self._close_debug_browser()
        raise RuntimeError(f"调试会话启动失败: {response.error}")
    if isinstance(response.data, dict):
        self._session.screenshot_url = response.data.get("screenshot_url")
```

### [75] `close` 方法取消超时定时器

- [ ] **Step 1: 在 close 开头添加取消**

```python
# app/services/debug_service.py:308-314
# 在方法开头添加
async def close(self) -> None:
    """关闭调试服务，清理资源。"""
    await self._cancel_debug_timer()
    # ... 其余清理逻辑
```

- [ ] **Step 2: 运行测试验证**

Run: `pytest tests/test_services/test_debug_service.py -v 2>$null`

- [ ] **Step 3: 提交**

```bash
git add app/services/debug_service.py
git commit -m "fix: 修复调试会话管理 5 个问题

- run_all 会话有效性检查移入锁内
- run_all 一次性持有 _exec_sem 直到批量完成
- _debug_timeout_watcher _last_activity 读取移入锁内
- start 方法 Worker 启动调用移到锁外
- close 方法添加 _cancel_debug_timer 调用"
```

---

## Task 9: 网络检测修复（`probes.py`）

**Files:**
- Modify: `app/network/probes.py:33-39`（[35] _get_probe_client TOCTOU）
- Test: `tests/test_core/test_network_probes.py`

### [35] `_get_probe_client` 快速路径移入锁内

- [ ] **Step 1: 移除快速路径，统一走锁内检查**

```python
# app/network/probes.py:30-47
# 替换原函数
def _get_probe_client(block_proxy: bool) -> httpx.Client:
    """获取全局复用的探测 Client，线程安全。代理设置变化时自动重建。"""
    global _probe_client, _probe_block_proxy
    with _probe_lock:
        if (
            _probe_client is not None
            and not _probe_client.is_closed
            and _probe_block_proxy == block_proxy
        ):
            return _probe_client
        # 重建客户端
        # ... 原慢速路径逻辑
```

- [ ] **Step 2: 运行测试验证**

Run: `pytest tests/test_core/test_network_probes.py -v 2>$null`

- [ ] **Step 3: 提交**

```bash
git add app/network/probes.py
git commit -m "fix: 修复 _get_probe_client 快速路径 TOCTOU 竞态

- 移除无锁快速路径，统一走锁内检查"
```

---

## Task 10: 前端修复（`ui.js`）

**Files:**
- Modify: `frontend/js/methods/ui.js:144-171`（[47] 自定义浏览器交互）
- Modify: `frontend/js/methods/ui.js:173-194`（[48] 安装超时保护）

### [47] 自定义浏览器增加独立分支

- [ ] **Step 1: 修改 `handleBrowserClick`**

```javascript
// frontend/js/methods/ui.js:158-170
// 替换原 else 分支
} else if (browser.channel === 'custom') {
  // 自定义浏览器：聚焦到路径输入框
  this.selectBrowser(browser.channel);
  this.$nextTick(() => {
    const input = document.querySelector('input[placeholder*="浏览器路径"], input[v-model*="browser_custom_path"]');
    if (input) input.focus();
  });
} else {
  // 其他浏览器未安装，弹窗提示跳转官网
  const downloadUrls = {
    msedge: 'https://www.microsoft.com/edge',
    chrome: 'https://www.google.com/chrome/',
    firefox: 'https://www.firefox.com/',
  };
  const url = downloadUrls[browser.channel] || 'https://playwright.dev/docs/browsers';
  if (confirm(`${browser.name} 未安装。\n\n是否跳转到官网下载？`)) {
    window.open(url, '_blank');
  }
}
```

### [48] `installPlaywrightChromium` 添加超时保护

- [ ] **Step 1: 添加 AbortController**

```javascript
// frontend/js/methods/ui.js:173-194
// 替换原方法
async installPlaywrightChromium() {
    this.browserLoading = true;
    this.notify(true, '正在下载 Playwright Chromium，请稍候...');
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 600000); // 10 分钟超时
    try {
      const response = await fetch('/api/browsers/install-playwright', {
        method: 'POST',
        signal: controller.signal,
      });
      clearTimeout(timeoutId);
      const data = await response.json();
      if (data.success) {
        this.frontendLogger.info('browser', 'Playwright Chromium 安装成功');
        this.notify(true, 'Playwright Chromium 安装成功！');
        await this.fetchBrowsers();
      } else {
        this.frontendLogger.error('browser', '安装失败: ' + data.message);
        this.notify(false, '安装失败: ' + data.message);
      }
    } catch (error) {
      clearTimeout(timeoutId);
      if (error.name === 'AbortError') {
        this.frontendLogger.error('browser', '安装超时');
        this.notify(false, '安装超时（超过 10 分钟），请检查网络后重试');
      } else {
        this.frontendLogger.error('browser', '安装请求失败', error);
        this.notify(false, '安装请求失败，请查看日志');
      }
    } finally {
      this.browserLoading = false;
    }
  },
```

- [ ] **Step 2: 提交**

```bash
git add frontend/js/methods/ui.js
git commit -m "fix: 修复前端浏览器选择 2 个问题

- 自定义浏览器点击时聚焦到路径输入框而非提示下载
- installPlaywrightChromium 添加 10 分钟 AbortController 超时"
```

---

## Task 11: Minor 问题修复（分散文件）

**Files:**
- Modify: `app/utils/browser.py:57-58`（[50] stealth script）
- Modify: `app/services/monitor_service.py:344-349`（[53] 注释修正）
- Modify: `app/utils/shell_utils.py:60-71`（[57] get_default_shell）
- Modify: `app/utils/crypto.py:218`（[60] 密码掩码判断）
- Modify: `app/schemas.py`（[61] 字段重复定义）
- Modify: `app/tasks/manager.py:136-165`（[66] docstring 解析）

### [50] `STEALTH_INIT_SCRIPT` 改用 `Object.defineProperty`

- [ ] **Step 1: 修改删除逻辑**

```python
# app/utils/browser.py:57-58
# 替换原代码
// 隐藏 Playwright 注入的属性（使用 Object.defineProperty 防止重新定义）
try { Object.defineProperty(window, '__playwright', {get: () => undefined, configurable: false}); } catch(e) {}
try { Object.defineProperty(window, '__pw_manual', {get: () => undefined, configurable: false}); } catch(e) {}
```

### [53] `consume_profile_switch_flag` 注释修正

- [ ] **Step 1: 修正注释**

```python
# app/services/monitor_service.py:344-345
# 替换原注释
def consume_profile_switch_flag(self) -> bool:
    """消费重启标志位。由引擎线程串行调用，无需额外同步。"""
```

### [57] `get_default_shell` 验证回退路径

- [ ] **Step 1: 添加路径验证**

```python
# app/utils/shell_utils.py:70-71
# 替换原代码
else:
    shell = os.environ.get("SHELL", "/bin/bash")
    if shutil.which(shell):
        return shell
    # 回退到已知存在的 shell
    for fallback in ("/bin/bash", "/bin/sh"):
        if shutil.which(fallback):
            return fallback
    return shell  # 最后回退，让调用方处理不存在的情况
```

### [60] 密码掩码判断改为完整匹配

- [ ] **Step 1: 修改 `save_password_field`**

```python
# app/utils/crypto.py:218
# 替换原条件
if raw == "••••••••":
```

### [61] `_SystemFieldsMixin` 和 `GlobalSettings` 字段去重

- [ ] **Step 1: 评估重构方案**

这是一个较大的重构，需要让 `GlobalSettings` 继承 `_SystemFieldsMixin` 或创建共享基类。由于涉及面广，建议：
1. 创建 `_SharedSettingsMixin` 包含两者共有的字段
2. 让 `_SystemFieldsMixin` 和 `GlobalSettings` 都继承它
3. 确保 Pydantic 模型兼容

由于此问题复杂度较高且风险较大，建议作为独立 Task 处理，或标记为后续优化。

### [66] `_extract_script_metadata` 使用 `ast.get_docstring()`

- [ ] **Step 1: 修改解析逻辑**

```python
# app/tasks/manager.py:136-165
# 替换原方法
@staticmethod
def _extract_script_metadata(file: Path) -> dict[str, str]:
    """从 Python 脚本提取 name 和 description。

    优先读取 # name: / # description: 注释，
    其次使用 ast.get_docstring() 提取模块级 docstring。
    """
    name = file.stem
    description = ""
    try:
        text = file.read_text(encoding="utf-8")
        lines = text.splitlines()[:10]
        for line in lines:
            stripped = line.strip()
            if stripped.lower().startswith("# name:"):
                name = stripped.split(":", 1)[1].strip()
            elif stripped.lower().startswith("# description:"):
                description = stripped.split(":", 1)[1].strip()
        # 如果没找到 name 注释，尝试 docstring
        if name == file.stem:
            import ast
            try:
                tree = ast.parse(text)
                docstring = ast.get_docstring(tree)
                if docstring:
                    name = docstring.split("\n")[0][:80]
            except SyntaxError:
                pass
    except Exception:
        logger.debug("解析脚本 docstring 失败: {}", file, exc_info=True)
    return {"name": name, "description": description}
```

- [ ] **Step 2: 运行测试验证**

Run: `pytest tests/ -v -k "stealth or shell or password or metadata" 2>$null`

- [ ] **Step 3: 提交**

```bash
git add app/utils/browser.py app/services/monitor_service.py app/utils/shell_utils.py app/utils/crypto.py app/tasks/manager.py
git commit -m "fix: 修复 6 个 Minor 问题

- STEALTH_INIT_SCRIPT 改用 Object.defineProperty 替代 delete
- consume_profile_switch_flag 修正注释为串行调用
- get_default_shell 验证回退路径是否存在
- save_password_field 掩码判断改为完整匹配
- _extract_script_metadata 使用 ast.get_docstring()"
```

---

## Task 12: 其余 Minor 问题

**Files:**
- Modify: `app/services/engine.py`（[54][55][56] 已在 Task 3 处理）
- Test: 已有测试覆盖

### [59] `BoundedExecutor.shutdown` 添加注释

- [ ] **Step 1: 添加注释说明**

```python
# app/services/task_executor.py:96-98
# 在 shutdown 方法添加注释
def shutdown(self, wait: bool = True) -> None:
    """关闭线程池。

    注意：wait=False 时已提交但未执行的任务信号量不会被释放。
    这在应用退出场景下影响有限，因为进程退出会自动回收资源。
    """
```

- [ ] **Step 2: 提交**

```bash
git add app/services/task_executor.py
git commit -m "docs: BoundedExecutor.shutdown 添加信号量残留说明"
```

---

## 最终验证

- [ ] **运行全量测试**

```bash
pytest tests/ -v --timeout=30 2>$null
```

- [ ] **更新 `.claude/change.md`**

在修改日志中记录所有修复。

- [ ] **最终提交**

```bash
git add .claude/change.md
git commit -m "docs: 更新修改日志，记录代码审查问题修复"
```
