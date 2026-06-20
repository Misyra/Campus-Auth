# 登录链路全面审计报告

> **审计日期**: 2026-06-20
> **审计范围**: 登录链路全链路（Orchestrator → Engine → Worker → 消费方）
> **审计方法**: 逐文件通读 + 流程追踪 + 竞态分析

---

## 一、审计范围

| 模块 | 文件 | 审计重点 |
|------|------|---------|
| 编排层 | `login_orchestrator.py` | 去重、抢占、取消联动、资源管理 |
| 策略层 | `retry_policy.py` | MonitoredPolicy 状态机、线程安全 |
| 取消机制 | `cancel_token.py` | CompositeCancelEvent 线程安全 |
| 引擎层 | `engine.py` | 登录提交、网络检测、退避、手动登录 |
| 执行层 | `task_executor.py` | 委托层、浏览器任务 |
| 消费方 | `login.py`、`browser.py` | cancel 检查点 |
| 入口 | `main.py` | login_once 路径 |
| 容器 | `container.py` | DI 注入、资源管理 |
| Worker | `playwright_worker.py` | CMD_LOGIN 处理 |

---

## 二、问题清单

### P1-01：去重命中时重复注册 _on_done 回调

**位置**: `engine.py:297-320` (`_do_async_login`)

**问题描述**:
`_do_async_login` 中 `handle.future is None` 分支（第 297-299 行）注释说"复用了旧 handle，不算新提交"，但实际上 `LoginOrchestrator.submit()` 复用旧 handle 时返回的 `LoginHandle.future` **不为 None**（它是原始提交时设置的 Future）。`future` 为 None 只在校验失败时出现，已被 `rejected_reason` 检查覆盖。

**实际影响**:
当网络检测周期性触发 `_do_async_login` 且上一次 `auto` 登录仍在执行中时：
1. `submit()` 返回复用的旧 handle（`future` 不为 None）
2. 代码不会提前返回，继续执行到 `handle.future.add_done_callback(_on_done)`
3. 同一个 Future 被重复注册 `_on_done` 回调
4. 登录完成时 `_retry_policy.on_login_done` 被多次调用
5. `_attempt` 计数错误，退避延迟被异常放大

**复现条件**: 网络检测间隔 < 登录执行时间（几乎总是成立）

**修复方案**:
```python
# 方案 A：在 _do_async_login 中判断是否为新提交
handle = self._orchestrator.submit(source="auto", config=config)
if handle.rejected_reason is not None:
    # ... 校验失败处理
    return False

if handle.future is None:
    return False  # 去重命中，不注册回调

# 只有新提交的 handle 才注册回调
# ...
```

**修复难度**: 低

---

### P1-02：_retry_policy 跨线程数据竞争

**位置**: `retry_policy.py:80-98` + `engine.py:309-316` + `engine.py:263-266`

**问题描述**:
`MonitoredPolicy` 的 `_attempt` 和 `_prev_network_ok` 字段在两个不同线程中被读写，无同步保护：

| 字段 | 写入线程 | 写入位置 |
|------|---------|---------|
| `_attempt += 1` | login-exec 线程 | `_on_done` 回调 → `on_login_done(False)` |
| `_attempt = 0` | 引擎线程 | `_do_network_check` → `on_network_check(False)` |
| `_prev_network_ok` | 引擎线程 | `_do_network_check` → `on_network_check()` |

**实际影响**:
- `_attempt` 的读-改-写（`_attempt += 1`）与 `_attempt = 0` 的竞态可能导致 `_attempt` 值不确定
- `_prev_network_ok` 的竞态可能导致 down→up 转换检测失败
- 在 CPython 中由于 GIL，简单整数赋值碰巧是原子的，但这是实现细节而非语言保证

**修复方案**:
```python
# 方案 A：MonitoredPolicy 内部加锁
class MonitoredPolicy:
    def __init__(self):
        self._lock = threading.Lock()
        # ...

    def on_network_check(self, need_login):
        with self._lock:
            # ...

    def on_login_done(self, success):
        with self._lock:
            # ...
```

