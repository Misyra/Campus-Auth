# WiFi Disconnect Handling Fix

## TL;DR

> **Quick Summary**: 修复 `is_local_network_connected()` 对 APIPA 地址（169.254.x.x）的误判，以及在认证地址不可达时仍尝试登录导致的浏览器卡死和事件循环冲突问题。
> 
> **Deliverables**:
> - APIPA 地址过滤，避免 DHCP 失败时误判网络已连接
> - 认证地址前置可达性探测，避免无效登录尝试
> - 浏览器健康检查增加超时，防止 30 秒卡死
> - `stop_monitoring()` 跨事件循环清理修复
> - 手动登录后同步监控状态到前端
> 
> **Estimated Effort**: Quick
> **Parallel Execution**: YES - 1 wave (all independent)
> **Critical Path**: N/A (all tasks are independent)

---

## Context

### Original Request
用户发现校园网 WiFi 虽然能连上但 DHCP 失败（只拿到 169.254.x.x APIPA 地址），系统误判为网络已连接，尝试登录时认证地址不可达导致浏览器卡死，手动停止时出现事件循环冲突错误，前端状态无法同步。

### Interview Summary
**Key Discussions**:
- 根因：`is_local_network_connected()` 只过滤 `127.x.x.x`，而 APIPA 地址 `169.254.x.x` 被当作有效连接
- 方案 A：过滤 APIPA 地址 — 1 行改动
- 方案 C：认证地址前置 TCP 可达性检查 — 避免无效的浏览器启动
- 浏览器健康检查加 timeout — 防止 evaluate("1") 卡住 30 秒
- 额外连带修复：`stop_monitoring()` 跨事件循环 bug、手动登录状态同步

**Research Findings**:
- `network_test.py:69` — `non_loopback` 只排除了 `127.x.x.x`，未排除 `169.254.x.x`
- `login.py:171` — `page.evaluate("1")` 无 timeout 参数，继承 Playwright 默认 30 秒
- `monitor_core.py:193-203` — `stop_monitoring()` 创建新事件循环关闭浏览器 → "不同事件循环" 错误
- `monitor_service.py:343` — `run_manual_login()` 创建临时 `NetworkMonitorCore`，不更新运行中的监控状态

### Metis Review
**Identified Gaps** (addressed):
- IPv6 链路本地 (fe80::) — 不在当前范围，用户场景为纯 IPv4
- 虚拟网卡 IP — APIPA 过滤器已覆盖用户的 DHCP 失败场景
- 建议：evaluate 超时后增加 cancel_event 检查，加速停止

---

## Work Objectives

### Core Objective
修复 `is_local_network_connected()` 对 APIPA 地址的误判，以及在认证地址不可达时仍尝试登录导致的浏览器卡死和事件循环冲突问题。

### Concrete Deliverables
- [x] `src/network_test.py` — `is_local_network_connected()` 过滤 169.254.x.x
- [x] `src/utils/login.py` — `page.evaluate("1")` 加 5s timeout
- [x] `src/monitor_core.py` — `_login_recovery_loop()` 加认证地址前置探测
- [x] `src/monitor_core.py` — `stop_monitoring()` 修复跨事件循环清理
- [x] `backend/monitor_service.py` — 手动登录后同步 `last_network_ok`

### Definition of Done
- [ ] 所有代码改动已应用并提交
- [ ] `is_local_network_connected()` 在仅有 APIPA 地址时返回 False
- [ ] `_login_recovery_loop()` 在认证地址不可达时返回 "net_disconnect" 而非尝试登录
- [ ] 浏览器健康检查在页面损坏时 5s 内超时而非 30s
- [ ] `stop_monitoring()` 不出现跨事件循环错误
- [ ] 手动登录成功后面板状态更新

### Must Have
- APIPA 地址（169.254.x.x）不被视为有效网络连接
- 浏览器健康检查不能无超时卡住
- 认证地址不可达时不启动浏览器
- 停止监控时不出现事件循环错误

### Must NOT Have (Guardrails)
- 不修改 `is_network_available()`、`is_network_available_socket()`、`is_network_available_http()` 三个函数
- 不修改 `LoginAttemptHandler` 类签名
- 不修改前端代码
- 不添加新的配置字段或 API 端点
- 不重写监控架构（仅手术式修复）

