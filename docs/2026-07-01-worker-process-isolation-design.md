# Worker 进程隔离与重试策略修复设计

- 日期：2026-07-01
- 状态：已批准（待规格审核）
- 适用范围：完整模式（WebUI 常驻）下的内存优化，附带监控模式重试策略 bug 修复

## 1. 背景与动机

### 1.1 现状

软件在完整模式下常态占用约 60MB 内存。架构为单 Python 进程承载全部职责：FastAPI/Uvicorn、ScheduleEngine（监控+定时任务，Actor 模型线程）、PlaywrightWorker（独立 asyncio 线程）、SystemTray（pystray 线程）、ServiceContainer 内全套服务。

PlaywrightWorker 当前是主进程内的 daemon 线程 + asyncio 事件循环，所有 Playwright 操作限制在该线程内。消费方（login_orchestrator / task_executor / debug_service / utils.browser / container）全部通过 `PlaywrightWorker.submit(cmd_type, data, wait, timeout) -> WorkerResponse` 这一个 API 调用。

### 1.2 核心问题：ddddocr native 扩展不可卸载

`OcrHandler._get_ocr()` 延迟 `import ddddocr`，并有 5 分钟空闲后 `del` 实例 + `gc.collect()` 的清理逻辑。但 CPython 无法卸载已导入的模块：

- `del` 只释放 `DdddOcr()` 实例（ONNX session）
- `ddddocr` 模块本身、`onnxruntime` 原生扩展（.pyd，约 30-50MB）、Pillow/numpy/opencv-helper 等依赖一旦 `import` 就永久驻留在 `sys.modules` 中，直到进程退出
- 现有清理逻辑只回收了「模型实例」，没回收「模块/native 扩展」的内存——OCR 一旦用过一次，进程内存地板就被永久抬高

### 1.3 附带发现的重试策略 bug

在设计过程中发现三个已存在的功能 bug：

1. **监控模式重试间隔不生效**：`MonitoredPolicy._DELAYS` 硬编码 `[5, 10, 20, 60, 100]`，用户配置的 `retry_interval` 在监控模式完全不生效。仅 login_once 路径使用了 `retry_interval`。
2. **`max_retries=0` 不可达**：`retry_policy.py` 和 `login_runner.py` 都有 `max(1, max_retries)` 强制至少 1 次重试。
3. **前后端范围不一致**（违反 project_memory 硬约束）：后端 `max_retries: ge=0, le=10`，前端 `min="1" max="5"`。

## 2. 目标

### 2.1 主目标

- 主进程内存地板从 ~60MB 降到 ~30-35MB
- OCR 触发后内存**真正回落**（不停留在抬高的地板）
- 主进程永远不 import `playwright` / `ddddocr` / `onnxruntime`

### 2.2 附带目标

- 修复监控模式 `retry_interval` 不生效 bug
- 修复 `max_retries=0` 不可达 bug
- 修复前后端 `max_retries` 范围不一致
- 简化 `OcrHandler` 清理逻辑（删除定时器机制）
- 调试会话在 worker 重启后有准确的状态提示

### 2.3 非目标

- 不重构 Worker 内部抽象（`LoginAttemptHandler` / `BrowserContextManager` / `_handle_*` 全部保留原样）
- 不改造脚本/shell 任务（已是 subprocess 隔离）
- 不做主进程常驻依赖瘦身（httpx/cryptography 等延迟导入收益小，留作未来 follow-up）
- 不引入 Go/Rust 原生守护进程

## 3. 架构设计

### 3.1 进程拓扑

