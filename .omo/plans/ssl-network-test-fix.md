# SSL 网络检测误判修复

## TL;DR

> **Quick Summary**: 修复 `is_network_available_http()` 在校园网 SSL 拦截环境下误判网络异常的问题，添加 `verify=False` 跳过证书验证、降级 SSL 错误日志、补充测试覆盖。
> 
> **Deliverables**:
> - `src/network_test.py` — `verify=False` + SSL 日志降级 + 设计文档注释
> - `tests/test_network_test.py` — 6 个 SSL 场景单元测试
> 
> **Estimated Effort**: Quick
> **Parallel Execution**: YES - 2 waves
> **Critical Path**: Task 1 → Task 2

---

## Context

### Original Request
日志 `2026-05-26.log` 中校园网认证门户拦截 HTTPS 流量并使用自签证书，导致 `is_network_available_http()` 的 HTTP 探测全部返回 `[SSL: CERTIFICATE_VERIFY_FAILED]`。严格模式下 TCP 通 + HTTP 断 → 误判为"网络异常" → 触发不必要的登录重试。

### Interview Summary
**Key Discussions**:
- 用户确认 `verify=False` + `follow_redirects=False` 的行为正确：302 重定向判为"网络异常"，200 才判为"网络正常"
- 不新增配置项 — 网络探测跳过 SSL 验证是正确行为，不需要用户选项
- 日志中 SSL 误判属于预期行为，应降级为 DEBUG

**Research Findings**:
- `src/network_test.py:L253` — `httpx.Client(trust_env=not _block_proxy)` 缺少 `verify` 参数，默认 `verify=True`
- `src/utils/browser.py:L147` — Playwright 已使用 `ignore_https_errors=True`，行为一致
- `is_network_available()` L296-306 — 严格模式用 `follow_redirects=False`，302 不算正常

### Metis Review
**Identified Gaps** (addressed):
- httpx 是否 emit console warnings when `verify=False` → httpx 用 httpcore 不走 urllib3，不会 emit `InsecureRequestWarning`，需测试验证
- Portal 返回 200 状态码（非 302）是已知局限 → 文档注释说明
- `trust_env` 与 `verify` 是独立参数，互不干扰 → 写法 `httpx.Client(verify=False, trust_env=not _block_proxy)`

---

## Work Objectives

### Core Objective
修复校园网 SSL 证书拦截导致 HTTP 网络探测误判的问题。

### Concrete Deliverables
- `src/network_test.py` — `is_network_available_http()` 加 `verify=False`，SSL 错误日志降级
- `tests/test_network_test.py` — 6 个 SSL 场景单元测试

### Definition of Done
- [ ] `uv run pytest tests/test_network_test.py -v` — 所有新测试通过
- [ ] `uv run ruff check src/network_test.py` — 无 lint 错误
- [ ] 模拟 SSL 证书错误时 `is_network_available_http()` 返回 `False`（不崩溃）
- [ ] 模拟 SSL 环境下 200 响应时 `is_network_available_http()` 返回 `True`
- [ ] 模拟 SSL 环境下 302 重定向时 `is_network_available_http(follow_redirects=False)` 返回 `False`

### Must Have
- `is_network_available_http()` 的 `httpx.Client()` 加 `verify=False`
- SSL 证书错误日志从 INFO 降级为 DEBUG
- 在函数/模块级添加设计文档注释解释 `verify=False` 的原因
- 单元测试覆盖 SSL 错误、SSL+200、SSL+302、严格模式集成、代理+SSL 组合
- 确认 httpx 使用 `verify=False` 时不会向 stderr 输出警告

### Must NOT Have (Guardrails)
- 不新增配置项（settings.json、环境变量、UI 选项）
- 不修改 TCP 探测逻辑 (`is_network_available_socket`)
- 不修改 `strict_mode` 语义或默认值
- 不修改前端 UI 或 schema
- 不添加全局 `urllib3.disable_warnings()`
- 不在 `_check_one` 之外重构错误处理
- 不做响应内容分析检测 Portal

---

## Verification Strategy (MANDATORY)

### Test Decision
- **Infrastructure exists**: YES
- **Automated tests**: Tests-after
- **Framework**: pytest (existing `tests/test_network_test.py`)

### QA Policy
- **Library/Module**: Use Bash (`uv run pytest`) — Import, call functions, compare output
- **Negative scenarios**: 每个任务至少 1 个失败/边界场景

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 1 (Start Immediately - implementation):
├── Task 1: Add verify=False and SSL log level adjustment to network_test.py [quick]
└── (no other tasks - sequential dependency)

Wave 2 (After Wave 1 - test coverage):
└── Task 2: Add SSL scenario unit tests to test_network_test.py [quick]