---

## Verification Strategy (MANDATORY)

> **ZERO HUMAN INTERVENTION** - ALL verification is agent-executed. No exceptions.

### Test Decision
- **Infrastructure exists**: YES (pytest)
- **Automated tests**: Unit tests for modified logic
- **Framework**: pytest
- **Coverage**: APIPA filter, auth URL pre-check, evaluate timeout behavior

### QA Policy
Every task MUST include agent-executed QA scenarios. Evidence saved to `.omo/evidence/task-{N}-{scenario-slug}.{ext}`.

- **Backend Python**: Use Bash (uv run pytest) - Run unit tests, verify logic
- **Runtime behavior**: Use Bash (uv run app.py) - Start server, verify monitor behavior

---

## Execution Strategy

### Parallel Execution Waves

All 5 tasks are on different files with no dependencies, so they can run in parallel.

```
Wave 1 (Start Immediately - all independent):
├── Task 1: APIPA filter in is_local_network_connected() [quick]
├── Task 2: Browser health check timeout in login.py [quick]
├── Task 3: Auth URL pre-check in _login_recovery_loop() [quick]
├── Task 4: Fix stop_monitoring() cross-loop cleanup [quick]
└── Task 5: Manual login state sync [quick]

Wave FINAL (After ALL tasks — parallel verification):
├── Task F1: Run all unit tests (pytest)
├── Task F2: Integration verification (start app, check behavior)
├── Task F3: Code quality review
└── Task F4: Scope fidelity check
```

### Dependency Matrix
- **1-5**: None - All independent, Wave 1
- **F1-F4**: All tasks 1-5 complete, Wave FINAL

### Agent Dispatch Summary
- **1**: All 5 tasks → `quick`
- **FINAL**: F1 → `quick`, F2 → `unspecified-high`, F3 → `unspecified-high`, F4 → `deep`

---

## TODOs

- [x] 1. `is_local_network_connected()` 过滤 APIPA 地址 + 单元测试

  **What to do**:
  - 在 `network_test.py:69` 的 `non_loopback` 列表推导式中增加 `169.254.` 过滤
  - 将 `[ip for ip in ip_list if not ip.startswith("127.")]` 改为 `[ip for ip in ip_list if not ip.startswith("127.") and not ip.startswith("169.254.")]`
  - 在 `tests/` 下创建 `test_network_apipa.py`，包含：
    - 测试仅有 `169.254.x.x` IP 时返回 False
    - 测试有正常 IP（如 `10.0.0.5`）+ `169.254.x.x` 时返回 True
    - 测试仅有环回地址时返回 False（保持现有行为）

  **Must NOT do**:
  - 不修改 `is_network_available()` 等函数
  - 不修改平台回退检测逻辑

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: N/A (simple 1-line change + test)

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 2, 3, 4, 5)
  - **Blocks**: None
  - **Blocked By**: None

  **References**:
  - `src/network_test.py:60-88` — `is_local_network_connected()` 完整函数
  - `src/network_test.py:69` — 当前 `non_loopback` 过滤行
  - `tests/test_task_executor.py` — 现有测试文件结构参考

  **Acceptance Criteria**:

  **Unit Tests:**
  - [ ] `pytest tests/test_network_apipa.py -v` → PASS (3 tests, 0 failures)
  - [ ] APIPA-only test: mock `socket.gethostbyname_ex` returns `["169.254.1.1", "169.254.2.2"]` → `False`
  - [ ] Mixed test: mock returns `["10.0.0.5", "169.254.1.1"]` → `True`
  - [ ] Loopback-only test: mock returns `["127.0.0.1"]` → `False`

  **QA Scenarios:**

  ```
  Scenario: APIPA-only returns False
    Tool: Bash
    Preconditions: Apply patch to network_test.py
    Steps:
      1. Create temp script that patches socket.gethostbyname_ex to return only 169.254.x.x IPs
      2. Call is_local_network_connected()
    Expected Result: Returns False
    Failure Indicators: Returns True
    Evidence: .omo/evidence/task-1-apipa-only.txt

  Scenario: Mixed IPs returns True
    Tool: Bash
    Preconditions: Same patch environment
    Steps:
      1. Mock returns ["10.0.0.5", "169.254.1.1"]
      2. Call is_local_network_connected()
    Expected Result: Returns True
    Failure Indicators: Returns False
    Evidence: .omo/evidence/task-1-mixed-ips.txt
  ```

  **Evidence to Capture:**
  - [ ] `task-1-apipa-only.txt` — APIPA-only test output
  - [ ] `task-1-mixed-ips.txt` — Mixed IPs test output

  **Commit**: YES (groups with 2, 3, 4, 5)
  - Message: `fix: filter APIPA addresses and improve browser/stop-monitoring robustness`
  - Files: `src/network_test.py`, `src/utils/login.py`, `src/monitor_core.py`, `backend/monitor_service.py`, `tests/test_network_apipa.py`
  - Pre-commit: `uv run pytest tests/test_network_apipa.py -v`

