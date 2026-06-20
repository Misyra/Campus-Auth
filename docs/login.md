# Campus-Auth 登录链路架构文档（重构后）

> **更新日期**: 2026-06-20
> **基于**: 登录链路三步重构（Orchestrator + MonitoredPolicy + 常驻取消线程）
> **前置文档**: 本文档替代旧版 `login.md`，反映重构后的架构

---

## 一、整体架构概览

项目采用分层架构，核心组件关系如下：

```
main.py（CLI 入口）
  ├── application.py（FastAPI + Uvicorn）
  │     └── api/*（16 个路由模块）
  ├── container.py（ServiceContainer — DI 容器）
  │     ├── services/login_orchestrator.py（LoginOrchestrator — 登录唯一入口）★ 新增
  │     ├── services/retry_policy.py（RetryPolicy — 重试策略框架）★ 新增
  │     ├── services/engine.py（ScheduleEngine — 核心 Actor）
  │     ├── services/task_executor.py（线程池执行器，委托 Orchestrator）
  │     ├── services/profile_service.py（配置 CRUD）
  │     ├── services/config_service.py（配置保存/回滚）
  │     └── services/login_retry.py（重试状态机，deprecated）
  ├── network/*（网络检测子系统）
  ├── tasks/*（浏览器自动化任务引擎）
  └── workers/playwright_worker.py（Playwright Actor）
```

**重构核心变化**：引入 `LoginOrchestrator` 作为登录执行的唯一入口，收敛了原本散落在 `main.py`、`engine.py`、`task_executor.py` 三处的登录横切逻辑（校验/去重/提交/超时/历史/取消）。

两个 Actor 模型仍是系统的核心：`ScheduleEngine`（引擎线程）和 `PlaywrightWorker`（浏览器线程），各自拥有独立的守护线程和命令队列。`LoginOrchestrator` 不是 Actor，而是一个同步编排层，被引擎线程和 main.py 调用方直接调用。

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
│  validate() → submit(source, policy) → 去重槽 → 历史/超时回调  │
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
- 配置校验（`validate_login_config`，唯一实现，消除 engine 与 main 的分歧）
- 去重与抢占（`_slot`，替代 `task_executor._login_future` 散落逻辑）
- Worker 提交与超时（`resolve_worker_timeout`，唯一来源）
- 登录历史记录（`LoginHistoryService`，统一记录点）
- cancel_event 生命周期（常驻单线程队列联动）

**Orchestrator 不负责**（交给调用方/RetryPolicy）：
- 重试间隔与停止策略（RetryPolicy）
- 网络检测触发（engine）
- 失败计数与降频退避（engine._on_done 回调）

### 2.2 核心数据结构

```python
LoginSource = Literal["auto", "manual", "login_once"]

@dataclass
class LoginHandle:
    """一次登录提交的句柄。"""
    future: Future | None        # None 表示被拒绝（校验/去重）
    source: LoginSource
    cancel_event: threading.Event
    rejected_reason: str | None  # 非 None 表示被拒绝

    def done(self) -> bool: ...
    def result(self, timeout=None) -> tuple[bool, str]: ...
    def cancel(self) -> None: ...  # 设置 cancel_event
```

`LoginHandle` 封装了 `Future` + `cancel_event` + `source` + `rejected_reason`，比裸 `Future` 语义更强。调用方通过 `handle.result()` 同步等待结果，或通过 `handle.future` 异步注册回调。

### 2.3 去重与抢占逻辑

```python
def submit(self, *, source, config=None, cancel_event=None) -> LoginHandle:
    # 1. 校验（F05 唯一实现）
    err = validate_login_config(cfg)
    if err: return LoginHandle(rejected_reason=err)

    # 2. 去重与抢占
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

        # 3. 提交新登录
        handle = self._dispatch(cfg, source, cancel_event)
        self._slot = handle
    return handle
```

**关键行为**：
- `manual` 抢占 `auto`：取消旧的，提交新的（F06 根治）
- `auto` 命中运行中的 `auto`/`manual`：复用旧 handle，联动 cancel_event
- `login_once` 总是新提交（进程级一次性任务）

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
  ├── on_network_check(need_login) → bool   # 网络检测回调
  └── on_login_done(success) → float | None # 登录完成回调
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

