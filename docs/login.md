# Campus-Auth 登录链路架构文档

> **更新日期**: 2026-06-20
> **基于**: 登录链路重构 + LoginRetryManager 清理 + CompositeCancelEvent 替代
> **前置文档**: 本文档替代旧版 `login.md`

---

## 一、整体架构概览

项目采用分层架构，核心组件关系如下：

```
main.py（CLI 入口）
  ├── application.py（FastAPI + Uvicorn）
  │     └── api/*（16 个路由模块）
  ├── container.py（ServiceContainer — DI 容器）
  │     ├── services/login_orchestrator.py（LoginOrchestrator — 登录唯一入口）
  │     ├── services/retry_policy.py（RetryPolicy — 重试策略框架）
  │     ├── services/engine.py（ScheduleEngine — 核心 Actor）
  │     ├── services/task_executor.py（线程池执行器，委托 Orchestrator）
  │     ├── services/profile_service.py（配置 CRUD）
  │     └── services/config_service.py（配置保存/回滚）
  ├── utils/cancel_token.py（CompositeCancelEvent — 组合取消事件）
  ├── network/*（网络检测子系统）
  ├── tasks/*（浏览器自动化任务引擎）
  └── workers/playwright_worker.py（Playwright Actor）
```

**架构核心**：`LoginOrchestrator` 是登录执行的唯一入口，收敛校验/去重/提交/超时/历史/取消横切逻辑。两个 Actor 模型（`ScheduleEngine` 引擎线程 + `PlaywrightWorker` 浏览器线程）仍是系统核心。`LoginOrchestrator` 不是 Actor，而是同步编排层。

---

## 二、LoginOrchestrator — 登录唯一入口

### 2.1 职责边界

```
┌─────────────────────────────────────────────────────────────┐
│ 调用方（只声明意图，零横切逻辑）                              │
│  main.py            engine._do_async_login    run_manual_login│
│  login_once         source="login_once"       source="manual" │
└──────────┬──────────────────┬──────────────────────┬────────┘
           │                  │                      │
           ▼                  ▼                      ▼
┌──────────────────────────────────────────────────────────────┐
│ LoginOrchestrator（唯一执行入口）                             │
│  validate() → submit(source) → 去重槽 → 历史/超时回调         │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ 去重槽 _slot: LoginHandle | None                    │    │
│  │  manual 可抢占 auto（取消旧的、提交新的）              │    │
│  │  auto 命中运行中则复用旧 handle                       │    │
│  │  login_once 总是新提交                                │    │
│  └─────────────────────────────────────────────────────┘    │
└──────────┬───────────────────────────────────────────────────┘
           │
     ┌─────┴─────┐
     ▼           ▼
┌─────────┐ ┌──────────────────────────────┐
│Worker   │ │ RetryPolicy（策略对象）        │
│submit() │ │  ImmediatePolicy  (login_once)│
│CMD_LOGIN│ │  MonitoredPolicy   (engine)   │
└─────────┘ └──────────────────────────────┘
```

**Orchestrator 负责**：
- 配置校验（`validate_login_config`，唯一实现）
- 去重与抢占（`_slot`，替代原 `task_executor._login_future`）
- Worker 提交与超时（`resolve_worker_timeout`，唯一来源）
- 登录历史记录（`LoginHistoryService`，统一记录点）
- cancel 联动（`CompositeCancelEvent` 惰性扫描，无线程）

**Orchestrator 不负责**：
- 重试间隔与停止策略（RetryPolicy）
- 网络检测触发（engine）
- 失败计数与降频退避（engine._on_done 回调）

### 2.2 核心数据结构

```python
LoginSource = Literal["auto", "manual", "login_once"]

@dataclass
class LoginHandle:
    """一次登录提交的句柄。"""
    future: Future | None            # None 表示被拒绝（校验/去重）
    source: LoginSource
    cancel_event: CompositeCancelEvent  # 组合取消事件
    rejected_reason: str | None      # 非 None 表示被拒绝

    def done(self) -> bool: ...
    def result(self, timeout=None) -> tuple[bool, str]: ...
    def cancel(self) -> None: ...    # 设置 cancel_event
```

