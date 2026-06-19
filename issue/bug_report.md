# Bug 报告 — 经三轮独立验证确认的问题清单

> 验证基准：三轮独立代码审查，覆盖 `main.py`、`engine.py`、`task_executor.py`、`config_service.py`、`profile_service.py`、`login_retry.py`、`playwright_worker.py`、`application.py`、`container.py`、`websocket_manager.py`。
>
> 验证范围：启动链路、网络监控、登录执行、配置管理、定时任务、WebSocket 广播。

---

## P0 — 严重

### 1. 配置回滚时 `reload_fn()` 失败被静默忽略

**位置：** `app/services/config_service.py:112-126`

**代码：**

```python
ok, msg = reload_fn()
if not ok:
    config_logger.error("配置重载失败，正在回滚: {}", msg)
    try:
        profile_service.update(
            lambda data: _rollback_config(data, backup_data)
        )
        reload_fn()                                   # ← 第 119 行：返回值未被检查
    except Exception as rollback_exc:                  # ← reload_fn 返回 (bool, str)，不抛异常
        config_logger.error(
            "回滚失败（磁盘配置已回滚，运行时状态可能不一致）: {}",
            rollback_exc,
            exc_info=True,
        )
    return SaveResult(success=False, message=f"配置重载失败: {msg}")
```

**缺陷说明：**

第 119 行的 `reload_fn()`（即 `engine.reload_config()`）返回 `tuple[bool, str]`，正常执行不抛异常。当它返回 `(False, "重载超时")` 时：

- `try/except` 不会捕获（因为不抛异常）
- 返回值被丢弃，无人检查
- 磁盘已通过 `_rollback_config` 恢复，但引擎的 `_runtime_config` 和 `_ui_config` 可能处于失败状态
- 函数返回的报错信息是第一次失败的 `msg`，而非第二次回滚重载失败的真相

**影响：** 配置保存成功时状态正常，失败时磁盘和运行时可能静默不一致，用户看到的是已过时的错误消息。

**修复方向：** 检查第二次 `reload_fn()` 的返回值；如果也失败，在日志中明确记录两次失败。

---

### 2. `_run_login_then_exit`（login_once 模式）不记录登录历史

**位置：** `main.py:213-247`

**代码：**

```python
def _execute_login_with_retries(runtime_config: dict, logger) -> LoginResult:
    from app.workers.playwright_worker import CMD_LOGIN, get_worker

    ...
    result = get_worker().submit(
        CMD_LOGIN,
        data={"config": runtime_config},       # ← 直接向 Worker 提交，绕过 TaskExecutor
        timeout=120,
    )
```

**对比——正常路径的登录历史记录（`task_executor.py:295-352`）：**

```python
def execute_login(self, cancel_event, config_snapshot) -> tuple[bool, str]:
    ...
    if result.success:
        self._record_login_history(True, duration_ms)      # ← 记录成功
    else:
        self._record_login_history(False, duration_ms, error=error_msg)  # ← 记录失败
```

`_record_login_history()` 的四处调用全部在 `TaskExecutor.execute_login()` 内部（`:335/340/346/351`），`_execute_login_with_retries()` 完全绕过此路径。

**影响：** `--startup-action login_once` 模式的登录在登录历史页面中不可见。

**修复方向：** 将 `_execute_login_with_retries()` 改为复用 `TaskExecutor.execute_login_async()`，或在直接调用 Worker 后手动记录历史。

---

## P1 — 高

### 3. 自动登录路径缺少配置校验

**位置：** `app/services/engine.py:269-273` vs `engine.py:418-422`

**校验路径（手动登录入口，有校验）：**

```python
def _handle_login(self, cmd: EngineCommand) -> None:
    config = self._copy_runtime_config()
    if not config.get("username") or not config.get("password") or not config.get("auth_url"):
        cmd.response_data = (False, "登录配置不完整（请先设置认证地址、用户名和密码）")
        return
```

