# Monitor Actor 重构：并发锁简化 + Bug 修复

## TL;DR

> **Quick Summary**: 将 MonitorService 从"共享状态多线程 asyncio"反模式重构为 Actor 模型（`queue.Queue` 通信 + 线程完全隔离），把并发同步机制从 ~9 个锁/Event 降到 1 个，消除所有跨线程 asyncio 操作，同时修复已发现的 3 个 P1、7 个 P2 bug。
>
> **核心简化原则**: 运行中不允许改配置 + Signal handler 只做 `os._exit(0)` + Monitor 线程状态完全不暴露给外部。
>
> **Deliverables**:
> - `backend/monitor_service.py` — Actor 模型重写
> - `src/monitor_core.py` — 移除 `_loop`/`_loop_stopped` 属性暴露，简化 `attempt_login()` task 追踪
> - `src/utils/logging.py` — 修复 `close()`/`emit()` 竞态 + 简化 deferred-open
> - `src/utils/browser.py` — dialog handler 改用 `expect_dialog()` + 暴露 `ignore_https_errors`
> - `src/network_test.py` — 修 TOCTOU + 用即弃 httpx.Client 替代 thread-local 缓存
> - `backend/main.py` — 简化 shutdown、移除 `set_event_loop()`、加 login 并发守卫
> - `app.py` — Signal handler → `os._exit(0)`
>
> **Estimated Effort**: Medium-Large
> **Parallel Execution**: YES — 6 waves, max 5 concurrent
> **Critical Path**: logging/browser/network_test/app.py → monitor_core → monitor_service → integration

---

## Context

### Original Request
用户对一个 27 项代码审查报告进行交叉验证，发现锁太多了（~9 个），要求简化并发模型。经分析，根因是 Monitor 线程拥有独立 asyncio 事件循环但跨线程被 API handler/signal handler 远程控制，导致 ~10 处竞态条件。

### Interview Summary
**Key Decisions**:
- **方法**: Actor 模型（`queue.Queue` 命令通道 + `threading.Event` 停止信号），Monitor 线程完全隔离
- **P1 bug**: 一并修，不做独立修复（重构自然修复 2/3 的 P1）
- **范围**: Monitor + 相关模块（monitor_service、monitor_core、logging、browser、network_test、main.py、app.py）
- **测试**: 重构后用集成测试验证 + Agent QA 场景，现有 pytest 全绿
- **运行时不改配置** → 消灭 `reload_config()` 热加载路径
- **Signal handler** → 仅 `os._exit(0)`，不获取任何锁
- **`attempt_login()`** → 简化 20 行不必要的 task 追踪代码

**Research Findings**:
- `MonitorService._lock` 是 `RLock`（`reload_config` → `_push_log` 路径重入），不可改成 `Lock`
- `stop_monitoring()` 不获取 `_config_lock`（报告 N-2 分析有误）
- Python signal handler 总是跑在主线程
- httpx.Client 缓存在线程局部存储中永不关闭
- `__del__` 在 CPython 中不可达（无 GC 循环）

### Metis Review
**Identified Gaps** (addressed):
- `run_manual_login()` 创建完整 `NetworkMonitorCore` → 重构后改为发 queue 命令，不再实例化
- `get_status()` 延迟问题 → 维护共享状态缓存（Actor 原子写入，API 无队列延迟直接读取）
- Queue consumer 跑在哪 → 独立消费者线程，不是主线程也不是 monitor 线程
- `_on_profile_switch` 回调反模式 → 改为 queue 命令 `"profile_switched"`
- 取消后发现的机会：简化 `attempt_login()` 中 20 行 task 追踪、简化 `network_test.py` thread-local 缓存

---

## Work Objectives

### Core Objective
将 MonitorService 的并发同步机制从 ~9 个锁/Event 降到 1 个（只保留 logging handler 的 `_emit_lock`），通过 Actor 模型（queue.Queue 命令调度 + 线程完全隔离）消除所有跨线程 asyncio 操作，同时修复审查发现的 3 个 P1 和 7 个 P2 bug。

### Concrete Deliverables
- 7 个源文件修改（monitor_service、monitor_core、logging、browser、network_test、main.py、app.py）
- 0 个新的源文件（全部 in-place 重构）
- 所有现有 pytest 测试通过

### Definition of Done
- [ ] `grep -rn "run_coroutine_threadsafe" backend/ src/` → 0 条
- [ ] `grep -rn "set_event_loop" backend/main.py` → 0 条
- [ ] `grep -rn "_loop_stopped" src/ backend/` → 0 条
- [ ] `curl -s http://127.0.0.1:50721/api/status` 响应时间 < 100ms
- [ ] `curl -X POST http://127.0.0.1:50721/api/shutdown` 后 5s 内进程退出
- [ ] 并发 2 次 `POST /api/actions/login` → 只开 1 个浏览器进程
- [ ] `start → stop → start` 1s 内快速循环 → 不崩溃不 hang
- [ ] `uv run pytest` → 全部 PASS

