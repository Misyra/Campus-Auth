# Campus-Auth 优化与改进计划

> 版本: v3.1.0 → 目标 v3.2.0
> 生成日期: 2026-04-29
> 基于: 全量代码审查（后端、前端、测试、安全、架构）

---

## 目录

- [一、安全修复（Critical）](#一安全修复critical)
- [二、稳定性与健壮性（High）](#二稳定性与健壮性high)
- [三、代码质量优化（Medium）](#三代码质量优化medium)
- [四、测试补全（Medium）](#四测试补全medium)
- [五、功能增强建议](#五功能增强建议)
- [六、前端改进](#六前端改进)
- [七、工程化改进](#七工程化改进)
- [优先级总览](#优先级总览)

---

## 一、安全修复（Critical）

### 1.1 API 认证加固

**文件:** `backend/main.py:72-81`

**问题:** 当 `API_TOKEN` 未设置时（默认情况），所有写接口（包括 `/api/shutdown`、`/api/config`）完全无认证保护。任意本地进程可调用关机接口。Token 比较使用 `==` 运算符，存在时序攻击风险。

**方案:**
- [ ] 为敏感端点（`/api/shutdown`、`/api/config`、`/api/autostart/*`）增加独立的访问控制层
- [ ] Token 比较改用 `hmac.compare_digest()` 防止时序攻击
- [ ] 首次启动生成随机 `API_TOKEN` 写入 `.env`，前端初始化向导中展示给用户

### 1.2 CORS 端口修复

**文件:** `backend/main.py:58-64`

**问题:** CORS origins 写死 `http://127.0.0.1` 和 `http://localhost`，不包含端口号。现代浏览器严格匹配 origin（含端口），导致动态端口下 CORS 拒绝。

**方案:**
- [ ] 从 `APP_PORT` 配置动态拼接 CORS origin：`f"http://127.0.0.1:{port}"`
- [ ] 收窄 `allow_methods` 和 `allow_headers`，仅允许实际使用的 HTTP 方法和必要 Header

### 1.3 Debug 静态目录鉴权

**文件:** `backend/main.py:340-341`

**问题:** `/debug` 静态挂载无任何认证，截图中可能包含用户名、Cookie 等敏感信息。

**方案:**
- [ ] 移除公开的 `/debug` 静态挂载
- [ ] 改为带认证的文件下载端点 `GET /api/debug/{filename}`，需验证 API_TOKEN
- [ ] 或在截图时对敏感信息做脱敏处理

### 1.4 `.env` 文件原子写入

**文件:** `backend/config_service.py:266`

**问题:** `write_env_file` 直接写入目标文件，若进程在写入中途崩溃（断电、被 kill），`.env` 文件将损坏。

**方案:**
- [ ] 先写入临时文件，再通过 `os.replace()` 原子替换原文件
- [ ] 增加文件写入锁，防止并发请求同时修改 `.env`

```python
import tempfile, os

def write_env_file_atomic(env_path: Path, content: str):
    tmp_fd, tmp_path = tempfile.mkstemp(dir=env_path.parent, suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, env_path)
    except:
        os.unlink(tmp_path)
        raise
```

### 1.5 加密模块安全修复

**文件:** `src/utils/crypto.py`

**问题:**
- 解密失败时静默返回密文（`ENC:...`），将作为明文密码发送到认证服务器
- 密钥文件无权限校验（Windows 上 `chmod` 无效）
- `cryptography` 缺失时静默降级为 Base64 "加密"，用户误认为密码已加密

**方案:**
- [ ] 解密失败时抛出明确异常或返回空字符串，而非返回密文
- [ ] 读取密钥文件前校验权限（Unix: `0o600`），Windows 上记录警告日志
- [ ] Base64 降级时记录 `WARNING` 级别日志，提示用户密码未真正加密
- [ ] 考虑移除 Base64 降级路径，将 `cryptography` 设为硬依赖

### 1.6 任务系统 JS 注入风险

**文件:** `src/task_executor.py:535, 561`

**问题:** `eval` 和 `custom_js` 步骤类型直接执行任意 JavaScript，通过 API 提交的恶意任务可实现浏览器内 RCE。

**方案:**
- [ ] 对通过 API 接收的任务 JSON 增加危险步骤类型警告或禁用策略
- [ ] 考虑增加任务来源标记（`source: "api"` vs `source: "file"`），对 API 来源的任务禁用 `eval`/`custom_js`
- [ ] 或增加任务签名机制，仅执行签名任务

---

## 二、稳定性与健壮性（High）

### 2.1 监控循环线程阻塞

**文件:** `src/monitor_core.py:99`

**问题:** `start_monitoring()` 内同步调用 `self.monitor_network()`，会阻塞调用线程。若从 HTTP 请求处理器调用，将导致请求永久挂起。

**方案:**
- [ ] 确认 `monitor_service.py` 中已在后台线程中调用 `start_monitoring()`，若否则重构
- [ ] 在 `start_monitoring()` 入口添加线程检查，非后台线程调用时记录警告

### 2.2 WebSocket 重试内存泄漏

**文件:** `frontend/js/methods/lifecycle.js:117-128`

**问题:** `ws.onclose` 中使用 `setTimeout` 进行重试，但 timeout ID 未存储。组件卸载时 `beforeUnmount` 无法取消待执行的重试，导致对已销毁组件的操作。

**方案:**
- [ ] 将 `setTimeout` 返回值存入 `this._wsRetryTimer`
- [ ] 在 `beforeUnmount` 中 `clearTimeout(this._wsRetryTimer)`
- [ ] 添加 `_wsDestroyed` 标志位，重试前检查组件是否已卸载

```javascript
// lifecycle.js
this._wsRetryTimer = setTimeout(() => {
  if (!this._wsDestroyed) this.connectWebSocket();
}, retryDelay);

// app-options.js beforeUnmount
this._wsDestroyed = true;
clearTimeout(this._wsRetryTimer);
```

### 2.3 并发竞态：`_push_log` 无锁访问 `_loop`

**文件:** `backend/monitor_service.py:100-113`

**问题:** `_push_log` 在后台线程中读取 `self._loop`，但 `set_event_loop()` 写入时未加锁，存在竞态条件。

**方案:**
- [ ] 在 `_push_log` 中使用 `self._lock` 保护对 `_loop` 的读取
- [ ] 或改用 `threading.Event` 通知机制，避免直接共享可变状态

### 2.4 监控间隔不刷新

**文件:** `src/monitor_core.py:133`

**问题:** 监控间隔在循环启动时读取一次，用户在 Web 控制台修改设置后不会生效。

**方案:**
- [ ] 每次循环迭代重新从配置读取 `interval`
- [ ] 或通过 `monitor_service` 的锁机制传递配置更新信号

### 2.5 自启动服务可靠性

**文件:** `backend/autostart_service.py`

**问题:**
- **Linux (L183):** `systemctl --user enable --now` 返回值被忽略，始终返回 `True`
- **Windows (L229):** 可执行路径为空时 VBS 静默失败
- **macOS (L134):** plist XML 未转义，路径含 `&`/`<` 时格式损坏
- **通用 (L29):** 回退到 `python` 命令，macOS/Linux 现代系统只有 `python3`

**方案:**
- [ ] Linux: 检查 `_run()` 返回值，失败时返回错误信息
- [ ] Windows: 写入 VBS 前校验可执行路径存在性，空路径时记录错误
- [ ] macOS: 对路径做 XML 转义（`xml.sax.saxutils.escape`）
- [ ] 通用: 优先尝试 `python3`，再回退 `python`

### 2.6 `NetworkMonitorCore` 资源泄漏

**文件:** `backend/monitor_service.py:219-230`

**问题:** `run_manual_login` 每次创建新的 `NetworkMonitorCore` 实例但未清理，可能持有浏览器或网络资源。

**方案:**
- [ ] 使用 `try/finally` 确保清理
- [ ] 或复用已有的 `self._monitor_core` 实例（如果可用）

---

## 三、代码质量优化（Medium）

### 3.1 消除重复代码

**文件:** `src/task_executor.py:320-337, 366-383, 453-470`

**问题:** `_find_element` 方法在 `InputHandler`、`ClickHandler`、`SelectHandler` 中重复 4 次。

**方案:**
- [ ] 提取到 `StepHandler` 基类中

### 3.2 变量缓存失效

**文件:** `src/task_executor.py:175`

**问题:** `VariableResolver._cache` 无界增长且从不失效。`set_runtime_var` 修改变量后，缓存中的旧值仍被使用。

**方案:**
- [ ] `set_runtime_var` 时清除相关缓存条目
- [ ] 或每次执行步骤前清空缓存

### 3.3 未实现的条件类型

**文件:** `src/task_executor.py:820-841`

**问题:** `ConditionType` 枚举定义了 5 种类型，但 `_evaluate_condition` 只处理 3 种。`ELEMENT_EXISTS` 和 `JS_EXPRESSION` 静默返回 `True`。

**方案:**
- [ ] 实现 `ELEMENT_EXISTS`：使用 Playwright 选择器检查元素是否存在
- [ ] 实现 `JS_EXPRESSION`：使用 `page.evaluate()` 执行表达式并检查返回值
- [ ] 对未知条件类型抛出 `ValueError` 而非静默通过

### 3.4 `SleepHandler` 无上限

**文件:** `src/task_executor.py:593-608`

**问题:** `duration` 参数无上限校验，`duration: 999999999` 可阻塞执行器 ~11.5 天。

**方案:**
- [ ] 添加 `MAX_SLEEP_MS` 常量（建议 300000ms = 5 分钟）
- [ ] 超过上限时记录警告并截断

### 3.5 截图路径遍历

**文件:** `src/task_executor.py:580-586`

**问题:** 截图 `path` 参数可包含 `../../` 路径遍历，可在任意位置创建文件。

**方案:**
- [ ] 将路径限制在项目 `debug/` 目录下
- [ ] 使用 `Path.resolve()` 后检查是否在允许的目录内

### 3.6 输入校验补全

**文件:** `backend/schemas.py`

**问题:**
- `auth_url` 无 URL 格式校验（可输入 `javascript:alert(1)`）
- `network_targets` 无格式校验
- `browser_extra_headers_json` 在 Schema 层不校验 JSON 合法性
- `custom_variables` 无大小限制
- `LogEntry.level` 不校验日志级别枚举

**方案:**
- [ ] 为 `auth_url` 添加 `HttpUrl` 类型或正则校验
- [ ] 为 `network_targets` 添加格式校验（`host:port` 逗号分隔）
- [ ] 为 `browser_extra_headers_json` 添加 JSON 格式预校验
- [ ] 为 `custom_variables` 添加 `max_length` 约束
- [ ] 为 `LogEntry.level` 使用 `Literal` 类型

### 3.7 废弃 API 迁移

**文件:** `backend/main.py:118, 130`

**问题:** 使用已废弃的 `@app.on_event("startup")` / `@app.on_event("shutdown")`。

**方案:**
- [ ] 迁移到 FastAPI `lifespan` 上下文管理器

### 3.8 配置管理器线程安全

**文件:** `src/utils/config.py:208-234`

**问题:**
- `ConfigManager` 单例的双重检查锁模式在非 CPython 实现上不安全
- `get_config()` 返回可变引用，调用方可就地修改缓存配置

**方案:**
- [ ] 简化为直接加锁（Python GIL 下性能影响可忽略）
- [ ] `get_config()` 返回 `copy.deepcopy(self._config)`

### 3.9 浏览器低资源模式增强

**文件:** `src/utils/browser.py:138-143`

**问题:** 低资源模式仅拦截图片，字体、媒体、样式表仍加载。

**方案:**
- [ ] 增加对 `font`、`media`、`stylesheet`（可选）的拦截

### 3.10 `networkidle` 等待策略

**文件:** `src/utils/browser.py:194`

**问题:** `networkidle` 不可靠，含长轮询/统计脚本的页面可能永远无法达到。

**方案:**
- [ ] 默认改为 `domcontentloaded`，保留 `networkidle` 作为可配置选项

---

## 四、测试补全（Medium）

当前测试覆盖极低：仅 2 个测试文件、15 个测试用例，核心模块零覆盖。

### 4.1 优先补全模块

| 优先级 | 模块 | 当前覆盖 | 目标 |
|--------|------|----------|------|
| P0 | `src/monitor_core.py` | 0% | 核心监控循环逻辑 |
| P0 | `src/network_test.py` | 0% | 网络检测判定逻辑 |
| P0 | `src/utils/crypto.py` | 0% | 加密/解密正确性 |
| P1 | `backend/config_service.py` | 0% | 配置读写原子性 |
| P1 | `backend/monitor_service.py` | 0% | WebSocket 广播、并发安全 |
| P1 | `src/utils/config.py` | ~10% | 配置加载、校验、边界值 |
| P1 | `src/utils/retry.py` | 0% | 重试逻辑、退避策略 |
| P2 | `src/utils/time.py` | 0% | 暂停时段判断 |
| P2 | `src/utils/login.py` | 0% | 登录编排逻辑 |
| P2 | `backend/autostart_service.py` | 0% | 跨平台自启动 |

### 4.2 测试基础设施

**当前缺失:**
- [ ] 共享 fixtures（mock 配置、mock API 响应）
- [ ] `httpx.Client` / `subprocess.run` 的 mock
- [ ] Playwright 页面 mock
- [ ] 测试覆盖率报告配置（`pytest-cov`）

**方案:**
- [ ] 扩展 `conftest.py`，添加通用 fixtures
- [ ] 添加 `pytest-cov` 依赖，配置覆盖率报告
- [ ] 在 CI 中设置最低覆盖率门槛（建议 ≥60%）

### 4.3 现有测试增强

**文件:** `tests/test_config_loader.py`

**补充测试:**
- [ ] 自定义环境变量值（非默认 `MONITOR_INTERVAL`、`PING_TARGETS`）
- [ ] `.env` 文件加载行为
- [ ] 畸形环境变量（`MONITOR_INTERVAL=abc`）
- [ ] `PING_TARGETS` 边界值（空字符串、尾逗号、空格）

---

## 五、功能增强建议

### 5.1 登录历史记录

**描述:** 记录每次登录尝试的时间、结果（成功/失败）、耗时、错误信息，持久化到 JSON 文件或 SQLite。

**价值:**
- 用户可查看认证历史，排查间歇性失败
- 为"连续失败冷却"机制提供更精确的数据支持

**实现思路:**
- [ ] 新增 `src/login_history.py`，使用 JSON 文件存储
- [ ] Web 控制台新增"历史记录"页面
- [ ] 保留最近 100 条记录，自动清理

### 5.2 多网络配置

**描述:** 支持保存多套认证配置（如宿舍 WiFi、教学楼 WiFi、图书馆 WiFi），根据当前网络环境自动切换。

**价值:** 多场景用户无需手动切换配置

**实现思路:**
- [ ] `.env` 改为目录结构 `profiles/`，每个 profile 一个配置文件
- [ ] 基于网关 IP 或 SSID 自动匹配 profile
- [ ] Web 控制台添加 profile 管理界面

### 5.3 通知系统

**描述:** 登录成功/失败、网络中断/恢复时发送通知。

**价值:** 用户无需盯着控制台，关键事件主动推送

**支持渠道:**
- [ ] 系统原生通知（`plyer` 或 `win10toast`）
- [ ] Server酱 / Bark / Telegram Bot（Webhook 方式）
- [ ] 邮件通知（可选）

**实现思路:**
- [ ] 新增 `src/notifier.py`，定义 `Notifier` 接口和多个实现
- [ ] 在 `.env` 中添加 `NOTIFY_CHANNELS` 配置
- [ ] 在监控循环的关键节点触发通知

### 5.4 健康检查端点增强

**文件:** `backend/main.py` — `GET /api/health`

**当前:** 仅返回 `{"status": "ok"}`

**增强:**
- [ ] 返回详细健康信息：运行时长、上次登录时间、上次登录结果、监控状态、浏览器状态
- [ ] 添加 `GET /api/metrics` 端点，返回 Prometheus 格式指标（可选）

### 5.5 任务执行超时

**描述:** 为整个任务执行设置全局超时，防止单个任务无限阻塞。

**方案:**
- [ ] 在 `TaskExecutor.execute()` 外层包裹 `asyncio.wait_for(task, timeout=MAX_TASK_TIMEOUT)`
- [ ] 默认超时 120 秒，可通过配置调整
- [ ] 超时后自动截图并记录日志

### 5.6 任务导入/导出

**描述:** 支持从文件导入任务 JSON，或将现有任务导出为文件，方便用户分享。

**实现思路:**
- [ ] `POST /api/tasks/import` — 上传 JSON 文件导入
- [ ] `GET /api/tasks/{id}/export` — 下载任务 JSON
- [ ] Web 控制台任务页面添加导入/导出按钮

### 5.7 浏览器 User-Agent 随机化

**描述:** 提供常见浏览器 User-Agent 池，每次启动随机选择，降低被指纹识别的概率。

**方案:**
- [ ] 在 `src/utils/browser.py` 中内置 UA 池
- [ ] `.env` 中 `BROWSER_USER_AGENT` 设为 `"random"` 时随机选取
- [ ] 保留手动指定 UA 的能力

---

## 六、前端改进

### 6.1 错误处理统一化

**文件:** `frontend/js/methods/actions.js:11,24,37`

**问题:** `toggleMonitor`、`manualLogin`、`testNetwork` 三个方法的 `catch` 块丢弃错误详情，只显示"操作失败"。

**方案:**
- [ ] 统一提取错误信息：`error?.response?.data?.detail || error.message || '操作失败'`
- [ ] 参考 `config.js:30` 的 `saveConfig` 实现

### 6.2 全局错误处理

**文件:** `frontend/app.js`

**问题:** `bootstrapApp()` 失败时用户看到空白页面，无任何反馈。

**方案:**
- [ ] 添加 `window.onerror` / `app.config.errorHandler` 全局错误捕获
- [ ] 显示友好的错误页面或 toast 通知

### 6.3 CSS 可访问性修复

**文件:** `frontend/styles/base.css:6`

**问题:** `--text-muted: #64748b` 在深色背景 `#0f172a` 上对比度约 3.9:1，不满足 WCAG AA 标准（需 4.5:1）。

**方案:**
- [ ] 调整为 `#94a3b8`（对比度约 5.3:1）

### 6.4 移除不必要的 `!important`

**文件:** `frontend/styles/settings.css:237-341`

**问题:** 7 处 `!important`，其中多数是相同值覆盖，无需 `!important`。

**方案:**
- [ ] 通过提升选择器特异性替代 `!important`
- [ ] 审查并移除冗余的 `!important` 声明

### 6.5 删除确认对话框

**文件:** `frontend/js/methods/tasks.js:92`

**问题:** 使用浏览器原生 `confirm()` 阻塞 UI 线程。

**方案:**
- [ ] 替换为自定义模态对话框组件

### 6.6 DOM 选择器健壮性

**文件:** `frontend/js/methods/ui.js:52, 73`

**问题:**
- 使用非标准属性 `var-key` 做 DOM 查询
- `scrollLogToBottom` 使用 `document.querySelector`，多实例时不可靠

**方案:**
- [ ] 改用 `data-var-key` 标准自定义属性
- [ ] `scrollLogToBottom` 改用 Vue `this.$refs`

---

## 七、工程化改进

### 7.1 CI/CD 流水线

**当前:** 无任何 CI/CD 配置

**方案:**
- [ ] 添加 GitHub Actions workflow：
  - **PR 触发:** `ruff check` + `ruff format --check` + `pytest`
  - **Push to main:** 上述 + 覆盖率报告 + PyInstaller 构建
- [ ] 添加 `.github/workflows/ci.yml`

```yaml
name: CI
on: [push, pull_request]
jobs:
  lint-and-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - run: uv sync
      - run: uv run ruff check .
      - run: uv run ruff format --check .
      - run: uv run pytest --cov=src --cov-report=term-missing
```

### 7.2 依赖锁定与安全扫描

**方案:**
- [ ] 添加 `pip-audit` 或 `safety` 到 CI，扫描已知漏洞
- [ ] 定期更新 `uv.lock`（Dependabot 或 Renovate）

### 7.3 Pre-commit Hooks

**方案:**
- [ ] 添加 `.pre-commit-config.yaml`
- [ ] Hooks: `ruff` (lint + format)、`mypy`（可选）、trailing whitespace、YAML 检查

### 7.4 类型标注完善

**当前:** 后端部分函数缺少类型标注（如 `backend/main.py:269` 使用 raw `dict`）

**方案:**
- [ ] 为 `save_task` 等端点使用 Pydantic 模型替代 `dict`
- [ ] 逐步添加 `mypy` 配置并修复类型错误
- [ ] 在 CI 中增加 `mypy --strict` 检查（分阶段推进）

### 7.5 发布自动化

**当前:** 手动执行 `package_zip.ps1`，无版本号自动化

**方案:**
- [ ] 基于 git tag 自动触发构建和发布
- [ ] GitHub Actions 中添加 release workflow：tag push → 构建 exe → 创建 GitHub Release → 上传产物

---

## 优先级总览

### P0 — 立即修复（安全 & 数据完整性）

| # | 问题 | 文件 | 预估工时 |
|---|------|------|----------|
| 1.1 | API 认证加固 | `backend/main.py` | 4h |
| 1.2 | CORS 端口修复 | `backend/main.py` | 1h |
| 1.3 | Debug 目录鉴权 | `backend/main.py` | 2h |
| 1.4 | `.env` 原子写入 | `backend/config_service.py` | 2h |
| 1.5 | 加密模块修复 | `src/utils/crypto.py` | 3h |
| 2.2 | WS 重试内存泄漏 | `frontend/js/methods/lifecycle.js` | 1h |

**P0 合计: ~13h**

### P1 — 近期优化（稳定性 & 质量）

| # | 问题 | 文件 | 预估工时 |
|---|------|------|----------|
| 1.6 | JS 注入风险 | `src/task_executor.py` | 4h |
| 2.1 | 监控线程阻塞 | `src/monitor_core.py` | 2h |
| 2.3 | `_push_log` 竞态 | `backend/monitor_service.py` | 2h |
| 2.4 | 监控间隔刷新 | `src/monitor_core.py` | 1h |
| 2.5 | 自启动可靠性 | `backend/autostart_service.py` | 4h |
| 3.1 | 消除重复代码 | `src/task_executor.py` | 2h |
| 3.2 | 变量缓存失效 | `src/task_executor.py` | 1h |
| 3.3 | 条件类型实现 | `src/task_executor.py` | 3h |
| 3.6 | 输入校验补全 | `backend/schemas.py` | 2h |
| 6.1 | 前端错误处理 | `frontend/js/methods/` | 2h |
| 7.1 | CI/CD 流水线 | `.github/workflows/` | 3h |

**P1 合计: ~26h**

### P2 — 后续迭代（功能 & 体验）

| # | 问题 | 预估工时 |
|---|------|----------|
| 3.4-3.5 | Sleep 上限 + 路径遍历 | 2h |
| 3.7-3.10 | 废弃 API、配置安全、低资源模式、等待策略 | 4h |
| 4.1-4.3 | 测试补全（核心模块） | 16h |
| 5.1 | 登录历史记录 | 6h |
| 5.3 | 通知系统 | 8h |
| 5.5 | 任务执行超时 | 3h |
| 5.6 | 任务导入/导出 | 4h |
| 6.2-6.6 | 前端其余改进 | 6h |
| 7.2-7.5 | 工程化改进 | 8h |

**P2 合计: ~57h**

---

## 附录：代码问题统计

| 严重级别 | 数量 | 分布 |
|----------|------|------|
| 🔴 Critical（安全/数据） | 9 | 后端 6、核心 3 |
| 🟡 High（稳定性） | 6 | 后端 2、核心 3、前端 1 |
| 🟠 Medium（质量） | 17 | 后端 5、核心 6、前端 3、CSS 3 |
| 🔵 Low（体验/规范） | 5 | 自启动 2、前端 2、配置 1 |
| **合计** | **37** | — |

---

*本文档将随开发进展持续更新。建议按 P0 → P1 → P2 顺序推进，每个优先级完成后进行一次版本发布。*