**关键设计**：reset 只在网络从 down→up 恢复时发生，不再每次网络检测都重置（F04 根因）。

---

## 四、登录执行链路（重构后）

### 4.1 自动登录（引擎触发）

```
ScheduleEngine._do_network_check()
  │
  ├── NetworkMonitorCore.check_once()
  │     └── need_login = True
  │
  ├── retry_policy.on_network_check(True)   # 通知 policy
  │     └── 返回 True（未达上限）或 False（已达上限）
  │
  └── [返回 True] _do_async_login()
        │
        ├── orchestrator.submit(source="auto", config=config)
        │     ├── validate_login_config(config)  # F05 唯一校验
        │     ├── _slot 去重检查
        │     └── _dispatch(config, "auto", cancel_event)
        │           ├── resolve_worker_timeout(config)  # F09 唯一超时来源
        │           ├── _pool.submit(_run)
        │           │     └── worker.submit(CMD_LOGIN, timeout=worker_timeout)
        │           │           └── PlaywrightWorker → LoginAttemptHandler
        │           ├── _record_history(success, duration, error)  # F02 统一记录
        │           └── _on_done: 清理 _slot
        │
        ├── _login_retry.record_attempt(time.time())
        │
        └── _on_done 回调（engine 层）
              ├── _update_status_snapshot()
              ├── [成功] _consecutive_login_failures = 0
              │         retry_policy.on_login_done(success=True)
              └── [失败] _consecutive_login_failures += 1
                        retry_policy.on_login_done(success=False)
                          → delay = 指数退避延迟
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
  │                 ├── orchestrator.validate(config)  # F05 唯一校验
  │                 └── _do_async_login(is_manual=True, config_snapshot)
  │                       └── orchestrator.submit(source="manual", config=config)
  │                             ├── [有运行中的 auto] cancel 旧的 → 提交新的  # F06
  │                             └── [无运行中的] 直接提交
  │
  ├─ 登录线程 ──→ _run()
  │                 └── worker.submit(CMD_LOGIN, timeout=worker_timeout)
  │                       └── PlaywrightWorker → LoginAttemptHandler
  │
  ├─ 登录线程 ──→ _on_done 回调
  │                 ├── orchestrator: 清理 _slot
  │                 └── engine: _update_status_snapshot + 日志
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
        │     ├── attempt=1 → 0（立即）
        │     └── attempt>1 → interval（固定间隔）
        │
        ├── orchestrator.submit(source="login_once", config=runtime_config)
        │     ├── validate_login_config(config)
        │     ├── _dispatch → worker.submit(CMD_LOGIN)
        │     └── _record_history(success, duration, error)  # F02 统一记录
        │
        ├── handle.result()  # 同步等待
        │     ├── (True, msg) → SUCCESS，退出
        │     └── (False, msg) → 打印失败，继续重试
        │
        └── 全部失败 → TEMPORARY_FAILURE，降级到监控模式
```

**关键收益**：
- F02：login_once 现在通过 Orchestrator 统一记录历史
- F08：使用 ImmediatePolicy，与引擎策略同源
- F09：Orchestrator.resolve_worker_timeout 读 login_timeout，不再硬编码

---

## 五、取消联动机制

### 5.1 架构

```
调用方 cancel_event（新）
  │
  ▼
LoginOrchestrator._link_cancel(new_event, target_event)
  │
  ├── 入队到 _cancel_link_queue
  └── _ensure_cancel_link_thread()
        └── 常驻单线程 _cancel_link_loop()
              │
              ├── 从队列取 (new_event, target_event, deadline)
              ├── 每秒扫描所有 pending 项
              │     ├── new_event.is_set() → target_event.set()（联动）
              │     ├── target_event.is_set() → 丢弃（已取消）
              │     └── now > deadline → 丢弃（超时 300s）
              └── shutdown 时投递毒丸 None 退出
```

### 5.2 与旧实现的对比

| 维度 | 旧实现（task_executor） | 新实现（orchestrator） |
|------|----------------------|----------------------|
| 线程模型 | 每次去重新建 watcher 线程 | 常驻单线程 + 队列 |
| 线程泄漏 | 高频去重时累积（F12） | 不会（单线程复用） |
| 超时机制 | 无（线程可能永远存活） | 300s deadline 自动丢弃 |
| shutdown | 毒丸 None | 毒丸 None |

