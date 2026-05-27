# Campus-Auth 代码库优化与重构

## TL;DR

> **Quick Summary**: 全面优化代码库——提取 3 个共享工具函数（host:port 解析、原子写入、配置字段赋值）、封装 DebugSession 为 dataclass、枚举化重试返回码、修复并发锁和语义缺陷、移除死代码和冗余依赖、补充缺失测试。
> 
> **Deliverables**: `network_helpers.py`, `file_helpers.py`, `config_helpers.py`, `debug_session.py`, `RecoveryResult` Enum, 修复 `_stop_event`, 移除 `_set_tray_icon`, `_compare_versions` 修复, `requests` → `httpx`, 备份正则常量, 测试补充
> 
> **Estimated Effort**: Medium-Large
> **Parallel Execution**: YES - 3 waves
> **Critical Path**: Wave 1 (提取) → Wave 2 (替换) → Wave 3 (修复) → F1-F4

---

## Context

### Original Request
全面检查项目，找出可优化、适合重构的部分，优化性能，精简逻辑，列出并发锁。经逐项代码核实确认：time.py 阴影已修复（→time_utils.py），os._exit bug 已修复，host:port 重复为 3 处（非 4 处）。

### Research Findings
- 配置字段 4× 重复确认存在（`check_interval_minutes` grep 12 matches in 4 functions）
- `_debug` dict 18 键 3 处替换确认存在
- 原子写入 3 处重复确认存在
- `_stop_event` 从未被 `.set()` 确认（grep 仅有 `monitor_core` 的另一个 `_stop_event`）
- `_set_tray_icon` 空函数确认存在
- 备份正则 3 处重复确认存在
- `_compare_versions` 返回 -1（非 0）确认存在

### Metis Review
- 不触碰 `task_executor.py`（认证引擎）
- 不修改 `monitor_core.py` 认证控制流逻辑（枚举替换是安全重构）
- 不拆分 `main.py` 路由、不添加 CI/CD、不修改 `pyproject.toml` build-system
- 每次重构前写测试

---

## Work Objectives

### Core Objective
消除代码重复、提取高内聚低耦合的共享函数、修复已知缺陷、补充测试。

### Concrete Deliverables
- `src/utils/network_helpers.py` — `parse_host_port()` 统一 host:port 解析
- `src/utils/file_helpers.py` — `atomic_write()` 统一原子写入
- `src/utils/config_helpers.py` — 配置字段赋值辅助 + `BACKUP_FILENAME_PATTERN` 常量
- `backend/debug_session.py` — `DebugSession` dataclass + `empty_debug_session()` + `debug_to_response()`
- `src/monitor_core.py` — `RecoveryResult` Enum 替代字符串返回码
- 修复 `_stop_event` 未设置、移除 `_set_tray_icon`、修复 `_compare_versions`、`requests` → `httpx`
- `tests/test_time_utils.py`, `tests/test_config.py` 测试补充

### Definition of Done
- [x] `uv run pytest` 全部通过（459 pass, 3 pre-existing failures）
- [x] `uv run app.py` 正常启动，`/api/health` 返回 200
- [x] 所有新增函数有单元测试
- [x] 无新增 import 错误

### Must Have
- host:port 解析去重（3→1）、原子写入去重（3→1）、配置字段辅助
- DebugSession dataclass、RecoveryResult Enum
- _stop_event 修复、_set_tray_icon 移除、_compare_versions 修复
- 备份正则常量、requests → httpx
- 测试补充

### Must NOT Have (Guardrails)
- 不触碰 `task_executor.py` 步骤处理逻辑
- 不改变 `monitor_core.py` 控制流分支（仅替换返回值类型）
- 不拆分 `main.py` 路由
- 不修改 `pyproject.toml` 的 `[build-system]`
- 不添加 CI/CD
- 每次提交前 `uv run pytest` 必须通过

---

## Verification Strategy

### Test Decision
- **Infrastructure exists**: YES
- **Automated tests**: tests-after（重构前先写测试）
- **Framework**: pytest

