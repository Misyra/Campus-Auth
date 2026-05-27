# Playwright Worker Loop 重构计划

## TL;DR

> **核心目标**: 创建独立 `PlaywrightWorker` 模块，用常驻守护线程 + 持久 asyncio 事件循环统一管理所有 Playwright 操作，消除 "different loop" 崩溃根因，修复 8 个未修 Bug。
> 
> **交付物**:
> - `src/playwright_worker.py`: 新 Worker 模块（常驻线程、命令派发、浏览器生命周期管理）
> - `src/utils/browser.py`: 修复 _cleanup_browser 异常吞没（Bug #8）
> - `src/monitor_core.py`: 重构 attempt_login 通过 Worker 派发（Bug #1 根治）
> - `backend/main.py`: DebugSession 路由到 Worker（Bug #5 根治）
> - `app.py`: login_then_exit 路由到 Worker、Worker 初始化/关闭钩子
> - `tests/test_playwright_worker.py`: Worker 模块单元测试
> - `tests/test_integration_worker.py`: 集成测试
> 
> **预估工作量**: Large
> **并行执行**: YES - 5 波次
> **关键路径**: Task 1 → Task 5 → Task 6 → Task 11 → Task 12 → F1-F4

---

## Context

### Original Request
用户要求修复所有未修的 Playwright 相关问题，常驻 Worker 线程方案（方案 A），全部 Playwright 操作走 Worker，Worker 统一管理浏览器复用，加上必要的中文注释。

### Interview Summary
**Key Discussions**:
- 架构方案选择: 独立模块（方案 A）胜出 — 所有 Playwright 路径统一走 Worker
- 资源开销确认: 常驻线程 ~10-15MB 内存，0% CPU，可忽略
- 测试策略: tests-after（重构完成后补充测试）
- 中文注释: 所有关键实现处必须加上

**Research Findings**:
- 3 处 `async_playwright()` 调用（browser.py、main.py DebugSession、bootstrap 安装检查）
- 2 处 `sync_playwright()` 调用（仅安装检查，不受影响）
- 核心崩溃根因: `monitor_core.py:553` 每次登录创建 `asyncio.new_event_loop()` 后关闭，Playwright 对象绑定到已关闭 loop
- `monitor_service.py` 已使用 Actor 模型（queue.Queue 命令派发），Worker 应复用此模式
- `MonitorService._login_in_progress` 是无锁 bool，存在竞态条件

### Metis Review
**Identified Gaps** (addressed):
- Worker 线程生命周期管理: uvicorn 启动前初始化，关闭时优雅清理
- Cancel 事件传播: threading.Event → asyncio.Event 桥接机制
- DebugSession page 对象跨线程问题: TaskExecutor 在 Worker 线程内执行
- Worker 崩溃恢复: 浏览器进程孤儿检测 + 自动重建机制

---

## Work Objectives

### Core Objective
创建 `src/playwright_worker.py` 独立模块，用常驻守护线程持有单个持久 asyncio 事件循环，通过 `queue.Queue` 命令派发模式（与 MonitorService 一致）统一管理所有 Playwright 操作，根治跨 loop 复用崩溃和 8 个相关 Bug。

### Concrete Deliverables
- `src/playwright_worker.py`: Worker 模块（命令类型、结果类型、浏览器生命周期、健康检查、取消传播）
- 修改 `src/monitor_core.py`: attempt_login 通过 Worker 派发
- 修改 `backend/monitor_service.py`: manual login 通过 Worker 派发
- 修改 `backend/main.py`: DebugSession 路由到 Worker
- 修改 `app.py`: login_then_exit 路由到 Worker + Worker 生命周期钩子
- 修改 `src/utils/browser.py`: 修复 Bug #8 异常吞没
- `tests/test_playwright_worker.py`: Worker 模块单元测试
- `tests/test_integration_worker.py`: 集成测试

### Definition of Done
- [ ] `uv run pytest tests/test_playwright_worker.py tests/test_integration_worker.py -v` 全部通过
- [ ] `uv run ruff check src/playwright_worker.py src/monitor_core.py backend/main.py app.py` 无错误
- [ ] 手动启动服务后触发登录/监控/调试三种路径均正常工作
- [ ] 无 `asyncio.new_event_loop()` 或 `async_playwright().start()` 在 Worker 管理的路径上残留

### Must Have
- 所有 Playwright 操作（监控登录、手动登录、调试模式、login_then_exit）通过 Worker 派发
- Worker 使用常驻守护线程 + 持久 asyncio 事件循环（永不关闭 loop）
- 命令派发使用 `queue.Queue`（与 MonitorService Actor 模型一致）
- Worker 管理浏览器生命周期（启动、健康检查、重连、关闭）
- 取消机制: `threading.Event` → Worker 内 `asyncio.Event` 桥接
- 关键实现处加中文注释
- 修复 Bug #1-#8 全部
- Bug #9 (close_browser __aexit__ 模式) 改为 Worker 管理的生命周期

### Must NOT Have (Guardrails)
- 不使用 `asyncio.run_coroutine_threadsafe()` 或 `call_soon_threadsafe()` 跨线程调用（AGENTS.md 反模式）
- 不使用 `sys.exit(0)` 在 Worker 守护线程中（AGENTS.md 反模式，用 `os._exit(0)` 替代）
- 不在 Worker 线程间传递 Playwright page 对象（page 不可跨线程）
- 不修改前端代码、任务模板 JSON、配置 schema
- 不修改 `sync_playwright()` 安装检查（`playwright_bootstrap.py` 和 `launcher.py`）
- 不添加新的配置项控制 Worker 行为（自动管理，无需手动配置）
- 不引入 `asyncio.run()` 在监控线程中创建新事件循环

---

## Verification Strategy (MANDATORY)

> **ZERO HUMAN INTERVENTION** - ALL verification is agent-executed. No exceptions.

### Test Decision
- **Infrastructure exists**: YES (pytest in `tests/`)
- **Automated tests**: Tests-after
- **Framework**: pytest
- **Strategy**: 重构完成后补充单元测试 + 集成测试

### QA Policy
Every task MUST include agent-executed QA scenarios.
Evidence saved to `.omo/evidence/task-{N}-{scenario-slug}.{ext}`.

