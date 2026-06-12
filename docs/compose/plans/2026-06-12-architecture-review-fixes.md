# 架构审查修复实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ []` syntax for tracking.

**Goal:** 修复全面架构审查中发现的 bug、代码重复、死代码和架构问题

**Architecture:** 按优先级和领域分 6 个 Task：(1) 关键 bug 修复 (2) 验证逻辑去重 (3) 前端死代码清理 (4) 后端配置/进程管理改进 (5) 异步/线程安全改进 (6) 低优先级清理

**Tech Stack:** Python 3.x, FastAPI, Vue 3 (no build), Playwright, Pydantic

**Base commit:** `3589f9ca`

---

## 风险评估

| Task | 风险 | 说明 |
|------|------|------|
| T1 | 低 | 纯 bug 修复，有测试覆盖 |
| T2 | 低 | 重构不改行为 |
| T3 | 低 | 删除未引用代码 |
| T4 | 中 | 4.4 涉及 Pydantic 验证链，需谨慎 |
| T5 | 中 | 5.2 涉及线程池架构，5.4 涉及业务语义 |
| T6 | 中低 | 各步骤独立，逐一验证 |

---

## 涉及文件总览

| 文件 | 操作 | 关联 Task |
|------|------|-----------|
| `app/utils/retry.py` | **新建** | T1 |
| `app/services/engine.py` | 修改 | T1, T5 |
| `app/services/monitor_service.py` | 修改 | T1 |
| `app/tasks/step_handlers.py` | 修改 | T1 |
| `app/schemas.py` | 修改 | T2 |
| `app/services/config_service.py` | 修改 | T2, T4 |
| `app/utils/config_utils.py` | 修改 | T2 |
| `app/utils/notify.py` | 修改 | T2 |
| `frontend/js/icons.js` | 删除 | T3 |
| `frontend/js/virtual-scroller.js` | 删除 | T3 |
| `frontend/app.js` | 修改 | T3 |
| `frontend/js/app-options.js` | 修改 | T3 |
| `frontend/js/methods/formatters.js` | 修改 | T3 |
| `frontend/js/methods/logfiles.js` | 修改 | T3 |
| `app/utils/process.py` | 修改 | T4 |
| `app/utils/login.py` | 修改 | T4 |
| `app/tasks/variable_resolver.py` | 修改 | T5 |
| `app/network/decision.py` | 修改 | T5 |
| `app/network/probes.py` | 修改 | T5 |
| `app/utils/crypto.py` | 修改 | T6 |
| `app/utils/files.py` | 修改 | T6 |
| `app/utils/logging.py` | 修改 | T6 |
| `app/container.py` | 修改 | T6 |
| `app/utils/browser.py` | 修改 | T6 |
| `frontend/js/data/websocket.js` | 修改 | T6 |
| `frontend/js/data/timers.js` | 修改 | T6 |
| `frontend/js/data/status.js` | 修改 | T6 |
| `frontend/js/data/config.js` | 修改 | T6 |
| `frontend/js/bootstrap.js` | 删除 | T6 |

---

## Task 1: 修复关键 Bug（3 个）

**Covers:** 登录竞态、重试策略不一致、超时计算错误

**Files:**
- Create: `app/utils/retry.py`
- Modify: `app/services/engine.py:315-327, 370-380`
- Modify: `app/services/monitor_service.py:285-296`
- Modify: `app/tasks/step_handlers.py:118-149`

### 1.1 修复 `_login_in_progress` 竞态

**问题**: `engine.py:326` 在 `execute_login_async()` 返回 Future 后立即清除标志，登录尚未完成，新请求可绕过检查。且如果 `execute_login_async()` 抛异常，标志永远不会清除。

- [ ] **Step 1: 修改 `_do_async_login` 方法**

将 `app/services/engine.py` 中 `_do_async_login` 的标志清除逻辑改为 Future 回调，并增加异常保护：