**修复难度**: 中

---

### P1-03：_next_network_check 跨线程写入

**位置**: `engine.py:315`（login-exec 线程）+ `engine.py:276`（引擎线程）

**问题描述**:
`_next_network_check` 在引擎线程中被读写（`_do_network_check`、`_engine_loop`），同时在 login-exec 线程的 `_on_done` 回调中被写入，无锁保护。

**实际影响**:
- 引擎线程设置 `_next_network_check = now + interval`
- 同时 `_on_done` 可能设置 `_next_network_check = now + delay`
- 竞态结果：`_next_network_check` 值不确定
- 可能导致网络检测被意外跳过（设置到很远的未来）或立即触发（被覆盖为较小的值）

**修复方案**:
与 P1-02 一起修复——将 `_on_done` 中的状态修改统一到引擎线程：

```python
# 在 _on_done 中，不直接修改 _next_network_check，
# 而是通过命令队列通知引擎线程
def _on_done(f: Future) -> None:
    ok, msg = f.result()
    if not ok and not is_manual:
        delay = self._retry_policy.on_login_done(success=False)
        if delay and delay > 0:
            # 通过队列通知引擎线程
            self._cmd_queue.put(DeferredAction(
                action="set_next_check",
                target=time.time() + delay,
            ))
```

**修复难度**: 中（需要引入 DeferredAction 机制或类似方案）

---

### P1-04：browser 任务复用 auto/manual 的 handle

**位置**: `login_orchestrator.py:192-205`（submit 去重逻辑）

**问题描述**:
`submit()` 的去重逻辑中，`browser` 源没有特殊处理。当已有 `auto` 或 `manual` 登录正在运行时，`browser` 任务走到 `else` 分支，复用已有 handle。

**实际影响**:
1. 浏览器任务的独立配置（timeout 等）被忽略
2. 浏览器任务等待登录完成后返回**登录的结果**而非浏览器任务的结果
3. `TaskExecutor._execute_browser` 中 `handle.result()` 返回的是登录成功/失败
4. 定时任务的历史记录被错误结果污染

**修复方案**:
```python
# 在去重逻辑中，browser 与 login_once 同等对待
if source == "login_once" or source == "browser":
    pass  # 总是新提交，不复用
```

**修复难度**: 低

---

### P1-05：_handle_login 阻塞引擎线程

**位置**: `engine.py:398-400`

**问题描述**:
`_handle_login` 在引擎线程中调用 `handle.result()`（无超时参数），同步等待登录完成。登录在 login_pool 线程中执行，内部通过 `worker.submit(wait=True, timeout=worker_timeout)` 等待 Worker。Worker 超时可达 600 秒。

**实际影响**:
引擎线程被阻塞期间，**所有其他功能停止工作**：
- 网络检测无法执行
- 定时任务无法调度
- 配置重载无法处理
- 停止监控命令无法处理

**时序图**:
```
用户点击"手动登录"
  → API 线程: 入队 LOGIN 命令, response_event.wait(5min)
  → 引擎线程: _handle_login → handle.result() 阻塞...
  → [引擎线程阻塞 600 秒]
  → [期间网络检测、定时任务全部停滞]
  → 登录完成
  → 引擎线程: cmd.response_data = result, response_event.set()
  → API 线程: 返回结果
  → 引擎线程: 继续处理积压的命令
```

**修复方案**:
```python
# 方案 A：给 handle.result() 添加超时
def _handle_login(self, cmd: EngineCommand) -> None:
    # ...
    ok, msg = handle.result(timeout=self._ui_config.login_timeout + 10)
    cmd.response_data = (ok, msg)

# 方案 B：改回异步模式（推荐）
def _handle_login(self, cmd: EngineCommand) -> None:
    # ...
    handle = self._orchestrator.submit(source="manual", config=config)
    # 不等待，注册回调
    def _on_done(f):
        cmd.response_data = f.result()
        cmd.response_event.set()
    handle.future.add_done_callback(_on_done)
```