- **Backend/API**: Use Bash (curl) — Send requests, assert status + response fields
- **Library/Module**: Use Bash (uv run python -c) — Import, call functions, compare output
- **Code Quality**: Use Bash (uv run ruff check + uv run pytest)

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 1 (Start Immediately — foundation + pre-Worker bug fixes):
├── Task 1: PlaywrightWorker module skeleton [quick]
├── Task 2: Fix _cleanup_browser exception swallowing — Bug #8 [quick]
├── Task 3: Fix reuse_browser never resets — Bug #7 [quick]
└── Task 4: Fix orphaned browser on shutdown — Bug #6 [quick]

Wave 2 (After Wave 1 — core Worker implementation):
└── Task 5: Implement PlaywrightWorker full logic [deep]
    (depends: 1)

Wave 3 (After Wave 2 — route all paths through Worker):
├── Task 6: Route monitor login through Worker [unspecified-high]
├── Task 7: Route manual login through Worker [unspecified-high]
├── Task 8: Route DebugSession through Worker [unspecified-high]
├── Task 9: Route login_then_exit through Worker [unspecified-high]
└── Task 10: Replace BrowserContextManager lifecycle with Worker [unspecified-high]
    (all depend on 5)

Wave 4 (After Wave 3 — testing):
├── Task 11: Worker module unit tests [unspecified-high]
└── Task 12: Integration tests (monitor, manual, debug paths) [unspecified-high]
    (depend on all Wave 3 tasks)

Wave FINAL (After ALL tasks — 4 parallel reviews):
├── Task F1: Plan compliance audit (oracle)
├── Task F2: Code quality review (unspecified-high)
├── Task F3: Real manual QA (unspecified-high)
└── Task F4: Scope fidelity check (deep)

Critical Path: Task 1 → Task 5 → Tasks 6-10 → Tasks 11-12 → F1-F4
Parallel Speedup: ~60% faster than sequential
Max Concurrent: 5 (Waves 1 & 3)
```

### Dependency Matrix

| Task | Depends On | Blocks |
|------|-----------|--------|
| 1 | - | 5 |
| 2 | - | - |
| 3 | - | - |
| 4 | - | - |
| 5 | 1 | 6, 7, 8, 9, 10 |
| 6 | 5 | 11, 12 |
| 7 | 5 | 11, 12 |
| 8 | 5 | 11, 12 |
| 9 | 5 | 11, 12 |
| 10 | 5 | 11, 12 |
| 11 | 6, 7, 8, 9, 10 | F1-F4 |
| 12 | 6, 7, 8, 9, 10 | F1-F4 |

### Agent Dispatch Summary

- **Wave 1**: 4 tasks — T1 `quick`, T2-T4 `quick`
- **Wave 2**: 1 task — T5 `deep`
- **Wave 3**: 5 tasks — T6-T10 `unspecified-high`
- **Wave 4**: 2 tasks — T11-T12 `unspecified-high`
- **FINAL**: 4 tasks — F1 `oracle`, F2-F3 `unspecified-high`, F4 `deep`

---

## TODOs

- [x] 1. PlaywrightWorker 模块骨架

  **What to do**:
  - 创建 `src/playwright_worker.py`，定义核心数据结构和接口骨架
  - 定义 `WorkerCommand` dataclass（type: str, data: dict, response_event: threading.Event, response_data: Any）— 与 MonitorService 的 `MonitorCommand` 模式一致
  - 定义 `WorkerResponse` dataclass（success: bool, data: Any, error: str | None）
  - 定义 `PlaywrightWorker` 类骨架：`__init__`、`start`、`stop`、`submit` 方法签名
  - 定义命令类型常量：`CMD_LOGIN`、`CMD_DEBUG_START`、`CMD_DEBUG_STEP`、`CMD_DEBUG_STOP`、`CMD_BROWSER_HEALTH_CHECK`、`CMD_SHUTDOWN`
  - 添加中文模块文档字符串，说明 Worker 的 Actor 模型架构
  - 添加 `get_worker()` 全局单例获取函数签名（类似 MonitorService 的模块级初始化模式）

  **Must NOT do**:
  - 不实现实际 Playwright 操作逻辑（仅骨架）
  - 不引入 `asyncio.run_coroutine_threadsafe`

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 2, 3, 4)
  - **Blocks**: Task 5
  - **Blocked By**: None

  **References**:

  **Pattern References** (existing code to follow):
  - `backend/monitor_service.py:34-41` — `MonitorCommand` dataclass 的 Actor 模式命令定义，Worker 应复用此模式
  - `backend/monitor_service.py:112-154` — MonitorService 构造函数中启动 `_consumer_thread` 守护线程的模式

  **API/Type References**:
  - `src/utils/browser.py:63-256` — `BrowserContextManager` 类，了解当前浏览器管理的接口（playwright, browser, context, page 属性）

  **WHY Each Reference Matters**:
  - MonitorCommand 模式是新 Worker 命令定义的直系模板 — 必须跟随同样的 dataclass + Event 模式
  - MonitorService 的守护线程启动模式是 Worker 线程生命周期管理的参考

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: 模块可导入且数据结构可用
    Tool: Bash (uv run python -c)
    Preconditions: 项目环境已安装
    Steps:
      1. 执行 `uv run python -c "from src.playwright_worker import PlaywrightWorker, WorkerCommand, WorkerResponse; print('OK')"`
      2. 断言输出包含 "OK"
    Expected Result: 模块导入成功，无 ImportError
    Failure Indicators: ModuleNotFoundError, ImportError, SyntaxError
    Evidence: .omo/evidence/task-1-import-check.txt

  Scenario: WorkerCommand 数据结构可实例化
    Tool: Bash (uv run python -c)
    Preconditions: 步骤 1 通过
    Steps:
      1. 执行 `uv run python -c "from src.playwright_worker import WorkerCommand; cmd = WorkerCommand(type='login', data={}); print(cmd.type)"`
      2. 断言输出为 "login"
    Expected Result: WorkerCommand 实例化正常
    Failure Indicators: TypeError, AttributeError
    Evidence: .omo/evidence/task-1-command-struct.txt
  ```

  **Commit**: YES (group with Wave 1)
  - Message: `feat: 创建 PlaywrightWorker 模块骨架`
  - Files: `src/playwright_worker.py`
  - Pre-commit: `uv run ruff check src/playwright_worker.py`

