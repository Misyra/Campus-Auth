# LoginSession 重试架构设计

**日期**：2026-07-04
**状态**：待审批

---

## 背景

### 当前问题

每次登录尝试都创建/销毁浏览器，导致：
- 浏览器启动占登录时间大头（1-3秒）
- 失败后无法快速重试
- 资源浪费

### 当前流程

```
Attempt1 → 创建浏览器 → 登录 → 失败 → 销毁浏览器
Attempt2 → 创建浏览器 → 登录 → 失败 → 销毁浏览器
Attempt3 → 创建浏览器 → 登录 → 成功 → 销毁浏览器
```

### 目标流程

```
LoginSession → 创建浏览器
  ├── Attempt1 → 失败
  ├── 等待 5s（可中断）
  ├── Attempt2 → 失败
  ├── 等待 5s（可中断）
  ├── Attempt3 → 成功
  └── 销毁浏览器
```

---

## 架构设计

### 目录结构

```
app/services/
├── login_orchestrator.py    # 提交到 Worker，去重/抢占
├── login_models.py          # 【新增】LoginResult、LoginResultType、LoginRetryPolicy
├── login_session.py         # 【新增】浏览器生命周期 + 重试循环
└── login_attempt.py         # 【重命名自 login_handler.py】单次登录尝试

app/utils/
├── async_utils.py           # 【新增】interruptible_sleep 等异步工具
```

### 职责边界

| 类 | 职责 | 不负责 |
|---|------|--------|
| `LoginOrchestrator` | 提交到 Worker，去重/抢占 | retry、浏览器管理 |
| `LoginSession` | 浏览器生命周期、重试循环、失败分类决策 | 具体登录步骤 |
| `LoginAttempt` | goto/fill/submit/解析结果 | retry、浏览器创建 |
| `LoginModels` | 数据模型定义 | 业务逻辑 |

### 调用链路

```
Engine
  │
  ▼
LoginOrchestrator.dispatch()
  │
  ▼
Worker._handle_login()
  │
  ▼
LoginSession.run(cancel_event)
  │
  ├── BrowserContextManager（整个 Session 共用）
  │
  ├── while retry < max_retries
  │      ├── 检查 cancel_event
  │      ├── LoginAttempt.execute(cancel_event)
  │      ├── SUCCESS → return
  │      ├── INVALID_CREDENTIAL → return
  │      ├── UNKNOWN → return
  │      ├── CANCELLED → return
  │      └── RETRYABLE → 可中断等待 5s
  │
  └── finally:
         关闭浏览器
```

---

## 核心设计

### 1. LoginResultType（app/services/login_models.py）

```python
from enum import Enum, auto

class LoginResultType(Enum):
    """登录结果类型。"""
    SUCCESS = auto()              # 登录成功
    RETRYABLE = auto()            # 网络/临时错误，可重试
    INVALID_CREDENTIAL = auto()   # 账号密码错误，不可重试
    CANCELLED = auto()            # 用户取消
```

**分类规则**：

| 类型 | 场景 |
|------|------|
| `RETRYABLE` | 浏览器启动失败、DNS 失败、TCP Timeout、Portal 无响应、HTTP 5xx、连接 Reset、Playwright Timeout、页面加载超时 |
| `INVALID_CREDENTIAL` | 用户名密码错误、运营商错误、Portal 明确认证失败 |

**异常处理**：
- 程序异常（TypeError、KeyError 等）不捕获，直接抛出让 Worker 处理
- 只捕获明确的网络异常：`ConnectionResetError`、`ConnectionAbortedError`、`ConnectionRefusedError`、`TimeoutError`、`PlaywrightTimeoutError`

### 2. LoginResult（app/services/login_models.py）

```python
@dataclass
class LoginResult:
    """登录结果。"""
    type: LoginResultType
    message: str = ""

    @property
    def should_retry(self) -> bool:
        """是否应该重试。"""
        return self.type == LoginResultType.RETRYABLE
```

### 3. LoginRetryPolicy（app/services/login_models.py）

