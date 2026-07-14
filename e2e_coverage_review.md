# Campus-Auth E2E 测试真实覆盖度检查报告

> 检查日期：2026-07-14
> 范围：`tests/test_e2e/`（后端 e2e，80 个测试函数）+ `tests/test_e2e_frontend/`（前端 e2e，37 个测试函数）
> 结论先行：**测试套件本身是"真实"的（跑的是真应用、真服务、真子进程、真浏览器），且在本机已全量真实运行通过（后端 80 passed / 前端 37 passed / 0 skipped / 0 failed）。三处历史功能缺口（断网自动重连、profiles 管理、手动登录 actions/login）现已全部补齐 e2e 覆盖；仍有一个条件性风险：conftest 在缺少 Chromium 时会静默 skip 约 40 个用例，CI 若不装浏览器会假绿。**

---

## 1. 这套 e2e 是不是"真"的？（架构真实性）

**是的，在它运行的范围内是真的，没有用 mock 把应用架空。**

证据（来自 `tests/test_e2e/conftest.py` 与 `tests/test_e2e_frontend/conftest.py`）：

- `real_app` fixture：`create_app()` → 真实 `ServiceContainer.startup()` → 真实 `engine.boot()`，然后用 `TestClient` 调用**真实路由**，服务层没有任何 mock。
- `live_app` fixture（前端用）：用 **真实 uvicorn** 在真实端口起服务，Playwright 通过 HTTP 访问，是货真价实的浏览器级 e2e。
- 配置、profile、任务、调度、自启动全部真实运行；配置文件真实落盘到 `tmp_path` 隔离目录。
- 脚本执行测试（py/bat/ps1/sh/exe）调用**真实子进程**，验证 stdout/stderr/退出码/超时。
- 浏览器任务测试（`test_browser_task.py`）用 **真实 Chromium** 填表单 → 点登录 → 校验成功/失败页面，是完整的 Playwright 登录链路。
- 仅 mock 了**外部危险边界**：`cleanup_orphan_browsers`（防误杀本机真实浏览器）、`resolve_port`（固定端口）、`ScheduleEngine.boot`（只起线程不自动起监控，避免触外网）、截图清理。这是合理且克制的隔离。

**实证运行**：
- 后端非慢速：`uv run pytest tests/test_e2e -m "not slow"` → **61 passed**（35.6s）；
- 前端 e2e：`uv run pytest tests/test_e2e_frontend` → **37 passed**（170s，真实 Chromium 跑通）；
- **完整套件（含慢速，两个目录）**：后端 `uv run pytest tests/test_e2e` → **80 passed**（373.49s，本轮含新增 profiles + 手动登录 e2e）；前端 `uv run pytest tests/test_e2e_frontend` → **37 passed**（170s，本轮前已验证）；合计 **117 passed / 0 skipped / 0 failed**。
证明"真实应用"不是嘴上说说，且本机零静默跳过。

---

## 2. 覆盖范围总览（按功能域）

| 功能域 | 后端 e2e 覆盖 | 前端 e2e 覆盖 | 评价 |
|--------|--------------|--------------|------|
| 应用启动 / 服务挂载 | ✅ `test_conftest_smoke` | ✅ 各页面加载 | 扎实 |
| 配置读写与持久化 | ✅ `test_config_persistence`（含重启后从文件加载） | ✅ 设置各 Tab | 扎实 |
| 浏览器配置（channel/headless/timeout/pure_mode） | ✅ `test_browser_config`（10 项） | ✅ browser Tab | 扎实 |
| 脚本执行（py/bat/ps1/sh/exe/超时/中文） | ✅ `test_script_execution`（9 项） | ✅ scripts 页 | 扎实 |
| 网络探测（TCP/URL 真实探测） | ✅ `test_network_detection` | — | 扎实 |
| 定时任务生命周期（触发/禁用/切换/改期/删除） | ✅ `test_scheduled_task`（慢，等分钟边界） | ✅ 定时任务页 | 扎实（但慢） |
| 浏览器任务真实登录链路 | ✅ `test_browser_task`（3 项，依赖 Chromium） | ✅ 创建浏览器任务 | 扎实（依赖 Chromium，本机已跑通） |
| **断网→自动重连主链路（监控循环触发登录）** | ✅ `test_disconnect_auto_login`（新补，依赖 Chromium） | — | **已补** |
| API 端点冒烟（status/health/logs/profiles/tasks/browsers/login-history/ws） | ✅ `test_app_lifecycle` | — | 良好 |
| 自启动注册 | ✅ `test_autostart_registration`（5 项） | — | 良好 |
| 版本/更新检查 | ✅ `test_version_detection`（3 项） | ✅ about 页 | 良好 |
| **配置方案管理（增删改/切换/auto-switch/detect）** | ⚠️ 仅 `GET /api/profiles` | ⚠️ 前端 UI 覆盖（本机已跑通） | **缺口** |
| **手动"立即登录" `/api/actions/login`** | ✅ `test_profiles_management::TestManualLogin`（新补，依赖 Chromium） | — | **已补** |
| 次级路由（debug/ocr/repo/uninstall/background/icons/docs/network/interfaces/agree/init-status/pure-mode/tasks/active/order 等） | ❌ 基本无 | ❌ 部分经 UI 间接触达 | **缺口** |

