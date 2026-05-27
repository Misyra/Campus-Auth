# PID 锁文件稳健化

## TL;DR

> **Quick Summary**: 修复 PID 锁文件残留导致软件无法启动的问题，增强进程身份验证防止 PID 复用误判，确保所有退出路径清理 PID 文件。
> 
> **Deliverables**: 
> - `_is_service_running()` 进程身份验证（PID + 进程名 + 启动时间）
> - PID 文件格式升级（第一行 PID，第二行进程信息）
> - 所有 `os._exit(0)` 路径添加 `_cleanup_pid()`
> - VBS 脚本向后兼容（`ReadAll` → `ReadLine`）
> - `_cmd_stop` 安全防误杀
> - PID 文件原子写入
> - 单元测试覆盖
> 
> **Estimated Effort**: Quick-Medium
> **Parallel Execution**: YES - 2 waves
> **Critical Path**: Task 1 → Task 3 → F1-F4

---

## Context

### Original Request
软件意外退出后 PID 锁文件残留，导致下次启动时误判"已有一个实例在运行"而拒绝启动。需要稳健修复。

### Interview Summary
**Key Discussions**:
- 用户选择"稳健修"：PID 文件写入进程名+时间，启动时验证进程身份
- Metis 发现 4 个 `os._exit(0)` 路径（不只是 1 个），3 个跳过 atexit 清理
- Oracle Phase 1 发现 VBS 脚本使用 `ReadAll()` 而非 `ReadLine()`，多行 PID 文件会打破自启动

**Research Findings**:
- `app.py:312` — `_signal_handler` 用 `os._exit(0)` 跳过 atexit
- `app.py:363` — 系统托盘 `on_exit` 同样用 `os._exit(0)`
- `backend/main.py:1106` — watchdog `_force_exit_after_timeout` 用 `os._exit(0)`
- `app.py:272` — `_run_login_then_exit` 正确地在 `sys.exit(0)` 前调了 `_cleanup_pid()`
- VBS 自启动脚本 `autostart_service.py:288,320` 用 `ReadAll` 读取 PID 文件
- `_cmd_stop()` 未验证进程身份，可能误杀无关进程

### Metis Review
**Identified Gaps** (addressed):
- 3 个遗漏的 `os._exit(0)` 路径 → 全部纳入修复范围
- VBS `ReadAll` 会读多行内容致 WMI 查询失败 → 改为 `ReadLine`
- `_cmd_stop` 可能误杀无关进程 → 增加进程身份验证
- 原子写入 → 采用 temp+rename 策略

---

## Work Objectives

### Core Objective
让软件在意外退出（崩溃、强杀、Ctrl+C）后能正常启动，即使 PID 文件残留也不会误判或误杀。

### Concrete Deliverables
- `app.py` `_is_service_running()` 进程身份验证
- `app.py` `_write_pid()` 多行格式 + 原子写入
- `app.py` 3 处 `_cleanup_pid()` 插入（signal_handler, tray on_exit, main.py watchdog）
- `app.py` `_cmd_stop()` 安全防误杀
- `autostart_service.py` VBS 脚本 `ReadAll` → `ReadLine`
- `tests/test_pid_lock.py` 单元测试覆盖

### Definition of Done
- [ ] `uv run pytest` 全部通过
- [ ] 残留 PID 文件（指向不存在进程）→ 正常启动
- [ ] 残留 PID 文件（指向其他进程）→ 清理后正常启动
- [ ] Ctrl+C 退出 → PID 文件被清理
- [ ] `--stop` 命令不会误杀无关进程

### Must Have
- 进程身份验证（PID + 进程名 + 启动时间）
- 所有 `os._exit(0)` 路径添加 `_cleanup_pid()`
- VBS 脚本向后兼容
- `_cmd_stop` 安全检查
- PID 文件原子写入

### Must NOT Have (Guardrails)
- 不提取 `PidManager` 类（保持 app.py 内联函数结构）
- 不改变 PID 文件路径（`~/.campus_network_auth/campus_network_auth.pid`）
- 不将 `os._exit(0)` 改为 `sys.exit(0)`（AGENTS.md 反模式明确禁止）
- 不修改后端 monitor_service 或其他启动逻辑
- 不添加 CI/CD