```
┌── 主进程（Python，常驻，目标 30-35MB）──────────────┐
│  FastAPI / Uvicorn / Engine / Scheduler / Tray       │
│  ServiceContainer 全部服务实例                       │
│  PlaywrightWorkerProxy（不 import playwright）       │
│    ├─ subprocess.Popen(worker_proc)                  │
│    ├─ stdin 写 JSON 命令                             │
│    ├─ 读线程：stdout 按行解析 → id→Future 派发       │
│    └─ watchdog：PING 心跳 + EOF 检测 → 自动重启      │
└────────────────────┬─────────────────────────────────┘
                     │ stdin  (JSON 请求)
                     │ stdout (JSON 响应)
                     │ stderr (loguru → 文件)
┌────────────────────▼─────────────────────────────────┐
│ Worker 子进程（Python，按需启动，闲置回收）          │
│  app.workers.worker_proc.main()                      │
│    ├─ PlaywrightWorker 实现（原 _async_run 保留）    │
│    ├─ Playwright + ddddocr + onnxruntime（仅本进程） │
│    └─ stdin 读循环 → _dispatch → stdout 写响应       │
│  浏览器子进程（Chromium，由 Playwright 自管）        │
│  内存：闲置 ~40MB，OCR 期尖峰 ~120MB，退出即归还 OS  │
└──────────────────────────────────────────────────────┘
```

### 3.2 IPC 协议

借鉴 LSP（rust-analyzer / gopls / Claude Desktop）风格：子进程是独立可执行入口，stdin 读命令、stdout 写响应、stderr 走日志。

**帧格式**：行分隔 JSON。

**请求（父→子，stdin）**：
```json
{"id": 1, "cmd": "login", "data": {"config": {...}}}
```

**响应（子→父，stdout）**：
```json
{"id": 1, "ok": true, "data": "登录成功"}
{"id": 1, "ok": false, "error": "超时"}
```

**事件（子→父，stdout，无对应请求）**：
```json
{"event": "ready"}
{"event": "shutdown", "reason": "idle_timeout"}
```

**取消**：
```json
{"id": 2, "cmd": "cancel", "data": {"cmd_id": 1}}
```

**心跳**：
```json
{"id": 3, "cmd": "ping"} → {"id": 3, "ok": true}
```

### 3.3 协议模型（Pydantic）

符合 project_memory 约定「API endpoints 应使用 Pydantic 模型进行请求/响应验证」。定义在 `app/workers/worker_protocol.py`：

- `WorkerRequest`：`id: int`, `cmd: str`, `data: dict`
- `WorkerResponse`：`id: int`, `ok: bool`, `data: Any | None`, `error: str | None`
- `WorkerEvent`：`event: str`, `reason: str | None`
- 命令常量：`CMD_LOGIN`, `CMD_CANCEL`, `CMD_PING`, `CMD_DEBUG_START`, `CMD_DEBUG_STEP`, `CMD_DEBUG_STOP`, `CMD_BROWSER_ACQUIRE`, `CMD_BROWSER_RELEASE`, `CMD_BROWSER_CLOSE`, `CMD_BROWSER_HEALTH_CHECK`, `CMD_SHUTDOWN`

### 3.4 关键设计决策

1. **IPC 选型**：stdin/stdout JSON-RPC 而非 `multiprocessing.Pipe`。理由：`multiprocessing.spawn`（Windows 必 spawn）会重新执行父模块顶层代码，副作用难控；stdin/stdout 方案子进程是独立可执行入口，可 `python -m app.workers.worker_proc` 独立调试，协议文本可日志记录，stdout EOF 即时表示死亡。

2. **取消机制重构**：原 `cancel_event` 是 `threading.Event`，不可跨进程序列化。改为：子进程维护 `current_cancel_events: dict[cmd_id, threading.Event]`，父进程发 `CMD_CANCEL` 时 set 对应 id 的事件。`login_orchestrator._dispatch()` 改为「先 submit LOGIN 拿到 cmd_id，再 submit CANCEL 传 cmd_id」。

3. **Worker 内部抽象不重构**：`LoginAttemptHandler` / `BrowserContextManager` / `_handle_*` 全部保留原样——它们都在子进程内执行，原样复用是优势而非负担。`BrowserContextManager` 内部 `from app.workers.playwright_worker import get_worker` 在子进程内返回真正的实现单例，调用链零改动。

4. **进程角色区分**：通过环境变量 `CAMPUS_AUTH_ROLE` 标记。主进程不设置（或设为 `main`），子进程设为 `worker`。`get_worker()` 在主进程返回 `PlaywrightWorkerProxy` 实例，在子进程返回真正的 `PlaywrightWorker` 单例。