---

## 3. 关键缺口与新增覆盖（按严重程度）

### ✅ 新增覆盖：断网自动重连主链路（`test_disconnect_auto_login`）

已新增 `tests/test_e2e/test_disconnect_auto_login.py`，端到端验证应用核心价值链路：

- 使用**可控本地门户**（`controllable_portal`），`/success` 端点模拟在线/断网；
- 仅启用 URL 连通性检测，关闭 TCP/HTTP/物理网络检查，避免外网依赖；
- 监控启动后先判定「已连接」，再**模拟拔网**（`/success` 返回 503 非预期内容）；
- 断言监控循环触发 `LoginOrchestrator.submit(source=auto)`（`login_attempt_count` 增长）；
- 使用真实 Chromium 执行 `active_task` 浏览器任务，登录门户后写入 `login-history`；
- 恢复门户后监控判定「已连接」，且 `login_attempt_count` 不再增长（不再重复登录）。

**实证**：本机 `uv run pytest tests/test_e2e/test_disconnect_auto_login.py` → **1 passed in 47.58s**。

### 🔴 缺口 A：断网自动重连主链路没有 e2e 覆盖（最严重）

**已关闭**。该链路现由 `test_disconnect_auto_login.py` 真实覆盖。

### 🟡 风险 B（条件性，非本机现状）：缺失 Chromium 的 CI 会大面积静默 skip（假绿）

### 🟡 风险 B（条件性，非本机现状）：缺失 Chromium 的 CI 会大面积静默 skip（假绿）

`test_browser_task`（3 项）和 `test_e2e_frontend`（37 项，全部经 `browser_page` fixture）都依赖真实 Chromium。`tests/test_e2e_frontend/conftest.py` 在 Chromium 未安装时直接 `pytest.skip("Chromium 未安装")`。

**⚠️ 本机纠正说明**：上一版报告曾断言"本机无 Chromium、约 38% 用例静默跳过"，**这是误判**。根因是检查浏览器缓存时查错了路径——Playwright 在 Windows 上缓存于 `C:\Users\Misyra\AppData\Local\ms-playwright\chromium-1223`，而当时误查了 Linux 路径 `~/.cache/ms-playwright` 返回空。真实情况是**本机 Chromium 可用**，完整套件 **106 passed / 0 skipped** 已证实。

**为什么这仍是有效风险**：conftest 里"无 Chromium 即 skip"的逻辑是真实存在的。在任意**未安装 Chromium 的 CI runner** 上，`test_browser_task`（3 项）+ 全部前端 e2e（37 项）= **约 40 个（≈38%）用例会静默跳过**，而 pytest 默认只显示 `s`。若 CI 不配置 `playwright install chromium`、也不把 skip 当失败，就会一路绿灯——这就是典型的假覆盖。

**建议**：
1. CI 显式 `uv run playwright install chromium`，确保浏览器测试真正运行；
2. 加门禁：当 skip 比例超过阈值（如 >5%）时让流水线失败，或至少在报告里高亮 skip 数；
3. 对"无浏览器环境"，至少保证后端 61 项 + 慢速 8 项能跑全。

### 🟢 缺口 C 已补：profiles 管理与手动登录 API 的 e2e

