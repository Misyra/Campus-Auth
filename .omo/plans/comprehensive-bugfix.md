# Comprehensive Bugfix Plan

## TL;DR

> **Quick Summary**: Fix 13 verified bugs across Campus-Auth (3 HIGH, 3 MEDIUM, 7 LOW), sync documentation to match actual code, and add pytest tests for backend fixes — with auto-high-accuracy Momus review (verdict: OKAY).
>
> **Deliverables**:
> - launcher.py: Playwright install subprocess deadlock fix + Zip Slip prevention (+ pytest tests)
> - frontend/js/methods/lifecycle.js: 3 fixes (autostart poll, status poll, WS onerror)
> - frontend/js/methods/ui.js: Toast timer nesting leak fix
> - frontend/js/methods/config.js, tasks.js, status.js: Delete sync fix + silent failure notifications (merged)
> - tools/task-recorder.user.js: rAF background tab fix
> - tasks/select_isp.json: Narrow fallback selector
> - tasks/click_isp.json: Narrow option_selector
> - doc/task-manual.md: Frame parsing method correction
> - README.md: Add 19 missing API endpoint rows
>
> **Estimated Effort**: Medium
> **Parallel Execution**: YES — 2 waves + final verification
> **Critical Path**: Wave 1 (all parallel) → Wave 2 (all parallel) → Final verification

---

## Context

### Original Request
Comprehensive scan of the Campus-Auth codebase found 18 potential issues across all layers. User requested each issue be re-verified to eliminate false positives, then all confirmed bugs fixed with documentation synced and pytest tests for backend fixes.

### Interview Summary
**Key Discussions**:
- **Scope**: Fix all 13 confirmed bugs (3 HIGH, 3 MEDIUM, 7 LOW)
- **False Positives**: 5 items confirmed as non-issues (silent launch toggle logic correct, `/temp/` mount exists, stopImmediatePropagation intentional, VariableResolver recursion by design, all JSON files valid)
- **Documentation**: Sync doc/task-manual.md and README.md with actual code state
- **Testing**: pytest for backend launcher.py fixes; agent-executed QA for JS/Doc/JSON fixes
- **Review**: Auto-Momus high-accuracy review after plan generation

**Metis Review**:
- Count corrected: 13 bugs (not 12) — correct MEDIUM severity count
- Fixed ordering recommended: backend first, then JS, then JSON/docs
- Scope guardrails added: no JS test framework, no WS re-engineering, no shared refactoring
- Key fix strategy for each bug provided

### Re-Verification Summary
| # | Sev | File | Issue | Status |
|---|-----|------|-------|--------|
| 1 | HIGH | launcher.py:666-682 | Playwright subprocess deadlock (pipe blocks on `\r` output) | ✅ Confirmed |
| 2 | HIGH | ui.js:9-15 | Toast timer nesting leak (inner setTimeout untracked) | ✅ Confirmed |
| 3 | HIGH | tasks.js:202-204 | Delete active task doesn't sync backend | ✅ Confirmed |
| 4 | MEDIUM | doc/task-manual.md:126 | Frame doc says `frame_locator()`, code uses `content_frame()` | ✅ Confirmed |
| 5 | MEDIUM | launcher.py:465-466 | Zip Slip via extractall() (no `filter='data'` pre-3.12) | ✅ Confirmed |
| 6 | MEDIUM | config.js, tasks.js, status.js | Silent API failures (fetchConfig, fetchTasks, fetchActiveTask, fetchLogs) | ✅ Confirmed |
| 7 | LOW | lifecycle.js:22 | Autostart poll every 12s (status rarely changes) | ✅ Confirmed |
| 8 | LOW | lifecycle.js:21 | Status poll setInterval could pile up (no in-flight check) | ✅ Confirmed |
| 9 | LOW | lifecycle.js:236-239 | WS onerror calls close() triggering redundant reconnect | ✅ Confirmed |
| 10 | LOW | task-recorder.js:2986 | rAF DOM guard delayed in background tabs | ✅ Confirmed |
| 11 | LOW | tasks/select_isp.json:44 | Bare `select` fallback matches ALL dropdowns | ✅ Confirmed |
| 12 | LOW | tasks/click_isp.json:46 | option_selector overly broad (includes `li`, `[class*=item]`) | ✅ Confirmed |
| 13 | LOW | README.md | ~19 API endpoints missing from documentation table | ✅ Confirmed |

