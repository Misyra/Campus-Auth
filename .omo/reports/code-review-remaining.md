# Code Review Report — Remaining Unaddressed Issues

**Generated:** 2026-05-24
**Scope:** Campus-Auth v3.7.0
**Basis:** AGENTS.md anti-patterns (root, src/, backend/) + codebase inspection

> **Excluded (already fixed in commits `746edc1`, `5496cee`, `a790959`):**
> 1. `sys.exit(0)` → `os._exit(0)` in `_force_exit_after_timeout` (`backend/main.py`)
> 2. `src/utils/time.py` → `src/utils/time_utils.py` rename
> 3. JS stealth init script deduplication to `STEALTH_INIT_SCRIPT` constant

---

## Critical (2 issues)

### CRIT-1: Service instances as module-level globals
| Field | Value |
|-------|-------|
| **File** | `backend/main.py` |
| **Lines** | 162–165 |
| **Pattern** | Anti-pattern documented in `backend/AGENTS.md:32` |

**Issue:**
Four service instances are initialized at module scope during import:
```python
profile_service = ProfileService(project_root=PROJECT_ROOT)     # line 162
service = MonitorService(project_root=PROJECT_ROOT, ...)         # line 163
autostart_service = AutoStartService(project_root=PROJECT_ROOT)  # line 164
task_service = TaskService(project_root=PROJECT_ROOT)            # line 165
```

These singletons are created the moment any code does `from backend.main import ...`. Because `app.py` imports `_resolve_port`, `run`, `service`, and `_set_tray_icon` from `backend.main`, all four services are initialized during `app.py`'s `_run_server()` execution — before the actual server starts. This creates:
- **Import-order fragility**: changing the import sequence in `app.py` (or in tests) can trigger `AttributeError` or `FileNotFoundError` if `PROJECT_ROOT` isn't ready.
- **Testing difficulty**: services cannot be cleanly mocked or replaced because they're module-level singletons, not dependency-injected.
- **Side effects during import**: service constructors may read filesystem state (`settings.json`), which fails before the working directory is set.

**Recommendation:**
- Convert to lazy initialization (e.g., `get_profile_service()` factory functions) or use FastAPI's `Depends()` with dependency injection.
- For async context, consider `@app.on_event("startup")` or the `lifespan` protocol to initialize services after the event loop starts.
- If keeping singletons, wrap in `@functools.lru_cache(None)` for testable lazy init.

---

### CRIT-2: `backend/main.py` contains server startup logic (mixed concerns)
| Field | Value |
|-------|-------|
| **File** | `backend/main.py` |
| **Lines** | 1345–1405 |
| **Pattern** | Anti-pattern documented in `backend/AGENTS.md:31` |

**Issue:**
The `run()` function at the bottom of `main.py` handles:
- Reading `settings.json` for log level and retention configuration
- Initializing the `LogConfigCenter` logging system
- Adding file handlers for persistent log storage
- Cleaning up expired debug screenshots
- Resolving the port and starting `uvicorn`

```python
def run() -> None:
    import uvicorn
    # ... 30+ lines of log setup, config reading, cleanup, port resolution ...
    uvicorn.run("backend.main:app", host="127.0.0.1", port=_resolve_port(), ...)
```

`main.py` is conceptually the **FastAPI application definition** module (routes, middleware, WebSocket). Embedding server startup logic here violates the single-responsibility principle and makes it impossible to import the app without also pulling in uvicorn startup code.

`app.py` imports `run()` from `backend.main` at line 344 and calls it at line 377.

**Recommendation:**
- Move `run()` to `app.py` or a dedicated `server.py` module.
- Move log initialization to the FastAPI `lifespan` async context manager (already exists at line 63).
- Keep `main.py` focused on route definitions and app configuration only.

---

## Major (3 issues)

### MAJ-1: 85% of FastAPI routes are synchronous (block event loop)
| Field | Value |
|-------|-------|
| **File** | `backend/main.py` |
| **Scope** | 41 of 48 route handlers use sync `def` |
| **Pattern** | Anti-pattern documented in `backend/AGENTS.md:33` |

**Issue:**
FastAPI sync routes run in a thread pool but still block the event loop's thread until the thread-pool worker finishes. This is particularly problematic for routes performing I/O:

| Route | Operation | I/O Type |
|-------|-----------|----------|
| `PUT /api/config` (line 548) | File write `save_config_combined()` | Disk I/O |
| `POST /api/backup/create` (line 1193) | `settings_path.read_bytes()` | Disk I/O |
| `POST /api/backup/restore` (line 1213) | `backup_path.read_text()` | Disk I/O |
| `GET /api/repo/fetch` (line 696) | `_repo_get()` via `requests` | Network I/O |
| `GET /api/repo/task` (line 720) | `_repo_get()` via `requests` | Network I/O |
| `GET /api/profiles/detect` (line 1020) | Subprocess calls for gateway/SSID | Subprocess I/O |

Only 7 handlers are async: `check_update` (line 440/485), the 5 debug routes (lines 766–922), and the WebSocket endpoint (line 447).

**Recommendation:**
- Convert I/O-heavy routes to `async def`, using `aiofiles` for file operations and `httpx.AsyncClient` for HTTP calls.
- At minimum, convert the backup, config save, and repo fetch routes (they do explicit I/O).
- Profile routes (`detect`) that shell out to subprocess should use `asyncio.create_subprocess_exec`.

---

### MAJ-2: Blurry `backend/` + `src/` package boundary
| Field | Value |
|-------|-------|
| **Files** | 8 files across `backend/` and `src/` |
| **Pattern** | Anti-pattern documented in `root/AGENTS.md:69` |

**Issue:**
Despite a two-package architecture intending separation, the boundary is porous in both directions:

**`backend/` importing `src/` (25 instances across 8 files):**
```
backend/config_service.py  → src.utils.crypto, src.utils.logging, src.utils.exceptions
backend/monitor_service.py → src.monitor_core, src.network_test, src.utils.*
backend/main.py            → src.utils.ConfigValidator, src.utils.env, src.version, src.task_executor
backend/profile_service.py → src.utils.platform_utils, src.utils.crypto
backend/task_service.py    → src.task_executor
backend/schemas.py         → src.utils.platform_utils
backend/autostart_service.py → src.utils.platform_utils
backend/uninstall_service.py → src.utils.platform_utils
```

**`src/` importing `backend/` (TYPE_CHECKING guarded):**
```python
# src/monitor_core.py:21
if TYPE_CHECKING:
    from backend.profile_service import ProfileService
```

**Circular import chain:**
```
app.py → backend/main.py → ... → src/... → backend/ (TYPE_CHECKING)
```

The TYPE_CHECKING guard prevents runtime circular imports but masks the architectural coupling. The heavy one-way dependency (`backend`→`src`) suggests the split is artificial.

**Recommendation:**
- Consider collapsing `backend/` and `src/` into a single `app/` package with clear sub-packages (e.g., `app/routes/`, `app/services/`, `app/core/`).
- Alternatively, formalize `src/` as a shared library with a strict public API surface in `src/__init__.py` and ban `from src` imports in `backend/` outside an adapter layer.

---

### MAJ-3: No CI/CD pipeline
| Field | Value |
|-------|-------|
| **Pattern** | Anti-pattern documented in `root/AGENTS.md:70` |

**Issue:**
All quality checks and releases are manual:
- Tests: `uv run pytest` (manual only)
- Linting: `uv run ruff check .` (manual only)
- Formatting: `uv run ruff format .` (manual only)
- Releases: `release/` zips are hand-produced
- No automated test running on push/PR
- No automated linting or formatting enforcement

Without automation:
- Regressions can be introduced without detection
- Release artifacts may have inconsistent content
- No quality gates protect the `main` branch

**Recommendation:**
- Add a minimal GitHub Actions workflow (`.github/workflows/ci.yml`) that runs on push and PR:
  - `uv sync` + `uv run ruff check .` + `uv run pytest`
- Add a release workflow that automates zip creation and GitHub Release publishing.

---

## Minor (4 issues)

### MIN-1: `BrowserContextManager` initialization race with `playwright_bootstrap.py`
| Field | Value |
|-------|-------|
| **Files** | `src/utils/browser.py` (lines 105–160), `src/playwright_bootstrap.py` (lines 19–20, 102+) |
| **Pattern** | Anti-pattern documented in `src/AGENTS.md:44` |

**Issue:**
`BrowserContextManager._start_browser()` (browser.py:105) launches Playwright/Chromium directly without first verifying that the browser binaries are installed:

```python
async def _start_browser(self) -> None:
    from playwright.async_api import async_playwright
    self.playwright = await async_playwright().start()
    self.browser = await self.playwright.chromium.launch(...)
```

Meanwhile, `playwright_bootstrap.py` provides `ensure_playwright_ready()` (line 102) that must be called separately — but there is no enforcement mechanism. If two concurrent login attempts occur:
1. Thread A calls `ensure_playwright_ready()` and begins installing Chromium.
2. Thread B calls `BrowserContextManager._start_browser()` without checking the bootstrap lock.
3. Both threads try to launch Playwright simultaneously, causing a race on the browser installation.