```python
# 修改前 (行 315-327):
def _do_async_login(self) -> None:
    if self._login_in_progress.is_set():
        return
    self._login_in_progress.set()
    ...
    executor.execute_login_async()
    self._login_in_progress.clear()  # BUG: 立即清除

# 修改后:
def _do_async_login(self) -> None:
    if self._login_in_progress.is_set():
        return
    self._login_in_progress.set()
    try:
        ...
        future = executor.execute_login_async()
    except Exception:
        self._login_in_progress.clear()
        raise
    future.add_done_callback(lambda _: self._login_in_progress.clear())
```

- [ ] **Step 2: 运行测试验证**

Run: `uv run pytest tests/ -v -k "login" --timeout=30`
Expected: PASS

### 1.2 统一重试退避策略

**问题**: `engine.py` 用固定间隔 `[30, 30, 30]`，`monitor_service.py` 用指数退避 `[5, 10, 20]`。同一功能两种行为。

- [ ] **Step 3: 创建独立的重试工具模块**

避免 `monitor_service` 导入 `engine` 形成循环依赖风险。新建 `app/utils/retry.py`：

```python
"""重试间隔计算工具。"""


def get_retry_intervals(
    retry_interval: int,
    max_retries: int,
    *,
    exponential: bool = False,
) -> list[int]:
    """计算重试间隔列表。

    exponential=True 时使用指数退避（间隔翻倍），否则使用固定间隔。
    """
    if exponential:
        return [retry_interval * (2 ** i) for i in range(max_retries)]
    return [retry_interval] * max_retries
```

- [ ] **Step 4: 更新 engine.py 中的调用点**

```python
# engine.py _get_retry_config 方法内:
from app.utils.retry import get_retry_intervals
intervals = get_retry_intervals(interval, max_retries, exponential=False)
```

- [ ] **Step 5: 更新 monitor_service.py 中的调用点**

```python
# monitor_service.py _get_retry_config 方法内:
from app.utils.retry import get_retry_intervals
intervals = get_retry_intervals(retry_interval, max_retries, exponential=True)
```

- [ ] **Step 6: 运行测试验证**

Run: `uv run pytest tests/ -v -k "retry" --timeout=30`
Expected: PASS

### 1.3 修复候选选择器降级超时计算

**问题**: `step_handlers.py:126` 中 `action_fn(loc, timeout)` 使用原始超时而非剩余时间，可能超出 deadline。

- [ ] **Step 7: 修改 `_try_candidates_with_fallback` 策略 1 的超时计算**

```python
# 修改前 (step_handlers.py 策略1):
await action_fn(loc, timeout)  # 使用原始超时

# 修改后:
remaining_ms = max(500, int((deadline - time.perf_counter()) * 1000))
await action_fn(loc, remaining_ms)
```

- [ ] **Step 8: 运行测试验证**

Run: `uv run pytest tests/ -v -k "step_handler or task_executor" --timeout=30`
Expected: PASS

- [ ] **Step 9: 提交**

```bash
git add app/utils/retry.py app/services/engine.py app/services/monitor_service.py app/tasks/step_handlers.py
git commit -m "fix: 修复登录竞态、统一重试策略、修正选择器降级超时计算"
```

---

## Task 2: 验证逻辑去重（4 处）

**Covers:** validate_auth_url 重复、headers 验证重复、URL 验证重复、CREATE_NO_WINDOW 不一致

**Files:**
- Modify: `app/schemas.py:12, 68-84, 132-138, 170-176`
- Modify: `app/services/config_service.py:98-114`
- Modify: `app/utils/config_utils.py:205`
- Modify: `app/utils/notify.py:73-75, 89-91`

### 2.1 消除 `validate_auth_url` 重复

- [ ] **Step 1: 提取公共验证函数**

在 `app/schemas.py` 顶部（`_URL_PATTERN` 定义之后）添加：

```python
def _validate_auth_url(v: str) -> str:
    v = v.strip()
    if v and not _URL_PATTERN.match(v):
        raise ValueError("认证地址必须以 http:// 或 https:// 开头")
    return v
```

- [ ] **Step 2: 两个 mixin 的 validator 改为调用公共函数**