---

## Work Objectives

### Core Objective
Fix all 13 verified bugs across the Campus-Auth codebase, update documentation to match actual code, and add pytest tests for each backend fix — with auto-high-accuracy Momus review after plan generation.

### Concrete Deliverables
- Modified: `launcher.py`, `ui.js`, `tasks.js`, `lifecycle.js`, `config.js`, `status.js`
- Modified: `tools/task-recorder.user.js`, `tasks/select_isp.json`, `tasks/click_isp.json`
- Modified: `doc/task-manual.md`, `README.md`
- New: `tests/test_launcher.py` (or additions to existing test files)

### Definition of Done
- [x] All 13 fixes implemented in their respective files
- [x] `uv run pytest tests/ -x` passes (new + existing tests)
- [x] `uv run ruff check launcher.py` passes (no new lint errors)
- [x] All doc references match actual code patterns
- [x] Momus high-accuracy review verdict: OKAY

### Must Have
- Playwright install subprocess must not deadlock on `\r`-only progress output
- Toast notifications must not clear each other prematurely on rapid calls
- Deleting the active task must sync the change to backend
- All frontend API failures must notify the user (guarded against spam)
- Task template selectors must not match unintended elements
- Documentation must match actual code implementation
- All existing tests must continue to pass

### Must NOT Have (Guardrails)
- No JavaScript test framework added
- No full WebSocket re-engineering
- No shared try-catch wrapper refactoring
- No expansion of README API section beyond adding rows
- No changes to `default.json`, `no_isp.json` task templates
- No touching danger/import setInterval timers in tasks.js
- No changes beyond the 13 confirmed bugs

---

## Verification Strategy

> **ZERO HUMAN INTERVENTION** — ALL verification is agent-executed. No exceptions.

### Test Decision
- **Infrastructure exists**: YES (pytest in pyproject.toml)
- **Automated tests**: Tests-after (no TDD requested)
- **Framework**: pytest (for launcher.py fixes)
- **Agent QA**: For JS/Doc/JSON fixes

### QA Policy
Every task MUST include agent-executed QA scenarios. Evidence saved to `.omo/evidence/task-{N}-{scenario-slug}.{ext}`.