5. **日志隔离**：子进程 loguru handler 只写 stderr（被父进程捕获转发到主日志）或直接写日志文件，**绝不污染 stdout**（stdout 是协议流）。

## 4. 生命周期与状态机

### 4.1 Worker 进程状态机

```
        ┌───────────┐
        │  STOPPED  │ ← 初始 / 退出后
        └─────┬─────┘
              │ submit() 首次调用
              ▼
        ┌───────────┐
        │ STARTING  │ ── Popen ── 等待 ready 事件
        └─────┬─────┘
              │ 收到 {"event":"ready"}
              ▼
        ┌───────────┐    submit     ┌─────────┐
        │   IDLE    │ ────────────▶ │  BUSY   │
        │ (0 活跃)  │◀── 响应回 ─── │ (≥1)    │
        └─────┬─────┘               └────┬────┘
              │ keepalive 定时器判定:    │ CMD_SHUTDOWN
              │  - 活跃=0              │ 或 stop()
              │  - now-last_active≥180s│
              │  - engine.can_shutdown()│
              ▼                        ▼
        ┌───────────┐             ┌──────────┐
        │  STOPPED  │             │ STOPPING │
        │ (主动杀)  │             │ kill+join│
        └───────────┘             └────┬─────┘
                                       ▼
                                 ┌───────────┐
                                 │  STOPPED  │
                                 └───────────┘
```

### 4.2 状态转换语义

| 转换 | 触发 | 代理层动作 |
|---|---|---|
| STOPPED → STARTING | 首次 submit 或代理被标记 dead | Popen 启动；读线程开始；写 stdin 不阻塞（有 buffer） |
| STARTING → IDLE | 收到子进程 `{"event":"ready"}` | 唤醒所有等待 submit 的协程 |
| IDLE → BUSY | submit 写入 CMD | id 计数 +1，注册 id→Future |
| BUSY → IDLE | 响应回到达，活跃计数归 0 | 重置 idle_since 时间戳 |
| IDLE → STOPPED | keepalive 判定可关闭 | 写 CMD_SHUTDOWN → wait 5s → kill → join |
| BUSY/IDLE → STOPPING | 父进程 `stop()` 或容器 shutdown | 写 CMD_SHUTDOWN → wait 5s → kill → join |
| 任意 → STOPPED | 读线程 EOF（崩溃） | 标记 dead；未完成 Future 全部置 `WorkerResponse(success=False, error="worker 崩溃")`；触发 `on_restart` |

### 4.3 idle 判定在主进程（非子进程）

**核心约束**：idle 判定由主进程代理层负责，子进程只响应 CMD_SHUTDOWN。

**理由**：主进程是唯一拥有全局调度知识的实体（engine 知道 retry_time / next_network_check，scheduler 知道 next_tick）。子进程自杀需要协议复杂化（shutdown 事件、EOF 兜底），主进程主动杀更简单且语义清晰。

### 4.4 `engine.can_shutdown_worker()` 新增方法

```python
def can_shutdown_worker(self) -> bool:
    """判断当前是否可以安全关闭 Worker 子进程。

    返回 False 的场景：有待执行重试、或短期内需要网络检测/定时任务。
    """
    # 监控未运行：可杀
    if not self._is_monitoring:
        return True
    # 有待执行重试：不可杀
    with self._retry_time_lock:
        if self._next_retry_time > 0:
            return False
    # 下次网络检测在 IDLE_TIMEOUT 内：不可杀（很快要用）
    if self._next_network_check - time.time() < WORKER_IDLE_TIMEOUT:
        return False
    # 定时任务即将触发：不可杀
    if self._scheduler and self._scheduler.running:
        if self._scheduler.next_tick_time - time.time() < WORKER_IDLE_TIMEOUT:
            return False
    return True
```

### 4.5 Keepalive 定时器（主进程代理层）

