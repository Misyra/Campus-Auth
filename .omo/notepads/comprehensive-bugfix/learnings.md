## Wave 1 — Complete

### Task 1: launcher.py + tests
- ✅ Playwright subprocess deadlock: replaced `Popen`+pipe with `subprocess.run(capture_output=True)`. Inner `try/except` for `TimeoutExpired` around just the `run()` call, outer `except Exception` for anything else.
- ✅ Zip Slip: added `PYTHON_DIR_RESOLVED` loop over `z.namelist()` checking `Path.resolve()` containment before `extractall()`.
- ✅ 8 new pytest tests covering both fixes pass.
- ✅ `ruff check launcher.py` + `ruff check tests/test_launcher.py` pass.

### Task 2: lifecycle.js
- ✅ Bug #7: autostart poll 12000→60000.
- ✅ Bug #8: `_statusPolling` flag with `.finally()` guard.
- ✅ Bug #9: `ws.close()` removed from onerror.

### Task 3: ui.js
- ✅ Both `toastOnly()` and `notify()` track inner timer in `_toastLeavingTimer`, clear on each call.

### Task 4: config.js, tasks.js, status.js
- ✅ deleteTask now syncs backend: `await this.setActiveTask('default')`.
- ✅ 4 catch blocks (fetchConfig, fetchTasks, fetchActiveTask, fetchLogs) use `_initErrorShown` spam guard.

### Regression
- ✅ Full suite: 345/345 passed, 0 failures, 0 errors.

## Wave 2 — Complete

### Task 5: Task templates
- ✅ select_isp.json: bare `, select` removed from ISP dropdown selector.
- ✅ click_isp.json: `option_selector` narrowed — removed `li`, `[class*='item']`, dropdown child patterns.

### Task 6: task-recorder.user.js
- ✅ `requestAnimationFrame` → `setTimeout(0)` to avoid rAF throttling in background tabs.

### Task 7: doc/task-manual.md
- ✅ Frame resolution doc corrected: `page.frame_locator()` → `content_frame()` with `query_selector()`.

### Task 8: README.md
- ✅ 19 missing API endpoints added across 6 existing/new sections (Debug, Uninstall, Backup new sections).

### Regression
- ✅ Full suite: 345/345 passed, 0 failures, 0 errors (re-verified).

## Final Verification Wave — Complete

### F1 — Full Test Suite
- **VERDICT: APPROVE** (345/345 passed, 0 failures)
- test_launcher.py: 8 tests covering Bug #1 (Playwright) and Bug #5 (Zip Slip)
- No skips/xfail/TODO markers found

### F2 — Code Quality + Lint
- **VERDICT: APPROVE**
- ruff check clean on launcher.py and test_launcher.py
- No empty catches, console.log, commented code, or AI slop in any modified file

### F3 — QA Scenario Execution
- **VERDICT: APPROVE** (21/21 scenarios pass)
- Evidence saved to `.omo/evidence/final-qa/`

### F4 — Scope Fidelity Check
- **VERDICT: APPROVE** (8/8 tasks compliant, contamination: CLEAN)
- All "Must NOT do" rules respected
- No changes beyond the 13 confirmed bugs

### User Note
- User requested: 先不要提交，等我review (don't commit, wait for review)
- All changes are uncommitted and ready for user review
