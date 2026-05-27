# codebase-optimization - Learnings

## 2026-05-26: config_helpers.py created

### PROFILE_FIELDS extraction
Extracted 40 profile field names from `MonitorConfigPayload` — the exact set of
fields repeated across `load_ui_config`, `load_runtime_config`, `build_runtime_config`,
and `save_config_combined` in `backend/config_service.py`.

The list was derived by unioning all field names that appear in field-by-field
assignments across those 4 functions. Key observations:
- All 40 fields come from `MonitorConfigPayload` (Pydantic model in `backend/schemas.py`)
- `backend/config_service.py` repeats the same field names ~4× across the 4 functions
- `ProfileSettings` has additional fields (`name`, `match_gateway_ip`, `match_ssid`,
  `use_global_auth_url`, `use_global_task`, `use_global_advanced`) that are NOT
  part of the repeated field pattern in config_service.py
- `BACKUP_FILENAME_PATTERN` matches the 3× inline regex at main.py:1248/1302/1317
## 2026-05-26: Extracted `atomic_write()` to shared utility

### Problem
3 identical `mkstemp + os.replace` patterns existed in the codebase:
- `backend/profile_service.py:_save_unsafe()` (line 377)
- `src/task_executor.py:save_task()` (line 1458)
- `backend/main.py:restore_backup()` (line 1273)

### Solution
Created `src/utils/file_helpers.py:atomic_write()` as a shared function.

### Key design decisions
- `os.makedirs(parent, exist_ok=True)` — auto-creates parent dirs, matching existing callers that pass `dir=parent`
- `dir=parent or None` — handles bare filenames (no directory component) gracefully by falling back to system temp dir
- PermissionError fallback — allows direct write when `os.replace` fails (Windows edge case)
- Temp file cleanup on any exception — matches existing pattern but also cleans up on PermissionError fallback unlink failure
- `errors="replace"` in `open()` — encoding error tolerance, same as used in `backend/config_service.py`

### Tests
5 tests in `tests/test_file_helpers.py` covering: success write, parent dir creation, overwrite, cleanup on failure, custom prefix/suffix. All pass.
- 2026-05-26: Created `tests/test_config.py` — 36 tests for `ConfigValidator.validate_gui_config()` and `validate_env_config()`. Covers empty/short/masked passwords, interval bounds, non-integer intervals, missing credentials, and missing auth URL.
## 2026-05-26: Replaced 3 inline atomic writes with `atomic_write()` calls

### Files modified
- `backend/profile_service.py:_save_unsafe()` — replaced `tempfile.mkstemp` + `os.replace` with `atomic_write()`
- `src/task_executor.py:save_task()` — replaced inner atomic write block with `atomic_write()`
- `backend/main.py:restore_backup()` — replaced `tempfile.mkstemp` + `os.replace` with `atomic_write()`

### Details
- All 3 callers now use the shared `src.utils.file_helpers.atomic_write()` function
- Removed unused `import os` and `import tempfile` from `profile_service.py`
- Removed unused `import tempfile` from `main.py`
- Removed unused `import os` and `import tempfile` from `task_executor.py`
- No logic changes — error handling is now centralized in `atomic_write()`
- All 33 existing tests pass unchanged

## 2026-05-26 — Created `parse_host_port()` shared function

- Created `src/utils/network_helpers.py` with `parse_host_port(targets: list[str]) -> list[tuple[str, int]]`
- Function uses `rsplit(":", 1)` to handle IPv6 bracket notation naturally (`[::1]:8080` → `("[::1]", 8080)`)
- Raises `ValueError` for: missing colon, empty host, non-numeric port, port out of range (1-65535)
- Existing inline parsers in `monitor_core.py:476`, `login.py:273`, `monitor_service.py:585` have identical `rsplit` + `isdigit` + default-port logic — these are candidates for Wave 2 replacement
- Created `tests/test_network_helpers.py` with 19 tests covering all edge cases
## 2026-05-26: Replaced string return values with `RecoveryResult` enum