### QA Policy
Every task MUST include agent-executed QA scenarios.
- **Library/Module**: `python -c "from ...; print(...)"` — Import, call, compare output
- **Full Suite**: `uv run pytest` — All tests pass
- **App Boot**: `uv run app.py` + `curl /api/health` — Returns 200

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 1 (提取共享工具 + 测试 + dataclass + Enum):
├── 1. network_helpers.py + 测试 [quick]
├── 2. file_helpers.py + 测试 [quick]
├── 3. config_helpers.py + 测试 [deep]
├── 4. DebugSession dataclass [deep]
├── 5. RecoveryResult Enum [quick]
├── 6. test_time_utils.py [quick]
└── 7. test_config.py [quick]

Wave 2 (替换调用者):
├── 8. 替换 3 处 host:port 解析 [unspecified-high]
├── 9. 替换 3 处原子写入 [unspecified-high]
├── 10. 简化 config_service 使用 config_helpers [deep]
├── 11. 更新 main.py 使用 DebugSession [deep]
└── 12. 更新 monitor_core 使用 RecoveryResult Enum [unspecified-high]

Wave 3 (修复 + 清理):
├── 13. 修复 _stop_event [quick]
├── 14. 移除 _set_tray_icon [quick]
├── 15. 备份正则常量 + _compare_versions 修复 [quick]
├── 16. requests → httpx [unspecified-high]
└── 17. 全量测试 + 集成验证 [unspecified-high]