### 2.3 去重与抢占逻辑

```python
def submit(self, *, source, config=None, cancel_event=None) -> LoginHandle:
    # 1. 校验
    err = validate_login_config(cfg)
    if err: return LoginHandle(rejected_reason=err)

    # 2. 包装 cancel_event（plain Event → CompositeCancelEvent）
    if cancel_event and not isinstance(cancel_event, CompositeCancelEvent):
        wrapper = CompositeCancelEvent()
        wrapper.add_source(cancel_event)
        cancel_event = wrapper

    # 3. 去重与抢占
    with self._slot_lock:
        existing = self._slot
        if existing and not existing.done():
            if source == "login_once":
                pass  # 一次性任务，不复用
            elif source == "manual" and existing.source == "auto":
                existing.cancel()  # manual 抢占 auto
            else:
                self._link_cancel(cancel_event, existing.cancel_event)
                return existing  # 复用旧 handle

        handle = self._dispatch(cfg, source, cancel_event)
        self._slot = handle
    return handle
```

---

## 三、RetryPolicy — 重试策略框架

### 3.1 类层次

```
RetryPolicy（抽象基类）
  ├── attempts() → Iterator[int]     # 产出重试序号
  └── delay_before(attempt) → float  # 返回等待秒数

ImmediatePolicy(RetryPolicy)
  ├── max_retries: int (1-10, 默认 3)
  ├── interval: int (≥1, 默认 5)
  └── 固定间隔，无指数退避

MonitoredPolicy(RetryPolicy)
  ├── max_retries: int (默认 10)
  ├── interval: int (默认 30)
  ├── backoff_after_cycles: int (默认 3)
  ├── on_network_check(need_login) → bool
  └── on_login_done(success) → float | None
```

### 3.2 使用场景

| 场景 | 策略 | 调用方 |
|------|------|--------|
| `--startup-action login_once` | `ImmediatePolicy` | main.py |
| 引擎自动登录（网络监控） | `MonitoredPolicy` | engine._do_network_check |
| 手动登录（API 触发） | 无策略（单次提交） | engine._handle_login |

### 3.3 MonitoredPolicy 状态机

```
                    ┌──────────────┐
                    │   初始状态    │
                    │ count=0      │
                    │ failed=0     │
                    └──────┬───────┘
                           │
          ┌────────────────┼────────────────┐
          ▼                ▼                ▼
   need_login=True   need_login=False   login_done(ok=True)
   on_network_check  on_network_check   on_login_done
   → 不触发登录      → 重置 count/failed → 重置 count/failed
   （count>=max）    （down→up 转换时）
          │
          ▼
   login_done(ok=False)
   → count += 1
   → 若 count >= max_retries:
       failed_cycles += 1
       → 若 failed_cycles >= backoff_after_cycles:
           返回 delay（指数退避，上限 1800s）
       → 否则返回 None
   → 否则返回 0.0（立即重试）
```

**关键设计**：reset 只在网络从 down→up 恢复时发生，不再每次网络检测都重置。

---

## 四、登录执行链路

### 4.1 自动登录（引擎触发）

```
ScheduleEngine._do_network_check()
  │
  ├── NetworkMonitorCore.check_once()
  │     └── need_login = True
  │
  ├── retry_policy.on_network_check(True)
  │     └── 返回 True（未达上限）或 False（已达上限）
  │
  └── [返回 True] _do_async_login()
        │
        ├── orchestrator.submit(source="auto", config=config)
        │     ├── validate_login_config(config)
        │     ├── _slot 去重检查
        │     └── _dispatch(config, "auto", cancel_event)
        │           ├── resolve_worker_timeout(config)
        │           ├── _pool.submit(_run)
        │           │     └── worker.submit(CMD_LOGIN, timeout=worker_timeout)
        │           │           └── PlaywrightWorker → LoginAttemptHandler
        │           ├── _record_history(success, duration, error)
        │           └── _on_done: 清理 _slot
        │
        └── _on_done 回调（engine 层）
              ├── _update_status_snapshot()
              ├── [成功] _consecutive_login_failures = 0
              │         retry_policy.on_login_done(success=True)
              └── [失败] _consecutive_login_failures += 1
                        retry_policy.on_login_done(success=False)
                          → delay = max(engine退避, policy退避)
                          → _next_network_check = now + delay
```