### Problem
`_login_retry_or_break()` and `_login_recovery_loop()` used bare string returns like `"break"`, `"give_up"`, `"login_ok"`, `"net_disconnect"`. `monitor_network()` compared results with string literals. No type safety — typo risks.

### Solution
Added `RecoveryResult(str, Enum)` at top of `src/monitor_core.py` with 4 members:
- `LOGIN_OK = "login_ok"`, `GIVE_UP = "give_up"`, `BREAK = "break"`, `NET_DISCONNECT = "net_disconnect"`

Using `str, Enum` as base preserves direct string comparison compatibility (`RecoveryResult.BREAK == "break"` works).

### Changes
- `_login_retry_or_break()`: `"break"` → `RecoveryResult.BREAK`, `"give_up"` → `RecoveryResult.GIVE_UP`
- `_login_recovery_loop()`: all 4 string returns replaced; 2 string comparisons replaced
- `monitor_network()`: 3 string comparisons replaced (`"login_ok"`, `"break"`, `"net_disconnect"`)
- `"retry"` kept as bare string — it's an internal signal not part of the 4-state result enum

## 2026-05-26: Replaced manual field assignments with config_helpers in config_service.py

### Problem
`backend/config_service.py` had ~40 fields manually assigned 4× across `load_ui_config()`,
`load_runtime_config()`, `build_runtime_config()`, and `save_config_combined()`.
`backend/main.py` had 3× inline backup regex strings.

### Changes

**`backend/config_service.py`:**
- `load_ui_config()`: Replaced 40 local variables + 40 `MonitorConfigPayload` kwargs with
  `extract_profile_fields()` from both `sys.__dict__` and `global_profile.__dict__`,
  plus 6 UI-specific overrides.
- `load_runtime_config()`: Replaced 2×20 advanced-field if/else blocks with
  `extract_profile_fields()` from `adv_source.__dict__`, excluding credential/auth keys.
  Kept explicit credential/auth/task/carrier logic (complex conditional).
- `build_runtime_config()`: Replaced 7 flat `base[key] = payload.key` assignments with
  `assign_profile_fields()`.
- `save_config_combined()`: Replaced 11 direct sys field assignments and 12 direct glob
  field assignments with `assign_profile_fields()`. Normalized fields remain explicit.

**`backend/main.py`:**
- Imported `BACKUP_FILENAME_PATTERN` from `src.utils.config_helpers`
- Replaced 3 inline `r"^settings_\d{8}_\d{6}..."` regexes with `BACKUP_FILENAME_PATTERN`

### Key design decisions
- Merge order: global_profile first, then sys (sys values win for overlapping fields like
  `block_proxy` that exist in both `SystemSettings` and `ProfileSettings`)
- Advanced settings in `load_runtime_config()` exclude `_CREDENTIAL_KEYS` to avoid
  overwriting the credential/auth fields resolved by upstream conditional logic
- `stealth_mode` now flows through all 4 functions (previously omitted in `load_ui_config`,
  `load_runtime_config`, `save_config_combined` — likely an oversight)
- Profile field lists for `assign_profile_fields` are explicit per-block (direct vs normalized)
  rather than using the full `PROFILE_FIELDS` list, to preserve normalization behavior

## 2026-05-26: Replaced `_debug` dict with `DebugSession` dataclass in main.py

### Problem
`backend/main.py` used a plain dict `_debug` with 11 keys accessed via `_debug["key"]` syntax
throughout the file (47 dict accesses across 8 functions). 3 places rebuilt the full dict
from scratch (initialization, `debug_start`, `debug_stop`). No type safety.

### Solution
- Replaced `_debug` dict with `_debug_session = empty_debug_session()` (DebugSession dataclass)
- All `_debug["key"]` → `_debug_session.key` attribute access
- All 3 full dict rebuilds → `empty_debug_session()` calls
- `_debug_response()` → delegates to `debug_to_response(_debug_session)`
- `_debug["_debug_gen"]` generation counter → module-level `_debug_gen` from `debug_session.py` + `_next_debug_gen()` function
- `from collections import deque` removed (dataclass uses `deque(maxlen=1000)` internally)
- `global _debug` → `global _debug_session`