---

- [x] 2. 浏览器健康检查增加 timeout + cancel_event 检查

  **What to do**:
  - 在 `login.py:171` 将 `await browser_manager.page.evaluate("1")` 改为 `await browser_manager.page.evaluate("1", timeout=5000)`
  - 在 `login.py:172` 的 except 块中，在重新创建浏览器前检查 `self.cancel_event`：
    ```python
    except Exception:
        if self.cancel_event and self.cancel_event.is_set():
            self.logger.warning("登录已被取消，跳过浏览器重建")
            raise LoginCancelledError("登录已被取消")
    ```
  - 创建 `tests/test_login_browser.py` 验证 timeout 参数传递

  **Must NOT do**:
  - 不修改 `LoginAttemptHandler` 的构造方法签名
  - 不修改 `attempt_login()` 的方法签名

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: N/A

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1, 3, 4, 5)
  - **Blocks**: None
  - **Blocked By**: None

  **References**:
  - `src/utils/login.py:168-177` — 当前健康检查代码块
  - Playwright evaluate API: `page.evaluate(expression, **kwargs)` supports `timeout` parameter

  **Acceptance Criteria**:

  **Code Changes:**
  - [ ] `page.evaluate("1")` 改为 `page.evaluate("1", timeout=5000)`
  - [ ] cancel_event 检查已添加在 except 块中

  **QA Scenarios:**

  ```
  Scenario: evaluate timeout triggers recreate path
    Tool: Bash
    Preconditions: Browser in bad state (after failed goto)
    Steps:
      1. Call attempt_login with reuse_browser=True
      2. Check log for "浏览器实例已失效，重新创建" within 6s
    Expected Result: Warning logged within 6s (not 30s)
    Failure Indicators: Takes 30s or hangs
    Evidence: .omo/evidence/task-2-timeout.txt
  ```

  **Commit**: YES (groups with 1)
  - Files: `src/utils/login.py`

---