### Must Have
- Actor 模型：`queue.Queue` 命令通道驱动的 Monitor 线程
- 唯一锁 `_emit_lock`：仅用于 logging handler，其他地方零锁
- Monitor 线程状态完全隔离：不暴露 `_loop`、`_loop_stopped`、`_login_handler`
- 零 `run_coroutine_threadsafe` 和 `call_soon_threadsafe`
- Signal handler 仅 `os._exit(0)`
- 运行中不能改配置（必须 stop 后才能改）
- `attempt_login()` 简化（去掉 task 追踪花样）
- 修复 3 个 P1 bug、7 个 P2 bug

### Must NOT Have (Guardrails)
- 不能新增 threading 锁（禁止新的 `Lock`/`RLock`/`Semaphore`/`Condition`）
- 不能引入第三方依赖（queue 是 stdlib）
- 不能改变现有的 HTTP API 签名（`/api/status`、`/api/monitor/*` 等保持兼容）
- 不能改变 WebSocket 日志广播行为
- 不能重写 logging 基础设施（只修 close/emit 竞态 + 简化 deferred-open）
- 不能重构 `TaskExecutor`（不在本次范围）
- 不能改前端代码（`quitApp` 等前端问题不在本次范围）

---

## Verification Strategy

> **ZERO HUMAN INTERVENTION** — ALL verification is agent-executed.

### Test Decision
- **Infrastructure exists**: YES (pytest)
- **Automated tests**: None (重构后用集成测试验证)
- **Agent-Executed QA**: MANDATORY for every task

### QA Policy
Every task MUST include agent-executed QA scenarios.
Evidence saved to `.omo/evidence/monitor-actor-refactor/task-{N}-{slug}.{ext}`.

- **API**: Bash (curl) — Send requests, assert status + response body fields
- **Process**: Bash (tasklist/pgrep) — Assert process state
- **CLI**: Bash (tmux) — Run app, observe output
- **WebSocket**: Bash (wscat or Python websocket client) — Assert broadcast

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 1 (5 tasks, MAX PARALLEL — infrastructure cleanup):
├── Task 1: app.py + main.py  — Signal handler, shutdown, lifespan  [quick]
├── Task 2: logging.py        — close/emit 竞态 + deferred-open    [unspecified-low]
├── Task 3: browser.py        — dialog handler + ignore_https       [unspecified-low]
├── Task 4: network_test.py   — TOCTOU + thread-local → on-demand  [unspecified-low]
└── Task 5: monitor_core.py   — 移除 _loop 暴露 + 简化 attempt_login [unspecified-high]

Wave 2 (1 task — 核心重构):
└── Task 6: monitor_service.py — Actor 模型重写                   [unspecified-high]

Wave 3 (2 parallel tasks — 集成):
├── Task 7: main.py            — login 并发守卫                   [quick]
└── Task 8: 集成验证           — 端到端测试                       [unspecified-high]

Wave FINAL (4 parallel reviewers → wait for user okay):
├── F1: Plan compliance audit (oracle)
├── F2: Code quality review (unspecified-high)
├── F3: Real manual QA (unspecified-high + playwright)
└── F4: Scope fidelity check (deep)
   → Present results → Get explicit user okay