The `_BOOTSTRAP_LOCK` in `playwright_bootstrap.py` (line 19) is only acquired within `ensure_playwright_ready()`, not by `BrowserContextManager`.

**Recommendation:**
- Have `BrowserContextManager` call `playwright_bootstrap.ensure_playwright_ready()` before launching.
- Alternatively, use a shared `asyncio.Lock` to serialize bootstrap + launch sequences.

---

### MIN-2: AGENTS.md out of sync — `VariableResolver` already has cycle detection
| Field | Value |
|-------|-------|
| **File** | `src/AGENTS.md` (line 43) vs `src/task_executor.py` (lines 280–282) |
| **Severity** | Documentation drift |

**Issue:**
`src/AGENTS.md` states:
> "`VariableResolver` has recursion limit but no cycle detection in template resolution"

But the code at `task_executor.py:280–282` implements cycle detection:

```python
# 检查循环引用
if var_name in visited:
    raise StepError(f"检测到变量循环引用: {var_name}")
```

The `visited` set is correctly propagated through recursive calls via `visited | {var_name}` (lines 291, 298). This detection was present since commit `c2311497` (2026-04-22). The AGENTS.md generation script (dated 2026-05-20) apparently did not capture this.

**Recommendation:**
- Update `src/AGENTS.md` line 43 to reflect the correct state: "`VariableResolver` has recursion limit AND cycle detection via `visited` set."
- Add a note about the detection mechanism.

---

### MIN-3: `_repo_get` uses synchronous `requests` in FastAPI context
| Field | Value |
|-------|-------|
| **File** | `backend/main.py` |
| **Lines** | 727–737 |

**Issue:**
The `_repo_get` helper function uses the synchronous `requests` library:

```python
def _repo_get(url: str):
    import requests as _requests
    resp = _requests.get(url, headers=..., timeout=15, proxies=...)
    resp.raise_for_status()
    return resp
```

This is called from the sync routes `/api/repo/fetch` (line 696) and `/api/repo/task` (line 720), making external HTTP calls that block the thread pool worker. The project already depends on `httpx` (used in `check_update` at line 442 with `AsyncClient`), so the inconsistency is purely a style and performance concern.

In production with concurrent users, a slow remote task repository would tie up multiple worker threads.

**Recommendation:**
- Replace `requests` with `httpx.AsyncClient` and convert the calling routes to `async def`.
- Or, if keeping sync, at least move the external HTTP call to a background task.

---

### MIN-4: No type checking (project-wide)
| Field | Value |
|-------|-------|
| **Scope** | All Python files |
| **Pattern** | Conventions in `root/AGENTS.md:63` |

**Issue:**
The project explicitly eschews type checking:
> "No type checking (no mypy, no TypeScript)"

This means:
- Type annotations are inconsistent — some functions use them, most don't.
- Mismatched argument types are discovered only at runtime.
- Refactoring (e.g., changing a function signature) requires manual grep across the codebase.
- FastAPI Pydantic models mitigate this for request/response data, but internal function calls are unchecked.

**Recommendation:**
- Add `mypy` or `pyright` to the development workflow (not required for CI gatekeeping, but useful locally).
- At minimum, adopt `from __future__ import annotations` project-wide.
- Gradually add type annotations to new/changed code.

---

## Summary

| Severity | Count | IDs |
|----------|-------|-----|
| Critical | 2 | CRIT-1 (module globals), CRIT-2 (mixed concerns in main.py) |
| Major | 3 | MAJ-1 (sync routes), MAJ-2 (blurry boundary), MAJ-3 (no CI/CD) |
| Minor | 4 | MIN-1 (browser race), MIN-2 (doc drift), MIN-3 (sync HTTP), MIN-4 (no types) |
| **Total** | **9** | |

### Quick Wins
1. **MIN-2**: Update `src/AGENTS.md` to acknowledge existing `VariableResolver` cycle detection (1-line fix).
2. **MIN-3**: Replace `requests` with `httpx.AsyncClient` in `_repo_get` (small refactor, uses existing dependency).
3. **MIN-1**: Add `ensure_playwright_ready()` call at the start of `BrowserContextManager._start_browser()`.

### Architectural Priorities
1. **CRIT-1**: Refactor service initialization to lazy/factory pattern to fix import-order fragility.
2. **CRIT-2**: Move `run()` from `main.py` to a dedicated module.
3. **MAJ-1**: Gradually convert I/O-heavy routes to `async def`.