---

## Verification Strategy

### Test Decision
- **Infrastructure exists**: YES (pytest)
- **Automated tests**: tests-after
- **Framework**: pytest

### QA Policy
Every task MUST include agent-executed QA scenarios.
- **CLI/TUI**: `app.py --status`, `app.py --stop` — 运行命令，验证输出
- **Library/Module**: `python -c "from app import ..."` — Import, call, compare output
- **Full Suite**: `uv run pytest` — All tests pass

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 1 (核心实现 — 2 个并行任务):
├── 1. PID 管理增强 (app.py) [deep]
└── 2. VBS 向后兼容 (autostart_service.py) [quick]

Wave 2 (验证 — 1 个任务):
└── 3. 测试覆盖 + 全量验证 [unspecified-high]

Wave FINAL (4 并行审查):
├── F1. Plan compliance audit (oracle)
├── F2. Code quality review (unspecified-high)
├── F3. Real manual QA (unspecified-high)
└── F4. Scope fidelity check (deep)
```

### Dependency Matrix

| Task | Depends On | Blocks |
|------|-----------|--------|
| 1 | - | 3 |
| 2 | - | 3 |
| 3 | 1, 2 | F1-F4 |

### Agent Dispatch Summary
- **Wave 1**: 2 — T1 deep, T2 quick
- **Wave 2**: 1 — T3 unspecified-high
- **FINAL**: 4 — F1 oracle, F2 unspecified-high, F3 unspecified-high, F4 deep

---

## TODOs

- [x] 1. PID 管理增强 (app.py + backend/main.py)

  **What to do**:
  - 修改 `_write_pid()` — PID 文件第一行为 PID 数字，第二行为 `进程名|创建时间戳`（如 `python.exe|1716712800`），使用原子写入（temp+rename）
  - 修改 `_is_service_running()` — 读取 PID 后增加进程身份验证：检查 `/proc/<pid>/cmdline`（Linux）或 `psutil.Process(pid)`（跨平台）或 `os.kill(pid, 0)` + 进程名匹配；如果进程名不匹配或进程不存在 → 清理 PID 文件返回 False
  - 修改 `_is_service_running()` 的向前兼容 — 如果 PID 文件只有一行（旧格式），依然按原逻辑只检查 PID 存活
  - 在 `_signal_handler`（line 312）的 `os._exit(0)` 前添加 `_cleanup_pid()` 调用
  - 在系统托盘 `on_exit` lambda（line 363）的 `os._exit(0)` 前添加 `_cleanup_pid()` 调用（需要 import `_cleanup_pid` 到可用作用域）
  - 在 `backend/main.py:1106` 的 `_force_exit_after_timeout` 的 `os._exit(0)` 前添加 `_cleanup_pid()` 调用（需要 from app import _cleanup_pid 或直接内联 `Path.home() / ".campus_network_auth" / "campus_network_auth.pid" unlink`）
  - 修改 `_cmd_stop()` — 在执行 `taskkill`/`os.kill` 前增加进程身份验证，如果 PID 文件中的进程名与目标进程不匹配，打印警告并中止，不执行杀进程操作
  - 修改 `_cmd_status()` — 如果有残留 PID 文件但进程身份不匹配，打印"服务未运行 (残留 PID 文件已清理)"

  **Must NOT do**:
  - 不提取 `PidManager` 类
  - 不将 `os._exit(0)` 改为 `sys.exit(0)`
  - 不改变 PID 文件路径
  - 不修改 monitor_service 或其他非 PID 相关的启动逻辑

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: 涉及多平台进程验证、信号处理、原子写入等复杂逻辑
  - **Skills**: []
    - Python 进程管理是常见领域，不需要额外技能

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Task 2)
  - **Blocks**: Task 3
  - **Blocked By**: None

  **References**:

  **Pattern References**:
  - `app.py:25-77` — 当前 PID 管理全部逻辑（`_get_pid_file`, `_is_service_running`, `_write_pid`, `_cleanup_pid`）
  - `app.py:120-178` — `_cmd_stop()` 停止逻辑（含 taskkill/kill 路径）
  - `app.py:298-309` — `_run_server()` 中 PID 检查和写入
  - `app.py:311-317` — `_signal_handler` 使用 `os._exit(0)`
  - `app.py:361-363` — 系统托盘 `on_exit` lambda 使用 `os._exit(0)`

  **API/Type References**:
  - `os.kill(pid, 0)` — 当前进程存活检测方式
  - `psutil.Process(pid).name()` / `psutil.Process(pid).create_time()` — 跨平台进程身份验证（需检查 psutil 是否在依赖中）

  **Test References**:
  - `tests/` — 现有测试结构

  **External References**:
  - Python `os.kill(pid, 0)` 在 Windows 上的行为：成功返回 0，进程不存在抛 `OSError`，权限不足抛 `PermissionError`

  **WHY Each Reference Matters**:
  - `app.py:25-77` — 需要全部重写的核心区域
  - `app.py:311-317` — 必须在 `os._exit(0)` 前加 `_cleanup_pid()`
  - `app.py:361-363` — 信号处理外的另一个 `os._exit(0)` 路径
  - `backend/main.py:1106` — watchdog 中的第三个 `os._exit(0)` 路径

  **Acceptance Criteria**:

  > **AGENT-EXECUTABLE VERIFICATION ONLY**

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: 残留 PID 指向不存在进程 → 正常启动
    Tool: Bash (python -c)
    Preconditions: 无运行中的 Campus-Auth 进程
    Steps:
      1. `python -c "from pathlib import Path; p = Path.home() / '.campus_network_auth' / 'campus_network_auth.pid'; p.parent.mkdir(exist_ok=True); p.write_text('99999')"` 写入不存在的 PID
      2. `python app.py --status` 应输出"服务未运行"或类似信息
      3. PID 文件应被自动清理
    Expected Result: `--status` 显示服务未运行，PID 文件被清理或标记为无效
    Failure Indicators: 显示"服务已在运行"
    Evidence: .omo/evidence/task-1-stale-pid-not-exist.txt

  Scenario: 残留 PID 指向其他进程 → 清理后正常启动
    Tool: Bash (python -c)
    Preconditions: 系统上有其他进程在运行（如 explorer.exe）
    Steps:
      1. `python -c "import os; from pathlib import Path; p = Path.home() / '.campus_network_auth' / 'campus_network_auth.pid'; p.write_text(str(os.getpid()) + '\nother_process|0')"` 写入当前 shell PID 但进程名为其他进程
      2. `python app.py --status` 应识别进程身份不匹配
    Expected Result: 进程身份验证失败 → PID 文件被清理 → 显示"服务未运行"
    Failure Indicators: 显示"服务已在运行 (PID: X)"
    Evidence: .omo/evidence/task-1-stale-pid-other-process.txt
  ```

  **Evidence to Capture**:
  - [ ] .omo/evidence/task-1-stale-pid-not-exist.txt
  - [ ] .omo/evidence/task-1-stale-pid-other-process.txt

  **Commit**: YES (groups with 2)
  - Message: `fix: PID 锁文件稳健化 — 进程身份验证 + 退出清理 + VBS 兼容`
  - Files: `app.py`, `backend/main.py`
  - Pre-commit: `uv run pytest tests/ --tb=short -q`

