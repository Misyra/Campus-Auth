# Task 10: BrowserContextManager → Worker Proxy

**Date**: 2026-05-27

## Summary
Replaced BrowserContextManager's direct Playwright lifecycle management with Worker delegation. BrowserContextManager now proxies through PlaywrightWorker for browser acquire/release.

## Key Design Decisions

### 1. Direct call vs submit() (Deadlock avoidance)
BrowserContextManager.__aenter__ runs inside the Worker's event loop thread (called from _handle_login → LoginAttemptHandler). Using worker.submit(CMD_BROWSER_ACQUIRE, wait=True) would **deadlock** — the event loop is blocked by the calling coroutine and can't process the queue command.

**Solution**: Added nsure_browser(config) as a public async method on PlaywrightWorker that can be called directly from within the Worker's event loop. __aenter__ calls this directly instead of going through the submit queue.

### 2. Thread-safe browser object access
Since BrowserContextManager is always used from within the Worker's event loop thread, we safely copy browser references from Worker's internal state (worker._playwright, worker._browser, worker._context, worker._page). These are the same objects in the same thread — no cross-thread access.

### 3. CMD_BROWSER_RELEASE is fire-and-forget
__aexit__ uses worker.submit(CMD_BROWSER_RELEASE, wait=False) since we don't need to wait for response. The browser stays alive in Worker for reuse. This is safe because:
- We're exiting the context manager and don't need the browser anymore
- Worker manages browser lifetime independently
- The release handler is a no-op (browser stays alive)

### 4. Deprecated stubs kept for backward compatibility
_start_browser() and _cleanup_browser() are kept as stubs that log deprecation warnings. They guard on self._worker_managed to skip actual browser operations. This provides graceful degradation if Worker isn't available.

### 5. Worker shared state
Added _handle_browser_acquire for the submit-queue path (external callers) and _handle_browser_release (no-op, browser stays alive). nsure_browser() is shared between both paths.

## Files Modified
- src/playwright_worker.py — Added CMD_BROWSER_ACQUIRE, CMD_BROWSER_RELEASE, handlers, nsure_browser()
- src/utils/browser.py — Rewrote __aenter__/__aexit__, deprecated _start_browser/_cleanup_browser

## Verification
- grep -n "async_playwright" src/utils/browser.py → No matches (removed)
- __aenter__ references get_worker() and nsure_browser() → confirmed via Python inspection
- All 13 existing browser tests pass
- Ruff check passes on both modified files

## Blocks
- Task 11: LoginAttemptHandler can now assume browser is managed by Worker
- Task 12: Further Worker consolidation