```python
# _MonitorFieldsMixin 和 _SystemFieldsMixin 中:
@field_validator("auth_url")
@classmethod
def validate_auth_url(cls, v: str) -> str:
    return _validate_auth_url(v)
```

- [ ] **Step 3: 运行测试验证**

Run: `uv run pytest tests/ -v -k "schema or config" --timeout=30`
Expected: PASS

### 2.2 消除 `validate_headers_json` 与 `_normalize_headers_json` 重复

**风险说明**: 需确认 `_normalize_headers_json` 的所有调用路径是否都经过 schema 验证。如果存在绕过 schema 直接调用 `_normalize_headers_json` 的路径，删除后会丢失格式化行为。

- [ ] **Step 4: 先 grep 确认调用链**

Run: `rg "_normalize_headers_json" --context=3`
确认所有调用点都在 `_build_config_payload` 内部（该函数构造 `MonitorConfigPayload` 时会触发 schema validator）。

- [ ] **Step 5: 在 schemas.py 的 validator 中增加格式化**

```python
# app/schemas.py _BrowserFieldsMixin.validate_headers_json:
@field_validator("custom_headers_json")
@classmethod
def validate_headers_json(cls, v: str) -> str:
    if not v or not v.strip():
        return ""
    try:
        parsed = json.loads(v)
    except json.JSONDecodeError as exc:
        raise ValueError(f"自定义请求头不是合法 JSON：{exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("自定义请求头必须是 JSON 对象")
    return json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))
```

- [ ] **Step 6: 删除 config_service.py 中的 `_normalize_headers_json`**

仅当 Step 4 确认所有调用路径都经过 schema 时才删除。否则保留但标注为"冗余安全网"。

- [ ] **Step 7: 运行测试验证**

Run: `uv run pytest tests/ -v -k "config" --timeout=30`
Expected: PASS

### 2.3 统一 URL 验证逻辑

- [ ] **Step 8: config_utils.py 改用 schemas 的 `_URL_PATTERN`**

```python
# app/utils/config_utils.py 行 205 附近:
# 修改前:
if not auth_url.startswith(("http://", "https://")):

# 修改后:
from app.schemas import _URL_PATTERN
if auth_url and not _URL_PATTERN.match(auth_url):
```

- [ ] **Step 9: 运行测试验证**

Run: `uv run pytest tests/ -v -k "config" --timeout=30`
Expected: PASS

### 2.4 统一 `CREATE_NO_WINDOW_FLAG` 使用

- [ ] **Step 10: notify.py 改用已有常量**

```python
# app/utils/notify.py 第 11 行:
# 修改前:
from .platform import is_linux, is_macos, is_windows

# 修改后:
from .platform import CREATE_NO_WINDOW_FLAG, is_linux, is_macos, is_windows
```

然后将行 73-75 和 89-91 的内联 `creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0` 替换为 `creationflags=CREATE_NO_WINDOW_FLAG`。

- [ ] **Step 11: 运行测试验证**

Run: `uv run pytest tests/ -v --timeout=30`
Expected: PASS

- [ ] **Step 12: 提交**

```bash
git add app/schemas.py app/services/config_service.py app/utils/config_utils.py app/utils/notify.py
git commit -m "refactor: 消除验证逻辑重复，统一 URL 验证和 CREATE_NO_WINDOW 使用"
```

---

## Task 3: 前端死代码清理（5 处）

**Covers:** icons.js 未使用、VirtualScroller 未使用、logLevelOptions 冲突、formatLogMeta 未使用、getCurrentLogFiles 未使用

**Files:**
- Delete: `frontend/js/icons.js`
- Delete: `frontend/js/virtual-scroller.js`
- Modify: `frontend/app.js:4, 86-89`
- Modify: `frontend/js/app-options.js:67-74`
- Modify: `frontend/js/methods/formatters.js:19-23`
- Modify: `frontend/js/methods/logfiles.js:56-59`

### 3.1 删除未使用的图标组件

- [ ] **Step 1: 全局引用扫描确认**