- [x] 2. 修复 _cleanup_browser 异常吞没 — Bug #8

  **What to do**:
  - 修改 `src/utils/browser.py` 的 `_cleanup_browser` 方法
  - 当前代码: 所有异常只 `self.logger.warning` 不 re-raise（第 251-254 行）
  - 修改为: 区分正常关闭异常和意外异常。正常关闭时的 `Playwright` 内部异常（如连接已断开）仅 warning；意外异常应该 re-raise 或至少记录为 ERROR 级别
  - 添加 `is_connected()` 检查：在尝试关闭 browser 之前，先检查 `self.browser.is_connected()`（如果 browser 对象存在），避免对已崩溃的浏览器执行关闭操作 — Bug #4 关联
  - 添加中文注释说明每种异常的处理策略

  **Must NOT do**:
  - 不改变 `__aexit__` 的返回值（仍返回 False 不抑制异常）
  - 不引入新的依赖

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1, 3, 4)
  - **Blocks**: None
  - **Blocked By**: None

  **References**:

  **Pattern References**:
  - `src/utils/browser.py:218-256` — `_cleanup_browser` 方法的当前实现，所有异常只 warning 不 re-raise
  - `src/utils/browser.py:88-101` — `__aenter__` 和 `__aexit__` 调用 `_cleanup_browser()` 的模式

  **WHY Each Reference Matters**:
  - 这就是要修复的代码 — Bug #8 的唯一位置

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: is_connected 检查在关闭前执行
    Tool: Bash (uv run python -c)
    Steps:
      1. 执行 `uv run python -c "from src.utils.browser import BrowserContextManager; import inspect; src = inspect.getsource(BrowserContextManager._cleanup_browser); print('is_connected' in src)"`
      2. 断言输出为 "True"
    Expected Result: _cleanup_browser 代码包含 is_connected() 检查
    Failure Indicators: 输出 "False"
    Evidence: .omo/evidence/task-2-connected-check.txt

  Scenario: 异常不再被静默吞没
    Tool: Bash (uv run ruff check)
    Steps:
      1. 执行 `uv run ruff check src/utils/browser.py`
      2. 断言退出码为 0
    Expected Result: ruff 检查通过
    Failure Indicators: lint 错误
    Evidence: .omo/evidence/task-2-lint.txt
  ```

  **Commit**: YES (group with Wave 1 fixes)
  - Message: `fix: 修复 _cleanup_browser 异常吞没, 添加 is_connected() 健康检查`
  - Files: `src/utils/browser.py`
  - Pre-commit: `uv run ruff check src/utils/browser.py`

- [x] 3. 修复 reuse_browser 永不重置 — Bug #7

  **What to do**:
  - 修改 `src/monitor_core.py` 的 `start_monitoring` / `stop_monitoring` / `_login_recovery_loop` 方法
  - 当前问题: `_reuse_browser = True` 在 `start_monitoring()` 设置（第 144 行），直到 `stop_monitoring()` 才清除。中间登录失败不会重置此标志，导致复用已崩溃的浏览器实例
  - 修改为: 在 `attempt_login()` 失败后重置 `_reuse_browser = False`，确保下次登录使用全新浏览器实例
  - 在 `attempt_login()` 成功后也可以保留 `_reuse_browser = True`（正常复用逻辑）
  - 同时修复 `_login_in_progress` 竞态条件：`MonitorService._login_in_progress` 是无锁 bool（第 148 行），改为 threading.Lock 保护或使用 atomic 操作

  **Must NOT do**:
  - 不改变 MonitorService 的 Actor 模式架构
  - 不引入 asyncio 操作

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1, 2, 4)
  - **Blocks**: None
  - **Blocked By**: None

  **References**:

  **Pattern References**:
  - `src/monitor_core.py:84-85` — `_login_handler` 和 `_reuse_browser` 的定义位置
  - `src/monitor_core.py:144` — `start_monitoring()` 中设置 `_reuse_browser = True`
  - `src/monitor_core.py:527-583` — `attempt_login()` 方法，此处需添加失败后的重置逻辑
  - `backend/monitor_service.py:148` — `_login_in_progress: bool` 无锁竞态风险

  **WHY Each Reference Matters**:
  - Bug #7 的根因位置: `_reuse_browser` 设置后永不重置
  - 竞态条件位置: `_login_in_progress` 需要 Lock 保护

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: _reuse_browser 在登录失败后重置为 False
    Tool: Bash (uv run python -c)
    Steps:
      1. 执行 `uv run python -c "from src.monitor_core import NetworkMonitorCore; import inspect; src = inspect.getsource(NetworkMonitorCore.attempt_login); print('reuse_browser' in src)"`
      2. 断言输出为 "True"，确认 attempt_login 中引用了 reuse_browser
    Expected Result: attempt_login 方法中包含 _reuse_browser 相关逻辑
    Failure Indicators: 输出 "False"
    Evidence: .omo/evidence/task-3-reuse-reset.txt

  Scenario: _login_in_progress 有线程安全保护
    Tool: Bash (uv run python -c)
    Steps:
      1. 执行 `uv run python -c "from backend.monitor_service import MonitorService; import inspect; src = inspect.getsource(MonitorService.__init__); print('Lock' in src or 'lock' in src)"`
      2. 断言输出为 "True"
    Expected Result: MonitorService 初始化中包含 Lock 变量
    Failure Indicators: 输出 "False"
    Evidence: .omo/evidence/task-3-lock-check.txt
  ```

  **Commit**: YES (group with Wave 1 fixes)
  - Message: `fix: 登录失败后重置 _reuse_browser, 添加 _login_in_progress 线程安全保护`
  - Files: `src/monitor_core.py`, `backend/monitor_service.py`
  - Pre-commit: `uv run ruff check src/monitor_core.py backend/monitor_service.py`

