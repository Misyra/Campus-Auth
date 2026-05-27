# Critical Bug Fixes: Campus-Auth

## TL;DR

> **Quick Summary**: Fix 3 critical bugs identified during code review: fix `sys.exit(0)` in signal handler (daemon thread issue), rename `src/utils/time.py` to avoid shadowing stdlib `time`, deduplicate browser anti-detection JS. Plus generate a code review report for remaining unaddressed issues.
>
> **Deliverables**:
> - `app.py`: `sys.exit(0)` → `os._exit(0)` in `_signal_handler`
> - `src/utils/time.py` → renamed to `src/utils/time_utils.py` + all imports updated
> - Shared `STEALTH_INIT_SCRIPT` constant extracted to `src/utils/browser.py`
> - Both callers (`main.py`, `browser.py`) updated to use shared constant
> - `.omo/reports/code-review-remaining.md` documenting remaining issues
>
> **Estimated Effort**: Short
> **Parallel Execution**: YES — 3 independent fixes can run in parallel (Wave 1)
> **Critical Path**: Wave 1 (parallel) → Wave Final (parallel reviews + report)

---

## Context

### Original Request
Fix 3 critical bugs found during code review of the Campus-Auth project, and generate a code review report for the remaining unaddressed issues.

### Interview Summary
**Key Discussions**:
- **sys.exit(0) fix**: `_signal_handler` in `app.py:305` calls `sys.exit(0)` inside a daemon thread, but `sys.exit()` raises `SystemExit` which only exits the calling thread, not the main process. Fix: use `os._exit(0)` to immediately terminate the entire process.
- **time.py rename**: `src/utils/time.py` shadows the stdlib `time` module, creating risk of accidental self-imports and confusing dual-import patterns. Fix: rename to `time_utils.py` per AGENTS.md suggestion, update all import references.
- **JS dedup**: A ~45-line browser anti-detection stealth init script is byte-for-byte duplicated in `backend/main.py:271-316` (`DebugSession`) and `src/utils/browser.py:105-150` (`BrowserContextManager`). Fix: extract to a module-level constant in `src/utils/browser.py` (both consumers already import from this module), update both sites.
- **Code review report**: Document all remaining issues from the code review that are not being fixed, saved to `.omo/reports/code-review-remaining.md`.

**Research Findings**:
- `sys.exit(0)` at `app.py:305` is in `_signal_handler`. Two other `sys.exit(0)` calls exist at lines 262 and 292, but those are in main-thread contexts (login-then-exit flow, already-running check) — they work correctly and should NOT be changed.
- `src/utils/time.py` exports: `TimeUtils` class (with `is_in_pause_period`), `get_runtime_stats` function. Direct importers: `__init__.py` (both via `from .time import ...`), `login.py` (TimeUtils via `from .time import ...`). Indirect (via `__init__.py` re-exports): `monitor_core.py` (`from .utils import ...`). Files using `import time` of stdlib: `app.py`, `monitor_core.py`, `task_executor.py`, `logging.py`, `network_test.py`, `backend/main.py`, `backend/monitor_service.py` — these must be verified not to accidentally import `src.utils.time`.
- JS stealth init script is byte-for-byte identical in both locations (modulo 4-space indentation difference).

### Metis Review
**Identified Gaps** (addressed):
- JS dedup location confirmed as `src/utils/browser.py` (both callers already import browser)
- `time_utils.py` naming confirmed per AGENTS.md convention
- Report location confirmed as `.omo/reports/code-review-remaining.md`
- Test strategy confirmed as Tests-after (pytest exists, no TDD mandate)

---

## Work Objectives

### Core Objective
Fix 3 critical bugs in Campus-Auth with minimal code changes and generate a code review report.

### Concrete Deliverables
- [ ] `app.py`: `sys.exit(0)` → `os._exit(0)` in `_signal_handler` method
- [ ] `src/utils/time.py` → `src/utils/time_utils.py` (renamed)
- [ ] All import references to `src.utils.time` updated to `src.utils.time_utils`
- [ ] All `import time` statements verified to import stdlib `time`, not the project module
- [ ] `STEALTH_INIT_SCRIPT` constant in `src/utils/browser.py`
- [ ] `backend/main.py` references shared constant instead of inline script
- [ ] `src/utils/browser.py` `BrowserContextManager` references shared constant instead of inline script
- [ ] `.omo/reports/code-review-remaining.md` documenting all remaining issues