### 4.2 手动登录（API 触发）

```
前端 → POST /api/actions/login
  │
  ├─ API 线程 ──→ run_manual_login()
  │                 ├── _manual_login_lock 获取
  │                 ├── 入队 LOGIN 命令
  │                 └── response_event.wait(timeout=login_timeout)
  │
  ├─ 引擎线程 ──→ _handle_login()
  │                 ├── orchestrator.validate(config)
  │                 └── _do_async_login(is_manual=True, config_snapshot)
  │                       └── orchestrator.submit(source="manual")
  │                             ├── [有运行中的 auto] cancel 旧的 → 提交新的
  │                             └── [无运行中的] 直接提交
  │
  ├─ 登录线程 ──→ _run()
  │                 └── worker.submit(CMD_LOGIN, timeout=worker_timeout)
  │
  └─ API 线程 ──→ 返回 (success, message)
```

### 4.3 login_once（CLI 启动模式）

```
main.py → _execute_login_with_retries(runtime_config, logger)
  │
  ├── 构造一次性 Orchestrator（容器尚未创建）
  │     LoginOrchestrator(
  │       worker_getter=get_worker,
  │       login_history=LoginHistoryService(AUTH_DATA_DIR),
  │       profile_service=create_profile_service(),
  │     )
  │
  ├── ImmediatePolicy(max_retries=3, interval=5)
  │
  └── for attempt in policy.attempts():
        ├── delay = policy.delay_before(attempt)
        ├── orchestrator.submit(source="login_once", config=runtime_config)
        ├── handle.result()  # 同步等待
        │     ├── (True, msg) → SUCCESS，退出
        │     └── (False, msg) → 继续重试
        └── 全部失败 → TEMPORARY_FAILURE，降级到监控模式
```

---

## 五、取消联动机制（CompositeCancelEvent）

### 5.1 架构

```
调用方 cancel_event（新）
  │
  ▼
LoginOrchestrator._link_cancel(new_event, target_event)
  │
  └── target_event.add_source(new_event)  ← 一行代码
        │
        └── CompositeCancelEvent（惰性扫描）
              ├── _sources: list[Event]  ← 所有取消源
              ├── add_source(event)      ← 添加源，已 set 则立即传播
              └── is_set()               ← 覆写为惰性扫描所有源
                    ├── super().is_set()  ← 缓存命中则跳过扫描
                    └── 扫描 _sources     ← 任一源 set → super().set()
```

### 5.2 CompositeCancelEvent 设计

```python
class CompositeCancelEvent(threading.Event):
    """组合多个取消事件，is_set() 惰性扫描所有源。"""

    def add_source(self, event: threading.Event) -> None:
        """添加取消源。源已 set 则立即传播。"""
        with self._lock:
            if event not in self._sources:
                self._sources.append(event)
                if event.is_set():
                    super().set()

    def is_set(self) -> bool:
        """惰性扫描：调用时检查所有源。"""
        if super().is_set():  # 缓存
            return True
        with self._lock:
            for src in self._sources:
                if src.is_set():
                    super().set()  # 缓存
                    return True
        return False
```

### 5.3 消费方兼容性

| 消费方 | 调用方式 | 兼容性 |
|--------|---------|--------|
| `login.py:145,228` | `cancel_event.is_set()` | ✅ 继承 threading.Event |
| `browser.py:92` | `_is_cancelled()` → `cancel_event.is_set()` | ✅ 继承 threading.Event |
| Worker data dict | `{"cancel_event": cancel_event}` | ✅ 子类兼容 |

**消费方零改动**——`CompositeCancelEvent` 继承 `threading.Event`，`is_set()` 被覆盖为惰性扫描。

### 5.4 演进对比