- [x] 4. 修复关闭时浏览器进程残留 — Bug #6

  **What to do**:
  - 修改 `app.py` 和 `backend/main.py` 的关闭流程
  - 当前问题: `os._exit(0)` 在 `/api/shutdown` 端点（`backend/main.py` 第 1110 行）立即终止进程，不给 Playwright 清理机会
  - 修改 `backend/main.py` 的 `lifespan` 函数：在 yield 之前添加 PlaywrightWorker 关闭逻辑（如果 Worker 已初始化）
  - 修改 `app.py` 的 `_run_login_then_exit`: 确保登录后清理 Worker（成功或失败都要清理）
  - 添加 `_force_cleanup_orphan_browsers()` 辅助函数：在启动时扫描并杀掉残留的 Chromium 进程（Windows 用 `taskkill`，Linux/macOS 用 `pkill`），仅清理 Campus-Auth 启动的实例（通过进程参数匹配）

  **Must NOT do**:
  - 不修改 `os._exit(0)` 为 `sys.exit(0)`（AGENTS.md 反模式）
  - 不引入新的进程管理依赖（psutil 等）
  - 不杀掉非 Campus-Auth 的 Chromium 进程

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1, 2, 3)
  - **Blocks**: None
  - **Blocked By**: None

  **References**:

  **Pattern References**:
  - `backend/main.py:71-131` — `lifespan` 函数中的清理逻辑
  - `backend/main.py:1092-1114` — `/api/shutdown` 端点中的强制退出
  - `app.py:284-360` — `_run_login_then_exit` 函数

  **WHY Each Reference Matters**:
  - lifespan 是 uvicorn 生命周期钩子 — Worker 关闭应在此处注册
  - shutdown 端点的 `os._exit(0)` 无法绕过，需要在退出前先发关闭命令
  - login_then_exit 也需要清理 Worker

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: lifespan 中有 Worker 关闭调用
    Tool: Bash (uv run python -c)
    Steps:
      1. 执行 `uv run python -c "from backend.main import lifespan; import inspect; src = inspect.getsource(lifespan); print('worker' in src.lower())"`
      2. 断言输出为 "True"
    Expected Result: lifespan 函数中包含 worker 相关的关闭逻辑
    Failure Indicators: "False" — 未包含 worker 关闭
    Evidence: .omo/evidence/task-4-shutdown-cleanup.txt

  Scenario: 孤儿浏览器检查函数存在
    Tool: Bash (uv run python -c)
    Steps:
      1. 执行 `uv run python -c "from src.playwright_worker import cleanup_orphan_browsers; print('OK')"`
      2. 断言输出为 "OK"
    Expected Result: cleanup_orphan_browsers 函数可导入
    Failure Indicators: ImportError
    Evidence: .omo/evidence/task-4-orphan-cleanup.txt
  ```

  **Commit**: YES (group with Wave 1 fixes)
  - Message: `fix: 添加浏览器进程孤儿清理和 Worker 关闭钩子`
  - Files: `backend/main.py`, `app.py`, `src/playwright_worker.py`
  - Pre-commit: `uv run ruff check backend/main.py app.py`

- [x] 5. 实现 PlaywrightWorker 完整逻辑

  **What to do**:
  - 在 `src/playwright_worker.py` 骨架（Task 1）基础上实现完整的 Worker 逻辑
  - **常驻守护线程**: `threading.Thread(target=self._worker_loop, daemon=True)`，线程函数内部运行 `asyncio.new_event_loop()` + `loop.run_forever()`，空闲时阻塞在 Queue 上，不做任何 CPU 操作
  - **命令派发**: `_worker_loop` 从 `self._cmd_queue` 获取 `WorkerCommand`，通过 `asyncio.run_coroutine_threadsafe()` 在 Worker 的 event loop 上调度对应的异步处理函数（注意: 此处使用 `run_coroutine_threadsafe` 是 Worker 内部从 Queue consumer 线程向 Worker 自己的 loop 提交协程，不是跨线程调用外部 loop — 这是 Playwright 官方推荐模式）
  - **浏览器生命周期管理**:
    - `async _start_browser()`: 按 config 启动 Chromium（headless/safe_mode/自定义参数），创建 context 和 page
    - `async _health_check()`: 检查 `browser.is_connected()`，失败时自动重建浏览器实例 — Bug #2 + #3
    - `async _close_browser()`: 按顺序关闭 page → context → browser → playwright stop，每步检查 `is_connected()` — Bug #4
    - `async _force_cleanup()`: 强制清理方法，用于 Worker 关闭和浏览器崩溃恢复
  - **取消事件桥接**: `_cancel_event_threading` (threading.Event) → 在 Worker loop 内创建 `asyncio.Event` 副本，`_bridge_cancel()` 方法将 threading.Event 状态同步到 asyncio.Event
  - **结果传递**: command.response_event.set() + command.response_data = result，与 MonitorService 模式一致
  - **中文注释**: 所有关键方法添加中文行注释，模块级文档字符串说明架构

  **Must NOT do**:
  - 不使用 `asyncio.run_coroutine_threadsafe()` 从外部线程向 Worker loop 提交任务（只允许 Worker 内部的 Queue consumer → own loop 桥接）
  - 不在 Worker 线程间传递 Playwright page 对象
  - 不使用 `asyncio.run()` 在 Worker 线程中创建新 loop（Worker 持有一个持久 loop）

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Sequential (Wave 2)
  - **Blocks**: 6, 7, 8, 9, 10
  - **Blocked By**: 1

  **References**:

  **Pattern References**:
  - `backend/monitor_service.py:112-154` — MonitorService `__init__` 中启动 `_consumer_thread` 守护线程的模式 — Worker 应复用此模式
  - `backend/monitor_service.py:158-183` — `_queue_consumer` 方法从 Queue 获取命令并派发的模式 — Worker 的 `_worker_loop` 应类似
  - `backend/monitor_service.py:230-254` — `_handle_login` 方法中同步执行登录并返回结果的模式 — Worker 的 login 命令处理应类似
  - `src/utils/browser.py:103-167` — `_start_browser` 方法：headless/safe_mode 参数处理、browser args 构建、context 创建 — Worker 应复用此逻辑
  - `src/utils/browser.py:218-256` — `_cleanup_browser` 方法（Task 2 已修复版）— Worker 应复用此关闭序列

  **API/Type References**:
  - `src/utils/browser.py:66-87` — BrowserContextManager 构造函数参数: config, cancel_event
  - `src/utils/login.py` — `LoginAttemptHandler` 接口: `attempt_login(reuse_browser, skip_pause_check)` → 返回 `(bool, str)`

  **Test References**:
  - `tests/test_network_test.py` — 项目测试模式参考（pytest + 类组织）

  **WHY Each Reference Matters**:
  - MonitorService 是 Worker 最直接的架构模板 — 相同的 Actor 模式、Queue、守护线程
  - BrowserContextManager 包含所有浏览器启动参数逻辑 — 需要迁移到 Worker 内部
  - LoginAttemptHandler 是 Worker 需要调用的核心登录逻辑

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: Worker 线程启动和停止
    Tool: Bash (uv run python -c)
    Preconditions: 项目环境已安装
    Steps:
      1. 执行 `uv run python -c "