### Definition of Done
- [ ] Commands pass: `uv run ruff check .` (no new errors) and `uv run pytest` (all existing tests pass)
- [ ] `app.py` no longer calls `sys.exit()` in any daemon-thread context
- [ ] `src/utils/time.py` no longer exists (renamed to `time_utils.py`)
- [ ] No duplicate JS stealth init scripts remain in the codebase
- [ ] Code review report saved, listing all remaining unaddressed issues from the review session
- [ ] Evidence files for each QA scenario exist in `.omo/evidence/`

### Must Have
- All 3 bugs fixed with minimal diff (change only what's needed)
- All existing tests pass after changes
- No linting/formatting regressions
- `import time` in files using stdlib `time` must not accidentally import project `time_utils.py`

### Must NOT Have (Guardrails)
- **NO refactoring** beyond the minimum required for these 3 fixes
- **NO functionality changes** — only bug fixes, no behavior modifications
- **NO touching `sys.exit(0)` at lines 262 and 292** — those are in main-thread context and work correctly
- **NO adding new dependencies** or modifying `pyproject.toml`
- **NO changing test behavior** — existing tests should pass as-is
- **NO modifying files outside** the scope of these 3 fixes + report

---

## Verification Strategy (MANDATORY)

> **ZERO HUMAN INTERVENTION** — ALL verification is agent-executed. No exceptions.

### Test Decision
- **Infrastructure exists**: YES (pytest)
- **Automated tests**: Tests-after
- **Framework**: pytest
- **Agent-Executed QA**: MANDATORY for every task

### QA Policy
Every task MUST include agent-executed QA scenarios. Evidence saved to `.omo/evidence/task-{N}-{scenario-slug}.{ext}`.

- **Code changes**: Run `uv run ruff check .` and `uv run pytest` to verify no regressions
- **File rename**: Verify old file deleted, new file exists, imports resolve correctly
- **JS dedup**: Verify no duplicate script blocks remain via grep

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 1 (Start Immediately — all 3 fixes independent, MAX PARALLEL):
├── Task 1: Fix sys.exit(0) → os._exit(0) in app.py:305 [quick]
├── Task 2: Rename time.py → time_utils.py + update imports [deep]
└── Task 3: Extract duplicated JS stealth script to shared constant [quick]

Wave FINAL (After ALL tasks — 5 parallel reviews + report):
├── Task F1: Generate code review report (remaining issues) [unspecified-high]
├── Task F2: Plan compliance audit (oracle)
├── Task F3: Code quality review (unspecified-high)
├── Task F4: Real manual QA (unspecified-high)
└── Task F5: Scope fidelity check (deep)
-> Present results -> Get explicit user okay

Critical Path: Task 1/2/3 (parallel) → F1-F5 (parallel) → user okay
Parallel Speedup: ~66% faster than sequential (3 fixes in Wave 1 instead of sequential)
Max Concurrent: 3 (Wave 1)
```

### Dependency Matrix
- **1**: None (can start immediately) — 1 blocks None
- **2**: None (can start immediately) — 2 blocks None
- **3**: None (can start immediately) — 3 blocks None
- **F1-F5**: 1, 2, 3 (all fixes must be done first) — Fs block None (final wave)

### Agent Dispatch Summary
- **Wave 1** (3 agents): T1 → `quick`, T2 → `deep`, T3 → `quick`
- **Wave FINAL** (5 agents): F1 → `unspecified-high`, F2 → `oracle`, F3 → `unspecified-high`, F4 → `unspecified-high`, F5 → `deep`

---

## TODOs

- [x] 1. Fix `sys.exit(0)` → `os._exit(0)` in `app.py` signal handler

  **What to do**:
  - In `app.py`, locate `_signal_handler` method (around line 305)
  - Change `sys.exit(0)` to `os._exit(0)` (only the one in the signal handler, not lines 262 or 292)
  - Verify `import os` is present at the top of the file (if not, add it)
  - Run `uv run ruff check .` and `uv run pytest` to verify no regressions

  **Must NOT do**:
  - Do NOT change `sys.exit(0)` at lines 262 or 292 (those are in main-thread contexts)
  - Do NOT change any logic or behavior beyond this single-line fix
  - Do NOT add any imports that don't exist yet (except possibly `os`)

  **Recommended Agent Profile**:
  > - **Category**: `quick`
  >   - Reason: Single-line change in one file, trivial scope
  > - **Skills**: None needed
  > - **Skills Evaluated but Omitted**:
  >   - `python-testing-patterns`: No new tests needed, just verify existing tests pass

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 2, 3)
  - **Blocks**: F1-F5
  - **Blocked By**: None (can start immediately)

  **References**:
  - `app.py:302-310` — The `_signal_handler` method containing `sys.exit(0)` at line 305
  - `app.py:260-295` — The other `sys.exit(0)` calls at lines 262, 292 (read to understand context, do NOT modify)
  - `AGENTS.md` lines 68-72 — Documents the `sys.exit(0)` → `os._exit(0)` pattern and the rationale
  - `app.py:1-20` — Import section (check if `import os` exists)

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: Verify sys.exit(0) replaced with os._exit(0) in _signal_handler
    Tool: Bash (grep)
    Preconditions: app.py exists
    Steps:
      1. Run: grep -n "sys.exit\|os._exit" app.py
      2. Check that line ~305 shows `os._exit(0)`, not `sys.exit(0)`
      3. Verify lines 262 and 292 still show `sys.exit(0)` (unchanged)
    Expected Result: Exactly one `os._exit(0)` call (in _signal_handler), two `sys.exit(0)` calls unchanged elsewhere
    Failure Indicators: All three changed to os._exit, or signal handler still uses sys.exit
    Evidence: .omo/evidence/task-1-fix-confirmed.txt

  Scenario: Verify no linting/regression issues
    Tool: Bash
    Preconditions: Working directory is repo root
    Steps:
      1. Run: uv run ruff check app.py
      2. Run: uv run pytest
    Expected Result: ruff exits 0 with no errors, pytest passes all existing tests
    Failure Indicators: Ruff reports errors, pytest fails pre-existing tests
    Evidence: .omo/evidence/task-1-lint-pass.txt
  ```

  **Evidence to Capture**:
  - [ ] grep output showing correct os._exit(0) placement
  - [ ] ruff + pytest output

  **Commit**: YES
  - Message: `fix(app): replace sys.exit(0) with os._exit(0) in signal handler for daemon thread`
  - Files: `app.py`
  - Pre-commit: `uv run ruff check app.py && uv run pytest`

---

- [x] 2. Rename `src/utils/time.py` to `src/utils/time_utils.py` and update all imports

  **What to do**:
  1. Rename `src/utils/time.py` → `src/utils/time_utils.py` (using `git mv` or OS-level rename)
  2. Update `src/utils/__init__.py` — change `from .time import ...` to `from .time_utils import ...`
  3. Update `src/utils/login.py` — change `from src.utils.time import TimeUtils` to `from src.utils.time_utils import TimeUtils`
  4. Update `src/monitor_core.py` — verify it uses `TimeUtils, get_runtime_stats` through `__init__.py` re-exports (`from .utils import ...`). No direct import changes needed.
  5. Search for any other `from .time import` or `from src.utils.time import` references and update
  6. Verify all `import time` statements in the project still import stdlib `time`, not the renamed module
  7. Run full test suite and linter

  **Must NOT do**:
  - Do NOT change any class names, function names, or behavior
  - Do NOT modify the content of `time_utils.py` beyond the rename
  - Do NOT touch any file that doesn't reference `src.utils.time`
  - Do NOT refactor the code inside time_utils.py

  **Recommended Agent Profile**:
  > - **Category**: `deep`
  >   - Reason: Requires careful import tracing across 5+ files to ensure no missed references
  > - **Skills**: None needed
  > - **Skills Evaluated but Omitted**:
  >   - `python-testing-patterns`: No new tests, just verify existing ones pass

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1, 3)
  - **Blocks**: F1-F5
  - **Blocked By**: None (can start immediately)

  **References**:
  - `src/utils/time.py` — File to be renamed
  - `src/utils/__init__.py` — Exports `TimeUtils` and `get_runtime_stats` from `.time` (line 11: `from .time import ...`)
  - `src/utils/login.py` — Imports `TimeUtils` via `from .time import TimeUtils` (line 19)
  - `src/monitor_core.py` — Uses `TimeUtils, get_runtime_stats` through `__init__.py` re-exports (`from .utils import ...`, lines 12-17). No direct import change needed.
  - `AGENTS.md` line 68 — Documents the `src/utils/time.py` shadowing anti-pattern

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: Verify file rename and import updates
    Tool: Bash
    Preconditions: Working directory is repo root
    Steps:
      1. Run: Test-Path -LiteralPath "src/utils/time_utils.py" → expect True
      2. Run: Test-Path -LiteralPath "src/utils/time.py" → expect False
      3. Run: python -c "from src.utils.time_utils import TimeUtils, get_runtime_stats; print('OK')" → expect OK
      4. Run: grep -rn "from src\.utils\.time import" src/ backend/ — expect empty output (no remaining references to old module path)
    Expected Result: time_utils.py exists, time.py is gone, all imports resolve, no stale references
    Failure Indicators: time.py still exists, imports fail, stale references remain
    Evidence: .omo/evidence/task-2-rename-verified.txt

  Scenario: Verify stdlib time imports still work
    Tool: Bash (grep)
    Preconditions: Working directory is repo root
    Steps:
      1. Run: grep -n "^import time$" app.py src/monitor_core.py src/utils/task_executor.py
      2. Run: grep -c "^import time$" app.py (these will import stdlib time)
    Expected Result: `import time` statements exist in expected files and resolve to stdlib, not the renamed module
    Failure Indicators: Any `import time` now resolves to the project module instead of stdlib
    Evidence: .omo/evidence/task-2-stdlib-time-verified.txt

  Scenario: Full regression check
    Tool: Bash
    Preconditions: All changes applied
    Steps:
      1. Run: uv run ruff check .
      2. Run: uv run pytest
    Expected Result: ruff exits 0, pytest passes all tests
    Failure Indicators: Lint errors or test failures
    Evidence: .omo/evidence/task-2-regression-pass.txt
  ```

  **Evidence to Capture**:
  - [ ] File existence verification
  - [ ] Import resolution test
  - [ ] grep for stale references
  - [ ] ruff + pytest output

  **Commit**: YES
  - Message: `fix(utils): rename time.py to time_utils.py to avoid shadowing stdlib time`
  - Files: `src/utils/time.py → src/utils/time_utils.py`, `src/utils/__init__.py`, `src/utils/login.py`, any other files with `from .time import` references
  - Pre-commit: `uv run ruff check . && uv run pytest`

---

- [x] 3. Deduplicate browser anti-detection JS stealth init script

  **What to do**:
  1. In `src/utils/browser.py`, add a module-level constant `STEALTH_INIT_SCRIPT` containing the ~45-line stealth init script (the one currently duplicated in `main.py:271-316` and `browser.py:105-150`)
  2. In `src/utils/browser.py` `BrowserContextManager._start_browser()`, replace the inline stealth script with a reference to `self.STEALTH_INIT_SCRIPT` (the constant)
  3. In `backend/main.py` `DebugSession.start()`, import `STEALTH_INIT_SCRIPT` from `src.utils.browser` and replace the inline script with the constant reference
  4. Verify the extracted script is byte-for-byte identical to the original in both locations
  5. Run full test suite and linter

  **Must NOT do**:
  - Do NOT modify the script content — preserve it exactly as-is
  - Do NOT change any browser initialization logic
  - Do NOT refactor other parts of `browser.py` or `main.py`
  - Do NOT introduce any new abstractions beyond the constant

  **Recommended Agent Profile**:
  > - **Category**: `quick`
  >   - Reason: Straightforward extraction of duplicated code to a shared constant
  > - **Skills**: None needed
  > - **Skills Evaluated but Omitted**:
  >   - `python-testing-patterns`: No new tests needed, just verify existing ones pass

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1, 2)
  - **Blocks**: F1-F5
  - **Blocked By**: None (can start immediately)

  **References**:
  - `backend/main.py:271-316` — `DebugSession.start()` with inline stealth script
  - `src/utils/browser.py:105-150` — `BrowserContextManager._start_browser()` with identical inline script
  - `src/utils/browser.py:1-20` — Import section (verify `from playwright.async_api import ...` or similar)
  - `backend/main.py:1-30` — Import section (will need to add `from src.utils.browser import STEALTH_INIT_SCRIPT`)

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: Verify STEALTH_INIT_SCRIPT constant exists and is used
    Tool: Bash (grep)
    Preconditions: Working directory is repo root
    Steps:
      1. Run: grep -n "STEALTH_INIT_SCRIPT" src/utils/browser.py
      2. Run: grep -n "STEALTH_INIT_SCRIPT" backend/main.py
    Expected Result: browser.py shows the constant definition, main.py shows an import and usage of STEALTH_INIT_SCRIPT
    Failure Indicators: No STEALTH_INIT_SCRIPT found in either file, or only in one
    Evidence: .omo/evidence/task-3-constant-verified.txt

  Scenario: Verify no duplicate inline scripts remain
    Tool: Bash (grep)
    Preconditions: Working directory is repo root
    Steps:
      1. Search for the unique identifier of the stealth script (e.g., "navigator.webdriver" or the override pattern)
      2. Run: grep -c "navigator\.webdriver" backend/main.py src/utils/browser.py
    Expected Result: The script content appears exactly once in the constant definition only, not duplicated inline
    Failure Indicators: Script content still duplicated in both files
    Evidence: .omo/evidence/task-3-no-duplicates.txt

  Scenario: Full regression check
    Tool: Bash
    Preconditions: All changes applied
    Steps:
      1. Run: uv run ruff check .
      2. Run: uv run pytest
    Expected Result: ruff exits 0, pytest passes all tests
    Failure Indicators: Lint errors or test failures
    Evidence: .omo/evidence/task-3-regression-pass.txt
  ```

  **Evidence to Capture**:
  - [ ] grep output for STEALTH_INIT_SCRIPT usage
  - [ ] grep output showing no duplicate inline scripts
  - [ ] ruff + pytest output

  **Commit**: YES
  - Message: `refactor(browser): deduplicate stealth init script into shared constant`
  - Files: `src/utils/browser.py`, `backend/main.py`
  - Pre-commit: `uv run ruff check . && uv run pytest`

