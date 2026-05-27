# monitor-actor-refactor: Learnings

## Task 4 — Fix TOCTOU race + replace thread-local httpx.Client caching in src/network_test.py

### Changes Made

1. **Removed 	hreading.local() caching (_thread_local, _get_http_client())**
   - _get_http_client() was caching httpx.Client per thread via 	hreading.local()
   - These clients were never explicitly closed — leaked resources
   - _block_proxy setting was cached at creation time, so proxy changes didn't take effect
   - **Fix**: Replaced with on-demand httpx.Client(trust_env=not _block_proxy) using with context manager at the single call site in is_network_available_http()

2. **Fixed TOCTOU race in _get_executor()**
   - Added _executor_lock = threading.Lock() to protect the check-create sequence
   - Now checks _executor._shutdown flag under lock — if executor was shut down by another thread, creates a fresh one
   - Prevents race between _get_executor() and _cleanup_resources() — but _cleanup_resources was also removed (see below)

3. **Removed texit registration and _cleanup_resources()**
   - _cleanup_resources() shut down the executor and set it to None
   - With thread-local httpx clients gone, the primary leak source was eliminated
   - Executor is a process-level resource that gets cleaned up on exit anyway
   - Removed import atexit (unused)

### Key Patterns

- with httpx.Client(trust_env=not _block_proxy) as client: — auto-closes on exit
- _executor._shutdown — internal flag on ThreadPoolExecutor, safe to check under lock
- Lock in _get_executor() handles both TOCTOU and initialization races
- _block_proxy is now read fresh on every HTTP check — set_block_proxy() changes take effect immediately

### Verification

- uff check src/network_test.py --quiet passes with no output
- No 	hreading.local() usage remains
- No _get_http_client() function
- No texit usage

## Task 2 — Fix _DateRotatingFileHandler.close() race + simplify deferred-open in src/utils/logging.py

### Changes Made

1. **Fixed close() race condition**
   - close() now acquires self._emit_lock before accessing self._stream
   - Previously accessed _unflushed_lines and _stream without lock, racing with emit()
   - Both emit() and close() now acquire/release the same lock — no nested locks, no deadlock

2. **Simplified deferred-open buffering**
   - Before: emit() accumulated messages in _unflushed_lines buffer, only opening file when count >= 10 or 5 seconds elapsed
   - After: emit() calls _open_file() immediately on first call (when self._stream is None), writes directly to self._stream
   - Removed fields: _unflushed_count, _last_flush_time, _unflushed_lines, _pending_path
   - Removed _pending_path = None from _open_file() (field no longer exists)

3. **close() simplified**
   - No need to flush _unflushed_lines since all lines are written immediately in emit()
   - Just closes _stream under the lock, sets it to None

### Files Modified
- src/utils/logging.py — _DateRotatingFileHandler class

### Files Added
- tests/test_logging_concurrent.py — 2 concurrency tests

### Verification
- ruff check src/utils/logging.py --quiet — passes
- ruff format src/utils/logging.py — clean
- uv run pytest tests/test_task_executor.py tests/test_logging_concurrent.py -v — 28 passed
- Concurrency test: 100 messages from 10 threads racing + close() — verified no corruption
- Immediate open test: first emit() opens file and writes immediately

## Task 5 — Simplify src/monitor_core.py: remove _loop/_loop_stopped/_config_lock/_login_tasks

### Changes Made

1. **Removed `_config_lock` (threading.RLock)**
   - Deleted from `__init__`
   - Removed all 7 `with self._config_lock:` wrappers in `update_config()`, `start_monitoring()`, `_get_retry_config()`, `monitor_network()` (x2), `_build_test_sites()`, `attempt_login()`
   - Config is now accessed via plain `self.config.get(...)` — safe because in the Actor model, config is only read by the monitor thread on startup, no concurrent writes

2. **Moved `_loop` from instance attribute to local variable in `attempt_login()`**
   - Removed `self._loop = asyncio.new_event_loop()` from `start_monitoring()`
   - Removed `self._loop.close()` from `stop_monitoring()`
   - Now creates `loop = asyncio.new_event_loop()` locally inside `attempt_login()`, closes with `loop.close()` in a `finally` block after `run_until_complete`
   - Loop only exists during login execution, not as a persistent shared resource

3. **Replaced `_loop_stopped` with `self._stop_event.is_set()`**
   - `self._loop_stopped` flag in `stop_monitoring()` → removed
   - Check `if self._loop_stopped:` in `attempt_login()` → replaced with `if self._stop_event.is_set():`
   - `_stop_event` is a `threading.Event()` already exists and is set in `stop_monitoring()`

4. **Simplified `attempt_login()` task tracking**
   - Before: ~20 lines capturing `asyncio.all_tasks()`, tracking `_login_tasks`, cancelling tasks, `asyncio.gather()`
   - After: simple `loop.run_until_complete(handler.attempt_login(...))` wrapped in try/finally for loop.close()
   - Since the event loop is created fresh each time, there are no "leaked tasks" from elsewhere

### Files Modified
- `src/monitor_core.py` — reduced from 624 to 572 lines (-52 lines)

### Key Patterns
- `loop = asyncio.new_event_loop()` + `asyncio.set_event_loop(loop)` + `loop.close()` — local, scoped creation
- `self._stop_event.is_set()` — replaces `_loop_stopped` flag, same thread-safe Event pattern
- Fresh loop per login call eliminates need for task tracking/cancellation

### Verification
- `ruff check src/monitor_core.py --quiet` — passes (no output)
- `grep -n "self\._loop" src/monitor_core.py` → 0 matches
- `grep -n "_loop_stopped" src/monitor_core.py` → 0 matches
- `grep -n "_config_lock" src/monitor_core.py` → 0 matches
- `grep -n "_login_tasks" src/monitor_core.py` → 0 matches
- `grep -n "all_tasks\|task\.cancel\|asyncio\.gather" src/monitor_core.py` → 0 matches