Run: `rg "icon-refresh|icon-close|icon-plus|icon-trash|ICONS" --include="*.js" --include="*.html"`
Expected: 仅在 `icons.js` 自身和 `app.js` 的导入/注册处匹配

- [ ] **Step 2: 删除 icons.js 文件**

```bash
rm frontend/js/icons.js
```

- [ ] **Step 3: 从 app.js 移除导入和注册**

删除 `frontend/app.js` 第 4 行的 `import { ICONS } from './js/icons.js';` 和第 86-89 行的注册循环：

```javascript
// 删除以下代码:
for (const [name, component] of Object.entries(ICONS)) {
  app.component(name, component);
}
```

- [ ] **Step 4: 浏览器验证**

启动服务 `uv run main.py --no-browser`，访问 `http://127.0.0.1:50721`，确认页面正常加载，无控制台错误。

### 3.2 删除未使用的 VirtualScroller

- [ ] **Step 5: 确认无引用后删除**

Run: `rg "virtual-scroller|VirtualScroller|virtualScroller"`
Expected: 仅在 `virtual-scroller.js` 自身匹配

```bash
rm frontend/js/virtual-scroller.js
```

### 3.3 修复 `logLevelOptions` 命名冲突

- [ ] **Step 6: 删除 data 中的死代码**

删除 `frontend/js/app-options.js` 第 67-74 行的 `logLevelOptions` data 属性（computed 版本在第 230 行已覆盖它）。

- [ ] **Step 7: 确认日志筛选器仍正常**

在 dashboard 页面验证日志级别筛选下拉框正常工作。

### 3.4 删除未使用的 `formatLogMeta`

- [ ] **Step 8: 从 formatters.js 删除方法**

删除 `frontend/js/methods/formatters.js` 中 `formatLogMeta` 方法定义（行 19-23）。

### 3.5 删除未使用的 `getCurrentLogFiles`

- [ ] **Step 9: 从 logfiles.js 删除方法**

删除 `frontend/js/methods/logfiles.js` 中 `getCurrentLogFiles` 方法定义（行 56-59）。

- [ ] **Step 10: 提交**

```bash
git add frontend/js/icons.js frontend/js/virtual-scroller.js frontend/app.js frontend/js/app-options.js frontend/js/methods/formatters.js frontend/js/methods/logfiles.js
git commit -m "chore: 删除前端死代码（icons、VirtualScroller、未使用方法）"
```

---

## Task 4: 后端配置与进程管理改进（4 处）

**Covers:** write_pid 原子性、close_browser 未定义变量、assign_profile_fields 绕过验证、_build_config_payload 多态返回

**风险说明:** T4.4 涉及 Pydantic 验证链，需要确认 `model_validate` 的行为。

**Files:**
- Modify: `app/utils/process.py:31-34, 142-145`
- Modify: `app/utils/login.py:300-316`
- Modify: `app/services/config_service.py:117-122, 426-443, 462-489`

### 4.1 修复 `write_pid` 原子性

- [ ] **Step 1: 使用 `atomic_write` 替代手动实现**

```python
# app/utils/process.py write_pid 函数:
# 修改前:
tmp = pid_file.with_suffix(".pid.tmp")
tmp.write_text(content, encoding="utf-8")
tmp.replace(pid_file)

# 修改后:
from app.utils.files import atomic_write
atomic_write(pid_file, content)
```

- [ ] **Step 2: 修复 `get_pid_file` 的副作用**

```python
# 修改前:
def get_pid_file() -> Path:
    AUTH_DATA_DIR.mkdir(exist_ok=True)
    return AUTH_DATA_DIR / "campus_network_auth.pid"

# 修改后:
def get_pid_file() -> Path:
    return AUTH_DATA_DIR / "campus_network_auth.pid"
```

在 `write_pid` 中添加 `AUTH_DATA_DIR.mkdir(exist_ok=True)`。

- [ ] **Step 3: 运行测试验证**

Run: `uv run pytest tests/ -v -k "process" --timeout=30`
Expected: PASS

### 4.2 修复 `close_browser` 中 worker 未定义风险

- [ ] **Step 4: 提前初始化 worker 变量**