- [x] 3. `_login_recovery_loop()` 添加认证地址前置可达性探测

  **What to do**:
  - 在 `monitor_core.py` 的 `_login_recovery_loop()` 中，在 `self.attempt_login()` 之前添加认证地址 TCP 连接检查
  - 创建辅助方法 `_is_auth_url_reachable()`：
    ```python
    def _is_auth_url_reachable(self) -> bool:
        auth_url = self.config.get("auth_url", "")
        if not auth_url:
            return True  # 无认证地址时跳过检查（兼容模式）
        from urllib.parse import urlparse
        import socket
        try:
            parsed = urlparse(auth_url)
            host = parsed.hostname
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            if not host:
                return True
            sock = socket.create_connection((host, port), timeout=3)
            sock.close()
            return True
        except Exception:
            return False
    ```
  - 在 `_login_recovery_loop()` 的 while 循环中，profile switch 检查之后、`attempt_login()` 之前：
    ```python
    if not self._is_auth_url_reachable():
        self.log_message(
            f"认证地址 {self.config.get('auth_url', '?')} 不可达，跳过登录重试",
            logging.WARNING,
        )
        self.login_attempt_count = 0
        self.last_network_ok = False
        return "net_disconnect"
    ```

  **Must NOT do**:
  - 不进行 HTTP 请求（仅 TCP 连接）
  - 不修改 `is_network_available()` 等现有网络检测函数
  - timeout 不超过 3 秒

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: N/A

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1, 2, 4, 5)
  - **Blocks**: None
  - **Blocked By**: None

  **References**:
  - `src/monitor_core.py:292-343` — `_login_recovery_loop()` 完整方法
  - `src/network_test.py:218-226` — 已有 `socket.create_connection` 使用模式
  - `src/monitor_core.py:234-246` — `_get_retry_config()` 作为辅助方法参考

  **Acceptance Criteria**:

  **Code Changes:**
  - [ ] `_is_auth_url_reachable()` 方法已添加
  - [ ] `_login_recovery_loop()` 中在 `attempt_login()` 前调用了该检查
  - [ ] 无认证地址时跳过检查

  **QA Scenarios:**

  ```
  Scenario: Auth URL unreachable skips login
    Tool: Bash
    Preconditions: Patch config with unreachable auth URL (e.g., http://10.255.255.1)
    Steps:
      1. Start monitoring with unreachable auth URL
      2. Check log for "认证地址 ... 不可达，跳过登录重试"
    Expected Result: Login not attempted, "net_disconnect" returned
    Failure Indicators: Browser started, "开始登录认证" logged
    Evidence: .omo/evidence/task-3-unreachable.txt

  Scenario: Auth URL reachable proceeds to login
    Tool: Bash
    Preconditions: Patch config with reachable auth URL
    Steps:
      1. Start monitoring
      2. Check log proceeds to "开始登录认证"
    Expected Result: Login attempted
    Evidence: .omo/evidence/task-3-reachable.txt
  ```

  **Commit**: YES (groups with 1)
  - Files: `src/monitor_core.py`

---

- [x] 4. 修复 `stop_monitoring()` 跨事件循环浏览器清理

  **What to do**:
  - 删除 `monitor_core.py:193-204` 中创建新事件循环并 `close_browser()` 的代码块
  - 改为：设置 `_cancel_login`、`_stop_event`、`monitoring = False` 后，不主动关闭浏览器
  - 浏览器会在以下情况之一被清理：
    - (a) `attempt_login()` 返回后，`login.py` 中原有的 `close_browser()` 路径
    - (b) `stop_monitoring()` 末尾的 `self._loop.close()` 在无待完成任务时正常关闭
  - 确保 `_loop_stopped = True` 在合适时机设置（在 `self._login_handler = None` 之前）

  **Must NOT do**:
  - 不创建新的事件循环
  - 不修改 `LoginAttemptHandler.close_browser()` 方法

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: N/A

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1, 2, 3, 5)
  - **Blocks**: None
  - **Blocked By**: None

  **References**:
  - `src/monitor_core.py:182-224` — 当前 `stop_monitoring()` 完整方法
  - `src/monitor_core.py:523-602` — `attempt_login()` 方法，了解浏览器创建和清理流程

  **Acceptance Criteria**:

  **Code Changes:**
  - [ ] `monitor_core.py:193-204` 的新事件循环代码已移除
  - [ ] `stop_monitoring()` 不再调用 `asyncio.new_event_loop()`
  - [ ] 关键行 `self._loop_stopped = True` 在正确的时机设置
  - [ ] `self._login_handler = None` 已保留

  **QA Scenarios:**

  ```
  Scenario: Stop monitoring without cross-loop errors
    Tool: Bash (uv run app.py)
    Preconditions: Start app, start monitoring with invalid auth URL
    Steps:
      1. Start monitoring (login will fail)
      2. Wait 3s, then stop monitoring
      3. Check log for "不同事件循环" error
    Expected Result: No "不同事件循环" or "different loop" errors in logs
    Failure Indicators: Log contains "The future belongs to a different loop"
    Evidence: .omo/evidence/task-4-no-loop-error.txt
  ```

  **Commit**: YES (groups with 1)
  - Files: `src/monitor_core.py`

---