from src.playwright_worker import PlaywrightWorker
w = PlaywrightWorker()
w.start()
import time; time.sleep(0.5)
print(f'alive={w.is_alive()}')
w.stop(timeout=5)
print(f'alive={w.is_alive()}')
"`
      2. 断言第一行包含 "alive=True"，第二行包含 "alive=False"
    Expected Result: Worker 线程能正常启动和停止
    Failure Indicators: 线程无法启动或停止超时
    Evidence: .omo/evidence/task-5-start-stop.txt

  Scenario: Worker 处理 SHUTDOWN 命令后不再接受新命令
    Tool: Bash (uv run python -c)
    Steps:
      1. 执行 `uv run python -c "
from src.playwright_worker import PlaywrightWorker, WorkerCommand
w = PlaywrightWorker()
w.start()
import time; time.sleep(0.3)
w.stop(timeout=5)
cmd = WorkerCommand(type='login', data={})
result = w.submit(cmd, timeout=2)
print(f'result={result}')
"`
      2. 断言 result 包含错误信息（Worker 已关闭不接受命令）
    Expected Result: Worker 关闭后提交命令返回错误
    Failure Indicators: 提交成功或挂起
    Evidence: .omo/evidence/task-5-shutdown-reject.txt
  ```

  **Commit**: YES
  - Message: `feat: 实现 PlaywrightWorker 完整逻辑（浏览器生命周期、健康检查、命令派发）`
  - Files: `src/playwright_worker.py`
  - Pre-commit: `uv run ruff check src/playwright_worker.py`

- [ ] 6. 路由监控登录到 Worker

  **What to do**:
  - 修改 `src/monitor_core.py` 的 `attempt_login()` 方法
  - **删除** 第 553-562 行的 `asyncio.new_event_loop()` + `loop.run_until_complete()` + `loop.close()` 模式
  - 替换为: 通过 `get_worker().submit(WorkerCommand(type='login', data={...}))` 提交登录命令到 Worker
  - 修改 `NetworkMonitorCore.__init__` 接受 `worker` 参数（或使用 `get_worker()` 全局单例）
  - 处理 `_cancel_login` Event 的桥接: Worker 命令的 `data` 字典传入 `cancel_event`，Worker 内部将其桥接到 asyncio.Event
  - 处理 `_reuse_browser` 逻辑: Worker 根据命令数据决定是否复用浏览器实例
  - 添加中文注释说明旧的 asyncio 循环模式已移除

  **Must NOT do**:
  - 不在 monitor_core 中保留任何 `asyncio.new_event_loop()` 调用
  - 不直接创建或管理 Playwright 对象

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3 (with Tasks 7, 8, 9, 10)
  - **Blocks**: 11, 12
  - **Blocked By**: 5

  **References**:

  **Pattern References**:
  - `src/monitor_core.py:527-583` — `attempt_login()` 方法的当前实现，包含需要删除的 `asyncio.new_event_loop()` 模式
  - `src/monitor_core.py:84-85` — `_login_handler` 和 `_reuse_browser` 属性
  - `src/monitor_core.py:142-144` — `start_monitoring()` 中设置 `_reuse_browser = True`

  **WHY Each Reference Matters**:
  - 这是 Bug #1 的根因位置 — 必须完全替换为 Worker 派发模式

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: monitor_core 中无 asyncio.new_event_loop 残留
    Tool: Bash (grep)
    Steps:
      1. 执行 `grep -n "asyncio.new_event_loop" src/monitor_core.py`
      2. 断言退出码为 1（无匹配）
    Expected Result: monitor_core.py 不再包含 asyncio.new_event_loop 调用
    Failure Indicators: 发现残留的 asyncio.new_event_loop 调用
    Evidence: .omo/evidence/task-6-no-new-loop.txt

  Scenario: attempt_login 使用 Worker 派发
    Tool: Bash (uv run python -c)
    Steps:
      1. 执行 `uv run python -c "from src.monitor_core import NetworkMonitorCore; import inspect; src = inspect.getsource(NetworkMonitorCore.attempt_login); print('WorkerCommand' in src or 'submit' in src or 'get_worker' in src)"`
      2. 断言输出为 "True"
    Expected Result: attempt_login 中包含 Worker 相关调用
    Failure Indicators: 仍使用旧的 asyncio 循环模式
    Evidence: .omo/evidence/task-6-worker-dispatch.txt
  ```

  **Commit**: YES (group with Wave 3)
  - Message: `refactor: 监控登录通过 PlaywrightWorker 派发，消除跨 loop 崩溃`
  - Files: `src/monitor_core.py`
  - Pre-commit: `uv run ruff check src/monitor_core.py`