---

## 六、TaskExecutor 委托层

### 6.1 兼容性设计

TaskExecutor 保留所有旧方法签名，内部委托 Orchestrator：

```python
class TaskExecutor:
    def __init__(self, ..., login_orchestrator=None):
        self._login_orchestrator = login_orchestrator  # 默认 None

    def execute_login_async(self, cancel_event=None, config_snapshot=None) -> Future:
        if self._login_orchestrator is None:
            return self._legacy_execute_login_async(cancel_event, config_snapshot)  # 旧路径
        handle = self._login_orchestrator.submit(source="auto", ...)
        return handle.future or failed_future

    def execute_login(self, cancel_event=None, config_snapshot=None) -> tuple[bool, str]:
        if self._login_orchestrator is None:
            return self._legacy_execute_login(cancel_event, config_snapshot)  # 旧路径
        handle = self._login_orchestrator.submit(source="auto", ...)
        return handle.result()
```

**关键保证**：
- 未注入 Orchestrator 时（单元测试），走 `_legacy_*` 路径，行为完全不变
- 生产路径（经 container.py）一定注入 Orchestrator
- 60+ 处测试无需大改（方法名不变，签名兼容）

### 6.2 依赖注入（container.py）

```python
# container.py — 注入顺序
self.task_executor = TaskExecutor(...)
self.engine = ScheduleEngine(..., task_executor=self.task_executor)

# 注入 Orchestrator
self.login_orchestrator = LoginOrchestrator(
    worker_getter=_get_worker,
    login_history=self.login_history_service,
    profile_service=self.profile_service,
    get_runtime_config=self.engine.get_runtime_config,
)
self.task_executor._login_orchestrator = self.login_orchestrator
self.login_orchestrator._pool = self.task_executor._login_pool  # 复用线程池
self.engine._orchestrator = self.login_orchestrator
```

---

## 七、已修复的问题清单

重构消化了 fix-plan 中的 9 项问题：

| 编号 | 问题 | 修复方式 | 状态 |
|------|------|---------|------|
| F02 | login_once 不记录历史 | Orchestrator._record_history 统一记录 | ✅ |
| F03 | record_attempt 早于提交 | 移到 orchestrator.submit 成功之后 | ✅ |
| F04 | 网络检测每次 reset 重试计数 | MonitoredPolicy 仅 down→up 时 reset | ✅ |
| F05 | 自动登录路径无配置校验 | validate_login_config 唯一实现 | ✅ |
| F06 | 手动取消竞态 | Orchestrator.submit 手动抢占 auto | ✅ |
| F08 | login_once 独立指数退避 | ImmediatePolicy 统一策略 | ✅ |
| F09 | 三处超时不统一 | resolve_worker_timeout 唯一来源 | ✅ |
| F12 | _link_cancel_event 线程泄漏 | 常驻单线程队列 | ✅ |
| F13 | cancel_event 冗余检查 | 队列模式消除 | ✅ |

---

## 八、架构级观察

**优点**：
- 单一入口：所有登录路径（auto/manual/login_once）通过 `Orchestrator.submit()` 统一进入
- 策略分离：重试策略（RetryPolicy）与执行逻辑（Orchestrator）解耦
- 向后兼容：`_legacy_*` 回退保证 60+ 处测试不受影响
- 线程安全：`_slot_lock`（RLock）保护去重槽，`_cancel_link_lock` 保护 watcher 线程启动

**遗留项**（不在本次重构范围）：
- `LoginRetryManager`（login_retry.py）保留但 deprecated，engine 仍用其 `_login_retry_needed` 和 `_calculate_wakeup`
- `_validate_login_config` 在 engine.py 中保留未删除（可后续清理）
- `_configure_retry` 成为死代码（可后续清理）
- 定时浏览器任务与登录共享 CMD_LOGIN 的并发控制问题（F11，按 fix-plan 单独修补）

**后续演进**：
- 彻底消除 LoginRetryManager，统一由 MonitoredPolicy 管理
- 改 login.py/browser.py 的 cancel 检查为轮询 CompositeCancelToken.refresh()，完全去线程
- 将 `_link_cancel` 的 watcher 线程替换为 CompositeCancelToken 组合模式