- [x] 2. VBS 向后兼容 (autostart_service.py)

  **What to do**:
  - 修改 `autostart_service.py` 中 VBS 模板的两处 `ReadAll` 为 `ReadLine`（line 288 和 line 320）
  - 确保 VBS 脚本只读取 PID 文件第一行（PID 数字），忽略后续的进程信息行
  - 测试 VBS 脚本逻辑在单行和多行 PID 文件情况下都能正确提取 PID

  **Must NOT do**:
  - 不修改 VBS 脚本的整体结构
  - 不添加新的 VBS 功能
  - 不改变 PID 文件路径

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 两行改动，范围明确
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Task 1)
  - **Blocks**: Task 3
  - **Blocked By**: None

  **References**:

  **Pattern References**:
  - `backend/autostart_service.py:284-298` — Windows 启动 VBS 模板中的 PID 读取
  - `backend/autostart_service.py:316-330` — macOS/Linux 启动 VBS 模板中的 PID 读取

  **WHY Each Reference Matters**:
  - `ReadAll` 读取整个文件内容，新的多行格式会导致 WMI 查询语法错误
  - 两处都需要改，缺一不可

  **Acceptance Criteria**:

  > **AGENT-EXECUTABLE VERIFICATION ONLY**

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: VBS ReadLine 只读第一行
    Tool: Bash (python -c)
    Preconditions: 有 autostart_service.py
    Steps:
      1. 检查 VBS 模板中 `ReadAll` 出现次数为 0
      2. 检查 VBS 模板中 `ReadLine` 出现次数为 2
      3. 模拟多行 PID 文件，VBS 脚本只取第一行数字
    Expected Result: VBS 模板使用 ReadLine 而非 ReadAll
    Failure Indicators: `ReadAll` 仍存在于 VBS 模板中
    Evidence: .omo/evidence/task-2-vbs-readline.txt
  ```

  **Evidence to Capture**:
  - [ ] .omo/evidence/task-2-vbs-readline.txt

  **Commit**: YES (groups with 1)
  - Message: `fix: PID 锁文件稳健化 — 进程身份验证 + 退出清理 + VBS 兼容`
  - Files: `backend/autostart_service.py`
  - Pre-commit: `uv run pytest tests/ --tb=short -q`

- [x] 3. 测试覆盖 + 全量验证

  **What to do**:
  - 创建 `tests/test_pid_lock.py`，覆盖以下场景：
    1. `_write_pid()` 写入多行格式，第二行含进程信息
    2. `_write_pid()` 原子写入（temp+rename）
    3. `_is_service_running()` — 无 PID 文件 → False
    4. `_is_service_running()` — PID 文件指向不存在进程 → False + 清理
    5. `_is_service_running()` — PID 文件指向其他进程（进程名不匹配）→ False + 清理
    6. `_is_service_running()` — PID 文件指向自身（真正运行中）→ True
    7. `_is_service_running()` — 旧格式单行 PID 文件向前兼容
    8. `_cleanup_pid()` 在所有 `os._exit(0)` 路径前被调用
    9. `_cmd_stop()` — PID 指向其他进程名时不执行杀操作
  - 运行 `uv run pytest` 全量验证
  - 运行 `uv run ruff check app.py backend/autostart_service.py backend/main.py` 确认无错误

  **Must NOT do**:
  - 不修改业务逻辑
  - 不添加新功能

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: 需要编写测试并做全量验证
  - **Skills**: [`python-testing-patterns`]
    - python-testing-patterns: 需要写多场景 Python 单元测试

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 2 (sequential, depends on Task 1 and 2)
  - **Blocks**: F1-F4
  - **Blocked By**: Task 1, Task 2

  **References**:

  **Pattern References**:
  - `tests/test_monitor_core.py` — 现有测试模式参考
  - `tests/conftest.py` — 现有 test fixtures 参考

  **API/Type References**:
  - `app.py:_is_service_running()` — 被测函数签名
  - `app.py:_write_pid()` — 被测函数签名
  - `app.py:_cleanup_pid()` — 被测函数签名
  - `app.py:_cmd_stop()` — 被测函数签名

  **Test References**:
  - `tests/test_monitor_core.py` — pytest 模式参考（mock, tmp_path fixture）

  **WHY Each Reference Matters**:
  - 需要参考现有测试模式确保风格一致
  - PID 管理函数需要 mock os.kill、文件系统操作等

  **Acceptance Criteria**:

  > **AGENT-EXECUTABLE VERIFICATION ONLY**

  **If tests-after**:
  - [ ] Test file created: tests/test_pid_lock.py
  - [ ] `uv run pytest tests/test_pid_lock.py -v` → 9+ passed, 0 failures

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: 全量测试通过
    Tool: Bash
    Preconditions: Task 1 和 Task 2 的代码改动已完成
    Steps:
      1. `uv run pytest tests/ --tb=short -q`
      2. 检查输出中无 FAILURES
      3. 检查 test_pid_lock.py 的测试数 ≥ 9
    Expected Result: 所有测试通过，test_pid_lock 覆盖 9+ 场景
    Failure Indicators: 任何测试失败
    Evidence: .omo/evidence/task-3-full-test-results.txt

  Scenario: 残留 PID 文件场景手动验证
    Tool: Bash
    Preconditions: 无 Campus-Auth 进程运行
    Steps:
      1. 写入残留 PID 文件: `python -c "from pathlib import Path; p = Path.home() / '.campus_network_auth' / 'campus_network_auth.pid'; p.parent.mkdir(exist_ok=True); p.write_text('99999')"`
      2. 运行 `uv run python app.py --status`
      3. 验证输出显示"服务未运行"而非"服务已在运行"
      4. 清理 PID 文件: `python -c "from pathlib import Path; (Path.home() / '.campus_network_auth' / 'campus_network_auth.pid').unlink(missing_ok=True)"`
    Expected Result: 显示"服务未运行"，PID 文件被自动清理
    Failure Indicators: 显示"服务已在运行"或抛异常
    Evidence: .omo/evidence/task-3-stale-pid-manual-qa.txt
  ```

  **Evidence to Capture**:
  - [ ] .omo/evidence/task-3-full-test-results.txt
  - [ ] .omo/evidence/task-3-stale-pid-manual-qa.txt

  **Commit**: YES (separate)
  - Message: `test: 补充 PID 锁文件管理单元测试`
  - Files: `tests/test_pid_lock.py`
  - Pre-commit: `uv run pytest tests/test_pid_lock.py -v`