- [ ] 7. 路由手动登录到 Worker

  **What to do**:
  - 修改 `backend/monitor_service.py` 中的 `_handle_login()` 方法
  - 当前实现（第 230-254 行）: 创建临时 `NetworkMonitorCore` 实例并调用 `attempt_login()`
  - 修改为: 通过 `get_worker().submit(WorkerCommand(type='login', data={...}))` 提交登录命令到 Worker
  - 保持 `_login_in_progress` Lock 保护（Task 3 已添加）
  - 保留 `response_event` + `response_data` 等待机制（与 MonitorService 中的 manual login 模式一致）

  **Must NOT do**:
  - 不创建临时 NetworkMonitorCore 实例（Worker 统一管理）
  - 不直接操作 Playwright 对象

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3 (with Tasks 6, 8, 9, 10)
  - **Blocks**: 11, 12
  - **Blocked By**: 5

  **References**:

  **Pattern References**:
  - `backend/monitor_service.py:230-254` — `_handle_login` 方法，当前创建临时 NetworkMonitorCore
  - `backend/monitor_service.py:541-575` — `run_manual_login` 方法中的 `_login_in_progress` 保护和 `response_event` 等待模式

  **WHY Each Reference Matters**:
  - _handle_login 是手动登录的执行点 — 需要改为 Worker 派发
  - run_manual_login 展示了现有的命令等待模式

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: _handle_login 使用 Worker 派发
    Tool: Bash (uv run python -c)
    Steps:
      1. 执行 `uv run python -c "from backend.monitor_service import MonitorService; import inspect; src = inspect.getsource(MonitorService._handle_login); print('get_worker' in src or 'WorkerCommand' in src or 'submit' in src)"`
      2. 断言输出为 "True"
    Expected Result: _handle_login 中包含 Worker 派发逻辑
    Failure Indicators: 仍直接创建 NetworkMonitorCore
    Evidence: .omo/evidence/task-7-manual-login-worker.txt

  Scenario: _handle_login 不再创建临时 NetworkMonitorCore
    Tool: Bash (grep)
    Steps:
      1. 执行 `grep -n "NetworkMonitorCore" backend/monitor_service.py`
      2. 断言只在 import 和类型注解中出现，不在 _handle_login 中出现
    Expected Result: _handle_login 不再创建临时 core 实例
    Failure Indicators: 仍在 _handle_login 中创建 NetworkMonitorCore()
    Evidence: .omo/evidence/task-7-no-temp-core.txt
  ```

  **Commit**: YES (group with Wave 3)
  - Message: `refactor: 手动登录通过 PlaywrightWorker 派发`
  - Files: `backend/monitor_service.py`
  - Pre-commit: `uv run ruff check backend/monitor_service.py`

- [ ] 8. 路由 DebugSession 到 Worker

  **What to do**:
  - 修改 `backend/main.py` 的 `DebugSession` 类和 debug API 端点
  - DebugSession 当前在 FastAPI 的 asyncio loop 中直接运行 `async_playwright().start()`（第 210-212 行）
  - 修改为: DebugSession 不再自己管理 Playwright — 所有 Playwright 操作通过 Worker 派发
  - **关键设计**: page 对象不能跨线程传递。DebugSession 的 step 执行（`executor.execute_step_at(page, idx)`）也必须在 Worker 线程内执行
  - 添加 WorkerCommand 类型: `CMD_DEBUG_START`、`CMD_DEBUG_NEXT`、`CMD_DEBUG_RUN_ALL`、`CMD_DEBUG_STOP`
  - Debug API 端点（`debug_start`、`debug_next`、`debug_run_all`、`debug_stop`）通过 `get_worker().submit()` 提交命令，等待结果
  - 保留 `_debug_lock` 和 `_debug_exec_sem` 的并发保护
  - 保留 `_debug_timeout_watcher` 超时清理机制

  **Must NOT do**:
  - 不在 FastAPI 的事件循环中直接调用 `async_playwright()`
  - 不在 API 线程和 Worker 线程之间传递 page 对象
  - DebugSession 的 TaskExecutor 必须在 Worker 线程内执行

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3 (with Tasks 6, 7, 9, 10)
  - **Blocks**: 11, 12
  - **Blocked By**: 5

  **References**:

  **Pattern References**:
  - `backend/main.py:198-310` — `DebugSession` 类的当前实现，直接管理 Playwright 生命周期
  - `backend/main.py:787-868` — `debug_start` 端点，创建 DebugSession 和 TaskExecutor
  - `backend/main.py:871-888` — `debug_next` 端点，执行单步
  - `backend/main.py:891-913` — `debug_run_all` 端点，执行剩余步骤
  - `backend/main.py:313-315` — `_debug_session` 全局状态和 `_debug_lock`

  **WHY Each Reference Matters**:
  - DebugSession 是 Bug #5（Debug+monitor 同时跑两个 Chromium）的主要原因 — 必须通过 Worker 共享浏览器实例

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: DebugSession 不再包含 async_playwright().start()
    Tool: Bash (grep)
    Steps:
      1. 执行 `grep -n "async_playwright" backend/main.py`
      2. 断言仅在 import 行出现，DebugSession 类内不再直接调用
    Expected Result: DebugSession 不再直接管理 Playwright 实例
    Failure Indicators: DebugSession.start() 中仍有 async_playwright().start()
    Evidence: .omo/evidence/task-8-debug-no-direct-pw.txt

  Scenario: Debug API 端点使用 Worker 派发
    Tool: Bash (uv run python -c)
    Steps:
      1. 执行 `uv run python -c "from backend.main import app; import inspect; src = inspect.getsource(app.routes); print('WorkerCommand' in src or 'get_worker' in src)"`
      2. 断言 True（或通过其他方式验证 debug 端点使用了 Worker）
    Expected Result: Debug API 端点通过 Worker 派发
    Failure Indicators: 仍直接创建 Playwright 实例
    Evidence: .omo/evidence/task-8-debug-worker-dispatch.txt
  ```

  **Commit**: YES (group with Wave 3)
  - Message: `refactor: DebugSession 路由到 PlaywrightWorker（共享浏览器实例，修复双 Chromium 问题）`
  - Files: `backend/main.py`, `src/playwright_worker.py`
  - Pre-commit: `uv run ruff check backend/main.py src/playwright_worker.py`