Wave FINAL (After ALL tasks — 4 parallel reviews, then user okay):
├── Task F1: Plan compliance audit (oracle)
├── Task F2: Code quality review (unspecified-high)
├── Task F3: Real manual QA (unspecified-high)
└── Task F4: Scope fidelity check (deep)
-> Present results -> Get explicit user okay

Critical Path: Task 1 → Task 2 → F1-F4 → user okay
```

### Dependency Matrix

| Task | Depends On | Blocks |
|------|------------|--------|
| 1 | — | 2 |
| 2 | 1 | F1-F4 |
| F1 | 2 | — |
| F2 | 2 | — |
| F3 | 2 | — |
| F4 | 2 | — |

### Agent Dispatch Summary

- **Wave 1**: 1 task — T1 → `quick`
- **Wave 2**: 1 task — T2 → `quick`
- **FINAL**: 4 tasks — F1 → `oracle`, F2 → `unspecified-high`, F3 → `unspecified-high`, F4 → `deep`

---

## TODOs

- [x] 1. Add verify=False and SSL log level adjustment to is_network_available_http()

  **What to do**:
  - 修改 `src/network_test.py` 的 `is_network_available_http()` 函数中 `_check_one` 内部（L253）的 `httpx.Client(trust_env=not _block_proxy)` → `httpx.Client(verify=False, trust_env=not _block_proxy)`
  - 修改 `_check_one` 的异常处理（L261-263），对 SSL 证书验证相关异常降级日志：当错误消息包含 `CERTIFICATE_VERIFY_FAILED` 或异常类型为 `ssl.SSLError` 时，用 `logger.debug` 代替 `logger.info` 记录 HTTP 失败
  - 在 `is_network_available_http()` 函数的 docstring 中添加设计说明："网络连通性探测主动禁用 SSL 验证（verify=False）。因为校园网认证门户通常使用自签证书拦截 HTTPS 流量，而探测的目的是检查连通性而非 TLS 安全性。这与 Playwright 浏览器的 ignore_https_errors=True 行为一致。follow_redirects=False 模式下，200<=status<300 判为正常，302 重定向判为需要认证（不算正常）。注意：直接返回 200 状态码并附带登录页面的 Portal（无重定向）会被误判为正常——这是已知的现存限制。"
  - 在文件顶部添加 `import ssl` （如果需要在异常处理中检查 `ssl.SSLError`）

  **Must NOT do**:
  - 不修改 `trust_env` 逻辑或 `_block_proxy` 行为
  - 不添加新的配置项或环境变量
  - 不修改 TCP 探测逻辑
  - 不修改 `is_network_available()` 函数的 `strict_mode` 或 `require_both` 逻辑
  - 不修改所有 HTTP 失败的日志级别 — 只降级 SSL 证书相关的失败

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: Single-file, ~10 lines of actual code change, well-defined scope
  - **Skills**: []
    - No specialized skills needed for a targeted 10-line change

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 1 (only task)
  - **Blocks**: Task 2
  - **Blocked By**: None

  **References** (CRITICAL - Be Exhaustive):

  **Pattern References** (existing code to follow):
  - `src/network_test.py:240-273` — `is_network_available_http()` 函数，修改目标
  - `src/utils/browser.py:145-147` — `ignore_https_errors=True` 设计先例，在注释中引用

  **API/Type References** (contracts to implement against):
  - `httpx.Client` API — `verify` 参数接受 `bool` 或 `ssl.SSLContext`，默认 `True`
  - `httpx.ConnectError` — 包含 SSL 错误时会有 `ssl.SSLCertVerificationError` 嵌套

  **Test References** (testing patterns to follow):
  - `tests/test_network_test.py` — 现有测试结构，使用 `unittest.mock.patch` 和 `MagicMock`

  **WHY Each Reference Matters**:
  - `network_test.py:240-273` is the ONLY function being modified — exact line numbers for the changes
  - `browser.py:145-147` confirms the project already disables SSL verification for browser automation — same rationale applies to network probing
  - `test_network_test.py` shows the test pattern: mock httpx responses, assert boolean returns

  **Acceptance Criteria**:

  > **AGENT-EXECUTABLE VERIFICATION ONLY** — No human action permitted.

  **If TDD (tests enabled):**
  - N/A — Tests added in Task 2

  **QA Scenarios (MANDATORY - task is INCOMPLETE without these):**

  ```
  Scenario: verify=False is applied to httpx.Client
    Tool: Bash
    Preconditions: Source code is modified
    Steps:
      1. Run: grep -n "verify=False" src/network_test.py
      2. Verify output contains line with `httpx.Client(verify=False`
    Expected Result: Line found with verify=False in httpx.Client() call
    Failure Indicators: No match found
    Evidence: .omo/evidence/task-1-verify-false-grep.txt

  Scenario: SSL certificate errors are logged at DEBUG level
    Tool: Bash
    Preconditions: Source code is modified
    Steps:
      1. Run: grep -n "CERTIFICATE_VERIFY_FAILED\|ssl.SSLError" src/network_test.py
      2. Verify there is explicit handling that logs SSL cert errors at DEBUG level (not INFO/WARNING)
    Expected Result: Code path exists where CERTIFICATE_VERIFY_FAILED errors are logged at DEBUG level
    Failure Indicators: No SSL-specific log level handling found
    Evidence: .omo/evidence/task-1-ssl-debug-log.txt

  Scenario: Ruff check passes on modified file
    Tool: Bash
    Preconditions: Source code is modified
    Steps:
      1. Run: uv run ruff check src/network_test.py
    Expected Result: No output (clean lint)
    Failure Indicators: Lint errors found
    Evidence: .omo/evidence/task-1-ruff-check.txt
  ```

  **Commit**: YES
  - Message: `fix: 网络检测 HTTP 探测跳过 SSL 证书验证，避免校园网门户误判网络异常`
  - Files: `src/network_test.py`
  - Pre-commit: `uv run ruff check src/network_test.py`

- [x] 2. Add SSL scenario unit tests to test_network_test.py

  **What to do**:
  - 在 `tests/test_network_test.py` 中添加以下 6 个测试类/方法：

  1. **`test_http_probe_ssl_cert_error_returns_false`**: Mock `httpx.Client` 抛出 `httpx.ConnectError(SSLCertVerificationError(...))`，调用 `_check_one`，验证返回 `(url, False, ...)` — 确认 SSL 证书错误不再导致崩溃，而是优雅地返回 False
  
  2. **`test_http_probe_ssl_redirect_returns_false`**: Mock 返回 302 状态码（SSL 环境下），调用 `is_network_available_http(follow_redirects=False)`，验证返回 `False` — 核心修复场景：校园网 Portal 重定向不算"网络正常"
  
  3. **`test_http_probe_ssl_200_returns_true`**: Mock 返回 200 状态码（SSL 环境下），调用 `is_network_available_http()`，验证返回 `True` — 确认 verify=False 不影响正常 HTTPS 响应
  
  4. **`test_http_probe_ssl_error_logged_at_debug`**: Mock `httpx.ConnectError(SSLCertVerificationError(...))`，使用 `caplog.at_level(logging.DEBUG, logger="network_test")`，验证 SSL 证书错误被记录在 DEBUG 级别（非 INFO/WARNING）
  
  5. **`test_http_strict_mode_ssl_error_returns_false`**: Mock `is_network_available_socket` 返回 True，Mock `is_network_available_http` 因 SSL 错误返回 False，调用 `is_network_available(require_both=True)`，验证返回 `False` — 严格模式集成测试
  
  6. **`test_http_probe_verify_false_no_console_warning`**: 调用 `is_network_available_http()` 并捕获 stderr/caplog，验证没有 `InsecureRequestWarning` 或类似 SSL 警告输出

  **Must NOT do**:
  - 不写需要真实 SSL 证书或真实网络连接的集成测试
  - 不写超出 SSL 证书验证错误范围的测试
  - 不修改 `is_network_available` 或 `is_network_available_socket` 的现有逻辑

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: Adding 6 unit tests to an existing test file, all mock-based, no complex setup
  - **Skills**: [`python-testing-patterns`]
    - `python-testing-patterns`: pytest fixture patterns and mocking strategies

  **Parallelization**:
  - **Can Run In Parallel**: NO (depends on Task 1 changes)
  - **Parallel Group**: Wave 2 (only task)
  - **Blocks**: F1-F4
  - **Blocked By**: Task 1

  **References** (CRITICAL - Be Exhaustive):

  **Pattern References** (existing code to follow):
  - `tests/test_network_test.py` — 现有测试结构和 mock 模式
  - `src/network_test.py:240-273` — 被测函数实现（Task 1 修改后版本）

  **API/Type References** (contracts to implement against):
  - `httpx.ConnectError` — 包装 SSL 错误的异常类型
  - `ssl.SSLCertVerificationError` — 具体的证书验证错误
  - `httpx.Response` — Mock 时需要构造的响应对象

  **Test References** (testing patterns to follow):
  - `tests/test_login.py` — 使用 `asyncio.new_event_loop()` + `loop.run_until_complete()` 的模式（不需要）
  - `tests/test_network_test.py` — 使用 `unittest.mock.patch` 和 `MagicMock` mock `is_network_available_socket`

  **WHY Each Reference Matters**:
  - `test_network_test.py` shows the existing test structure — match the style and import patterns
  - `network_test.py:240-273` is the modified function — test against the new `verify=False` behavior
  - `test_login.py` shows `@pytest.mark.asyncio` patterns NOT needed here (network tests are sync)

  **Acceptance Criteria**:

  > **AGENT-EXECUTABLE VERIFICATION ONLY** — No human action permitted.

  **If TDD (tests enabled):**
  - [ ] Test file created: `tests/test_network_test.py` (modified, not new)
  - [ ] `uv run pytest tests/test_network_test.py -v` → PASS (6 new SSL tests, 0 failures)

  **QA Scenarios (MANDATORY - task is INCOMPLETE without these):**

  ```
  Scenario: All SSL tests pass
    Tool: Bash
    Preconditions: Task 1 changes are in place
    Steps:
      1. Run: uv run pytest tests/test_network_test.py -v -k "ssl or SSL or verify or cert"
      2. Check for 6 passed tests with SSL-related names
    Expected Result: 6 passed, 0 failed, 0 errors
    Failure Indicators: Any test failure or collection error
    Evidence: .omo/evidence/task-2-ssl-tests-pass.txt

  Scenario: Full test suite still passes
    Tool: Bash
    Preconditions: All changes applied
    Steps:
      1. Run: uv run pytest tests/test_network_test.py -v
    Expected Result: All existing + new tests pass
    Failure Indicators: Any regression in existing tests
    Evidence: .omo/evidence/task-2-full-test-suite.txt

  Scenario: Ruff check passes
    Tool: Bash
    Preconditions: All changes applied
    Steps:
      1. Run: uv run ruff check tests/test_network_test.py
    Expected Result: No lint errors
    Failure Indicators: Lint errors found
    Evidence: .omo/evidence/task-2-ruff-check.txt
  ```

  **Commit**: YES (groups with Task 1)
  - Message: `test: 补充 SSL 证书验证错误场景的单元测试`
  - Files: `tests/test_network_test.py`
  - Pre-commit: `uv run pytest tests/test_network_test.py -v`

---

## Final Verification Wave (MANDATORY — after ALL implementation tasks)

> 4 review agents run in PARALLEL. ALL must APPROVE. Present consolidated results to user and get explicit "okay" before completing.

- [x] F1. **Plan Compliance Audit** — `oracle`
  Read the plan end-to-end. For each "Must Have": verify implementation exists (read file, run command). For each "Must NOT Have": search codebase for forbidden patterns — reject with file:line if found. Check evidence files exist in .omo/evidence/. Compare deliverables against plan.
  Output: `Must Have [N/N] | Must NOT Have [N/N] | Tasks [N/N] | VERDICT: APPROVE/REJECT`

- [x] F2. **Code Quality Review** — `unspecified-high`
  Run `uv run ruff check src/network_test.py tests/test_network_test.py` + `uv run pytest tests/test_network_test.py -v`. Review changed files for: `as any`/`@ts-ignore` (N/A - Python), empty catches, console.log in prod (N/A), commented-out code, unused imports. Check AI slop: excessive comments beyond what's specified, over-abstraction, generic variable names.
  Output: `Lint [PASS/FAIL] | Tests [N pass/N fail] | Files [N clean/N issues] | VERDICT`

- [x] F3. **Real Manual QA** — `unspecified-high`
  Start from clean state. Execute EVERY QA scenario from EVERY task — follow exact steps, capture evidence. Test edge cases: verify that `is_network_available_http()` with a mock SSL error returns False, verify with a mock 200 response returns True. Save to `.omo/evidence/final-qa/`.
  Output: `Scenarios [N/N pass] | Integration [N/N] | Edge Cases [N tested] | VERDICT`

- [x] F4. **Scope Fidelity Check** — `deep`
  For each task: read "What to do", read actual diff. Verify 1:1 — everything in spec was built (no missing), nothing beyond spec was built (no creep). Check "Must NOT Have" compliance: no new config options, no TCP changes, no strict_mode changes, no UI changes. Detect unaccounted changes.
  Output: `Tasks [N/N compliant] | Contamination [CLEAN/N issues] | Unaccounted [CLEAN/N files] | VERDICT`

---

## Commit Strategy

- **1**: `fix: 网络检测 HTTP 探测跳过 SSL 证书验证，避免校园网门户误判网络异常` — `src/network_test.py`
- **2**: `test: 补充 SSL 证书验证错误场景的单元测试` — `tests/test_network_test.py`

---

## Success Criteria

### Verification Commands
```bash
uv run pytest tests/test_network_test.py -v          # Expected: all tests pass
uv run pytest tests/test_network_test.py -v -k "ssl" # Expected: 6 SSL tests pass
uv run ruff check src/network_test.py                 # Expected: clean
uv run ruff check tests/test_network_test.py          # Expected: clean
```

### Final Checklist
- [x] All "Must Have" present
- [x] All "Must NOT Have" absent
- [x] All tests pass