```python
@dataclass
class LoginRetryPolicy:
    """登录重试策略。"""
    max_retries: int = 5
    _delays: list[float] = field(default_factory=lambda: [5.0, 5.0, 5.0, 5.0, 5.0])

    def next_delay(self, attempt: int) -> float | None:
        """返回第 attempt 次重试前的延迟，None 表示不再重试。"""
        if attempt >= self.max_retries:
            return None
        idx = min(attempt, len(self._delays) - 1)
        return self._delays[idx]
```

**设计优势**：
- `next_delay(attempt)` 支持固定间隔、指数退避、随机抖动
- Session 只调用 `next_delay()`，不关心具体策略

**配置来源**：
- `max_retries`：从 `RuntimeConfig.retry.max_retries` 读取
- `_delays`：当前固定 `[5.0, 5.0, 5.0, 5.0, 5.0]`，后续可配置

**配置变更**：

```python
# app/schemas.py
class RetrySettings(BaseModel):
    """重试设置。"""
    max_retries: int = Field(default=5, ge=1, le=20)
    retry_interval: float = Field(default=5.0, ge=1.0, le=60.0)  # 新增
```

### 4. LoginSession（app/services/login_session.py）

```python
class LoginSession:
    """登录会话 — 管理浏览器生命周期和重试循环。"""

    def __init__(
        self,
        config: dict[str, Any],
        cancel_event: threading.Event,
        retry_policy: LoginRetryPolicy | None = None,
    ):
        self._config = config
        self._cancel_event = cancel_event
        self._retry_policy = retry_policy or LoginRetryPolicy()
        self._logger = get_logger("login_session", source="backend")

    async def run(self) -> LoginResult:
        """执行登录会话。"""
        from app.utils.async_utils import interruptible_sleep
        from app.utils.browser import BrowserContextManager

        try:
            async with BrowserContextManager(self._config) as browser:
                # 创建 Attempt 执行器（复用，不每次 new）
                attempt = LoginAttempt(browser, self._config, self._cancel_event)

                for i in range(self._retry_policy.max_retries):
                    # 检查取消
                    if self._cancel_event.is_set():
                        return LoginResult(LoginResultType.CANCELLED, "登录已取消")

                    # 执行单次尝试
                    self._logger.info("登录尝试 {}/{}", i + 1, self._retry_policy.max_retries)
                    result = await attempt.execute()

                    # 成功或不可重试，直接返回
                    if not result.should_retry:
                        return result

                    # 可重试：可中断等待
                    delay = self._retry_policy.next_delay(i + 1)
                    if delay is not None:
                        self._logger.info("等待 {}s 后重试", delay)
                        if not await interruptible_sleep(delay, self._cancel_event):
                            return LoginResult(LoginResultType.CANCELLED, "登录已取消")

                # 重试次数用尽
                return LoginResult(
                    LoginResultType.RETRYABLE,
                    f"重试 {self._retry_policy.max_retries} 次后仍失败"
                )
        except Exception as exc:
            self._logger.exception("登录会话异常: {}", exc)
            raise  # 程序异常不捕获，让 Worker 处理
```

### 5. LoginAttempt（app/services/login_attempt.py，重命名自 login_handler.py）

```python
class LoginAttempt:
    """单次登录尝试 — 负责 goto/fill/submit/解析结果。"""

    # 明确的可重试网络异常
    _RETRYABLE_ERRORS = (
        ConnectionResetError,
        ConnectionAbortedError,
        ConnectionRefusedError,
        TimeoutError,
    )

    def __init__(
        self,
        browser: BrowserContextManager,
        config: dict[str, Any],
        cancel_event: threading.Event,
    ):
        self._browser = browser
        self._config = config
        self._cancel_event = cancel_event

    async def execute(self) -> LoginResult:
        """执行单次登录尝试。"""
        try:
            # 1. 导航到登录页并验证页面
            await self._navigate_to_login()

            # 2. 填写表单
            await self._fill_form()

            # 3. 提交
            await self._submit()

            # 4. 解析结果
            return await self._parse_result()

        except LoginCancelledError:
            return LoginResult(LoginResultType.CANCELLED, "登录已取消")
        except self._RETRYABLE_ERRORS as exc:
            return LoginResult(LoginResultType.RETRYABLE, str(exc))
        # 程序异常不捕获，直接抛出

    async def _navigate_to_login(self) -> None:
        """导航到登录页并验证页面就绪。"""
        login_url = self._config.get("auth_url", "")
        if not login_url:
            return

        page = self._browser.page
        await page.goto(login_url, wait_until="domcontentloaded")

        # 验证页面就绪（URL 匹配或标题包含预期内容）
        # 具体验证逻辑在实现阶段确定
```