**修复难度**: 中

---

### P2-06：login_once 不取消正在运行的 auto 登录

**位置**: `login_orchestrator.py:194-195`

**问题描述**:
`login_once` 在去重逻辑中只是 `pass`（不复用、不取消），然后创建新的 handle。但 `_pool` 是单线程的（`max_workers=1`），新提交的 `_run()` 会排队等待旧任务的 `_run()` 完成。

**实际影响**:
如果 `login_once` 启动时已有 `auto` 登录正在执行：
1. `login_once` 不会取消 `auto`
2. `login_once` 的 `_run()` 排队等待 `auto` 的 `_run()` 完成
3. `auto` 的 `_run()` 阻塞在 `worker.submit(wait=True)` 处，最长 600 秒
4. 用户看到程序长时间无响应

**修复方案**:
```python
# login_once 也取消正在运行的 auto
if source == "login_once":
    if existing.source == "auto":
        existing.cancel()  # 取消 auto
    # else: 不取消 manual（手动登录优先级更高）
```

**修复难度**: 低

---

### P2-07：manual 抢占 auto 后仍需等待 Worker

**位置**: `login_orchestrator.py:197-200` + `login_orchestrator.py:241-248`

**问题描述**:
`manual` 抢占 `auto` 时调用 `existing.cancel()`，然后提交新的 `manual` 到 `_pool`。但 `_pool` 是单线程的，`auto` 的 `_run()` 仍在执行中。

**实际影响**:
1. 用户点击"手动登录"
2. cancel_event 被设置
3. `auto` 的 `_run()` 在 `worker.submit(wait=True)` 处等待 Worker
4. Worker 中的 `LoginAttemptHandler` 在关键步骤检查 cancel_event
5. 如果正在等待页面加载，可能需要等待页面超时（默认 15 秒）
6. `auto` 的 `_run()` 返回，`_pool` 线程释放
7. `manual` 的 `_run()` 才开始执行

用户可能需要等待数十秒才能看到手动登录的结果。

**修复方案**:
```python
# 增大 _pool 的 max_workers 为 2
self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="login-orch")
```

**修复难度**: 低（但需要验证两个并发登录不会冲突）

---

### P2-09：_attempt 计数因重复回调联动错误

**位置**: `retry_policy.py:91-98` + `engine.py:301-318`

**问题描述**:
与 P1-01 联动：重复注册的回调导致 `_attempt` 被多次增加。

**实际影响**:
- `_attempt` 可能被错误地多次增加
- 可能提前触发 `max_retries` 限制
- 监控过早停止重试登录

**修复方案**: 修复 P1-01 即可解决。

---

### P2-10：run_manual_login 超时后引擎线程仍阻塞

**位置**: `engine.py:737-780`

**问题描述**:
`run_manual_login` 超时后返回超时错误，但 `_handle_login` 仍在引擎线程中阻塞在 `handle.result()` 处。

**实际影响**:
1. 用户超时后可以再次提交手动登录
2. 新的 LOGIN 命令进入队列但无法被处理（引擎线程被阻塞）
3. 旧的登录最终完成后，`cmd.response_data` 被设置但无人读取

**修复方案**: 与 P1-05 一起修复——给 `handle.result()` 添加超时。

---

### P2-11：engine.shutdown() 的 join(5s) 可能不够

**位置**: `engine.py:706-707`

**问题描述**:
`shutdown()` 设置 `_shutdown_event`，放入 SHUTDOWN 命令，然后 `join(timeout=5.0)` 等待引擎线程退出。但如果引擎线程被阻塞在 `_handle_login` → `handle.result()` 处（P1-05），5 秒后 join 超时返回。

**实际影响**:
- 引擎线程仍在运行
- `container.shutdown()` 继续清理其他资源（如关闭 Worker）
- 引擎线程可能在 `handle.result()` 返回后尝试访问已关闭的 Worker