- [ ] 9. 路由 login_then_exit 到 Worker

  **What to do**:
  - 修改 `app.py` 的 `_run_login_then_exit()` 函数（第 284-360 行）
  - 当前实现: 创建 `asyncio.new_event_loop()` + `loop.run_until_complete()` + `loop.close()`（第 326-344 行）
  - 修改为: 通过 `get_worker().submit(WorkerCommand(type='login', data={...}))` 提交登录命令
  - Worker 应在 uvicorn 启动前就已初始化，login_then_exit 复用 Worker 实例
  - 保留重试逻辑（指数退避）和失败后的回退到正常模式
  - 移除 `asyncio.new_event_loop()` 调用

  **Must NOT do**:
  - 不保留 `asyncio.new_event_loop()` 在 login_then_exit 路径中
  - 不创建临时 Playwright 实例

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3 (with Tasks 6, 7, 8, 10)
  - **Blocks**: 11, 12
  - **Blocked By**: 5

  **References**:

  **Pattern References**:
  - `app.py:284-360` — `_run_login_then_exit()` 函数，包含 `asyncio.new_event_loop()` 使用
  - `app.py:310-311` — 创建 LoginAttemptHandler 实例
  - `app.py:326-344` — asyncio 循环创建、运行、关闭模式

  **WHY Each Reference Matters**:
  - 这是第三处 asyncio.new_event_loop() 调用点 — 也需要通过 Worker 统一管理

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: login_then_exit 中无 asyncio.new_event_loop
    Tool: Bash (grep)
    Steps:
      1. 执行 `grep -n "asyncio.new_event_loop" app.py`
      2. 断言退出码为 1（无匹配）
    Expected Result: app.py 不再包含 asyncio.new_event_loop
    Failure Indicators: 仍有残留调用
    Evidence: .omo/evidence/task-9-no-new-loop.txt

  Scenario: login_then_exit 使用 Worker 派发
    Tool: Bash (uv run python -c)
    Steps:
      1. 执行 `uv run python -c "from app import _run_login_then_exit; import inspect; src = inspect.getsource(_run_login_then_exit); print('WorkerCommand' in src or 'get_worker' in src or 'submit' in src)"`
      2. 断言输出为 "True"
    Expected Result: login_then_exit 中包含 Worker 派发逻辑
    Failure Indicators: 仍使用 asyncio 循环
    Evidence: .omo/evidence/task-9-lte-worker.txt
  ```

  **Commit**: YES (group with Wave 3)
  - Message: `refactor: login_then_exit 通过 PlaywrightWorker 派发`
  - Files: `app.py`
  - Pre-commit: `uv run ruff check app.py`

- [ ] 10. 替换 BrowserContextManager 生命周期为 Worker 管理

  **What to do**:
  - 修改 `src/utils/browser.py` 的 `BrowserContextManager`
  - `BrowserContextManager` 当前独立管理 Playwright 生命周期（`__aenter__` 启动浏览器，`__aexit__` 关闭）
  - 修改为: Worker 成为唯一的浏览器生命周期管理者
  - `BrowserContextManager.__aenter__` 改为向 Worker 请求浏览器上下文（`WorkerCommand(type='browser_acquire')`）
  - `BrowserContextManager.__aexit__` 改为向 Worker 释放浏览器上下文（`WorkerCommand(type='browser_release')`）
  - 保留 `cancel_event` 参数 — 桥接到 Worker 内的 asyncio.Event
  - 添加 `is_connected()` 健康检查 — Bug #3 修复（挂起浏览器检测）
  - 添加中文注释说明 Worker 统一管理浏览器生命周期

  **Must NOT do**:
  - 不在 BrowserContextManager 中直接调用 `async_playwright().start()`
  - 不在 BrowserContextManager 中创建新的 asyncio 事件循环
  - 不破坏 `LoginAttemptHandler` 对 `BrowserContextManager` 的使用接口

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3 (with Tasks 6, 7, 8, 9)
  - **Blocks**: 11, 12
  - **Blocked By**: 5

  **References**:

  **Pattern References**:
  - `src/utils/browser.py:63-101` — `BrowserContextManager` 构造函数和 `__aenter__` / `__aexit__`
  - `src/utils/browser.py:103-167` — `_start_browser` 方法，启动 Playwright + 浏览器
  - `src/utils/login.py` — `LoginAttemptHandler` 使用 `BrowserContextManager` 的方式

  **WHY Each Reference Matters**:
  - BrowserContextManager 是当前浏览器管理的核心 — 必须改为 Worker 代理模式

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: BrowserContextManager 不再直接调用 async_playwright()
    Tool: Bash (grep)
    Steps:
      1. 执行 `grep -n "async_playwright" src/utils/browser.py`
      2. 断言仅在 import 行出现或不出现
    Expected Result: browser.py 不再直接管理 Playwright 实例
    Failure Indicators: _start_browser 中仍有 async_playwright().start()
    Evidence: .omo/evidence/task-10-bcm-no-direct-pw.txt

  Scenario: BrowserContextManager 使用 Worker 派发
    Tool: Bash (uv run python -c)
    Steps:
      1. 执行 `uv run python -c "from src.utils.browser import BrowserContextManager; import inspect; src = inspect.getsource(BrowserContextManager.__aenter__); print('WorkerCommand' in src or 'get_worker' in src or 'submit' in src)"`
      2. 断言输出为 "True"
    Expected Result: __aenter__ 通过 Worker 获取浏览器上下文
    Failure Indicators: 仍直接调用 _start_browser
    Evidence: .omo/evidence/task-10-bcm-worker.txt
  ```

  **Commit**: YES (group with Wave 3)
  - Message: `refactor: BrowserContextManager 生命周期通过 PlaywrightWorker 管理，添加健康检查`
  - Files: `src/utils/browser.py`
  - Pre-commit: `uv run ruff check src/utils/browser.py`