Critical Path: Task 5 → Task 6 → Task 8 → F1-F4 → user okay
Parallel Speedup: ~60% faster than sequential
Max Concurrent: 5 (Wave 1)
```

### Dependency Matrix
```
Task  Blocks  Blocked By
1     -       -
2     -       -
3     -       -
4     -       -
5     6       -
6     7, 8    5
7     -       6
8     -       6
F1-F4 -       7, 8
```

### Agent Dispatch Summary
- **Wave 1**: 5 agents — T1: `quick`, T2: `unspecified-low`, T3: `unspecified-low`, T4: `unspecified-low`, T5: `unspecified-high`
- **Wave 2**: 1 agent — T6: `unspecified-high`
- **Wave 3**: 2 agents — T7: `quick`, T8: `unspecified-high`
- **FINAL**: 4 agents — F1: `oracle`, F2: `unspecified-high`, F3: `unspecified-high` (+playwright), F4: `deep`

---

## TODOs

- [x] 1. **Signal handler / app lifespan 简化** — `app.py` + `backend/main.py`

  **What to do**:
  - `app.py`: 替换 signal handler 为只调用 `os._exit(0)`，删除所有 `service.stop_monitoring()` / lock 获取
  - `backend/main.py`: 删除 lifespan 中的 `asyncio.set_event_loop(loop)` 调用（移除过时的跨线程 event loop 设置）
  - `backend/main.py`: 简化 `/api/shutdown` — 发 stop 命令到 queue 后直接返回，不等待线程 join

  **Must NOT do**:
  - 不要在 signal handler 中添加任何清理逻辑（含 log 写入、文件关闭）
  - 不要改变 API 响应格式

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 改动小（~3 个点），单文件模式，无复杂逻辑
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 2, 3, 4, 5)
  - **Blocks**: None
  - **Blocked By**: None

  **References**:
  - `app.py:signal_handler()` — 当前的 signal handler 实现，需要全部替换
  - `backend/main.py:lifespan` — 当前设置 event loop 的地方，需要删除
  - `backend/main.py:/api/shutdown` — 当前 shutdown 实现

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: Signal handler does not hang on shutdown
    Tool: Bash (start app in background, send signal, check exit)
    Preconditions: app.py running on port 50721
    Steps:
      1. Start app: uv run app.py --no-browser & (background, capture PID)
      2. Wait 3s for startup
      3. Kill via signal (SIGTERM on Linux/CTRL_BREAK on Windows): taskkill /PID $PID
      4. Wait 2s
      5. Check process is gone: tasklist /FI "PID eq $PID" → "INFO: No tasks"
    Expected Result: Process exits immediately, no hang
    Evidence: .omo/evidence/monitor-actor-refactor/task-1-signal-exit.txt

  Scenario: /api/shutdown returns quickly (does not block)
    Tool: Bash (curl + timeout)
    Preconditions: app.py running
    Steps:
      1. curl -X POST http://127.0.0.1:50721/api/shutdown (with timeout 3s)
      2. Measure response time
      3. Check process exit after response
    Expected Result: Response received within 3s, process exits within 5s total
    Evidence: .omo/evidence/monitor-actor-refactor/task-1-shutdown.txt
  ```

  **Commit**: YES
  - Message: `chore: 简化 signal handler 为 os._exit(0)，移除 set_event_loop`
  - Files: `app.py`, `backend/main.py`
  - Pre-commit: `uv run ruff check . --quiet`