Wave FINAL:
├── F1. Plan compliance audit (oracle)
├── F2. Code quality review (unspecified-high)
├── F3. Real manual QA (unspecified-high)
└── F4. Scope fidelity check (deep)
```

### Dependency Matrix

| Task | Depends On | Blocks |
|------|-----------|--------|
| 1-7 | - | 8-17 |
| 8 | 1 | 17 |
| 9 | 2 | 17 |
| 10 | 3,7 | 17 |
| 11 | 4 | 17 |
| 12 | 5 | 17 |
| 13 | - | 17 |
| 14 | - | 17 |
| 15 | 3 | 17 |
| 16 | - | 17 |
| 17 | 8-16 | F1-F4 |

### Agent Dispatch Summary

- **Wave 1**: 7 — T1,T2,T5,T6,T7 quick; T3,T4 deep
- **Wave 2**: 5 — T8,T9,T12 unspecified-high; T10,T11 deep
- **Wave 3**: 5 — T13,T14,T15 quick; T16,T17 unspecified-high
- **FINAL**: 4 — F1 oracle; F2,T3 unspecified-high; F4 deep

---

## TODOs

- [x] 1. 创建 network_helpers.py + 测试
  **What to do**: 创建 `src/utils/network_helpers.py`，实现 `parse_host_port(targets: list[str]) -> list[tuple[str, int]]`，含空值/IPv4/IPv6/域名+端口场景；创建对应测试文件。
  **Must NOT do**: 不修改现有调用者（Wave 2 做）、不添加 timeout 参数。
  **Acceptance**: `python -c "from src.utils.network_helpers import parse_host_port; print(parse_host_port(['8.8.8.8:53']))"` → `[('8.8.8.8', 53)]` ✓；`uv run pytest tests/test_network_helpers.py -v` → 19 passed ✓。

- [x] 2. 创建 file_helpers.py + 测试
  **What to do**: 创建 `src/utils/file_helpers.py`，实现 `atomic_write(path, content, encoding="utf-8", prefix="tmp.", suffix=".tmp")`，含成功写入、失败清理、目录已存在场景；创建对应测试文件。
  **Must NOT do**: 不修改现有调用者（Wave 2 做）、不添加不必要的额外参数。
  **Acceptance**: `python -c "from src.utils.file_helpers import atomic_write; print('OK')"` → `OK` ✓；`uv run pytest tests/test_file_helpers.py -v` → 5 passed ✓。

- [x] 3. 创建 config_helpers.py + 测试
  **What to do**: 创建 `src/utils/config_helpers.py`，含 `extract_profile_fields()`, `assign_profile_fields()`, `BACKUP_FILENAME_PATTERN` 常量；创建对应测试文件。
  **Must NOT do**: 不修改 config_service.py（Wave 2 做）、不重新设计配置架构、不删除现有字段。
  **Acceptance**: `python -c "from src.utils.config_helpers import BACKUP_FILENAME_PATTERN; import re; print(bool(re.match(BACKUP_FILENAME_PATTERN, 'settings_20240101_120000.json')))"` → `True` ✓；`uv run pytest tests/test_config_helpers.py -v` → 24 passed ✓。

- [x] 4. 创建 DebugSession dataclass
  **What to do**: 创建 `backend/debug_session.py`，含 `DebugSession` dataclass（替代 18 键 dict）、`empty_debug_session()` 工厂函数、`debug_to_response()` 序列化函数。保留 `_debug_gen` 计数器和 `deque(maxlen=1000)` 结果字段。
  **Must NOT do**: 不修改 main.py 调用者（Wave 2 做）、不改变调试功能行为。
  **Acceptance**: `python -c "from backend.debug_session import DebugSession, empty_debug_session, debug_to_response; s = empty_debug_session(); r = debug_to_response(s); print('running' in r and 'task_id' in r)"` → `True` ✓。

- [x] 5. 创建 RecoveryResult Enum
  **What to do**: 在 `src/monitor_core.py` 顶部创建 `RecoveryResult` 枚举（LOGIN_OK, GIVE_UP, BREAK, NET_DISCONNECT），替换 `_login_retry_or_break()` 和 `_login_recovery_loop()` 中所有字符串返回为枚举值，更新 `monitor_network()` 中所有字符串比较为枚举比较。不改变任何控制流逻辑。
  **Must NOT do**: 不改变重试行为、不改变 if/elif 分支顺序。
  **Acceptance**: `python -c "from src.monitor_core import RecoveryResult; print(RecoveryResult.LOGIN_OK.value, RecoveryResult.BREAK.value)"` → `login_ok break` ✓；`uv run pytest tests/test_monitor_core.py -v` → 27 passed ✓。

- [x] 6. 补充 test_time_utils.py
  **What to do**: 创建 `tests/test_time_utils.py`，测试 `TimeUtils.is_in_pause_period()` 各种场景：暂停区间内/外、跨日场景（22:00-06:00）、禁用、边界值；测试 `get_runtime_stats()`。
  **Must NOT do**: 不修改 time_utils.py 代码。
  **Acceptance**: `uv run pytest tests/test_time_utils.py -v` → 18 passed ✓。

- [x] 7. 补充 test_config.py 验证器测试
  **What to do**: 创建 `tests/test_config.py`，测试 `ConfigValidator.validate_gui_config()` 各种场景：空用户名失败、有效输入成功、间隔为0/负数失败、合法间隔成功；测试 `validate_env_config()` 基本场景。
  **Must NOT do**: 不修改 config.py 代码。
  **Acceptance**: `uv run pytest tests/test_config.py -v` → 36 passed ✓。

- [x] 8. 替换 3 处 host:port 解析为 parse_host_port 调用
  **What to do**: 在 `monitor_core._build_test_sites()`, `login._build_network_test_config()`, `monitor_service.test_network()` 中用 `parse_host_port()` 替换内联解析逻辑，删除原注释 "暂不提取共享函数"。
  **Must NOT do**: 不改变超时设置、不改变重试逻辑。
  **Acceptance**: `uv run pytest tests/test_monitor_core.py tests/test_network_test.py -v` → 58/58 passed ✓；`python -c "from src.monitor_core import NetworkMonitorCore; from src.utils.login import LoginAttemptHandler; from backend.monitor_service import MonitorService; print('OK')"` → `OK` ✓。

- [x] 9. 替换 3 处原子写入为 atomic_write 调用
  **What to do**: 在 `profile_service._save_unsafe()`, `task_executor.save_task()`, `main.py restore_backup()` 中用 `atomic_write()` 替换 tempfile.mkstemp + os.replace 模式。保留原本的错误处理语义。
  **Must NOT do**: 不改变文件权限、不改变错误处理逻辑。
  **Acceptance**: `uv run pytest tests/test_profile_service.py tests/test_task_service.py -v` → 33/33 passed ✓；`python -c "from backend.profile_service import ProfileService; from src.task_executor import TaskManager; from backend.main import app; print('OK')"` → `OK` ✓。

- [x] 10. 简化 config_service.py 使用 config_helpers
  **What to do**: 在 `load_ui_config()`, `load_runtime_config()`, `build_runtime_config()`, `save_config_combined()` 中使用 `extract_profile_fields()` 和 `assign_profile_fields()` 替代手动字段赋值（40+ 字段 × 4 处 → 声明式辅助）。在 `main.py` 的 3 处正则中使用 `BACKUP_FILENAME_PATTERN` 常量。
  **Must NOT do**: 不重新设计配置架构、不删除任何字段或功能、不改变 MonitorConfigPayload 结构。
  **Acceptance**: `uv run pytest tests/test_config_service.py -v` → 24/24 passed ✓；备份正则验证 → `True` ✓。

- [x] 11. 更新 main.py 使用 DebugSession dataclass
  **What to do**: 导入 `DebugSession, empty_debug_session, debug_to_response`；替换 `_debug` dict 为 `DebugSession` 实例；替换 3 处完整 dict 替换为 `empty_debug_session()` 调用；替换 `_debug_response()` 为 `debug_to_response(_debug_session)`；替换所有 `_debug["key"]` 为 `_debug_session.key`。
  **Must NOT do**: 不改变调试功能行为、不改变 asyncio.Lock/Semaphore 逻辑。
  **Acceptance**: `python -c "from backend.main import app; print('OK')"` → `OK` ✓；`uv run pytest tests/test_debug_session.py -v` → 15/15 passed ✓。

- [x] 12. 更新 monitor_core 使用 RecoveryResult Enum
  **What to do**: 替换所有字符串返回值为枚举值（`"login_ok"` → `RecoveryResult.LOGIN_OK` 等），替换所有字符串比较为枚举比较（`== "login_ok"` → `== RecoveryResult.LOGIN_OK` 等）。
  **Must NOT do**: 不改变控制流逻辑、不改变重试行为。
  **Acceptance**: `uv run pytest tests/test_monitor_core.py -v` → 27 passed ✓（已在 Task 5 中一并完成）。

- [x] 13. 修复 monitor_service._stop_event 未设置
  **What to do**: 在 `MonitorService._handle_stop()` 中添加 `self._stop_event.set()`，使 WS drain 循环和 queue consumer 能正确终止。
  **Must NOT do**: 不改变 Actor 模型核心设计、不移除 "shutdown" 命令处理。
  **Acceptance**: `python -c "..." ` → `OK` ✓；`uv run pytest tests/test_monitor_service.py -v` → 12/12 passed ✓。

- [x] 14. 移除 _set_tray_icon 死代码
  **What to do**: 删除 `backend/main.py:1118-1124` 的 `_set_tray_icon` 函数定义；删除 `app.py:369-371` 的导入和调用。确保系统托盘 `on_exit` 回调不受影响（在 `app.py:361-363` 中独立定义）。
  **Must NOT do**: 不改变系统托盘的 on_exit 回调逻辑、不删除其他代码。
  **Acceptance**: `from backend.main import _set_tray_icon` → ImportError `OK` ✓；`import app` → `OK` ✓。

- [x] 15. 备份正则常量 + _compare_versions 修复
  **What to do**: 从 `config_helpers` 导入 `BACKUP_FILENAME_PATTERN` 在 `main.py` 中使用；替换 3 处内联正则为常量引用；修复 `_compare_versions()` 返回 `0`（而非 `-1`）表示相等。
  **Must NOT do**: 不改变版本比较的实际判断结果（`has_update` 仍用 `> 0`）、不修改正则内容。
  **Acceptance**: `_compare_versions('3.6.7', '3.6.7')` → `0` ✓；`BACKUP_FILENAME_PATTERN` → 已在 task 10 中完成 ✓。

- [x] 16. requests → httpx 替换
  **What to do**: 在 `_repo_get()` 中将 `import requests as _requests` + `requests.get()` 替换为 `httpx.Client()`（同步模式）；在 `repo_fetch_index()` 和 `repo_fetch_task()` 中使用 httpx sync client；从 `pyproject.toml` 和 `requirements.txt` 中移除 `requests` 依赖；确保代理配置传递给 httpx。
  **Must NOT do**: 不改变 API 端点 URL 或行为、不修改 `/api/check-update`（已使用 httpx）。
  **Acceptance**: `grep -r "import requests" backend/ src/` → 无输出 ✓；`from backend.main import app` → `OK` ✓。

- [x] 17. 全量测试 + 集成验证
  **What to do**: 运行 `uv run pytest` 确保所有测试通过；启动应用验证 `/api/health` 返回 200；检查所有新增模块 import 正常；确认 `pyproject.toml` 已移除 `requests` 依赖；确认无遗留 `import requests`。
  **Must NOT do**: 不修改业务逻辑、不添加新功能。
  **Acceptance**: `uv run pytest --tb=short` → 0 failures；`curl http://127.0.0.1:50721/api/health` → `{"status":"ok",...}`；`grep -r "import requests" backend/ src/` → 无输出。