```python
# app/utils/login.py close_browser 方法:
# 修改后:
async def close_browser(self) -> None:
    if self._browser_ctx:
        worker = None
        try:
            from app.workers.playwright_worker import get_worker
            worker = get_worker()
            await self._browser_ctx.__aexit__(None, None, None)
        except Exception as exc:
            self.logger.warning("浏览器上下文关闭异常: {}", exc)
        finally:
            if worker is not None:
                try:
                    await worker.close_browser()
                except Exception as exc:
                    self.logger.warning("浏览器关闭时异常: {}", exc)
            self._browser_ctx = None
```

- [ ] **Step 5: 运行测试验证**

Run: `uv run pytest tests/ -v -k "login" --timeout=30`
Expected: PASS

### 4.3 修复 `assign_profile_fields` 绕过 Pydantic 验证

**风险说明**: `model_copy(update=...)` 默认不重新执行 validator。需要使用 `model_validate()` 确保验证生效。

- [ ] **Step 6: 确认当前 `assign_profile_fields` 的调用模式**

Run: `rg "assign_profile_fields" --context=5`
理解所有调用点的上下文。

- [ ] **Step 7: 改用 `model_validate` 确保验证生效**

```python
# app/services/config_service.py 行 426-443 附近:
# 修改前:
assign_profile_fields(
    system_settings.__dict__,
    payload.model_dump(),
    [...],
)

# 修改后: 使用 model_validate 确保 validator 重新执行
update_data = {
    k: v for k, v in payload.model_dump().items()
    if k in FIELD_LIST and v is not None
}
merged = {**system_settings.model_dump(), **update_data}
validated = type(system_settings).model_validate(merged)
for field in FIELD_LIST:
    if field in update_data:
        setattr(system_settings, field, getattr(validated, field))
```

- [ ] **Step 8: 运行测试验证**

Run: `uv run pytest tests/ -v -k "config or profile" --timeout=30`
Expected: PASS

### 4.4 统一 `_build_config_payload` 返回类型

- [ ] **Step 9: 始终返回元组**

```python
# app/services/config_service.py:
# 修改前:
def _build_config_payload(...) -> MonitorConfigPayload | tuple[MonitorConfigPayload, bool]:

# 修改后:
def _build_config_payload(...) -> tuple[MonitorConfigPayload, bool]:
```

调整函数体，无论 `apply_overrides` 为何值都返回元组。更新 `load_ui_config` 的调用处解包元组。

- [ ] **Step 10: 运行测试验证**

Run: `uv run pytest tests/ -v -k "config" --timeout=30`
Expected: PASS

- [ ] **Step 11: 提交**

```bash
git add app/utils/process.py app/utils/login.py app/services/config_service.py
git commit -m "fix: 修复 PID 原子性、close_browser 变量风险，统一配置返回类型"
```

---

## Task 5: 异步与线程安全改进（3 处）

**Covers:** reload_config 阻塞 API、ThreadPoolExecutor 嵌套、resolve_for_js 静默替换

**风险说明:**
- 5.2 涉及线程池架构，需理解 probes.py 和 decision.py 的调用关系
- ~~5.4 `_is_auth_url_reachable` 的 extra_targets 语义需先确认业务定义~~ （已取消，见下方说明）

**Files:**
- Modify: `app/services/engine.py:682-701`
- Modify: `app/network/probes.py:18`
- Modify: `app/network/decision.py:156-178`
- Modify: `app/tasks/variable_resolver.py:112-114`

### 5.1 缩短 `reload_config`/`apply_profile` 超时

- [ ] **Step 1: 缩短超时并改善日志**

```python
# app/services/engine.py 行 682-701 附近:
# 修改前:
if not cmd.response_event.wait(timeout=30):

# 修改后:
if not cmd.response_event.wait(timeout=10):
    logger.warning("配置重载超时（10s），引擎线程可能繁忙，配置将在引擎空闲后生效")
```

- [ ] **Step 2: 运行测试验证**

Run: `uv run pytest tests/ -v -k "engine or config" --timeout=30`
Expected: PASS