### Key design decisions
- `DebugSession` dataclass in `debug_session.py` has 10 fields matching old dict keys (minus `_debug_gen`)
- `_debug_gen` kept as standalone module-level counter to preserve stale-generation watcher logic
- `debug_to_response()` strips internal fields (`executor`, `_last_activity`, `_timer_task`) — matches old `_debug_response()` behavior
- `_debug_timeout_watcher` still uses field-by-field reset (not `empty_debug_session()`) to preserve in-place mutation semantics for the active session reference
- The local `class DebugSession` (Playwright browser wrapper) at line 192 shadows the imported dataclass name — works because the dataclass is only used implicitly via `empty_debug_session()` and `debug_to_response()`

## 2026-05-26: `MonitorService._handle_stop()` missing `_stop_event.set()`
- **Bug**: `_handle_stop()` ran cleanup but never signaled `self._stop_event`. Any loops waiting on `self._stop_event.is_set()` (WS drain line 160, queue consumer line 382) blocked indefinitely.
- **Fix**: Added `self._stop_event.set()` as first line of `_handle_stop()` in `backend/monitor_service.py:211`.
- **Verification**: `MonitorService._handle_stop()` acceptance test passes; all 12 existing tests pass unchanged.

## 2026-05-26: Removed `_set_tray_icon` dead code

- **Files modified**: `backend/main.py` (removed empty function), `app.py` (removed import + call)
- **Problem**: `_set_tray_icon()` was a no-op function with a docstring saying "保留给将来系统托盘集成使用". It was imported and called in `app.py` but did nothing — the tray icon is managed by pystray directly.
- **Details**: Function at `backend/main.py:1093-1098` was empty (just docstring + blank body). Import + call at `app.py:369-371` (`from backend.main import _set_tray_icon` + `_set_tray_icon(tray_icon)`) were both removed.
- **Impact**: No functional change. Shutdown has used independent thread stopping for a while; the `_tray_icon_ref` mechanism was never implemented.
- **Verification**: `from backend.main import _set_tray_icon` → `ImportError` ✅; `import app` → succeeds ✅; system tray `on_exit` callback (app.py:360-363) untouched.

## 2026-05-26: Replaced `requests` with `httpx` (sync mode)

### Problem
`backend/main.py` used `requests` library in 3 functions (`_repo_get`, `repo_fetch_index`, `repo_fetch_task`) while already using `httpx` in `/api/check-update`. This added an unnecessary dependency.

### Changes
- **`backend/main.py`**:
  - `_repo_get()`: `import requests as _requests` + `_requests.get()` → `import httpx` + `httpx.Client(proxies=..., timeout=httpx.Timeout(15))` context manager
  - `repo_fetch_index()`: `import requests as _requests` → `import httpx`; `_requests.HTTPError` → `httpx.HTTPStatusError`
  - `repo_fetch_task()`: same pattern as `repo_fetch_index()`
- **`pyproject.toml`**: Removed `"requests>=2.33.1"` line from `[project]dependencies`
- **`requirements.txt`**: Removed `requests>=2.33.1` line

### Key design decisions
- `httpx.Client()` used as context manager (`with` block) for proper connection cleanup
- `proxies` default changed from `None` to `{}` — `httpx` treats empty dict as no proxy (same behavior)
- `timeout=httpx.Timeout(15)` used instead of bare `timeout=15` for explicit timeout config
- Inline imports kept in all 3 functions (matching original pattern of local imports)
- `httpx.HTTPStatusError.has_response` used same way as `requests.HTTPError.response`
- `resp.json()` works identically on `httpx.Response`

### Verification
- `Select-String -Path "backend/*.py", "src/**/*.py" -Pattern "import requests"` → no output ✅
- `python -c "from backend.main import app; print('OK')"` → `OK` ✅
- 459/462 tests pass (3 pre-existing failures unrelated) ✅