**无校验路径（自动登录入口，无校验）：**

```python
def _do_network_check(self) -> None:
    ...
    if result.get("need_login", False):
        self._login_retry.reset()
        self._configure_retry()
        self._do_async_login()                  # ← 直接提交，无任何配置校验
```

**影响：** 配置不完整时，`_do_async_login()` → `execute_login_async()` → `execute_login()` 会将空配置传递给 PlaywrightWorker，Worker 启动浏览器、创建页面，在步骤执行级才失败，浪费约 5-15 秒的资源。

**修复方向：** 在 `_do_async_login()` 或 `_do_network_check()` 中增加与 `_handle_login()` 一致的配置完整性检查。

---

### 4. 手动取消自动登录存在竞态窗口

**位置：** `app/services/engine.py:313-354`

**代码：**

```python
def _do_async_login(self, is_manual: bool = False, config_snapshot: dict | None = None) -> bool:
    if self._task_executor.is_login_running():
        if not is_manual:
            return False
        # 手动登录：取消卡住的自动登录，等待完成后重新提交
        self._task_executor.cancel_login()
        deadline = time.time() + 5
        while self._task_executor.is_login_running() and time.time() < deadline:
            time.sleep(0.1)
        if self._task_executor.is_login_running():
            logger.warning("取消当前登录超时，将尝试提交新登录")
    ...
    future = self._task_executor.execute_login_async(       # ← 无 cancel_event 参数
        config_snapshot=config_snapshot,
    )
```

**内部 `execute_login_async()` 的去重逻辑（`task_executor.py:190-197`）：**

```python
with self._login_lock:
    if self._login_future is not None and not self._login_future.done():
        logger.debug("登录任务已在执行中，跳过重复提交")
        return self._login_future           # ← 返回旧 Future，新登录不被提交
```

**缺陷说明：**

1. `cancel_login()` 是协作式取消，设置 `cancel_event` 但旧登录不一定立即停止
2. 5 秒等待超时后，调用 `execute_login_async()` 时不传 `cancel_event`
3. `execute_login_async()` 检测到旧 `_login_future` 未完成，返回旧 Future
4. 手动登录的 API 调用（`run_manual_login()`）实际在等待旧登录完成，而非新提交的登录

典型场景：自动登录正在执行 `page.goto()`（15 秒超时），用户点击手动登录。取消设置后 5 秒内旧登录未响应，手动登录显示"已提交"但实际阻塞在旧登录上，可能在 15 秒后才返回旧登录的失败结果。

**修复方向：** 向 `execute_login_async()` 传入新的 `cancel_event`，或延长等待时间使其与 Worker 操作超时匹配。

---

### 5. 网络检测每次重置重试计数器导致无限重试

**位置：** `app/services/engine.py:269-275`

**代码：**

```python
def _do_network_check(self) -> None:
    ...
    if result.get("need_login", False):
        self._login_retry.reset()             # ← count 归零
        self._configure_retry()
        self._do_async_login()                # → record_attempt() → count=1
    else:
        self._login_retry.reset()
```

**时序推演：**

```
T=0s  网络检测：need_login=True → reset(count=0) → configure → record_attempt(count=1) → 提交登录
T=5s  重试检查：need_retry? → count=1 < max_retries → 提交第二次登录 (count=2)
T=10s 重试检查：need_retry? → count=2 < max_retries → 提交第三次登录 (count=3)
T=15s 重试检查：count=3 >= max_retries → 停止
T=30s 网络检测：need_login=True → reset(count=0) → ... → 开始新一轮重试系列
T=60s 网络检测：need_login=True → reset(count=0) → ... → 又开始一轮
```

**影响：** 重试管理器在 `max_retries` 次后停止，但下一轮网络检测又将其重置。系统永不停机地循环"网络检测 → 重试系列 → 网络检测 → 重试系列"。这在网络不可恢复时（如认证服务器宕机）造成无意义的浏览器启动和登录尝试。