```python
async def _keepalive_loop(self):
    """每 30s 检查一次是否可以关闭 Worker。"""
    while not self._stop_event.is_set():
        await asyncio.sleep(KEEPALIVE_CHECK_INTERVAL)
        if self._active_count == 0:  # 无活跃命令
            last_active_age = time.time() - self._last_active_ts
            if last_active_age >= WORKER_IDLE_TIMEOUT:
                if self._engine.can_shutdown_worker():
                    await self._graceful_shutdown()
                    return
                # engine 说不能杀，重置 last_active_ts 给下一个周期
                self._last_active_ts = time.time()
```

**重置 `last_active_ts` 的妙处**：engine 拒绝关闭时，代理层不立即杀，而是再等一个 IDLE_TIMEOUT 周期。这样重试期间（`_next_retry_time > 0`）代理层每 30s 检查一次都被拒绝，直到重试用尽（`_next_retry_time` 归零）才放行。

### 4.6 心跳检测（僵死兜底）

父进程每 30s 发 PING，3 次超时（90s）判定僵死 → kill + 重启。捕获「进程活着但 asyncio 卡死」场景。EOF 检测是常态（含自杀和崩溃），心跳只用于僵死兜底。

### 4.7 配置参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `WORKER_IDLE_TIMEOUT` | 180s | 主进程判定空闲阈值（3 分钟） |
| `PING_INTERVAL` | 30s | 僵死检测心跳间隔 |
| `PING_MAX_MISS` | 3 | 心跳超时次数（90s） |
| `SHUTDOWN_GRACE` | 5s | 优雅退出等待 |
| `STARTUP_TIMEOUT` | 30s | 等待 ready 事件 |
| `KEEPALIVE_CHECK_INTERVAL` | 30s | keepalive 定时器周期 |

所有参数均在主进程代理层常驻，子进程不持有任何 idle/keepalive 配置（idle 判定由主进程负责，子进程只响应 CMD_SHUTDOWN）。子进程启动后通过首条 `{"cmd":"init","data":{"project_root":"..."}}` 消息接收项目根路径等必要运行时信息。

### 4.8 各场景验证

| 场景 | 行为 |
|---|---|
| 连续重试（retry_interval=5s） | 每次 submit 重置 `last_active_ts`，keepalive 永远判定非空闲 → worker 持续存活 |
| 大间隔重试（retry_interval=200s） | 重试期间 `_next_retry_time > 0` → `can_shutdown` 返回 False → 代理层重置 `last_active_ts` → worker 保活到重试触发 |
| 重试用尽→下次网络检测 300s | 重试结束后 `_next_retry_time=0`，180s 后 `can_shutdown` 返回 True（若 next_network_check 在 180s 内则保活，否则杀） |
| 监控停止 | `_is_monitoring=False` → `can_shutdown=True` → 180s 后杀 |
| 定时任务即将触发 | `next_tick_time - now < 180s` → `can_shutdown=False` → 保活 |

## 5. 自定义任务相关优化

### 5.1 任务执行路径梳理

| 任务类型 | 当前执行位置 | 是否污染主进程内存 | 改造后 |
|---|---|---|---|
| 登录（CMD_LOGIN） | worker 线程 → LoginAttemptHandler | 是 | 自动进入子进程，零改动 |
| 浏览器定时任务（`_execute_browser`） | login_orchestrator → worker.submit | 是 | 自动进入子进程，零改动 |
| 调试任务（CMD_DEBUG_*） | worker 线程 → TaskExecutor | 是 | 自动进入子进程，零改动 |
| 脚本任务（`_execute_script`） | 主进程线程池 → `subprocess.run` | 否 | 不动 |
| Shell 任务（`_execute_shell`） | 主进程线程池 → subprocess | 否 | 不动 |
| 登录内的脚本子任务（`_execute_script_task`） | worker 线程内 ScriptRunner | 否 | 自动进入子进程（脚本本身仍 subprocess） |

**关键发现**：登录 / 浏览器 / 调试这三类已经全部走 `worker.submit`——worker 进程化后它们自动进入子进程，零改动。

### 5.2 优化 1：移除 OcrHandler 的 5 分钟空闲定时清理