- [x] 5. 手动登录成功后同步 `last_network_ok` 到运行中的监控

  **What to do**:
  - 在 `monitor_service.py` 的 `run_manual_login()` 方法中，在 `success` 分支后更新 `self._monitor_core`
  - 在 `finally` 块之前，添加：
    ```python
    if success and self._monitor_core and self._monitor_core.monitoring:
        self._monitor_core.last_network_ok = True
        with self._lock:
            self._push_status()
    ```
  - 注意：`_push_status()` 在锁外调用以避免死锁（参考现有 `reload_config()` 中的锁模式）

  **Must NOT do**:
  - 不修改前端代码
  - 不添加新的 API 端点
  - 不修改 `get_status()` 方法

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: N/A

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1, 2, 3, 4)
  - **Blocks**: None
  - **Blocked By**: None

  **References**:
  - `backend/monitor_service.py:336-372` — 当前 `run_manual_login()` 方法
  - `backend/monitor_service.py:108-119` — `_push_status()` 方法
  - `backend/monitor_service.py:314-334` — `get_status()` 读取 `last_network_ok`

  **Acceptance Criteria**:

  **Code Changes:**
  - [ ] `run_manual_login()` 成功时更新 `self._monitor_core.last_network_ok`
  - [ ] 触发 `_push_status()` 推送更新到前端
  - [ ] `self._monitor_core` 为 None 或监控未运行时不报错

  **QA Scenarios:**

  ```
  Scenario: Manual login updates monitor status
    Tool: Bash (curl + log check)
    Preconditions: Start app, monitoring running, network disconnected
    Steps:
      1. POST /api/actions/login with valid credentials
      2. Wait for login success
      3. GET /api/status and check network_connected field
    Expected Result: network_connected = true after successful login
    Failure Indicators: network_connected = false after success
    Evidence: .omo/evidence/task-5-status-sync.txt
  ```

  **Commit**: YES (groups with 1)
  - Files: `backend/monitor_service.py`

---

## Final Verification Wave (MANDATORY — after ALL implementation tasks)

- [x] F1. **Unit Tests Verification** — `quick`
  Run all tests:
  ```bash
  uv run pytest tests/test_network_apipa.py -v
  ```
  Verify: all tests pass.
  Output: `Tests [N/N pass] | VERDICT: APPROVE/REJECT`

- [x] F2. **Integration Verification** — `unspecified-high`
  Start the app, verify end-to-end:
  1. Start app with `uv run app.py`
  2. Check monitor starts correctly
  3. Verify no event loop errors in logs when stopping
  4. Verify manual login syncs status
  Output: `Integration [N/N pass] | VERDICT: APPROVE/REJECT`

- [x] F3. **Code Quality Review** — `unspecified-high`
  Run linter:
  ```bash
  uv run ruff check .
  uv run ruff format --check .
  ```
  Review for: unused imports, exception handling issues, logic errors.
  Output: `Lint [PASS/FAIL] | VERDICT: APPROVE/REJECT`

- [x] F4. **Scope Fidelity Check** — `deep`
  Verify no unintended changes: read git diff, confirm only targeted files changed, no scope creep.
  Output: `Scope [CLEAN/N issues] | VERDICT: APPROVE/REJECT`

---

## Commit Strategy

- **1-5**: `fix: filter APIPA addresses and improve browser/stop-monitoring robustness`
  - Files: `src/network_test.py`, `src/utils/login.py`, `src/monitor_core.py`, `backend/monitor_service.py`, `tests/test_network_apipa.py`
  - Pre-commit: `uv run pytest tests/test_network_apipa.py -v && uv run ruff check .`

---

## Success Criteria

### Verification Commands
```bash
uv run pytest tests/test_network_apipa.py -v   # Expected: 3 passed
uv run ruff check .                              # Expected: no issues
# Start app and verify runtime behavior
uv run app.py --no-browser                       # Expected: starts without errors
```

### Final Checklist
- [x] APIPA-only scenario: `is_local_network_connected()` returns False ✅ unit test passes
- [x] Mixed IPs scenario: `is_local_network_connected()` returns True ✅ unit test passes
- [x] Auth URL unreachable: login skipped, "net_disconnect" returned ✅ code + code review
- [x] Browser health check times out in ≤5s ✅ timeout=5000 + unit test
- [x] Stop monitoring: no "different loop" errors ✅ stop_monitoring fix + all tests pass
- [x] Manual login: status updates to connected ✅ sync code + code review
- [x] All unit tests pass ✅ 351/351 pass
- [x] Ruff linter passes ✅ no new issues in changed files