### 5.2 解决 ThreadPoolExecutor 嵌套共享

**问题分析**: `decision.py` 的 `is_network_available()` 将 TCP/HTTP/URL 三个检测提交到 `probes.py` 共享的同一个 3-worker executor，而 probes 内部也用同一个 executor 做并发。外层 3 个任务恰好用完 3 个 worker，内层再提交时会被排队，导致性能降级。

**方案**: 将 `probes.py` 的共享 executor 和 `decision.py` 的外层 executor 分离。最简方案：`decision.py` 使用独立的 executor。

- [ ] **Step 3: 为 `decision.py` 创建独立 executor**

```python
# app/network/decision.py 顶部:
_decision_executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="net-decision")

# is_network_available 函数中:
# 修改前:
with ThreadPoolExecutor(max_workers=3) as executor:

# 修改后:
with _decision_executor as executor:  # 使用独立 executor，不与 probes 共享
    ...
```

注意：`with` 共享 executor 不会关闭它（只有 `shutdown()` 才会），所以这是安全的。

- [ ] **Step 4: 运行测试验证**

Run: `uv run pytest tests/ -v -k "network or probe" --timeout=30`
Expected: PASS

### 5.3 修复 `resolve_for_js` 未解析变量处理

- [ ] **Step 5: 未解析变量保留原样而非替换为空字符串**

```python
# app/tasks/variable_resolver.py 行 112-114:
# 修改前:
if resolved == match.group(0):
    logger.warning("[var] 未解析的变量: {}", match.group(0))
    return '""'  # Default to empty string

# 修改后:
if resolved == match.group(0):
    logger.warning("[var] 未解析的变量: {}", match.group(0))
    return json.dumps(match.group(0))  # 保留原样，转义后作为 JS 字符串
```

- [ ] **Step 6: 运行测试验证**

Run: `uv run pytest tests/ -v -k "variable" --timeout=30`
Expected: PASS

- [ ] **Step 7: 提交**

```bash
git add app/services/engine.py app/network/decision.py app/tasks/variable_resolver.py
git commit -m "fix: 缩短配置重载超时，分离网络检测线程池，修复变量解析未解析变量处理"
```

### ~~5.4 `_is_auth_url_reachable` 的 extra_targets 互斥问题~~ — 已取消

**取消原因**: `extra_targets` 的业务语义不明确——它可能是"必须全部成功的强约束"而非"附加检测"。贸然 fallback 到 `auth_url` 可能产生假阳性。建议先在日志中增加 extra_targets 检测结果的详细记录，观察实际使用模式后再决定是否修改行为。

---

## Task 6: 低优先级清理（7 处）

**Covers:** 散布在各文件中的小问题

**已取消项:**
- ~~6.3 `save_screenshot` 搬家~~ — 低收益高改动面，不值得
- ~~6.7 前端 `_` 状态移出 data~~ — 需要验证生命周期，风险收益比不合适
- ~~6.9 `config` 深度 watcher 改版本号~~ — 会引入"忘记 ++"的隐性 bug，当前 JSON.stringify 方案虽笨但可靠

**Files:**
- Modify: `app/utils/crypto.py:56-62`
- Modify: `app/utils/files.py:36-37`
- Modify: `app/utils/logging.py:296-312`
- Modify: `app/container.py:58-60, 110-119`
- Modify: `app/utils/browser.py:133`
- Delete: `frontend/js/bootstrap.js`

### 6.1 密钥文件备份的 TOCTOU 竞态

- [ ] **Step 1: 移除多余的 exists() 检查**

```python
# app/utils/crypto.py 行 56-62:
# 修改前:
if _KEY_FILE.exists():
    backup_path = ...
    _KEY_FILE.rename(backup_path)

# 修改后:
backup_path = ...
try:
    _KEY_FILE.rename(backup_path)
except FileNotFoundError:
    pass  # 文件不存在，无需备份
```

### 6.2 `atomic_write` 的 prefix/suffix 限制

- [ ] **Step 2: 删除不合理的长度限制**

