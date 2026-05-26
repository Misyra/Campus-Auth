# Playwright Worker Loop Refactor Design

## Goal
Eliminate cross-event-loop Playwright usage by routing all browser lifecycle and login execution through a single dedicated thread that owns a persistent asyncio event loop.

## Background and Root Cause
The current monitor login path creates and closes a new event loop per attempt while reusing Playwright objects. Reuse across attempts binds the browser/context/page to the first loop, but subsequent attempts run on a different loop. This mismatch triggers cleanup failures ("different loop") and can crash the driver during navigation.

## Proposed Architecture
- Introduce a dedicated Playwright worker thread that owns one persistent asyncio event loop for all login and browser operations.
- All Playwright interactions (create, reuse, navigate, close) happen on this worker loop only.
- The monitor thread communicates with the worker using a blocking queue of requests and responses (actor style), preserving the existing single-threaded control flow in the monitor core.

## Components and Responsibilities
- **PlaywrightWorker (new module)**
  - Owns thread + loop lifecycle.
  - Maintains a single `LoginAttemptHandler` instance for reuse across retries.
  - Executes `attempt_login()` on its own loop.
  - Handles `close_browser()` and shutdown cleanup on the same loop.
- **NetworkMonitorCore (existing)**
  - Delegates login attempts to the worker.
  - Remains synchronous from the caller perspective (block on worker response).
  - Retains retry and cancel logic.
- **MonitorService (existing)**
  - Starts and stops the worker with monitor lifecycle.

## Data Flow (Happy Path)
1. Monitor core detects network issue and requests a login attempt.
2. Request is pushed to worker queue.
3. Worker pulls request, runs `LoginAttemptHandler.attempt_login()` on its loop.
4. Worker returns success/error result to monitor core.
5. Monitor core logs and continues normal flow.

## Error Handling and Recovery
- Any Playwright exception during login is captured within the worker, returned to the monitor core as a failed attempt.
- Cleanup errors are logged but do not abort the monitor thread.
- On driver disconnect or cleanup failure, worker clears cached handler/browser state so the next attempt starts fresh on the same loop.
- Worker shutdown always runs `close_browser()` on its loop before exiting.

## Threading Model
- **Monitor thread**: synchronous logic and retry scheduling.
- **Worker thread**: exclusive owner of Playwright objects and asyncio loop.
- Communication via `queue.Queue`, avoiding cross-thread asyncio calls.

## Testing Strategy
- Update tests to ensure login attempts run through worker and do not create per-attempt loops.
- Add a test that simulates two consecutive login attempts with reuse enabled to ensure no loop mismatch occurs.
- Maintain existing behavior for cancel events and retry logic.

## Migration Plan
1. Add Playwright worker module and integrate with monitor lifecycle.
2. Route monitor core login attempts through worker.
3. Update tests and validate with focused pytest runs.

## Out of Scope
- Changes to task execution logic or UI.
- Changes to Playwright task templates.

## Risks and Mitigations
- **Risk**: Worker thread lifecycle mismatches monitor lifecycle.
  - **Mitigation**: Worker start/stop is tied to monitor start/stop only.
- **Risk**: Blocking wait on worker could stall shutdown.
  - **Mitigation**: Use timeout and fallback cleanup path in worker.