---

## Final Verification Wave (MANDATORY — after ALL implementation tasks)

> 5 review agents run in PARALLEL. ALL must APPROVE. Present consolidated results to user and get explicit "okay" before completing.

- [x] F1. **Generate Code Review Report** — `unspecified-high`
  Review all issues from the original code review session that are NOT addressed by Tasks 1-3. Compile them into `.omo/reports/code-review-remaining.md` with: issue description, file location, severity (critical/major/minor), and recommendation. Do NOT re-list the 3 fixes already completed. Save the report and verify it's readable.
  Evidence: `.omo/evidence/task-F1-report-generated.txt`

- [x] F2. **Plan Compliance Audit** — `oracle`
  Read the plan end-to-end. For each "Must Have": verify implementation exists (read file, grep, run command). For each "Must NOT Have": search codebase for forbidden patterns — reject with file:line if found. Check evidence files exist in `.omo/evidence/`. Compare deliverables against plan.
  Output: `Must Have [N/N] | Must NOT Have [N/N] | Tasks [N/N] | VERDICT: APPROVE/REJECT`

- [x] F3. **Code Quality Review** — `unspecified-high`
  Run `uv run ruff check .` + `uv run pytest`. Review all changed files for: `as any`/`@ts-ignore` (N/A for Python), empty catches, `console.log`/`print` in prod, commented-out code, unused imports. Check: excessive comments, over-abstraction (shouldn't happen given guardrails).
  Output: `Lint [PASS/FAIL] | Tests [N pass/N fail] | Files [N clean/N issues] | VERDICT`

- [x] F4. **Real Manual QA** — `unspecified-high`
  Execute EVERY QA scenario from EVERY task — follow exact steps, capture evidence. Test cross-task integration (e.g., all 3 fixes applied, project builds and tests pass). Save to `.omo/evidence/final-qa/`.
  Output: `Scenarios [N/N pass] | Integration [N/N] | VERDICT`

- [x] F5. **Scope Fidelity Check** — `deep`
  For each task: read "What to do", read actual diff (`git diff`). Verify 1:1 — everything in spec was built (no missing), nothing beyond spec was built (no creep). Check "Must NOT do" compliance. Detect cross-task contamination: Task N touching Task M's files. Flag unaccounted changes.
  Output: `Tasks [N/N compliant] | Contamination [CLEAN/N issues] | Unaccounted [CLEAN/N files] | VERDICT`

---

## Commit Strategy

- **1**: `fix(app): replace sys.exit(0) with os._exit(0) in signal handler` - `app.py`, `uv run ruff check app.py && uv run pytest`
- **2**: `fix(utils): rename time.py to time_utils.py to avoid shadowing stdlib time` - `src/utils/time.py→time_utils.py`, `src/utils/__init__.py`, `src/utils/login.py` (plus any other files with `from .time import` references), `uv run ruff check . && uv run pytest`
- **3**: `refactor(browser): deduplicate stealth init script into shared constant` - `src/utils/browser.py`, `backend/main.py`, `uv run ruff check . && uv run pytest`

---

## Success Criteria

### Verification Commands
```bash
uv run ruff check .   # Expected: 0 errors (no new lint issues)
uv run pytest         # Expected: all tests pass
```

### Final Checklist
- [x] `app.py`: `os._exit(0)` in `_signal_handler`, `sys.exit(0)` only at lines 262, 292
- [x] `src/utils/time.py` no longer exists
- [x] `src/utils/time_utils.py` exists with same content
- [x] All `from src.utils.time import` updated to `from src.utils.time_utils import`
- [x] `STEALTH_INIT_SCRIPT` constant in `src/utils/browser.py`
- [x] Both callers reference the shared constant, no duplicate inline scripts
- [x] `.omo/reports/code-review-remaining.md` exists with remaining issues
- [x] All QA evidence files present in `.omo/evidence/`
- [x] All 3 commits made, all tests pass