| 维度 | 旧实现（task_executor） | 中间态（watcher 线程） | 当前（CompositeCancelEvent） |
|------|----------------------|---------------------|---------------------------|
| 线程模型 | 每次去重新建线程 | 单常驻 watcher | 无线程 |
| 取消延迟 | ≤1s | ≤1s（队列轮询） | 0（惰性扫描） |
| 代码量 | ~30 行 + 线程 | ~50 行 + 队列/锁/毒丸 | 1 行 add_source |

---

## 六、TaskExecutor 委托层

TaskExecutor 登录逻辑完全委托 Orchestrator，自身只保留线程池与定时任务：

```python
class TaskExecutor:
    def __init__(self, registry, history_store, worker_getter,
                 get_runtime_config=None, login_orchestrator=None):
        self._login_orchestrator = login_orchestrator
        # 登录历史由 Orchestrator 管理，TaskExecutor 不再持有

    def execute_login_async(self, cancel_event=None, config_snapshot=None) -> Future:
        handle = self._login_orchestrator.submit(source="auto", ...)
        return handle.future or failed_future

    def execute_login(self, cancel_event=None, config_snapshot=None) -> tuple[bool, str]:
        handle = self._login_orchestrator.submit(source="auto", ...)
        return handle.result()

    def is_login_running(self) -> bool:
        return self._login_orchestrator.is_running()

    def cancel_login(self) -> None:
        self._login_orchestrator.cancel_running()
```

### 依赖注入（container.py）

```python
self.task_executor = TaskExecutor(
    registry=..., history_store=..., worker_getter=_get_worker,
)
self.engine = ScheduleEngine(..., task_executor=self.task_executor)

self.login_orchestrator = LoginOrchestrator(
    worker_getter=_get_worker,
    login_history=self.login_history_service,
    profile_service=self.profile_service,
    get_runtime_config=self.engine.get_runtime_config,
)
self.task_executor._login_orchestrator = self.login_orchestrator
self.login_orchestrator._pool = self.task_executor._login_pool
self.engine._orchestrator = self.login_orchestrator
```

---

## 七、已修复的问题清单

| 编号 | 问题 | 修复方式 | 状态 |
|------|------|---------|------|
| F02 | login_once 不记录历史 | Orchestrator._record_history 统一记录 | ✅ |
| F03 | record_attempt 早于提交 | 移到 orchestrator.submit 成功之后 | ✅ |
| F04 | 网络检测每次 reset 重试计数 | MonitoredPolicy 仅 down→up 时 reset | ✅ |
| F05 | 自动登录路径无配置校验 | validate_login_config 唯一实现 | ✅ |
| F06 | 手动取消竞态 | Orchestrator.submit 手动抢占 auto | ✅ |
| F08 | login_once 独立指数退避 | ImmediatePolicy 统一策略 | ✅ |
| F09 | 三处超时不统一 | resolve_worker_timeout 唯一来源 | ✅ |
| F12 | _link_cancel_event 线程泄漏 | CompositeCancelEvent 无线程 | ✅ |
| F13 | cancel_event 冗余检查 | 惰性扫描消除 | ✅ |
| — | LoginRetryManager 双轨运行 | 完全删除，MonitoredPolicy 统一管理 | ✅ |
| — | engine.py 死代码 | 删除 _validate_login_config、_configure_retry | ✅ |
| — | TaskExecutor 死代码 | 删除 _legacy_*、_record_login_history、死参数 | ✅ |

---

## 八、架构级观察

**优点**：
- 单一入口：所有登录路径通过 `Orchestrator.submit()` 统一进入
- 策略分离：重试策略（RetryPolicy）与执行逻辑（Orchestrator）解耦
- 无线程：CompositeCancelEvent 惰性扫描替代 watcher 线程
- 最小化：TaskExecutor 只保留线程池 + 定时任务，登录相关字段全部移交

**遗留项**：
- 定时浏览器任务与登录共享 CMD_LOGIN 的并发控制问题（F11）
- engine.py 仍有 `_consecutive_login_failures` + `_apply_backoff_interval` 与 MonitoredPolicy 的退避交互（已修复为取最大值）