**修复方向：** 区分"网络状态变化（从正常到异常）触发快速重试"和"长期异常后降频检查"。不要在每次网络检测时无条件 `reset()`。

---

### 6. 启动时 `boot()` 早于 DashboardSink 注入

**位置：** `main.py:525-526`（`_run_full`）vs `app/container.py:124-131`（`start_web_services`）

**代码：**

```python
# main.py:525-526 — 在 _run_full 中调用
if should_boot_engine:
    container.engine.boot()       # → start_monitoring() → record_log("监控已启动")

# 稍后在 application.py lifespan 中...
# container.py:124-131 — 由 start_web_services() 调用
dashboard_sink = DashboardSink()
self._log_handler_id = logger.add(
    dashboard_sink.write,         # DashboardSink 在此处才注入到 loguru
    ...
)
self.engine.set_dashboard_sink(dashboard_sink)   # ← boot() 后才注入
```

**缺陷说明：**

- `_run_full()` 先调 `container.engine.boot()`，日志写入 loguru 但 DashboardSink 尚未注册
- `Uvicorn` 启动后，lifespan 调 `start_web_services()` 才注入 DashboardSink
- `boot()` 期间产生的日志被 DashboardSink 遗漏，不出现于前端面板

**修复方向：** 将 `boot()` 延迟到 lifespan 中 `start_web_services()` 之后调用，或交换调用顺序。

---

## P2 — 中

### 7. `_run_login_then_exit` 绕过引擎使用独立重试逻辑

**位置：** `main.py:195-247`

**指数退避代码：**

```python
def _execute_login_with_retries(runtime_config: dict, logger) -> LoginResult:
    ...
    retry_settings = runtime_config.get("retry_settings", {})
    raw = retry_settings.get("max_retries", 3)
    max_retries = max(1, min(raw, 10))
    retry_interval = int(retry_settings.get("retry_interval", 5))

    attempt = 0
    while True:
        attempt += 1
        if attempt > 1:
            delay = min(retry_interval * (2 ** (attempt - 2)), 300)   # ← 指数退避
            time.sleep(delay)

        result = get_worker().submit(CMD_LOGIN, data={"config": runtime_config}, timeout=120)
```

**对比——引擎内的 `LoginRetryManager`（`login_retry.py:41-58`）：**

```python
def need_retry(self, now: float) -> bool:
    if self.count == 0 or not self.config:
        return False
    max_retries, intervals = self.config
    if self.count >= max_retries:
        return False
    idx = self.count - 1
    if idx >= len(intervals):
        return False
    return now >= self.last_attempt + intervals[idx]
```

**差异：**

| 维度 | `_execute_login_with_retries` | `LoginRetryManager` |
|------|-------------------------------|---------------------|
| 重试间隔 | 指数退避 `min(interval × 2^(n-2), 300)` | 配置生成（等间隔或线性） |
| 超时 | 硬编码 120s | 不控制超时 |
| 登录历史 | 不记录 | 通过 `_record_login_history` 记录 |
| pure_mode 传递 | 通过 config 内部（有效） | 额外传 `data["pure_mode"]`（实际未被 Worker 使用） |

**修复方向：** 复用 `TaskExecutor.execute_login()` 以统一重试行为和登录历史记录。

---

### 8. 三处登录超时不统一

**位置：** `main.py:228` / `task_executor.py:329` / `engine.py:771`

**代码：**

```python
# main.py:225-228 — login_once 模式
result = get_worker().submit(
    CMD_LOGIN, data={"config": runtime_config},
    timeout=120,                          # ← 超时值 1：120 秒
)

# task_executor.py:321-329 — 正常登录路径
result = worker.submit(
    CMD_LOGIN, data={...},
    wait=True,
    timeout=300,                          # ← 超时值 2：300 秒（硬编码）
)

# engine.py:770-772 — 手动登录 API 等待
login_timeout = self._ui_config.login_timeout    # ← 超时值 3：用户可配（默认 90 秒）
cmd.response_event.wait(timeout=login_timeout)   # ← 这是 API 等待超时，非 Worker 超时
```