当前 `OcrHandler` 维护 `_ocr_instances` 字典 + `_cleanup_timers` 字典 + `_ocr_lock` + 5min Timer，逻辑复杂。这些代码是为了在单进程内「尽量回收 OCR 模型实例」而存在——但 native 扩展（onnxruntime.pyd）本就卸不掉，定时清理只回收了 Python 实例对象，省不了多少。

worker 进程化后：**子进程闲置自杀 = OCR 模型 + native 扩展全部归还 OS**，比 Timer 清理彻底得多。

**改造**：删除 `schedule_cleanup` / `_cancel_cleanup` / `_do_cleanup` / `_cleanup_timers` / `_IDLE_TIMEOUT`，OcrHandler 退化为简单的「按需 import + 缓存实例」。代码量减少 ~40 行，复杂度下降。

### 5.3 优化 2：调试会话跨进程状态一致性

**核心挑战**：调试会话是多次 submit 的有状态序列（`CMD_DEBUG_START → CMD_DEBUG_STEP × N → CMD_DEBUG_STOP`），子进程内缓存 `debug_page` + `debug_executor`。worker 自杀会导致状态丢失，破坏调试流程。

**三处必须处理的问题**：

1. **调试期间 worker 不能被 keepalive 杀**：调试会话预期持续 30 分钟（`_debug_timeout_watcher` 默认 1800s），远大于 `WORKER_IDLE_TIMEOUT=180s`。step 之间的空闲间隙会被 keepalive 误判。
2. **worker 自杀后 `_close_debug_browser` 会白启动新子进程**：当前 `submit(CMD_DEBUG_STOP)` 在 worker dead 时自动重启，但新子进程没有 debug_page，CMD_DEBUG_STOP 是无意义操作。
3. **`run_all` 循环中 worker 自杀的并发 race**：单步执行耗时长时，keepalive 在期间判定活跃=0 触发自杀。

**改造方案**：

#### 5.3.1 代理层新增 keepalive 锁（引用计数）

```python
class PlaywrightWorkerProxy:
    def __init__(self):
        self._keepalive_lock_count = 0
        self._keepalive_lock = threading.Lock()
    
    def acquire_keepalive_lock(self):
        """调试/长任务期间锁定，keepalive 不再判定可关闭。"""
        with self._keepalive_lock:
            self._keepalive_lock_count += 1
    
    def release_keepalive_lock(self):
        with self._keepalive_lock:
            self._keepalive_lock_count = max(0, self._keepalive_lock_count - 1)
    
    def is_alive(self) -> bool:
        """子进程是否存活（供调用方判断状态是否还有效）。"""
        return self._proc is not None and self._proc.poll() is None
```

`_keepalive_loop` 增加判断：

```python
async def _keepalive_loop(self):
    while not self._stop_event.is_set():
        await asyncio.sleep(KEEPALIVE_CHECK_INTERVAL)
        if self._active_count == 0 and self._keepalive_lock_count == 0:
            # 仅在无活跃命令且无 keepalive 锁时才判定 idle
            ...
```

#### 5.3.2 DebugSessionManager 在 start 时 acquire，stop/close/on_restart 时 release

```python
async def start(self, ...):
    ...
    get_worker().acquire_keepalive_lock()  # 调试期间锁定 worker
    try:
        response = await asyncio.to_thread(
            lambda: get_worker().submit(CMD_DEBUG_START, data=worker_data)
        )
    except:
        get_worker().release_keepalive_lock()
        raise
    if not response.success:
        get_worker().release_keepalive_lock()
        ...
    ...

async def stop(self) -> dict:
    async with self._exec_sem, self._lock:
        await self._cancel_debug_timer()
        if self._session._browser_active:
            await self._close_debug_browser()
        get_worker().release_keepalive_lock()
        self._session = DebugSession()
    ...
```

#### 5.3.3 `on_restart` 回调兜底 release

```python
def _on_worker_restart(self):
    """worker 重启回调（在代理读线程中调用）。"""
    if self._session._browser_active:
        get_worker().release_keepalive_lock()
    self._session = DebugSession()
```

并发安全：`on_restart` 在代理读线程触发，`acquire/release` 在 asyncio 线程触发。两者都受 `_keepalive_lock` 保护，线程安全。