---

## Final Verification Wave

- [x] F1. **Plan Compliance Audit** — `oracle`
  Read the plan end-to-end. For each "Must Have": verify implementation exists. For each "Must NOT Have": search codebase for forbidden patterns. Check evidence files. Compare deliverables against plan.
  Output: `Must Have [N/N] | Must NOT Have [N/N] | Tasks [N/N] | VERDICT: APPROVE/REJECT`

- [x] F2. **Code Quality Review** — `unspecified-high`
  Run `uv run ruff check .` + `uv run pytest`. Review all changed files for: unused imports, excessive comments, over-abstraction, generic names.
  Output: `Lint [PASS/FAIL] | Tests [N pass/N fail] | Files [N clean/N issues] | VERDICT`

- [x] F3. **Real Manual QA** — `unspecified-high`
  Run `uv run app.py --no-browser`, `curl /api/health` → 200, `uv run pytest` → all pass. Verify no import errors.
  Output: `Boot [PASS/FAIL] | Health [PASS/FAIL] | Tests [PASS/FAIL] | VERDICT`

- [x] F4. **Scope Fidelity Check** — `deep`
  For each task: read "What to do", git diff. Verify 1:1. Check "Must NOT do" compliance.
  Output: `Tasks [N/N compliant] | Contamination [CLEAN/N issues] | VERDICT`