- **Backend (launcher.py)**: Use Bash — run pytest, check pass/fail output
- **Frontend JS**: Use grep/Read — confirm bug pattern is replaced, confirm new pattern exists
- **Task JSON**: Use grep/Read — confirm selector no longer contains broad patterns
- **Documentation**: Use grep — confirm corrected API, confirm new rows exist
- **Tampermonkey**: Use grep — confirm rAF replaced with timeout fallback

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 1 (Start Immediately — all parallel, independent files):
├── Task 1: launcher.py (#1 Playwright deadlock, #5 Zip Slip) + pytest tests [quick]
├── Task 2: lifecycle.js (#7 autostart poll, #8 status poll, #9 WS onerror) [quick]
├── Task 3: ui.js (#2 toast timer nesting leak) [quick]
└── Task 4: Frontend fixes: delete sync + silent failures (#3, #6 — config.js, tasks.js, status.js) [quick]

Wave 2 (After Wave 1 — all parallel):
├── Task 5: task templates (#11 select_isp.json, #12 click_isp.json) [quick]
├── Task 6: task-recorder.user.js (#10 rAF background tab) [quick]
├── Task 7: doc/task-manual.md (#4 frame parsing method) [quick]
└── Task 8: README.md (#13 missing API endpoints) [quick]

Wave FINAL (After ALL tasks — 4 parallel reviews):
├── Task F1: Full test suite run (oracle)
├── Task F2: Code quality + lint check (unspecified-high)
├── Task F3: QA scenario execution (unspecified-high)
└── Task F4: Scope fidelity check (deep)
```

### Dependency Matrix
- **1**: None — 5, 6, 7, 8, F1-F4
- **2**: None — F1-F4
- **3**: None — F1-F4
- **4**: None — 5, 6, 7, 8, F1-F4
- **5**: 1-4 completed — F1-F4
- **6**: 1-4 completed — F1-F4
- **7**: 1-4 completed — F1-F4
- **8**: 1-4 completed — F1-F4

### Agent Dispatch Summary
- **Wave 1**: 4 tasks → all `quick`
- **Wave 2**: 4 tasks → all `quick`
- **FINAL**: 4 tasks → `oracle`, `unspecified-high`, `unspecified-high`, `deep`

---

## TODOs

- [x] 1. **launcher.py: Fix Playwright subprocess deadlock + Zip Slip** (#1, #5)

  **What to do**:
  - **Bug #1 (HIGH)** — Replace `Popen`+`pipe` with `subprocess.run(capture_output=True)` or use async `create_subprocess_exec` with iteration on `\n`-delimited output. Current code at launcher.py:666-682 iterates `proc.stdout` line-by-line (`for line in proc.stdout:`), but Playwright's install progress uses `\r` carriage returns (progress bars). The pipe buffer fills, blocking both the parent's `readline()` and the child's `write()`, causing a deadlock.
  - **Bug #5 (MEDIUM)** — Add path traversal check before `zipfile.extractall()`: either iterate `z.namelist()` and validate each path with `Path.resolve()` against `PYTHON_DIR.resolve()`, or use `z.extractall(filter='data')` on Python 3.12+.
  - Write pytest tests in `tests/test_launcher.py` for both fixes.

  **Must NOT do**:
  - Do NOT refactor surrounding launcher code beyond these two fixes
  - Do NOT remove the existing `for line in proc.stdout` pattern without replacing it with working iteration

  **Recommended Agent Profile**:
  > `quick` — single file, clear isolated fixes, pytest tests follow existing patterns

  **Parallelization**:
  - **Wave**: 1
  - **Can Run In Parallel**: YES (with Tasks 2, 3, 4, 5)
  - **Blocks**: Tasks 5, 6, 7, 8 (Wave 2)
  - **Blocked By**: None

  **References**:
  - `launcher.py:666-682` — Current Playwright install code (Popen + stdout iteration)
  - `launcher.py:465-466` — Current zipfile.extractall code
  - `tests/test_task_executor.py` — Existing pytest patterns (fixtures, mock usage)
  - `tests/test_notify.py` — Example of unittest.mock.patch usage in this project

  **Acceptance Criteria**:

  **QA Scenarios**:

  ```
  Scenario: Playwright subprocess no longer blocks on \r output
    Tool: Bash
    Preconditions: launcher.py has been modified
    Steps:
      1. Run: grep -c "for line in proc.stdout" launcher.py
      2. If count > 0, check that iteration uses a different mechanism (e.g., readline with timeout, or subprocess.run with capture_output)
    Expected Result: Either the grep count is 0 (pattern removed) OR the surrounding code handles \r-delimited output
    Evidence: .omo/evidence/task-1-subprocess-fix.txt

  Scenario: Zip extractall path traversal prevented
    Tool: Bash
    Preconditions: launcher.py has been modified
    Steps:
      1. Run: grep -A5 "z\.extractall\|z\.namelist\|Path.*resolve\|filter.*data" launcher.py
      2. Verify the extraction code checks or sanitizes paths
    Expected Result: extractall is either guarded by path validation or uses filter='data'
    Evidence: .omo/evidence/task-1-zipslip-fix.txt

  Scenario: pytest tests pass
    Tool: Bash
    Preconditions: tests/test_launcher.py exists
    Steps:
      1. Run: uv run pytest tests/test_launcher.py -v
    Expected Result: All tests PASS
    Evidence: .omo/evidence/task-1-pytest.txt
  ```

  **Commit**: YES
  - Message: `fix(launcher): prevent Playwright install subprocess deadlock and Zip Slip`
  - Files: `launcher.py`, `tests/test_launcher.py`
  - Pre-commit: `uv run pytest tests/test_launcher.py -v`

- [x] 2. **lifecycle.js: Fix 3 timer/WebSocket issues** (#7, #8, #9)

  **What to do**:
  - **Bug #7 (LOW)** — Change `setInterval(() => this.fetchAutostart(), 12000)` at line 22 to `60000` (1 min) or remove it entirely (WS push handles status updates). Autostart status rarely changes — polling every 12s is wasteful.
  - **Bug #8 (LOW)** — Add an in-flight flag `this._statusPolling` before `fetchStatus()` calls. In `setInterval(() => this.fetchStatus(), 30000)`, check the flag — if a previous request is still pending, skip this interval tick. Reset flag in both success and error handlers of `fetchStatus()`.
  - **Bug #9 (LOW)** — Remove `this.ws.close()` from the `onerror` handler (line 238). The browser automatically closes the WebSocket on error, and `onclose` fires naturally. Calling `close()` inside `onerror` can cause `onclose` to fire twice (once naturally, once from `close()`), potentially double-incrementing `wsRetryCount`.

  **Must NOT do**:
  - Do NOT touch `_wsDestroyed`, `wsRetryCount`, or the reconnect logic itself
  - Do NOT change `showDangerConfirm` or `confirmRepoImport` setInterval timers
  - Do NOT change `fetchStatus` logic beyond the in-flight check

  **Recommended Agent Profile**:
  > `quick` — single file, isolated changes, low risk

  **Parallelization**:
  - **Wave**: 1
  - **Can Run In Parallel**: YES (with Tasks 1, 3, 4, 5)
  - **Blocks**: Tasks 5, 6, 7, 8 (Wave 2)
  - **Blocked By**: None

  **References**:
  - `frontend/js/methods/lifecycle.js:21-23` — setInterval lines
  - `frontend/js/methods/lifecycle.js:236-239` — onerror handler
  - `frontend/js/methods/lifecycle.js:2-4` — fetchAutostart logic

  **Acceptance Criteria**:

  **QA Scenarios**:

  ```
  Scenario (Bug #7): Autostart poll interval increased
    Tool: Bash
    Preconditions: lifecycle.js modified
    Steps:
      1. Run: grep -n "fetchAutostart()" frontend/js/methods/lifecycle.js
      2. Check that the interval is now 60000 or the line is gone
    Expected Result: Line shows setInterval with >= 60000ms or the line is removed
    Evidence: .omo/evidence/task-2-autostart-interval.txt

  Scenario (Bug #8): Status poll in-flight guard added
    Tool: Bash
    Preconditions: lifecycle.js modified
    Steps:
      1. Run: grep -n "_statusPolling\|fetchStatus" frontend/js/methods/lifecycle.js
      2. Confirm there's an in-flight check pattern (flag set before call, cleared on callback)
    Expected Result: fetchStatus is guarded by a polling-in-progress flag
    Evidence: .omo/evidence/task-2-status-poll-guard.txt

  Scenario (Bug #9): ws.close() removed from onerror
    Tool: Bash
    Preconditions: lifecycle.js modified
    Steps:
      1. Run: grep -A5 "ws.onerror" frontend/js/methods/lifecycle.js
      2. Confirm there's no this.ws.close() call inside onerror
    Expected Result: onerror only logs the error, does NOT call ws.close()
    Evidence: .omo/evidence/task-2-ws-onerror.txt
  ```

  **Commit**: YES
  - Message: `fix(lifecycle): optimize polling, add status poll in-flight guard, remove redundant ws.close()`
  - Files: `frontend/js/methods/lifecycle.js`

- [x] 3. **ui.js: Fix toast timer nesting leak** (#2)

  **What to do**:
  - **Bug #2 (HIGH)** — In `toastOnly()` at ui.js:9-15, the inner `setTimeout` (300ms for leaving animation at line 11) is not stored in any variable. If `toastOnly()` is called between 3000ms and 3300ms, the outer timer is cleared, but the old inner timer still fires, prematurely clearing the new toast's message.
  - Fix: Store the inner setTimeout handle (e.g., `this._toastLeavingTimer`). In `beforeUnmount` (or the `toastOnly` function entry), clear `this._toastLeavingTimer` alongside `this._toastTimer`.
  - Apply the same fix to `notify()` at lines 26-31 (same pattern).

  **Must NOT do**:
  - Do NOT restructure the toast/notification system
  - Do NOT change the toast duration (3s display + 0.3s leaving)

  **Recommended Agent Profile**:
  > `quick` — single file, clear timer leak fix, follows existing patterns

  **Parallelization**:
  - **Wave**: 1
  - **Can Run In Parallel**: YES (with Tasks 1, 2, 4)
  - **Blocks**: Tasks 5, 6, 7, 8 (Wave 2)
  - **Blocked By**: None

  **References**:
  - `frontend/js/methods/ui.js:5-16` — toastOnly function
  - `frontend/js/methods/ui.js:17-30` — notify function (same pattern)
  - `frontend/js/methods/lifecycle.js` — Check how other timers are cleaned up

  **Acceptance Criteria**:

  **QA Scenarios**:

  ```
  Scenario: Inner toast timer tracked
    Tool: Bash
    Preconditions: ui.js modified
    Steps:
      1. Run: grep -n "_toastTimer\|_toastLeavingTimer\|clearTimeout" frontend/js/methods/ui.js
      2. Confirm inner setTimeout is stored in a tracking variable (e.g., this._toastLeavingTimer)
      3. Confirm the tracking variable is cleared before setting a new one
    Expected Result: Inner setTimeout handle is tracked and cleared on new calls
    Evidence: .omo/evidence/task-3-toast-timer-fix.txt
  ```

  **Commit**: YES
  - Message: `fix(ui): track inner toast timeout to prevent timer leak`
  - Files: `frontend/js/methods/ui.js`

- [x] 4. **Frontend fixes: delete sync + silent failure notifications** (#3, #6)

  **What to do**:
  - **Bug #3 (HIGH)** — In `deleteTask()` at tasks.js:201-204, after setting `this.activeTaskId = 'default'` locally, add an explicit call to sync the backend: `this.setActiveTask('default')` or `$api.post('/api/tasks/active/default')`.
  - **Bug #6 (MEDIUM)** — Four API call functions catch errors but only log them without notifying the user:
    - `fetchConfig()` at config.js:17-18 — catches error, logs only
    - `fetchTasks()` at tasks.js:28-30 — catches error, logs only
    - `fetchActiveTask()` at tasks.js:36-38 — catches error, logs only
    - `fetchLogs()` at status.js:23-25 — catches error, logs only
  - For each: after the `frontendLogger.error(...)` call, add `this.notify(false, 'Failed to load X: ...')`.
  - **UI spam guard**: These 4 are called in parallel during `init()` (lifecycle.js:5-17). If the server is down, showing 4 toasts simultaneously is overwhelming. Use a single notification approach:
    - Option A: Add a `this._initErrorShown` flag — only show the notification for the first failure in `init()` context.
    - Option B: Wrap in a short debounce (e.g., only show toast if >2s since last notification).
    - Recommended: Option A — simplest, most reliable.

  **Must NOT do**:
  - Do NOT add notifications to `fetchBackups`, `fetchSafeMode`, `fetchAppVersion`, `fetchStatus`
  - Do NOT refactor the try-catch pattern into a shared wrapper
  - Do NOT change the existing log-first pattern

  **Recommended Agent Profile**:
  > `quick` — 3 files (config.js, tasks.js, status.js), each change is small and well-defined

  **Parallelization**:
  - **Wave**: 1
  - **Can Run In Parallel**: YES (with Tasks 1, 2, 3)
  - **Blocks**: Task 5, 6, 7, 8
  - **Blocked By**: None

  **References**:
  - `frontend/js/methods/tasks.js:195-212` — deleteTask function (Bug #3)
  - `frontend/js/methods/tasks.js:40-50` — setActiveTask pattern (Bug #3)
  - `frontend/js/methods/config.js:4-19` — fetchConfig (Bug #6)
  - `frontend/js/methods/tasks.js:24-30` — fetchTasks (Bug #6)
  - `frontend/js/methods/tasks.js:32-38` — fetchActiveTask (Bug #6)
  - `frontend/js/methods/status.js:17-25` — fetchLogs (Bug #6)
  - `frontend/js/methods/lifecycle.js:5-17` — init() parallel calls (Bug #6 spam guard)

  **Acceptance Criteria**:

  **QA Scenarios**:

  ```
  Scenario (Bug #3): Backend sync call added after activeTaskId reset
    Tool: Bash
    Preconditions: tasks.js modified
    Steps:
      1. Run: grep -A15 "activeTaskId === taskId" frontend/js/methods/tasks.js
      2. Confirm there's a $api.post or this.setActiveTask('default') call after setting activeTaskId locally
    Expected Result: After local reset, there's an API call to sync backend
    Evidence: .omo/evidence/task-4-delete-sync.txt

  Scenario (Bug #6): fetchConfig notifies user on error
    Tool: Bash
    Preconditions: config.js modified
    Steps:
      1. Run: grep -A5 "catch" frontend/js/methods/config.js | head -20
      2. Confirm there's a this.notify(false, ...) call in the catch block
    Expected Result: notify() added after frontendLogger.error()
    Evidence: .omo/evidence/task-4-fetchconfig-notify.txt

  Scenario (Bug #6): fetchTasks/fetchActiveTask notifies user on error
    Tool: Bash
    Preconditions: tasks.js modified
    Steps:
      1. Run: grep -A5 "catch" frontend/js/methods/tasks.js | head -15
      2. Confirm there's this.notify(false, ...) in BOTH fetchTasks and fetchActiveTask catch blocks
    Expected Result: notify() added in both error handlers
    Evidence: .omo/evidence/task-4-fetchtasks-notify.txt

  Scenario (Bug #6): Spam guard exists for init() calls
    Tool: Bash
    Preconditions: config.js and/or tasks.js modified
    Steps:
      1. Run: grep -n "_initErrorShown\|_notifyDebounce\|notify.*fail\|notify.*error" config.js tasks.js status.js
      2. Confirm there's a mechanism to prevent 4 simultaneous toasts
    Expected Result: Some guard (flag, debounce, or conditional) prevents spam
    Evidence: .omo/evidence/task-4-spam-guard.txt
  ```

  **Commit**: YES
  - Message: `fix(frontend): sync active task on delete + add notification on silent API failures`
  - Files: `frontend/js/methods/config.js`, `frontend/js/methods/tasks.js`, `frontend/js/methods/status.js`

- [x] 5. **Task templates: Narrow selectors in select_isp.json and click_isp.json** (#11, #12)

  **What to do**:
  - **Bug #11 (LOW)** — In `tasks/select_isp.json:44`, the selector is `"select[name='isp'], select[name='ISP_select'], select[id='isp'], select[class*='isp'], select"`. The final bare `, select` catches ANY `<select>` element on the page. Remove or restrict it (e.g., `select:not([name]), select[class]`).
  - **Bug #12 (LOW)** — In `tasks/click_isp.json:46`, `option_selector` includes `li` and `[class*='item']` which are overly broad and could match non-dropdown list items. Remove `li` and scope `[class*='item']` to dropdown-specific patterns.

  **Must NOT do**:
  - Do NOT change `default.json` or `no_isp.json`
  - Do NOT change variable resolution or step structure
  - Do NOT modify URL or timeout fields

  **Recommended Agent Profile**:
  > `quick` — two JSON files, simple string changes, low risk

  **Parallelization**:
  - **Wave**: 2
  - **Can Run In Parallel**: YES (with Tasks 6, 7, 8)
  - **Blocks**: None (Final Verification)
  - **Blocked By**: Tasks 1-4 (Wave 1)

  **References**:
  - `tasks/select_isp.json:44` — Current selector with bare `select` fallback
  - `tasks/click_isp.json:46` — Current option_selector with `li` and `[class*=item]`

  **Acceptance Criteria**:

  **QA Scenarios**:

  ```
  Scenario: Bare select removed from select_isp.json
    Tool: Bash
    Preconditions: select_isp.json modified
    Steps:
      1. Run: grep -c '", select"' tasks/select_isp.json
    Expected Result: Count is 0 (bare `, select` removed)
    Evidence: .omo/evidence/task-5-select-fix.txt

  Scenario: li removed from click_isp.json option_selector
    Tool: Bash
    Preconditions: click_isp.json modified
    Steps:
      1. Run: grep "option_selector" tasks/click_isp.json
      2. Confirm 'li' is NOT present in the option_selector value
    Expected Result: No `li` in option_selector
    Evidence: .omo/evidence/task-5-option-fix.txt
  ```

  **Commit**: YES
  - Message: `fix(tasks): narrow selectors in select_isp.json and click_isp.json`
  - Files: `tasks/select_isp.json`, `tasks/click_isp.json`

- [x] 6. **task-recorder.user.js: Add setTimeout fallback to rAF DOM guard** (#10)

  **What to do**:
  - **Bug #10 (LOW)** — In `tools/task-recorder.user.js:2986`, `_restoreAll()` uses `requestAnimationFrame` to defer DOM element restoration. In background browser tabs, rAF is throttled (1fps or less), significantly delaying restoration when the user switches back.
  - Fix: Replace or augment rAF with a more reliable mechanism:
    - Option A: Replace rAF with `setTimeout(0)` or `setTimeout(16)` (reliable even in background tabs)
    - Option B: Use rAF but add a `setTimeout(1000)` fallback that fires if rAF hasn't executed within 1s

  **Must NOT do**:
  - Do NOT change the `_restoreAll` logic beyond the rAF invocation
  - Do NOT touch other parts of the Tampermonkey script (event handlers, panel creation, etc.)

  **Recommended Agent Profile**:
  > `quick` — single function change, well-understood fix

  **Parallelization**:
  - **Wave**: 2
  - **Can Run In Parallel**: YES (with Tasks 5, 7, 8)
  - **Blocks**: None (Final Verification)
  - **Blocked By**: Tasks 1-4 (Wave 1)

  **References**:
  - `tools/task-recorder.user.js:2982-3003` — _restoreAll function

  **Acceptance Criteria**:

  **QA Scenarios**:

  ```
  Scenario: rAF replaced or supplemented with setTimeout
    Tool: Bash
    Preconditions: task-recorder.user.js modified
    Steps:
      1. Run: grep -B2 -A8 "requestAnimationFrame\|_restoreAll" tools/task-recorder.user.js
      2. Confirm rAF is either removed or has a setTimeout fallback
    Expected Result: setTimeout fallback exists alongside or replacing rAF
    Evidence: .omo/evidence/task-6-raf-fix.txt
  ```

  **Commit**: YES
  - Message: `fix(recorder): add setTimeout fallback to rAF DOM guard for background tabs`
  - Files: `tools/task-recorder.user.js`

- [x] 7. **doc/task-manual.md: Correct frame resolution method** (#4)

  **What to do**:
  - **Bug #4 (MEDIUM)** — At doc/task-manual.md:126, change `page.frame_locator(frame_selector)` to `page.query_selector(frame_selector).content_frame()`.
  - The third fallback in `_resolve_frame()` (task_executor.py:393-405) uses:
    1. `page.query_selector(frame_selector)` to find the iframe element
    2. `await frame_element.content_frame()` to get the frame object
  - `page.frame_locator()` returns a `FrameLocator` (for chaining locators), NOT a frame — the doc is incorrect.

  **Must NOT do**:
  - Do NOT change task_executor.py (the code is already correct)
  - Do NOT change other parts of task-manual.md

  **Recommended Agent Profile**:
  > `quick` — single line doc fix

  **Parallelization**:
  - **Wave**: 2
  - **Can Run In Parallel**: YES (with Tasks 5, 6, 8)
  - **Blocks**: None (Final Verification)
  - **Blocked By**: Tasks 1-4 (Wave 1)

  **References**:
  - `doc/task-manual.md:120-127` — The frame section needing correction
  - `src/task_executor.py:392-405` — Actual _resolve_frame code (ground truth)

  **Acceptance Criteria**:

  **QA Scenarios**:

  ```
  Scenario: frame_locator replaced with content_frame in docs
    Tool: Bash
    Preconditions: task-manual.md modified
    Steps:
      1. Run: grep -c "frame_locator" doc/task-manual.md
      2. Run: grep -c "content_frame" doc/task-manual.md
    Expected Result: frame_locator occurs 0 times, content_frame occurs >= 1 time
    Evidence: .omo/evidence/task-7-frame-doc-fix.txt
  ```

  **Commit**: YES
  - Message: `fix(doc): correct frame resolution method in task-manual.md`
  - Files: `doc/task-manual.md`

- [x] 8. **README.md: Add missing API endpoints** (#13)

  **What to do**:
  - **Bug #13 (LOW)** — Add 19 missing API endpoints to the README.md API overview table (section starting at line 308). Missing endpoints:
    - Updates: `GET /api/check-update`
    - Tools: `GET /api/tools/task-recorder.user.js`
    - Docs: `GET /api/docs/task-writing-guide`
    - Task Repo: `GET /api/repo/fetch`, `GET /api/repo/task`
    - Safe Mode: `GET /api/safe-mode`, `POST /api/safe-mode`
    - Debug: `POST /api/debug/start`, `POST /api/debug/next`, `POST /api/debug/run-all`, `POST /api/debug/stop`, `GET /api/debug/status`
    - Uninstall: `GET /api/uninstall/detect`, `POST /api/uninstall`
    - Backup: `GET /api/backup/list`, `POST /api/backup/create`, `POST /api/backup/restore/{filename}`, `GET /api/backup/download/{filename}`, `DELETE /api/backup/{filename}`
  - Follow existing table format: ```text\nMETHOD /path    # Description\n```

  **Must NOT do**:
  - Do NOT add full API reference, schemas, or examples
  - Do NOT change any existing table rows
  - Do NOT restructure the README

  **Recommended Agent Profile**:
  > `quick` — single file, adding rows to existing table

  **Parallelization**:
  - **Wave**: 2
  - **Can Run In Parallel**: YES (with Tasks 5, 6, 7)
  - **Blocks**: None (Final Verification)
  - **Blocked By**: Tasks 1-4 (Wave 1)

  **References**:
  - `README.md:308-385` — Existing API overview table section
  - `backend/main.py` — Ground truth for all API endpoints (search for `@app.(get|post|put|delete)`)

  **Acceptance Criteria**:

  **QA Scenarios**:

  ```
  Scenario: Missing endpoints added to README
    Tool: Bash
    Preconditions: README.md modified
    Steps:
      1. Run: grep -c "^|" README.md (check row count before and after)
      2. Run: grep "/api/check-update" README.md
      3. Run: grep "/api/safe-mode" README.md
      4. Run: grep "/api/debug/start" README.md
      5. Run: grep "/api/uninstall/detect" README.md
      6. Run: grep "/api/backup/list" README.md
    Expected Result: All 19 endpoints appear in the documentation table
    Evidence: .omo/evidence/task-8-readme-api.txt
  ```

  **Commit**: YES
  - Message: `fix(doc): add missing API endpoints to README.md`
  - Files: `README.md`

---

## Final Verification Wave

- [x] F1. **Full Test Suite Run** — `oracle`
  Run `uv run pytest tests/ -x`. All tests must pass (new + existing). Check test output for any failures. If test_launcher.py exists, verify it contains tests for both #1 and #5.
  Output: `pytest [N passed/N total] | VERDICT: APPROVE/REJECT`

- [x] F2. **Code Quality + Lint Check** — `unspecified-high`
  Run `uv run ruff check launcher.py`. Check all modified files for: `as any`/`@ts-ignore`, empty catches, console.log in prod, commented-out code, unused imports. Check AI slop: excessive comments, over-abstraction.
  Output: `ruff [PASS/FAIL] | Files [N clean/N issues] | VERDICT`

- [x] F3. **QA Scenario Execution** — `unspecified-high`
  Execute ALL QA scenarios from ALL tasks. Follow exact steps, capture evidence. Save to `.omo/evidence/final-qa/`. Verify each QA precondition (grep patterns, file content checks).
  Output: `Scenarios [N/N pass] | VERDICT`

- [x] F4. **Scope Fidelity Check** — `deep`
  For each task: read "What to do", read actual diff (git diff). Verify 1:1 — everything in spec was built, nothing beyond spec was built. Check "Must NOT do" compliance. Detect cross-task contamination.
  Output: `Tasks [N/N compliant] | Contamination [CLEAN/N issues] | VERDICT`

---

## Commit Strategy

- **1**: `fix(launcher): prevent Playwright install subprocess deadlock and Zip Slip` — `launcher.py`, `tests/test_launcher.py`, `uv run pytest tests/test_launcher.py -v`
- **2**: `fix(lifecycle): optimize polling, add status poll in-flight guard, remove redundant ws.close()` — `frontend/js/methods/lifecycle.js`
- **3**: `fix(ui): track inner toast timeout to prevent timer leak` — `frontend/js/methods/ui.js`
- **4**: `fix(frontend): sync active task on delete + add notification on silent API failures` — `frontend/js/methods/config.js`, `frontend/js/methods/tasks.js`, `frontend/js/methods/status.js`
- **5**: `fix(tasks): narrow selectors in select_isp.json and click_isp.json` — `tasks/select_isp.json`, `tasks/click_isp.json`
- **6**: `fix(recorder): add setTimeout fallback to rAF DOM guard for background tabs` — `tools/task-recorder.user.js`
- **7**: `fix(doc): correct frame resolution method in task-manual.md` — `doc/task-manual.md`
- **8**: `fix(doc): add missing API endpoints to README.md` — `README.md`

---

## Success Criteria

### Verification Commands
```bash
uv run pytest tests/ -x        # Expected: all tests pass
uv run ruff check launcher.py  # Expected: no lint errors
grep -c "frame_locator" doc/task-manual.md  # Expected: 0
grep -c "content_frame" doc/task-manual.md  # Expected: ≥1
```

### Final Checklist
- [x] All 13 fixes implemented
- [x] All existing tests pass
- [x] New pytest tests for launcher.py pass
- [x] No lint regressions
- [x] All doc references match actual code
- [x] Momus verdict: OKAY