#### 5.3.4 `_close_debug_browser` 容错（避免白启动）

```python
async def _close_debug_browser(self) -> None:
    worker = get_worker()
    # 仅在 worker 存活时才发送 CMD_DEBUG_STOP，避免白启动新子进程
    if not worker.is_alive():
        debug_logger.debug("worker 已不存活，跳过 CMD_DEBUG_STOP")
        self._session._browser_active = False
        return
    try:
        await asyncio.to_thread(
            lambda: worker.submit(CMD_DEBUG_STOP, timeout=10)
        )
    except Exception:
        debug_logger.warning("关闭调试会话失败: Worker 提交失败", exc_info=True)
    self._session._browser_active = False
```

#### 5.3.5 代理层暴露 `is_alive()` 方法

`PlaywrightWorkerProxy.is_alive()` 返回子进程是否存活。供 `_close_debug_browser` 短路判断，避免在 worker 已死时自动重启并发无意义的 CMD_DEBUG_STOP。

### 5.4 不做的优化

ScriptRunner 的 binary 检测缓存（YAGNI）——PATH 扫描本就快，与本次内存优化目标无关。

## 6. 重试策略修复

### 6.1 MonitoredPolicy 改造

```python
class MonitoredPolicy:
    """监控重试策略 — 固定间隔，使用用户配置的 retry_interval。"""

    def __init__(self, max_retries: int = 3, retry_interval: int = 5) -> None:
        self.max_retries = max(0, max_retries)  # 允许 0=不重试
        self.retry_interval = max(1, retry_interval)
        self._attempt: int = 0
        self._prev_network_ok: bool | None = None
        self._lock = threading.Lock()

    @property
    def retries_exhausted(self) -> bool:
        return self._attempt >= self.max_retries

    def delay_before(self, attempt: int) -> float:
        return float(self.retry_interval)  # 固定间隔

    def on_login_done(self, success: bool) -> float | None:
        with self._lock:
            if success:
                self._attempt = 0
                return None
            self._attempt += 1
            if self._attempt >= self.max_retries:
                return None  # 用尽，停止重试
            return self.delay_before(self._attempt)
```

**关键变化**：
- 删除 `_DELAYS` 硬编码表
- 构造函数接收 `retry_interval`（由 engine 从 RuntimeConfig 注入）
- `max_retries=0` 时 `retries_exhausted` 立即 True，`on_login_done` 返回 None → 永不重试

### 6.2 engine.py 注入点

