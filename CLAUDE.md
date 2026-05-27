# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Campus-Auth is a campus network auto-authentication tool built with FastAPI (backend) + Vue 3 (frontend, no build step) + Playwright (browser automation). It monitors network connectivity and automatically re-authenticates when disconnected.


## 交互要求

- 与用户沟通、询问问题、回复内容必须全部使用中文
- 代码注释必须使用中文（包括行内注释、函数/类文档字符串、模块说明等）

## 提交规范

- 提交信息使用中文描述
- 格式：`<type>: <简要描述>`，可选 body 说明具体变更
- type 类型：`feat` / `fix` / `refactor` / `docs` / `style` / `test` / `chore`
- 示例：
  ```
  fix: 修复调试会话双重启动与 run_all 信号量阻塞
  refactor: 网络检测配置重构，支持独立勾选检测方式
  ```

## Commands

```bash
# Install dependencies (uses uv with Tsinghua mirror)
uv sync

# Run the server (default port 50721)
uv run app.py

# Run all tests
uv run pytest

# Run a single test file
uv run pytest tests/test_task_executor.py -v

# Run tests by name pattern
uv run pytest -k "test_name"

# Run with specific Python (embedded env, Windows)
.\environment\python\python.exe app.py
```

## Architecture

### Entry Point

`app.py` — Unified entry point. Handles PID lock, Playwright bootstrap, signal handling, then delegates to `backend.main:run()` which starts Uvicorn.

### Backend (`backend/`)

FastAPI application. **All routes live in a single file** `main.py` (~1300 lines, 50+ endpoints). Services are module-level globals initialized at import time.

| File | Purpose |
|------|---------|
| `main.py` | FastAPI app, all API routes, DebugSession, lifespan management |
| `monitor_service.py` | Monitor start/stop, WebSocket broadcast, login trigger (Actor model — message queue to background thread) |
| `profile_service.py` | Multi-network profile CRUD, gateway IP / WiFi SSID detection, auto-switch |
| `config_service.py` | Config read/write, init status |
| `task_service.py` | Task CRUD, active task, danger step detection |
| `schemas.py` | Pydantic models (`MonitorConfigPayload`, `ProfileSettings`, `ProfilesData`, etc.) |

### Core Logic (`src/`)

| File | Purpose |
|------|---------|
| `task_executor.py` | Task execution engine (~1400 lines). Step handlers (`StepHandler` subclasses registered in `StepExecutorRegistry`): navigate, input, click, select, wait, eval, screenshot, sleep, ocr. Variable resolution: `{{VAR_NAME}}` |
| `monitor_core.py` | Network monitoring loop, profile auto-switch, login trigger with retry/backoff |
| `network_decision.py` | Decision layer: `should_attempt_login()`, `is_auth_url_reachable()` |
| `network_probes.py` | TCP socket + HTTP probes, local network detection |
| `playwright_worker.py` | Actor model worker thread — all Playwright ops run in a dedicated thread via command queue (`submit()` → `WorkerCommand` → `WorkerResponse`) |
| `playwright_bootstrap.py` | Playwright/Chromium install check and auto-download |
| `system_tray.py` | System tray icon + menu (pystray) |

### Utilities (`src/utils/`)

| File | Purpose |
|------|---------|
| `browser.py` | `BrowserManager` — browser lifecycle, health check, context creation |
| `login.py` | `build_login_env_vars()`, login retry logic |
| `crypto.py` | Password encrypt/decrypt (Fernet). `ENC:` prefix in settings.json |
| `logging.py` | `get_logger()`, `LogBuffer` (ring buffer 1200 entries), WebSocket handler, `LogConfigCenter` |
| `config.py` | `ConfigValidator` — input validation |
| `notify.py` | Cross-platform desktop notifications |
| `time_utils.py` | Time utilities |
| `network_helpers.py` | Host:port parsing helpers |
| `file_helpers.py` | `atomic_write()` for safe file operations |
| `platform_utils.py` | `is_windows()`, `is_macos()`, `is_linux()`, `get_default_ua()` |

### Frontend (`frontend/`)

Vue 3 SPA served as static files by FastAPI. **No build tool** — uses UMD Vue + native ES modules.

- `index.html` — Root HTML, loads Vue 3 + Axios from `vendor/`
- `app.js` — Vue app entry, mounts after partials loaded
- `template-loader.js` — Fetches HTML partials, injects into DOM before Vue mount
- `js/app-options.js` — Vue options (data, computed, methods, lifecycle for all pages)
- `js/methods/` — Business logic modules (actions, config, profiles, tasks, ui, etc.)
- `partials/pages/` — HTML templates: dashboard, settings, tasks, profiles, about
- `vendor/` — Vendored UMD: `vue.global.prod.js`, `axios.min.js`

Page navigation is hash-based show/hide with `v-if`, not Vue Router.

### Tasks (`tasks/`)

JSON files describing browser automation steps. Each task has a `url`, `variables`, and `steps` array. Steps use types like `eval`, `input`, `click`, `select`, `wait`, `screenshot`, `sleep`, `ocr`. Variable templates: `{{USERNAME}}`, `{{PASSWORD}}`, `{{ISP}}`, `{{LOGIN_URL}}`.

The active task is tracked in `tasks/active.txt`.

### Configuration

All config lives in `settings.json` (gitignored). Structure: `{ auto_switch, active_profile, system: SystemSettings, profiles: { [id]: ProfileSettings } }`. Passwords are encrypted with Fernet (`ENC:` prefix).

## Key Patterns

- **Actor model threading**: `PlaywrightWorker` and `MonitorService` use message queues to isolate browser ops and monitoring loops in dedicated threads. External code calls `submit()` and optionally waits for `WorkerResponse`.
- **Step handler registry**: New task step types = subclass `StepHandler`, register in `StepExecutorRegistry`.
- **Variable resolution**: `{{VAR_NAME}}` resolves through env vars → task variables → runtime vars.
- **Network detection**: Layered — `network_probes.py` (TCP/HTTP probes) → `network_decision.py` (decision logic) → `monitor_core.py` (monitoring loop).
- **Frontend API calls**: Functions in `js/methods/` call backend endpoints defined in `backend/main.py`.

## Important Notes

- `settings.json` is gitignored — never commit it (contains encrypted credentials).
- `tasks/active.txt` is gitignored — local user preference.
- The `environment/` directory contains an embedded Python for Windows distribution — also gitignored.
- The frontend has no build step — edit HTML/JS files directly and refresh.
- All routes are in `backend/main.py` — there is no route splitting across files.
- `src/utils/time_utils.py` was renamed from `time.py` to avoid shadowing stdlib `time`.
- 本项目仅本地运行，安全类问题（API 无鉴权、CORS 全开等）属于设计决策，不属于代码审查范围。
- 依赖版本以 `pyproject.toml` 为权威来源，版本锁定要严格（精确到 patch 或窄范围），避免依赖不一致导致 bug。`requirements.txt` 是面向用户运行的简化清单，只列必要运行依赖，不包含开发工具。