- [ ] 11. PlaywrightWorker 单元测试

  **What to do**:
  - 创建 `tests/test_playwright_worker.py`
  - 测试 Worker 命令派发: submit 同步命令并获取结果
  - 测试 Worker 启动/停止生命周期
  - 测试浏览器健康检查: `is_connected()` 返回 True/False
  - 测试取消事件桥接: threading.Event → asyncio.Event
  - 测试 Worker 在浏览器崩溃后自动恢复
  - 测试 SHUTDOWN 命令后拒绝新命令
  - 使用 `unittest.mock` 模拟 Playwright 对象（不启动真实浏览器）
  - Mock `playwright.async_api.async_playwright` 返回 mock 对象链

  **Must NOT do**:
  - 不启动真实浏览器（所有测试使用 mock）
  - 不需要网络连接

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: [`python-testing-patterns`]

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 4 (with Task 12)
  - **Blocks**: F1-F4
  - **Blocked By**: 6, 7, 8, 9, 10

  **References**:

  **Test References**:
  - `tests/test_network_test.py` — 项目测试模式参考（pytest + 类组织、mock 策略）
  - `tests/test_task_executor.py` — 更复杂的测试模式参考

  **WHY Each Reference Matters**:
  - 需要遵循项目已有的测试风格

  **Acceptance Criteria**:

  **If TDD**: N/A (tests-after strategy)

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: 所有 Worker 单元测试通过
    Tool: Bash (uv run pytest)
    Steps:
      1. 执行 `uv run pytest tests/test_playwright_worker.py -v`
      2. 断言所有测试通过，0 failures
    Expected Result: 所有测试 PASS
    Failure Indicators: 任何测试 FAIL 或 ERROR
    Evidence: .omo/evidence/task-11-unit-tests.txt

  Scenario: 测试覆盖关键路径
    Tool: Bash (uv run pytest)
    Steps:
      1. 执行 `uv run pytest tests/test_playwright_worker.py --co -q`
      2. 断言输出包含: test_start_stop, test_submit_command, test_shutdown_reject, test_cancel_bridge, test_health_check
    Expected Result: 关键测试函数名称出现在收集列表中
    Failure Indicators: 缺少关键测试
    Evidence: .omo/evidence/task-11-test-coverage.txt
  ```

  **Commit**: YES (group with Wave 4)
  - Message: `test: 补充 PlaywrightWorker 单元测试`
  - Files: `tests/test_playwright_worker.py`
  - Pre-commit: `uv run pytest tests/test_playwright_worker.py -v`

- [ ] 12. 集成测试（监控、手动、调试路径）

  **What to do**:
  - 创建 `tests/test_integration_worker.py`
  - 测试监控登录路径: `MonitorService.start_monitoring()` → 网络异常 → Worker 登录 → 成功/失败
  - 测试手动登录路径: `POST /api/actions/login` → Worker 登录 → 返回结果
  - 测试调试路径: `POST /api/debug/start` → `POST /api/debug/next` → `POST /api/debug/stop`
  - 测试 Worker 崩溃恢复: Worker 线程异常退出 → 自动重启
  - 测试并发请求: 同时触发监控登录和手动登录 → 排队执行（不并发浏览器操作）
  - 测试 `login_then_exit` 路径: 启动 Worker → 登录 → 成功后退出
  - 使用 FastAPI TestClient + mock Playwright

  **Must NOT do**:
  - 不启动真实浏览器（使用 mock）
  - 不需要真实网络连接
  - 不修改生产代码

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: [`python-testing-patterns`]

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 4 (with Task 11)
  - **Blocks**: F1-F4
  - **Blocked By**: 6, 7, 8, 9, 10

  **References**:

  **Test References**:
  - `tests/test_network_test.py` — 项目测试模式参考
  - `backend/main.py:787-868` — debug API 端点

  **WHY Each Reference Matters**:
  - 需要测试所有三个 Playwright 路径（监控、手动、调试）都通过 Worker

  **Acceptance Criteria**:

  **If TDD**: N/A (tests-after strategy)

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: 所有集成测试通过
    Tool: Bash (uv run pytest)
    Steps:
      1. 执行 `uv run pytest tests/test_integration_worker.py -v`
      2. 断言所有测试通过，0 failures
    Expected Result: 所有测试 PASS
    Failure Indicators: 任何测试 FAIL 或 ERROR
    Evidence: .omo/evidence/task-12-integration-tests.txt

  Scenario: 三个路径都通过 Worker
    Tool: Bash (uv run pytest)
    Steps:
      1. 执行 `uv run pytest tests/test_integration_worker.py --co -q`
      2. 断言输出包含: test_monitor_login, test_manual_login, test_debug_session
    Expected Result: 三个路径的测试都存在
    Failure Indicators: 缺少某个路径的测试
    Evidence: .omo/evidence/task-12-three-paths.txt
  ```

  **Commit**: YES (group with Wave 4)
  - Message: `test: 补充 PlaywrightWorker 集成测试（监控、手动、调试路径）`
  - Files: `tests/test_integration_worker.py`
  - Pre-commit: `uv run pytest tests/test_integration_worker.py -v`

---

## Final Verification Wave (MANDATORY — after ALL implementation tasks)

> 4 review agents run in PARALLEL. ALL must APPROVE. Present consolidated results to user and get explicit "okay" before completing.

- [ ] F1. **Plan Compliance Audit** — `oracle`
  Read the plan end-to-end. For each "Must Have": verify implementation exists (read file, curl endpoint, run command). For each "Must NOT Have": search codebase for forbidden patterns — reject with file:line if found. Check evidence files exist in .omo/evidence/. Compare deliverables against plan.
  Output: `Must Have [N/N] | Must NOT Have [N/N] | Tasks [N/N] | VERDICT: APPROVE/REJECT`

- [ ] F2. **Code Quality Review** — `unspecified-high`
  Run `uv run ruff check .` + `uv run ruff format --check .` + `uv run pytest`. Review all changed files for: `as any`/type ignores, empty catches, console.log in prod, commented-out code, unused imports. Check AI slop: excessive comments, over-abstraction, generic names. Verify Chinese comments on key implementations.
  Output: `Build [PASS/FAIL] | Lint [PASS/FAIL] | Tests [N pass/N fail] | Files [N clean/N issues] | VERDICT`

- [ ] F3. **Real Manual QA** — `unspecified-high`
  Start from clean state. Execute EVERY QA scenario from EVERY task. Test cross-task integration: monitor login, manual login, debug session all work through Worker. Test edge cases: Worker crash recovery, cancel during login, concurrent requests. Save to `.omo/evidence/final-qa/`.
  Output: `Scenarios [N/N pass] | Integration [N/N] | Edge Cases [N tested] | VERDICT`

- [ ] F4. **Scope Fidelity Check** — `deep`
  For each task: read "What to do", read actual diff (`git diff main`). Verify 1:1 — everything in spec was built (no missing), nothing beyond spec was built (no creep). Check "Must NOT do" compliance. Detect cross-task contamination: Task N touching Task M's files. Flag unaccounted changes.
  Output: `Tasks [N/N compliant] | Contamination [CLEAN/N issues] | Unaccounted [CLEAN/N files] | VERDICT`

---

## Commit Strategy

- **Wave 1**: `fix: 修复 _cleanup_browser 异常吞没, reuse_browser 不重置, 关闭时浏览器残留` (Tasks 2-4 together)
- **Wave 1**: `feat: 创建 PlaywrightWorker 模块骨架` (Task 1)
- **Wave 2**: `feat: 实现 PlaywrightWorker 完整逻辑（浏览器生命周期、健康检查、命令派发）` (Task 5)
- **Wave 3**: `refactor: 所有 Playwright 路径统一走 PlaywrightWorker，消除跨 loop 崩溃` (Tasks 6-10 together)
- **Wave 4**: `test: 补充 PlaywrightWorker 单元测试和集成测试` (Tasks 11-12 together)

---

## Success Criteria

### Verification Commands
```bash
# 所有测试通过
uv run pytest tests/test_playwright_worker.py tests/test_integration_worker.py -v
# 全部测试通过（确认无回归）
uv run pytest
# 代码质量检查
uv run ruff check src/playwright_worker.py src/monitor_core.py backend/main.py app.py src/utils/browser.py
# 确认无残留的 asyncio.new_event_loop() 在 Worker 管理的文件中
grep -rn "asyncio.new_event_loop" src/monitor_core.py app.py
grep -rn "async_playwright" src/utils/browser.py backend/main.py src/monitor_core.py
```

### Final Checklist
- [ ] 所有 "Must Have" 项已实现
- [ ] 所有 "Must NOT Have" 模式不存在
- [ ] 所有测试通过
- [ ] 无 asyncio.new_event_loop() 残留在 Worker 管理的路径上
- [ ] 中文注释已添加到关键实现处