---

## Final Verification Wave (MANDATORY — after ALL implementation tasks)

- [x] F1. **Plan Compliance Audit** — `oracle`
  Read the plan end-to-end. For each "Must Have": verify implementation exists. For each "Must NOT Have": search codebase for forbidden patterns. Check evidence files. Compare deliverables against plan.
  Output: `Must Have [N/N] | Must NOT Have [N/N] | Tasks [N/N] | VERDICT: APPROVE/REJECT`

- [x] F2. **Code Quality Review** — `unspecified-high`
  Run `uv run ruff check .` + `uv run pytest`. Review all changed files for: `as any`, empty catches, commented-out code, unused imports. Check AI slop: excessive comments, over-abstraction, generic names.
  Output: `Lint [PASS/FAIL] | Tests [N pass/N fail] | Files [N clean/N issues] | VERDICT`

- [x] F3. **Real Manual QA** — `unspecified-high`
  Start from clean state. Test PID scenarios: (1) normal start → stop → restart, (2) stale PID file pointing to dead process, (3) Ctrl+C → PID file cleaned, (4) `--stop` with stale PID → graceful message. Save to `.omo/evidence/`.
  Output: `Scenarios [N/N pass] | Integration [N/N] | VERDICT`

- [x] F4. **Scope Fidelity Check** — `deep`
  For each task: read "What to do", read actual diff. Verify 1:1. Check "Must NOT do" compliance. Detect scope creep.
  Output: `Tasks [N/N compliant] | Contamination [CLEAN/N issues] | VERDICT`

---

## Commit Strategy

- **Wave 1**: `fix: PID 锁文件稳健化 — 进程身份验证 + 退出清理 + VBS 兼容`

---

## Success Criteria

### Verification Commands
```bash
uv run pytest tests/test_pid_lock.py -v         # PID scenarios pass
uv run pytest --tb=short -q                       # all tests pass
uv run ruff check app.py backend/autostart_service.py backend/main.py  # no errors
python -c "from app import _is_service_running; print(_is_service_running())"  # returns (False, None) when no stale file
```

### Final Checklist
- [x] All "Must Have" present
- [x] All "Must NOT Have" absent
- [x] All tests pass
- [x] VBS `ReadAll` → `ReadLine` changed
- [x] All `os._exit(0)` paths have `_cleanup_pid()` before them