- [x] 2. **`_DateRotatingFileHandler` close/emit 竞态修复 + 简化 deferred-open** — `src/utils/logging.py`

  **What to do**:
  - `close()`: 加 `self._emit_lock` 保护 `_unflushed_lines` 刷新和文件打开/写入操作
  - **简化**: 移除 deferred-open 模式（第一条日志到来时立即打开文件，不再积攒到 10 条/5 秒才打开）
  - 确保 `close()` 和 `emit()` 不会互相死锁（两者都获取 `_emit_lock`，但临界区小且无嵌套）

  **Must NOT do**:
  - 不要改动 `LogBuffer`、`WebSocketHandler` 或其他 handler
  - 不要重构日志基础设施的架构

  **Recommended Agent Profile**:
  - **Category**: `unspecified-low`
    - Reason: 单文件改动，逻辑简单但需要仔细考虑竞态
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1, 3, 4, 5)
  - **Blocks**: None
  - **Blocked By**: None

  **References**:
  - `src/utils/logging.py:class _DateRotatingFileHandler` — 完整阅读 handle()/emit()/close()/shouldRollover()
  - `src/utils/logging.py:close()` ~line 197 — 当前无锁实现的 close()
  - `src/utils/logging.py:emit()` ~line 153 — 已使用 `_emit_lock` 的 emit()
  - `src/utils/logging.py:_open_file()` — 文件打开逻辑

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: Log file is written immediately (no deferred-open delay)
    Tool: Bash
    Preconditions: Clean logs/ directory
    Steps:
      1. Start app: uv run app.py --no-browser (background)
      2. Wait 1s for first log message
      3. Check log file exists: Get-ChildItem logs/ -Filter *.log
      4. Read first line: Get-Content logs/*.log -Head 1
    Expected Result: Log file exists with timestamped content immediately
    Evidence: .omo/evidence/monitor-actor-refactor/task-2-immediate-log.txt

  Scenario: Rapid close/emit does not corrupt log file
    Tool: Bash (python -c snippet that simulates race)
    Preconditions: Python test script that creates handler, emits 100 logs rapidly, closes
    Steps:
      1. Write test script that creates handler, emits 100 messages in tight loop, calls close()
      2. Run with 10 concurrent threads (simulating race)
      3. Read resulting log file
      4. Check for: no partial lines, no missing lines, no double headers
    Expected Result: Log file is clean and complete
    Evidence: .omo/evidence/monitor-actor-refactor/task-2-race-test.txt
  ```

  **Commit**: YES
  - Message: `fix: 修复 DateRotatingFileHandler close/emit 竞态，简化 deferred-open`
  - Files: `src/utils/logging.py`
  - Pre-commit: `uv run ruff check . --quiet`

- [x] 3. **Dialog handler 泄漏修复（login.py）+ `ignore_https_errors` 配置化（browser.py）** — `src/utils/login.py` + `src/utils/browser.py`

  **What to do**:
  - **`src/utils/login.py`（dialog handler 修复）**:
    - 将 `page.on("dialog", self._dialog_handler)` 持久监听器改为 `async with page.expect_dialog() as dialog_info:` 上下文管理器（每次弹窗用完即弃）
    - 删除 `self._dialog_handler` 实例属性（\~L45）
    - 删除 `page.remove_listener("dialog", ...)` 清理代码（\~L193）
    - 删除 `page.on("dialog", ...)` 注册代码（\~L201）
    - 删除 `__del__` 中的 `self._dialog_handler = None`（\~L279）
  - **`src/utils/browser.py`（ignore_https_errors 配置化）**:
    - 暴露 `ignore_https_errors`：从 config 读取 `browser_args.ignore_https_errors`（默认 True 保持向后兼容）
    - 在创建 browser context 时传入 `ignore_https_errors` 参数

  **Must NOT do**:
  - 不要改动 `BrowserContextManager` 的生命周期管理逻辑
  - 不要改动 browser 健康检查逻辑

  **Recommended Agent Profile**:
  - **Category**: `unspecified-low`
    - Reason: 两个文件，模式替换（listener → context manager），改动明确
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1, 2, 4, 5)
  - **Blocks**: None
  - **Blocked By**: None

  **References**:
  - `src/utils/login.py:_handle_dialog()` (\~L200) — 当前 dialog 处理器函数（将被 expect_dialog 替代）
  - `src/utils/login.py:attempt_login()` (\~L192-201) — page.on 注册 + remove_listener 清理
  - `src/utils/login.py:_dialog_handler` (L45, L279) — 实例属性声明和清理
  - `src/utils/browser.py:playwright.launch()` — context 创建位置，`ignore_https_errors` 要传在这
  - Playwright docs: `page.expect_dialog()` — 上下文管理器 API

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: Dialog is still handled during login flow
    Tool: Python test script using sync_playwright
    Preconditions: BrowserContextManager initialised, page with dialog
    Steps:
      1. Create BrowserContextManager with test config
      2. Trigger a dialog during login simulation (alert/confirm/prompt)
      3. Verify dialog is accepted (not left hanging, no crash)
      4. Check no listener leak: page.listeners("dialog") is empty after dialog
    Expected Result: Dialog is handled, no listener remains attached
    Evidence: .omo/evidence/monitor-actor-refactor/task-3-dialog-handled.txt

  Scenario: ignore_https_errors config is read and applied
    Tool: grep + code review
    Preconditions: browser.py source
    Steps:
      1. grep for "ignore_https_errors" in browser.py
      2. Verify it reads from config
      3. Verify it's passed to browser context creation
    Expected Result: Config-driven https error handling
    Evidence: .omo/evidence/monitor-actor-refactor/task-3-ignore-https.txt
  ```

  **Commit**: YES
  - Message: `fix: 修复 login.py dialog handler 泄漏，暴露 browser ignore_https_errors 配置项`
  - Files: `src/utils/login.py`, `src/utils/browser.py`
  - Pre-commit: `uv run ruff check . --quiet`

- [x] 4. **`network_test.py` TOCTOU + thread-local 缓存泄漏修复** — `src/network_test.py`

  **What to do**:
  - **TOCTOU 修复**: `_get_executor()` 中检查 executor 是否 shutdown 时，加锁保护 read-shutdown-create 序列，或使用 `try/except` 捕获 `RejectedExecutionError`
  - **简化**: 删除 `_thread_local` 和 `_get_http_client()` 的 threading.local() 缓存模式，改为每次检测时直接 `httpx.Client()` 创建，用完 `.close()`
  - 修复 `_block_proxy` 修改后不生效的问题：移除 thread-local 缓存
  - 清理 `atexit` 注册（不再需要关闭 thread-local 资源）

  **Must NOT do**:
  - 不要重写 `is_network_available()` 的检测逻辑
  - 不要改动模块的公开 API 签名
  - 不要添加新依赖

  **Recommended Agent Profile**:
  - **Category**: `unspecified-low`
    - Reason: 模式替换，改动明确，单文件
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1, 2, 3, 5)
  - **Blocks**: None
  - **Blocked By**: None

  **References**:
  - `src/network_test.py:_get_executor()` — TOCTOU: check-then-use 模式
  - `src/network_test.py:_get_http_client()` — thread-local 缓存模式
  - `src/network_test.py:_cleanup_resources()` — 当前 atexit 清理
  - `src/network_test.py:set_block_proxy()` — proxy 配置入口
  - `src/network_test.py:is_network_available()` — httpx.Client 使用位置

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: Network test works after rapid restart (no TOCTOU crash)
    Tool: Bash (uv run python -c "test import + rapid calls")
    Preconditions: Module importable
    Steps:
      1. Write test: import network_test, call is_network_available 5 times rapidly
      2. Verify no RejectedExecutionError or thread pool errors
    Expected Result: All 5 calls succeed
    Evidence: .omo/evidence/monitor-actor-refactor/task-4-toctou.txt

  Scenario: _block_proxy toggle takes effect immediately (no stale cache)
    Tool: Bash (uv run python -c)
    Preconditions: Module importable
    Steps:
      1. Set block_proxy=True, call is_network_available
      2. Set block_proxy=False, call is_network_available
      3. Verify proxy setting changes between calls
    Expected Result: Each call uses the current proxy setting (no stale thread-local cache)
    Evidence: .omo/evidence/monitor-actor-refactor/task-4-proxy-toggle.txt
  ```

  **Commit**: YES
  - Message: `fix: 修复 network_test TOCTOU 和 thread-local httpx 缓存泄漏`
  - Files: `src/network_test.py`
  - Pre-commit: `uv run ruff check . --quiet`

- [x] 5. **`monitor_core.py` 简化：移除 `_loop`/`_loop_stopped` 暴露 + 简化 `attempt_login()`** — `src/monitor_core.py`

  **What to do**:
  - `_loop`（asyncio event loop）：从实例属性改为 `attempt_login()` 方法内部的局部变量，不再在 `start_monitoring()` 中预先创建
  - `_loop_stopped`：删除此属性，改用已有的 `_stop_event`（`threading.Event`）检测是否停止
  - **简化 `attempt_login()`**（~40 行 → ~15 行）：删除 `_existing_tasks` 捕获、`_login_tasks` cancel/gather 的复杂逻辑。因为 event loop 是孤立的且只在单次 login 调用期间存在，不存在"别的 async task 泄漏进来"的问题
  - 确保 `attempt_login()` 调用前后 `_loop.close()` 正确清理

  **Must NOT do**:
  - 不要改变 `monitor_network()` 主循环逻辑（它是同步的 socket/Ping/Playwright 检测）
  - 不要改变 `start_monitoring()`/`stop_monitoring()` 对 `MonitorService` 的 API 契约
  - 不要删除 `_cancel_login` 的 thread-safe 取消功能
  - 保留 `_reuse_browser`（浏览器复用逻辑），保留 `_cancel_login`（thread-safe 取消）
  - **删除 `_config_lock`**：Actor 模型中 config 只由 monitor 线程在启动时读取，无人并发写入，不再需要此锁

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: 中等复杂度，需要理解 asyncio event loop 生命周期和 task 管理的原理
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES（独立于 Tasks 1-4）
  - **Parallel Group**: Wave 1 (with Tasks 1, 2, 3, 4)
  - **Blocks**: Task 6（monitor_service Actor 重构依赖新的 monitor_core API）
  - **Blocked By**: None

  **References**:
  - `src/monitor_core.py:start_monitoring()` (~L148-150) — `_loop = asyncio.new_event_loop()` 创建位置
  - `src/monitor_core.py:stop_monitoring()` (~L196-205) — `_loop.close()` + `_loop_stopped = True`
  - `src/monitor_core.py:attempt_login()` (~L560-603) — 需要简化的 task 追踪代码（30 行→10 行）
  - `src/monitor_core.py:__init__` — 移除 `_loop`/`_login_tasks`/`_loop_stopped` 属性声明

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: attempt_login works correctly after simplification (no task leak)
    Tool: Bash（uv run pytest + curl integration）
    Preconditions: app.py running with proper config
    Steps:
      1. POST /api/monitor/start → 200
      2. POST /api/actions/login → 200 with success/message
      3. POST /api/monitor/stop → 200
      4. Repeat 3x (start → login → stop) — verify no crash, no asyncio Task warnings
    Expected Result: All 3 cycles complete without error
    Evidence: .omo/evidence/monitor-actor-refactor/task-5-login-cycle.txt

  Scenario: No `_loop` or `_loop_stopped` attributes remain
    Tool: grep
    Preconditions: monitor_core.py source
    Steps:
      1. grep "self\._loop" src/monitor_core.py — should only be local var inside attempt_login
      2. grep "_loop_stopped" src/monitor_core.py — should be 0
    Expected Result: No instance-level event loop attribute, no _loop_stopped anywhere
    Evidence: .omo/evidence/monitor-actor-refactor/task-5-no-loop-attr.txt
  ```

  **Commit**: YES
  - Message: `refactor: 移除 monitor_core _loop/_loop_stopped 暴露，简化 attempt_login`
  - Files: `src/monitor_core.py`
  - Pre-commit: `uv run ruff check . --quiet`

- [x] 6. **MonitorService Actor 模型重构（核心）** — `backend/monitor_service.py`

  **What to do**:
  这是整个计划的核心重构。将 `MonitorService` 从"跨线程共享 asyncio event loop"改为 Actor 模型。

  **架构变更**:
  ```
  旧: API 线程 → call_soon_threadsafe → Monitor 线程的 event loop
  新: API 线程 → queue.Queue.put() → QueueConsumer 线程 → 命令分发
                    ↑                        ↓
              StatusSnapshot  ←──  Monitor 线程 push 状态
              (原子写入, API 直接读, 无锁)
  ```

  **具体改动**:

  1. **添加 `MonitorCommand` dataclass**:
     ```python
     @dataclass
     class MonitorCommand:
         type: Literal["start", "stop", "login", "reload", "get_status"]
         data: dict = field(default_factory=dict)
         response_event: threading.Event | None = None
         response_data: Any = None
     ```

  2. **添加命令队列**:
     - `self._cmd_queue: queue.Queue[MonitorCommand] = queue.Queue(maxsize=50)`
     - `self._stop_signal: threading.Event = threading.Event()` — 消费者线程停止信号

  3. **添加 Queue 消费者线程**:
     - 独立线程，持续从 `_cmd_queue.get()` 读取命令
     - 根据命令类型分发给相应处理逻辑
     - 处理 `log` 类型的命令：将 monitor 发来的日志写入 `_logs` deque
     - 处理 `status` 类型的命令：更新 `StatusSnapshot`
     - 处理 `stop` 命令时：发 stop 给 monitor 线程 → 等待线程 join → 清理

  4. **移除**:
     - 删除 `_loop` 属性（不再需要跨线程 asyncio）
     - 删除 `set_event_loop()` / `asyncio.run_coroutine_threadsafe()` 调用
     - 删除 `_push_log()` 和 `_push_status()` 中的 ws_manager.broadcast() 跨线程调用
     - 删除 `self._lock`（RLock） — 不再需要，Actor 内部单线程处理

  5. **新增 `StatusSnapshot`**:
     ```python
     @dataclass
     class StatusSnapshot:
         monitoring: bool = False
         last_network_ok: float | None = None
         start_time: float | None = None
         network_check_count: int = 0
         login_attempt_count: int = 0
         snapshot_time: float = 0.0
     ```
     - Queue consumer 原子写入
     - `get_status()` 直接读取，无需 queue 往返
     - 用 `copy.copy()` 或直接字段读取（Python 的 `@dataclass` 字段读取是原子操作）

  6. **`run_manual_login()` 简化**:
     - 不再创建完整 `NetworkMonitorCore` 实例
     - 改为发 `MonitorCommand(type="login", response_event=...)` 到 queue，等待响应
     - 或更简单：同步创建 `LoginAttemptHandler`（仅登录），不走 queue

  7. **WebSocket broadcast（零 run_coroutine_threadsafe）**:
     - Queue consumer 线程将新日志写入一个 `deque`（线程安全的单生产者-单消费者 deque）
     - 主 asyncio loop 通过 `asyncio.ensure_future` 启动一个定时 task（每 100ms 检查一次）
     - 该 task 从 deque 中 drain 新条目，调用 `ws_manager.broadcast(data)` （在主 loop 中，无跨线程）
     - 这样**零 `run_coroutine_threadsafe`** 调用，完全遵守验收标准

  **Must NOT do**:
  - 不能改变 `/api/status` 的 JSON 响应格式
  - 不能改变 WebSocket `/ws/logs` 的消息格式
  - 不能引入不在 `pyproject.toml` 中的依赖
  - 不能添加新的 `threading.Lock`/`RLock`（只用 `queue.Queue` 自带的线程安全）
  - 不能改动 `NetworkMonitorCore` 已有的公开 API 签名

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: 核心重构，需要全面理解旧模型的线程交互和 asyncio 生命周期
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: NO（核心重构）
  - **Parallel Group**: Wave 2 (alone)
  - **Blocks**: Tasks 7, 8
  - **Blocked By**: Task 5（依赖新的 monitor_core API）

  **References**:
  - `backend/monitor_service.py` — 完整文件，全量理解
  - `backend/main.py:MonitorService` 的使用方式（`service.start_monitoring()` 等）
  - `backend/monitor_service.py:_push_log()` (~L115-121) — 跨线程 asyncio 调用
  - `backend/monitor_service.py:run_manual_login()` (~L336-377) — 需要简化的重实例化
  - `backend/monitor_service.py:get_status()` (~L310-334) — 当前返回格式
  - `backend/monitor_service.py:set_event_loop()` (~L105) — 删除
  - Python docs: `queue.Queue` — 线程安全的有界队列

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: Monitor start/stop/login works through Actor model
    Tool: Bash (curl)
    Preconditions: app.py running
    Steps:
      1. POST /api/monitor/start → 200
      2. POST /api/actions/login → 200 with result
      3. POST /api/monitor/stop → 200
      4. POST /api/monitor/start → 200
      5. POST /api/monitor/stop → 200
    Expected Result: All calls succeed, no timeout, no crash
    Evidence: .omo/evidence/monitor-actor-refactor/task-6-basic-cycle.txt

  Scenario: /api/status returns immediately (no queue round-trip)
    Tool: Bash (curl with timing)
    Preconditions: app.py running
    Steps:
      1. time curl -s http://127.0.0.1:50721/api/status
      2. Check timing: real < 100ms
    Expected Result: Response time < 100ms (direct read from StatusSnapshot)
    Evidence: .omo/evidence/monitor-actor-refactor/task-6-status-latency.txt

  Scenario: No run_coroutine_threadsafe calls remain
    Tool: grep
    Preconditions: monitor_service.py source
    Steps:
      1. grep -n "run_coroutine_threadsafe" backend/monitor_service.py
      2. grep -n "call_soon_threadsafe" backend/monitor_service.py
    Expected Result: Zero matches
    Evidence: .omo/evidence/monitor-actor-refactor/task-6-no-cross-asyncio.txt

  Scenario: Config changes rejected while monitoring is running
    Tool: Bash (curl)
    Preconditions: app.py running, monitoring active
    Steps:
      1. POST /api/monitor/start
      2. PUT /api/profiles/default with modified config
      3. Verify: 400 or 409 with message "监控运行时不能修改配置，请先停止监控"
    Expected Result: Config change rejected with clear message
    Evidence: .omo/evidence/monitor-actor-refactor/task-6-config-rejected.txt
  ```

  **Commit**: YES
  - Message: `refactor: MonitorService Actor 模型重构 — queue 命令通道，拉式日志，消除跨线程 asyncio`
  - Files: `backend/monitor_service.py`
  - Pre-commit: `uv run ruff check . --quiet`

- [x] 7. **login 并发守卫** — `backend/main.py`

  **What to do**:
  - `POST /api/actions/login`: 在入口检查是否已有 login 进行中
  - 在 `MonitorService` 上添加 `_login_in_progress: bool` 标志
  - 如果 login 正在进行，返回 `{"success": False, "message": "登录操作正在进行中，请稍后再试"}` 状态码 409
  - login 完成后（不论成功失败）重置标志
  - 确保即使 login 抛出异常，标志也会被重置（try/finally）

  **Must NOT do**:
  - 不要添加 `threading.Lock`（`_login_in_progress` 是简单的 bool 标志，在 API 线程同步上下文中已天然串行）
  - 不要改动其他路由

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 单点改动，~5 行代码
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3 (with Task 8)
  - **Blocks**: None
  - **Blocked By**: Task 6（login 走新的 Actor 路径）

  **References**:
  - `backend/main.py:POST /api/actions/login` — 当前 handler
  - `backend/monitor_service.py:run_manual_login()` — 被调用的方法

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: Concurrent login requests — second is rejected
    Tool: Bash (parallel curl)
    Preconditions: app.py running
    Steps:
      1. Send 2 POST /api/actions/login simultaneously: curl -X POST ... & curl -X POST ...
      2. Collect both responses
      3. Assert: one returns success/failure normally, one returns 409
    Expected Result: No concurrent login executions, no duplicate browser processes
    Evidence: .omo/evidence/monitor-actor-refactor/task-7-concurrent-login.txt
  ```

  **Commit**: YES
  - Message: `fix: POST /api/actions/login 加并发守卫，防止多浏览器实例`
  - Files: `backend/main.py`
  - Pre-commit: `uv run ruff check . --quiet`

- [x] 8. **集成验证** — 全模块端到端测试

  **What to do**:
  - 运行 `uv run pytest` 确认现有测试全部通过
  - 运行 `uv run ruff check . --quiet` 确认 lint 通过
  - 启动 app.py，验证所有核心 API 路径可用:
    - `/api/health`, `/api/status`, `/api/config`
    - `/api/monitor/start`, `stop` 循环
    - `/api/actions/login`
    - `/api/shutdown`
  - 验证 WS `/ws/logs` 正常广播（用 Python 短脚本订阅）
  - 验证快速 start/stop 循环不崩溃
  - 验证信号 `SIGTERM` 正常退出

  **Must NOT do**:
  - 不改任何代码（纯验证）
  - 不改测试基础设施

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: 需要端到端验证多个模块协作
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3 (with Task 7)
  - **Blocks**: F1-F4
  - **Blocked By**: Task 6

  **References**:
  - 本计划的所有 Deliverables
  - `tests/` 目录

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY)**:
  ```
  Scenario: All existing pytest tests pass
    Tool: Bash
    Preconditions: uv sync completed
    Steps:
      1. uv run pytest -v 2>&1
      2. Check exit code 0
    Expected Result: All tests pass
    Evidence: .omo/evidence/monitor-actor-refactor/task-8-pytest.txt

  Scenario: Full integration check — start → status → stop → shutdown
    Tool: Bash (curl sequence)
    Preconditions: app.py running
    Steps:
      1. curl /api/health → 200
      2. curl /api/status → 200, monitoring=false
      3. curl -X POST /api/monitor/start → 200
      4. curl /api/status → 200, monitoring=true
      5. curl -X POST /api/monitor/stop → 200
      6. curl /api/status → 200, monitoring=false
      7. Rapid cycle: start → stop → start → stop (all within 2s)
      8. curl -X POST /api/shutdown → 200
      9. Verify process exited within 5s
    Expected Result: All API calls return 200, rapid cycle no crash, process exits
    Evidence: .omo/evidence/monitor-actor-refactor/task-8-integration.txt
  ```

  **Commit**: NO（验证不改代码）

---

## Final Verification Wave (MANDATORY)

> 4 review agents run in PARALLEL. ALL must APPROVE. Present consolidated results to user and get explicit "okay" before completing.

- [x] F1. **Plan Compliance Audit** — `oracle`
  Read the plan end-to-end. For each "Must Have": verify implementation exists (read file, curl endpoint, run command). For each "Must NOT Have": search codebase for forbidden patterns — reject with file:line if found. Check evidence files exist. Compare deliverables against plan.
  Output: `Must Have [N/N] | Must NOT Have [N/N] | Tasks [N/N] | VERDICT: APPROVE/REJECT`

- [x] F2. **Code Quality Review** — `unspecified-high`
  Run `ruff check .` + `ruff format --check .` + `uv run pytest`. Review all changed files for: empty catches (`except: pass`), `sys.exit(0)` vs `os._exit(0)` confusion, unused imports, dead code. Check AI slop: over-abstraction, generic names.
  Output: `Lint [PASS/FAIL] | Format [PASS/FAIL] | Tests [N pass/N fail] | Files [N clean/N issues] | VERDICT`

- [x] F3. **Real Manual QA** — `unspecified-high` (+ `playwright` skill)
  Start from clean state. Execute EVERY QA scenario from EVERY task — follow exact steps, capture evidence. Test cross-task integration (features working together, not isolation). Test edge cases: empty state, rapid start/stop, concurrent requests.
  Save to `.omo/evidence/final-qa/`.
  Output: `Scenarios [N/N pass] | Integration [N/N] | Edge Cases [N tested] | VERDICT`

- [x] F4. **Scope Fidelity Check** — `deep`
  For each task: read "What to do", read actual diff (git diff). Verify 1:1 — everything in spec was built (no missing), nothing beyond spec was built (no creep). Check "Must NOT do" compliance. Flag cross-task contamination (Task N touching files outside its scope).
  Output: `Tasks [N/N compliant] | Contamination [CLEAN/N issues] | Unaccounted [CLEAN/N files] | VERDICT`

---

## Commit Strategy

- **Task 1**: `chore: 简化 Signal handler 为 os._exit(0)，移除 set_event_loop`
  - Files: `app.py`, `backend/main.py`
- **Task 2**: `fix: 修复 DateRotatingFileHandler close/emit 竞态，简化 deferred-open`
  - Files: `src/utils/logging.py`
- **Task 3**: `fix: 修复 login.py dialog handler 泄漏，暴露 browser ignore_https_errors 配置项`
  - Files: `src/utils/login.py`, `src/utils/browser.py`
- **Task 4**: `fix: 修复 network_test TOCTOU 和 thread-local httpx 缓存泄漏`
  - Files: `src/network_test.py`
- **Task 5**: `refactor: 移除 monitor_core _loop/_loop_stopped 暴露，简化 attempt_login task 追踪`
  - Files: `src/monitor_core.py`
- **Task 6**: `refactor: MonitorService Actor 模型重构 — queue.Queue 命令通道，拉式日志，消除跨线程 asyncio`
  - Files: `backend/monitor_service.py`
- **Task 7**: `fix: POST /api/actions/login 加并发守卫，防止多浏览器`
  - Files: `backend/main.py`
- **Task 8**: 无提交（集成验证，不改代码）

---

## Success Criteria

### Verification Commands
```bash
# 零跨线程 asyncio
grep -rn "run_coroutine_threadsafe" backend/ src/        # Expected: 0
grep -rn "set_event_loop" backend/main.py                # Expected: 0
grep -rn "_loop_stopped" src/ backend/                   # Expected: 0

# 单锁原则 — 只允许 logging 的 _emit_lock
grep -rn "threading\.Lock\|threading\.RLock\|asyncio\.Lock" backend/ src/  # Expected: only src/utils/logging.py

# 测试
uv run pytest                                            # Expected: all pass

# Lint
uv run ruff check . --quiet                              # Expected: exit 0
uv run ruff format . --check --quiet                     # Expected: exit 0
```

### Final Checklist
- [ ] Zero `run_coroutine_threadsafe` calls remain
- [ ] Zero `set_event_loop` calls in main.py
- [ ] Zero `_loop_stopped` attribute across codebase
- [ ] Only 1 threading lock remains (`_emit_lock` in logging.py)
- [ ] Signal handler calls only `os._exit(0)`
- [ ] All Must Have satisfied, all Must NOT Have absent
- [ ] All existing pytest tests pass