**影响：** 用户通过 UI 配置的 `login_timeout` 只控制 API 层收到 HTTP 响应的等待时间，不影响 Worker 层 `playwright_worker` 执行登录的实际超时。即使将 `login_timeout` 设为 600，Worker 层仍然在 300 秒后就停止等待。

**修复方向：** 让 `execute_login()` 的 `timeout` 参数也使用 `login_timeout` 配置值，确保 API 超时和 Worker 超时一致。

---

### 9. 定时任务无去重保护

**位置：** `app/services/task_executor.py:157-166`

**代码：**

```python
def execute_task_async(self, task_id: str) -> Future:
    return self._ensure_task_pool().submit(self.execute_task, task_id)
    #                                  ^^^^^^^ 直接提交，无 task_id 去重
```

**场景：** 若一个每 5 分钟执行的任务因网络延迟超过 5 分钟，`_run_schedule_tick()` 在下一个分钟点发现该任务再次到期，会再次调用 `execute_task_async()`，提交第二个实例。`BoundedExecutor` 的 Semaphore 限制总队列深度，但不防同一任务的重复。

**修复方向：** 提交前检查该 task_id 是否已有 pending 的 Future。

---

### 10. 定时浏览器任务与登录争抢 PlaywrightWorker 队列

**位置：** `app/services/task_executor.py:394-408`

**代码：**

```python
def _execute_browser(self, task_id: str, timeout: int) -> tuple[bool, str]:
    ...
    from app.workers.playwright_worker import CMD_LOGIN

    config = self._get_runtime_config() if self._get_runtime_config else {}
    worker = self._worker_getter()
    result = worker.submit(
        CMD_LOGIN,                    # ← 与登录使用同一命令类型
        data={"config": config, ...},
        wait=True,
        timeout=timeout,
    )
```

**对比——登录路径（`task_executor.py:320-329`）：**

```python
worker = self._worker_getter()
result = worker.submit(
    CMD_LOGIN,                        # ← 同一命令
    data={"config": config, "cancel_event": cancel_event},
    wait=True,
    timeout=300,
)
```

**缺陷说明：**

两条路径都使用 `CMD_LOGIN` 命令 + `worker.submit(wait=True)`，在 PlaywrightWorker 的串行命令队列中竞争。区别：
- 登录路径传 `cancel_event`，支持取消
- 浏览器任务路径不传 `cancel_event`，不支持取消

如果登录正在运行一个超长任务（如慢速网络登录），定时浏览器任务排队等待；反之，如果定时浏览器任务在慢速页面中执行，自动登录也被阻塞。

**修复方向：** 为定时浏览器任务使用独立的命令类型（如 `CMD_BROWSER_TASK`），并考虑是否应支持超时抢占。

---

### 11. `_link_cancel_event` 产生无界守护线程

**位置：** `app/services/task_executor.py:210-222`

**代码：**

```python
@staticmethod
def _link_cancel_event(
    new_event: threading.Event, target_event: threading.Event
) -> None:
    def _watcher() -> None:
        new_event.wait(timeout=300)        # 最多等 5 分钟
        if new_event.is_set():
            target_event.set()

    t = threading.Thread(target=_watcher, daemon=True, name="cancel-link")
    t.start()                              # ← 每次去重调用都新建线程
```

**调用点（`:195-196`）：**

```python
if cancel_event is not None and self._login_cancel_event is not None:
    self._link_cancel_event(cancel_event, self._login_cancel_event)
```

**影响：** 每个未传入 `cancel_event` 的去重请求（或传入但非 None）创建一条守护线程，300 秒超时后退出。在短时间内触发大量重复登录请求时累积。

**修复方向：** 使用单个 watcher 线程或 `threading.Timer` 替代每次都 `start()`。