[engine.py#L374](file:///e:/Campus-Auth/app/services/engine.py#L374) 当前 `self._retry_policy = MonitoredPolicy()` 改为：

```python
self._retry_policy = MonitoredPolicy(
    max_retries=self._runtime_config.retry.max_retries,
    retry_interval=self._runtime_config.retry.retry_interval,
)
```

`_reload_config_internal()` 重载配置时同步更新 retry_policy 参数（新增 `_sync_retry_policy()` 私有方法）。

### 6.3 login_runner.py 改造

```python
max_retries = max(0, min(runtime_config.retry.max_retries, 10))
interval = max(1, runtime_config.retry.retry_interval)

if max_retries == 0:
    # 不重试：只执行一次，失败即返回
    handle = orchestrator.submit(source="login_once", config=runtime_config)
    ok, msg = handle.result()
    if ok:
        cleanup_orphan_browsers()
        return LoginResult.SUCCESS
    return LoginResult.TEMPORARY_FAILURE

for attempt in range(1, max_retries + 1):
    if attempt > 1:
        time.sleep(interval)
    # ... 原逻辑
```

### 6.4 前端文案修订

`settings-monitor.html` 中：

- `max_retries` input：`min="1" max="5"` → `min="0" max="10"`
- `max_retries` data-tip：改为「登录失败后最多重试几次，0 表示不重试。超出后等待下次网络检测周期再试。」
- `retry_interval` data-tip：改为「登录失败后每次重试的固定等待秒数。」
- `retry_interval` input：`min="1" max="300"` 不变

## 7. 改造影响面与文件清单

### 7.1 新增文件（3 个）

| 文件 | 职责 |
|---|---|
| `app/workers/worker_protocol.py` | Pydantic 协议模型：`WorkerRequest` / `WorkerResponse` / `WorkerEvent`，及命令常量 |
| `app/workers/worker_proxy.py` | `PlaywrightWorkerProxy`：Popen 管理、stdin 写、stdout 读线程、id→Future 派发、keepalive、心跳、`on_restart` 回调注册、`acquire/release_keepalive_lock` 引用计数、`is_alive()` 查询 |
| `app/workers/worker_proc.py` | 子进程入口 `main()`：stdin 读循环 → `_dispatch` → stdout 写响应；`python -m app.workers.worker_proc` 可独立运行调试 |

### 7.2 修改文件（9 个）

| 文件 | 改动 |
|---|---|
| `app/workers/playwright_worker.py` | 保留 `PlaywrightWorker` 类（子进程内实现）；`get_worker()` 在主进程返回 `PlaywrightWorkerProxy` 实例，在子进程返回真正实现。用 `CAMPUS_AUTH_ROLE` 环境变量区分进程角色 |
| `app/services/engine.py` | 新增 `can_shutdown_worker() -> bool`；`_reload_config_internal` 重载时同步更新 retry_policy 参数 |
| `app/services/retry_policy.py` | 删除 `_DELAYS` 硬编码表；构造函数接收 `retry_interval`；`delay_before()` 返回 `retry_interval`；`max_retries=0` 直接生效（删除 `max(1, ...)`） |
| `app/services/login_runner.py` | 删除 `max(1, ...)`，允许 `max_retries=0`（直接 return TEMPORARY_FAILURE） |
| `app/services/debug_service.py` | 启动时注册 `worker.on_restart()` 回调（兜底 release keepalive 锁 + 重置 `_session`）；`start` 时 `acquire_keepalive_lock()`，`stop`/`close`/失败路径时 `release_keepalive_lock()`；`_close_debug_browser` 增加 `is_alive()` 短路判断避免白启动新子进程 |
| `app/tasks/step_handlers.py` | `OcrHandler`：删除 `schedule_cleanup` / `_cancel_cleanup` / `_do_cleanup` / `_cleanup_timers` / `_IDLE_TIMEOUT`（~40 行） |
| `app/services/login_orchestrator.py` | `_dispatch()` 取消机制：`cancel_event` 不再通过 `data` 传递，改为 submit LOGIN 后拿 cmd_id，再 submit CMD_CANCEL(cmd_id) |
| `app/container.py` | `_get_worker()` 仍返回 `get_worker()`；新增将 `engine` 引用注入 worker proxy（用于 `can_shutdown_worker`） |
| `frontend/partials/pages/settings/settings-monitor.html` | `max_retries`：`min="1" max="5"` → `min="0" max="10"`；重试间隔提示文案更新为「固定间隔」 |

### 7.3 不动的文件（关键）

- `app/utils/browser.py`（BrowserContextManager 在子进程内运行，原样复用）
- `app/services/login_handler.py`（在子进程内运行，原样复用）
- `app/services/task_executor.py`（消费方，submit API 不变）
- `app/services/scheduler_service.py`（无关）
- `app/workers/script_runner.py`（已是 subprocess，无关）

### 7.4 调用链变化对照

```
旧：API → orchestrator._dispatch → worker.submit(CMD_LOGIN, data={cancel_event})
                                          ↓
                                    主进程线程 → _handle_login

新：API → orchestrator._dispatch → proxy.submit(CMD_LOGIN, data={})
                                          ↓
                                    stdin JSON → 子进程 _handle_login
    （取消）→ proxy.submit(CMD_CANCEL, data={cmd_id: N})
```

## 8. 测试策略

### 8.1 单元测试（新增）

| 测试文件 | 覆盖点 |
|---|---|
| `tests/test_workers/test_worker_protocol.py` | 协议模型序列化/反序列化、id 分配、命令常量 |
| `tests/test_workers/test_worker_proxy.py` | 代理状态机转换、id→Future 派发、EOF 检测、keepalive 判定、keepalive 锁引用计数、`is_alive()`、on_restart 回调 |
| `tests/test_workers/test_worker_proc.py` | 子进程入口独立运行（`python -m app.workers.worker_proc` 喂 JSON 验证） |
| `tests/test_services/test_retry_policy.py` | `max_retries=0` 永不重试、`retry_interval` 生效、`retries_exhausted` 边界 |

### 8.2 集成测试（修订）

| 测试文件 | 改动 |
|---|---|
| `tests/test_integration/test_login_flow.py` | 验证登录走子进程、OCR 后子进程自杀、内存回落 |
| `tests/test_services/test_engine.py` | 新增 `can_shutdown_worker()` 各场景测试（监控中/重试中/定时任务临近） |
| `tests/test_services/test_debug_session_manager.py` | 新增 worker 重启后会话重置测试、keepalive 锁 acquire/release 配对测试、`_close_debug_browser` 在 worker dead 时短路测试、调试期间 worker 不被 keepalive 杀测试 |

### 8.3 手动验证清单

1. 启动完整模式，主进程内存 < 35MB（任务管理器观察）
2. 触发 OCR 登录，观察子进程内存尖峰 ~120MB
3. OCR 后 3 分钟无操作，子进程自杀，主进程内存回落
4. 大间隔重试（retry_interval=200s）期间 worker 不被杀
5. max_retries=0 时登录失败立即返回，不重试
6. 前端设置 max_retries=10 能保存且生效
7. 调试会话期间 worker 崩溃 → 用户得到「会话已失效」提示
8. 调试会话持续 30 分钟期间 worker 不被 keepalive 杀（keepalive 锁生效）
9. 调试会话正常 stop 后，worker 恢复可被 keepalive 杀（锁已 release）
10. 调试会话中 worker 自杀后，再次点击「停止」不白启动新子进程（`is_alive()` 短路）

## 9. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 子进程启动延迟（首次 submit 多 ~1.5-2s） | 仅首次启动有延迟；后续 submit 复用已存活子进程。可接受（用户已选「地板低，允许瞬态尖峰」） |
| IPC 序列化开销 | 命令本就是小 dict，JSON 序列化开销极小；config dict 已是 IPC 友好形式 |
| 子进程崩溃检测 | EOF 即时检测 + 心跳僵死兜底；未完成 Future 全部置错误响应；on_restart 回调通知 DebugSessionManager |
| `cancel_event` 跨进程 | 重构为 CMD_CANCEL 命令，子进程维护 cmd_id→Event 映射 |
| 子进程入口 pickle 兼容 | `python -m app.workers.worker_proc` 是独立入口，不依赖 multiprocessing spawn 的父模块重执行 |
| 配置重载后 retry_policy 不同步 | `_reload_config_internal` 新增 `_sync_retry_policy()` 调用 |
| 调试期间 worker 被 keepalive 误杀 | keepalive 锁（引用计数）在调试 start 时 acquire、stop/close/on_restart 时 release；keepalive 判定增加 `_keepalive_lock_count == 0` 条件 |
| 调试期间 worker 崩溃后 `_close_debug_browser` 白启动新子进程 | `_close_debug_browser` 增加 `is_alive()` 短路判断；`on_restart` 回调兜底 release 锁并重置 session |
| `on_restart` 回调与 asyncio 线程并发 release 锁 | `_keepalive_lock` 是 `threading.Lock`，acquire/release 均在其保护下，线程安全 |
| keepalive 锁泄漏（acquire 后异常未 release） | `start` 失败路径、`stop`、`close`、`on_restart` 四处均有 release；用 try/finally 保证 |

## 10. 预期效果

- 主进程内存地板：60MB → 30-35MB
- OCR 触发后内存：原 60MB→120MB 后停留在 ~90MB 地板；改造后主进程保持 30-35MB，子进程 OCR 期尖峰 120MB，3 分钟后子进程自杀、内存彻底归还 OS
- OcrHandler 代码简化：删除 ~40 行定时清理逻辑
- 调试会话失效有准确提示
- 重试策略三个 bug 修复（间隔生效、max_retries=0 可达、前后端范围一致）