**修复方案**:
```python
# shutdown 中先取消正在执行的登录
self._orchestrator.cancel_running()
self._shutdown_event.set()
self._cmd_queue.put(EngineCommand(type=EngineCmdType.SHUTDOWN))
self._engine_thread.join(timeout=5.0)
if self._engine_thread.is_alive():
    logger.warning("引擎线程未能在 5 秒内退出")
```

**修复难度**: 低

---

### P3-08：Orchestrator 的 _pool 被替换后泄漏

**位置**: `login_orchestrator.py:127-130` + `container.py:85`

**问题描述**:
`LoginOrchestrator.__init__` 中创建了 `self._pool = ThreadPoolExecutor(max_workers=1)`。container 中替换为 `task_executor._login_pool`。原始的 ThreadPoolExecutor 成为孤立对象。

**实际影响**: 一个空闲线程泄漏，影响极小。

**修复方案**:
```python
# container.py 中替换前先关闭旧的
self.login_orchestrator._pool.shutdown(wait=False)
self.login_orchestrator._pool = self.task_executor._login_pool
```

**修复难度**: 低

---

### P3-12：CompositeCancelEvent.clear() 语义不符

**位置**: `cancel_token.py:42-44`

**问题描述**:
`clear()` 只调用 `super().clear()` 清除自身 flag，不清除 sources 列表。如果某个 source 仍为 set 状态，`is_set()` 会立即返回 True。

**实际影响**: 当前代码中没有调用 `clear()`，不是实际问题。

**修复方案**: 在文档中说明 `clear()` 不清除 sources。

---

### P3-13：is_manual 参数是死代码

**位置**: `engine.py:286,305`

**问题描述**:
`_do_async_login(is_manual=True)` 目前没有被任何代码调用。`_handle_login` 处理手动登录但不调用 `_do_async_login`。`is_manual` 参数和相关的 `if is_manual: pass` 分支是死代码。

**修复方案**: 移除 `is_manual` 参数。

---

### P3-14：日志消息与实际行为不符

**位置**: `engine.py:772`

**问题描述**:
`run_manual_login` 记录"手动登录任务已提交"，但 `_handle_login` 实际上已同步等待登录完成。

**修复方案**: 改为"手动登录成功"。

---

## 三、修复优先级

### 第一批：简单修复（1-2 小时）

| 问题 | 修复 | 影响 |
|------|------|------|
| P1-01 | 去重命中时不注册回调 | 消除重复回调 + 退避计数错误 |
| P1-04 | browser 不复用 handle | 消除浏览器任务结果污染 |
| P1-13 | 删除 is_manual 死代码 | 代码清洁 |
| P1-14 | 修正日志消息 | 调试准确性 |

### 第二批：中等修复（2-4 小时）

| 问题 | 修复 | 影响 |
|------|------|------|
| P1-05 | _handle_login 加超时或改异步 | 消除引擎线程阻塞 |
| P2-06 | login_once 取消 auto | 消除排队等待 |
| P2-11 | shutdown 先取消登录 | 消除关闭时序问题 |
| P3-08 | 替换 _pool 前关闭旧的 | 消除资源泄漏 |

### 第三批：架构修复（需要设计决策）

| 问题 | 修复 | 影响 |
|------|------|------|
| P1-02 + P1-03 | MonitoredPolicy 加锁或统一到引擎线程 | 消除跨线程竞争 |
| P2-07 | 增大 _pool 为 2 或改 Worker 取消 | 减少手动登录等待 |

---

## 四、总体评估

**代码质量**: 良好。架构清晰，职责分离明确，测试覆盖充分。

**主要风险**: 跨线程数据竞争（P1-02/P1-03）在 CPython 中碰巧安全，但不是语言保证。引擎线程阻塞（P1-05）在手动登录期间影响所有功能。

**建议**: 第一批修复后跑一段时间观察稳定性，再决定是否做第二批和第三批。