---

## P3 — 低

### 12. 轻量模式广播队列容量仅 10

**位置：** `app/services/engine.py:118`、`:587-591`

**代码：**

```python
# 轻量模式下的空广播队列（仅接收不消费，小容量即可）
self._empty_broadcast_queue: deque = deque(maxlen=10)

@property
def ws_broadcast_queue(self) -> deque:
    if self._dashboard_sink is None:
        return self._empty_broadcast_queue    # ← 轻量模式下使用此队列
    return self._dashboard_sink.broadcast_queue
```

**影响：** 轻量模式运行时，状态更新追加到 `_empty_broadcast_queue`（maxlen=10），无 drain 循环消费，满 10 条后旧消息被丢弃。当通过系统托盘唤醒 WebUI 时，`start_web_services()` 注入新的 DashboardSink，但旧队列内容不迁移。新打开的 Web 页面看不到之前的状态历史。

**修复方向：** 在 `set_dashboard_sink()` 时将 `_empty_broadcast_queue` 中的残留消息迁移到新队列。

---

### 13. WebSocket 广播无总超时

**位置：** `app/services/websocket_manager.py:52-71`

**代码：**

```python
async def broadcast(self, message: str):
    async with self._lock:
        connections = self._connections.copy()

    if not connections:
        return

    tasks = [self._send_safe(ws, message) for ws in connections]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    #                                    ^^^^^^^^^^^^^^^^^^^^^^^^ 无总体超时

async def _send_safe(self, ws: WebSocket, message: str):
    try:
        await asyncio.wait_for(ws.send_text(message), timeout=5.0)
    except TimeoutError:
        ...                                  # 单个有 5s 超时，但 gather 本身无超时
```

**影响：** `asyncio.gather` 无 `timeout` 参数。如果有 N 个连接同时卡住，drain 循环最多等待 N × 5 秒。对本地桌面应用（127.0.0.1，通常 1-2 连接）无实际影响。

**修复方向：** 在 `asyncio.gather` 上增加 `timeout=5.0` 总体超时。

---

## 修正后优先级分布

```
P0  2 个  │ 1. 配置回滚静默失败          2. login_once 丢失登录历史
P1  4 个  │ 3. 自动登录缺失校验          4. 手动取消竞态窗口
          │ 5. 重试计数器无限循环        6. boot 早于 DashboardSink
P2  5 个  │ 7. login_once 独立重试机制    8. 三处超时不统一
          │ 9. 定时任务无去重            10. Worker 队列竞争
          │ 11. link_cancel 线程泄漏
P3  2 个  │ 12. 轻量广播队列容量 10      13. WS 无总体超时
```

---

## 原报告中已被驳回的问题

| 原问题 | 原定级 | 驳回原因 |
|--------|--------|----------|
| 定时浏览器任务通过 `is_login_running()` 阻塞登录 | P0 | `is_login_running()` 检查 `_login_future`，浏览器任务不走该路径，不设该字段（`task_executor.py:224-227`）。实际为 Worker 队列竞争（P2#10） |
| 网络检测与登录重试在同一轮循环同时触发 | P2 | 使用同一 `now` 变量比较，`need_retry()` 必然返回 False（`login_retry.py:58`） |
| 启动阶段双重 `boot()` 调用 | P1 | Lifespan 中 `existing_container` 分支不调 `boot()`。子问题（日志丢失）真实存在（P1#6） |
| `_rollback_config` 使用 `model_fields` 可能不同步 | P2 | Pydantic v2 自动生成全部字段，无遗漏风险（`schemas.py:437-440`） |
| `_run_login_then_exit` 丢失 pure_mode | 新增 | Worker 从 `config["browser_settings"]["pure_mode"]` 读取，两路径都正确构造，无丢失 |

---

*报告生成日期：2026-06-20*
*验证方法：三轮独立代码审查，覆盖全部 13 个源文件，逐行溯源确认*