删除 `app/utils/files.py` 行 36-37 的 prefix/suffix 长度检查。

### 6.3 `DateRotatingSink._cleanup_old_dirs` 安全改进

- [ ] **Step 3: 只删除已知日志文件而非整个目录**

```python
# app/utils/logging.py 行 296-312:
# 修改前: shutil.rmtree(d)
# 修改后: 只删除日志文件，保留截图等其他文件
for f in d.iterdir():
    if f.is_file() and (f.name == "app.log" or f.name.startswith("app.log.")):
        f.unlink(missing_ok=True)
# 如果目录为空则删除
try:
    d.rmdir()
except OSError:
    pass  # 目录非空，保留
```

注意：使用 `f.name.startswith("app.log.")` 而非 `f.suffix in ('.log',)` 因为 `Path("app.log.1").suffix` 返回 `".1"` 不是 `".log"`。

### 6.4 `container.py` 可读性改进

- [ ] **Step 4: 将 `__import__` 改为延迟导入函数**

```python
# app/container.py 行 58-60:
# 修改前:
worker_getter=lambda: __import__(
    "app.workers.playwright_worker", fromlist=["get_worker"]
).get_worker(),

# 修改后:
def _get_worker():
    from app.workers.playwright_worker import get_worker
    return get_worker()

# 然后:
worker_getter=_get_worker,
```

同样修改行 79-81 的 `debug_worker_getter`。

- [ ] **Step 5: 为 `startup()` 添加异常处理**

```python
# app/container.py startup 方法:
async def startup(self):
    try:
        cleanup_orphan_browsers()
        self.start_web_services()
        self.engine.boot()
        if self.task_registry.has_enabled_tasks():
            self.engine.start_scheduler()
    except Exception:
        logger.exception("服务启动失败，正在清理...")
        try:
            await self.shutdown()
        except Exception:
            logger.exception("清理过程中也发生异常")
        raise
```

注意：`shutdown()` 本身也可能异常（因为 startup 可能只完成了一半），所以用嵌套 try/except 保护。

### 6.5 `BrowserContextManager` 封装改进

- [ ] **Step 6: 在 PlaywrightWorker 中增加 `submit_nowait` 方法**

```python
# app/workers/playwright_worker.py:
def submit_nowait(self, cmd_type: str, data: dict | None = None) -> None:
    """提交命令但不等待响应（fire-and-forget）。"""
    self._cmd_queue.put_nowait(WorkerCommand(type=cmd_type, data=data or {}))
```

然后修改 `app/utils/browser.py:133`：

```python
# 修改前:
worker._cmd_queue.put_nowait(WorkerCommand(type=CMD_BROWSER_RELEASE))

# 修改后:
worker.submit_nowait(CMD_BROWSER_RELEASE)
```

### 6.6 合并 `bootstrap.js` 到 `app.js`

- [ ] **Step 7: 内联 bootstrap.js**

将 `frontend/js/bootstrap.js` 的 5 行代码直接内联到 `frontend/app.js` 中，删除 `bootstrap.js` 文件。更新 `index.html` 中的导入（如有）。

- [ ] **Step 8: 运行全部测试**

Run: `uv run pytest tests/ -v --timeout=60`
Expected: ALL PASS

- [ ] **Step 9: 运行 lint**

Run: `uv run ruff check . && uv run ruff format --check .`
Expected: No errors

- [ ] **Step 10: 提交**

```bash
git add -A
git commit -m "chore: 低优先级清理——密钥备份竞态、日志清理安全、容器可读性、浏览器封装"
```

---

## 验证清单

所有 Task 完成后：

- [ ] `uv run pytest tests/ -v --timeout=60` — 全部通过
- [ ] `uv run ruff check .` — 无错误
- [ ] `uv run ruff format --check .` — 无格式问题
- [ ] `uv run main.py --no-browser` — 服务正常启动
- [ ] 浏览器访问 `http://127.0.0.1:50721` — 页面正常加载，无控制台错误
- [ ] 手动验证：日志筛选器、任务编辑器、配置保存等核心功能正常