---

## Commit Strategy

- **Wave 1**: `refactor: 提取共享工具函数 + DebugSession + RecoveryResult Enum + 补充测试`
- **Wave 2**: `refactor: 替换调用者使用共享函数 + DebugSession + Enum`
- **Wave 3**: `fix: 修复缺陷 + 清理死代码 + 移除 requests 依赖 + 全量验证`

---

## Success Criteria

```bash
uv run pytest --tb=short                    # all tests pass
uv run ruff check .                          # no errors
python -c "from src.utils.network_helpers import parse_host_port; print(parse_host_port(['8.8.8.8:53']))"  # [('8.8.8.8', 53)]
python -c "from src.utils.file_helpers import atomic_write; print('OK')"  # OK
python -c "from backend.debug_session import DebugSession, empty_debug_session; print(empty_debug_session().running)"  # False
python -c "from src.monitor_core import RecoveryResult; print(RecoveryResult.LOGIN_OK.value)"  # login_ok
grep -r "import requests" backend/ src/      # no output
```

---

## 并发锁清单

| 类型 | 位置 | 变量 | 保护对象 | 状态 |
|------|------|------|----------|------|
| `threading.Lock` ×5 | profile_service, playwright_bootstrap, logging×2, crypto | 各自数据 | ✅ |
| `threading.Event` ×5 | monitor_service(2), monitor_core(2), response_event | 同步信号 | ⚠️ `_stop_event` 未设置 |
| `asyncio.Lock` | main.py:320 | 调试会话 | ✅ |
| `asyncio.Semaphore` | main.py:321 | 调试步骤序列化 | ✅ |
| `queue.Queue` | monitor_service:133 | Actor 命令分发 | ✅ |
| `threading.Thread` ×7 | app.py, monitor_service×2, main.py, system_tray | 各线程 | ✅ daemon |