---

## 取消事件传递

沿用现有机制，从 Engine 到 Attempt 一路传递：

```
Engine → Worker → Session.run(cancel_event) → Attempt.execute(cancel_event)
```

### interruptible_sleep（app/utils/async_utils.py）

```python
async def interruptible_sleep(seconds: float, cancel_event: threading.Event) -> bool:
    """可中断等待。

    Args:
        seconds: 等待秒数
        cancel_event: 取消事件

    Returns:
        True 表示等待完成，False 表示被取消
    """
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if cancel_event.is_set():
            return False
        await asyncio.sleep(0.2)
    return True
```

**响应时间**：最坏情况 0.2 秒内响应取消。

**复用**：Engine、Scheduler、Network Monitor 等后续可共用此函数。

---

## 与现有代码的关系

### LoginOrchestrator

**不改动**。它只负责提交到 Worker，不关心重试。

### Worker._handle_login()

**简化**。改为调用 `LoginSession.run()`：

```python
async def _handle_login(self, data: dict) -> WorkerResponse:
    config = data.get("config", {})
    cancel_event = data.get("cancel_event")

    session = LoginSession(config, cancel_event)
    result = await session.run()

    return WorkerResponse(
        success=result.type == LoginResultType.SUCCESS,
        data=result.message if result.type == LoginResultType.SUCCESS else None,
        error=result.message if result.type != LoginResultType.SUCCESS else None,
    )
```

### MonitoredPolicy

**不改动**。它只看到最终成功/失败，不知道内部重试几次。

### BrowserContextManager

**不改动**。仍然是上下文管理器，`__aexit__` 关闭浏览器。

---

## 文件变更

| 操作 | 文件 | 说明 |
|------|------|------|
| 新增 | `app/services/login_models.py` | LoginResultType、LoginResult、LoginRetryPolicy |
| 新增 | `app/services/login_session.py` | LoginSession |
| 新增 | `app/utils/async_utils.py` | interruptible_sleep |
| 重命名 | `app/services/login_handler.py` → `app/services/login_attempt.py` | LoginAttemptHandler → LoginAttempt |
| 修改 | `app/schemas.py` | RetrySettings 新增 retry_interval 字段 |
| 修改 | `app/workers/playwright_worker.py` | `_handle_login` 改为调用 LoginSession |
| 修改 | `app/services/login_orchestrator.py` | 更新 import 路径 |
| 修改 | `tests/` | 更新测试 |

## 需要确认的问题

### BrowserContextManager 是否支持多次 execute()

当前 `BrowserContextManager.__aexit__()` 总是关闭浏览器。需要确认：

1. 如果 `LoginAttempt.execute()` 内部创建新 page，Session 复用仍然有效
2. 如果 `BrowserContextManager` 在 `__aexit__` 中关闭整个浏览器，Session 的复用才有意义

**结论**：需要检查 `LoginAttempt._execute_browser_task()` 的实现，确认浏览器生命周期是否与 Session 对齐。

---

## 测试策略

1. **LoginSession**：mock LoginAttempt，验证重试逻辑、取消响应、失败分类
2. **LoginAttempt**：mock BrowserContextManager，验证各种结果类型
3. **集成测试**：验证完整链路（Session → Attempt → 结果）

---

## 后续扩展

此架构支持以下扩展，无需改动 Session/Attempt 以外的代码：

- 验证码处理（在 Attempt 中）
- 短信验证（在 Attempt 中）
- 指数退避（修改 RetryPolicy）
- 多认证方式（在 Session 中选择 Attempt 类型）