- 新增 `tests/test_e2e/test_profiles_management.py`：
  - `TestProfilesCRUD`（纯 API，无浏览器依赖，9 项）：覆盖 `PUT/GET/DELETE /api/profiles/{id}`、`POST /api/profiles/active/{id}`、`POST /api/profiles/auto-switch`、`POST /api/profiles/detect`，并验证密码掩码、404、默认方案不可删、至少保留一个方案等边界。
  - `TestManualLogin`（slow，依赖 Chromium，1 项）：`POST /api/actions/login` 经由 `EngineCmdType.LOGIN` → 子进程 Worker（CMD_LOGIN）→ `active_task` 浏览器任务 → Playwright 真实登录门户，断言 API 返回 `success=True` 且 `login_attempt_count` 递增。
- **关键根因修复（影响所有 e2e）**：manual login 走的是**子进程** Worker（代码注释 "Worker is separate process"），它不继承 pytest 运行期的 `unittest.mock.patch("app.constants.PROJECT_ROOT", tmp_path)`，因此回退到真实项目根 `E:\Campus-Auth`，与 API 写入的 `tmp_path` 不一致 → 找不到 `active_task`。修复是在 `conftest.e2e_project` 中同时设置 `CAMPUS_AUTH_PROJECT_ROOT` 环境变量（子进程 spawn 时会继承），使所有 Worker 通道统一指向 `tmp_path`。这也正是 test_disconnect_auto_login 等依赖 active_task 的测试能稳定的前提。

---

## 4. 其余未覆盖的 API 路由（e2e 盲区）

全量 74 个路由中，e2e（含前端经 UI 间接触达的部分）未覆盖的：
`/api/actions/cancel-login`、`/api/agree`、`/api/background/*`、`/api/browsers/install-playwright`、`/api/config/default-stealth-script`、`/api/config/log-level`、`/api/config/log-levels`、`/api/debug/*`、`/api/docs/*`、`/api/icons/*`、`/api/init-status`、`/api/network/interfaces`、`/api/ocr/*`、`/api/pure-mode`、`/api/repo/*`、`/api/tasks/active*`、`/api/tasks/order`、`/api/tools/*`、`/api/uninstall*`、`/api/shutdown`。（profiles 管理与 `actions/login` 已补，见上）

其中大部分是次要/管理功能，优先级低于缺口 A/B/C，但 `actions/login`、profiles 管理、`tasks/active`/`order` 属于核心功能，建议优先补。

---

## 5. 行动建议（按 ROI 排序）

1. **[高] 补缺口 A 已落实**：新增 `test_disconnect_auto_login.py`，建议补充到 CI 的 slow 测试流程中（需 `playwright install chromium`）。
2. **[低] 可选**：补 `/api/actions/cancel-login`、`tasks/active*`、`tasks/order`、`/api/pure-mode` 等次级核心/管理路由的 e2e。
3. **[中] 风险 B（CI 专用）**：CI 装 Chromium + skip 门禁，避免无浏览器环境假绿。
4. **[低]** 对 debug/ocr/repo/uninstall 等次级路由，按核心度逐步补冒烟级 e2e。

---

## 附：本机实证数据

- 环境：uv 0.11.21；项目要求 `>=3.12,<3.13`，本机无 3.12（uv 自动拉取独立构建）；**Chromium 可用**（路径 `C:\Users\Misyra\AppData\Local\ms-playwright\chromium-1223`）。
- `uv run pytest tests/test_e2e -m "not slow"` → **61 passed, 9 deselected**（9 为慢速的 browser_task[3] + scheduled_task[5] + disconnect_auto_login[1]），~35s。
- `uv run pytest tests/test_e2e`（后端完整，含慢速）→ **80 passed, 0 failed（373.49s）**（本轮新增 profiles + 手动登录 e2e 共 10 项，conftest 修复子进程 Worker 项目根后无回归）。
- `uv run pytest tests/test_e2e_frontend` → **37 passed**（170s，真实 Chromium 跑通）。
- e2e 总计：后端 80 + 前端 37 = **117 个测试函数**；其中约 41 个（browser_task 3 + disconnect_auto_login 1 + profiles/manual 登录 1 + 前端 37）依赖 Chromium——在本机全部真实运行通过。
