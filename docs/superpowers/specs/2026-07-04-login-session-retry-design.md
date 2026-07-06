# LoginSession 重试架构设计

**日期**：2026-07-04
**状态**：待审批
**作者**：—
**关联模块**：`app/services/login_*`、`app/workers/playwright_worker.py`、`app/utils/browser.py`

---

## 1. 背景

### 1.1 当前问题

当前一次"登录"的执行链路是：

```
LoginOrchestrator.submit()
  → Worker._handle_login()
  → LoginAttemptHandler.attempt_login()
  → BrowserContextManager.__aenter__()   ← 创建/复用 Worker 中的浏览器
  → BrowserTaskRunner.execute(page)
  → BrowserContextManager.__aexit__()    ← 关闭整个浏览器（worker._close_browser）
```

每次登录尝试都伴随浏览器创建/销毁，导致：

- **浏览器启动占登录耗时大头**（1–3s，是单次失败重试的主要成本）
- **失败后无法在浏览器复用的前提下快速重试**，因为浏览器已被 `__aexit__` 关闭
- **资源浪费**：高并发监控场景下浏览器进程频繁创建/销毁
- **重试分散在两处**：
  - `app/services/login_runner.py::execute_login_with_retries` —— 进程级 `login_once` 模式的外层重试（每次都重新 `submit`）
  - `app/services/retry_policy.py::MonitoredPolicy` —— 引擎长期监控的延迟表
  - 单次 `Worker._handle_login` 内部**没有**重试循环

### 1.2 目标流程

引入 `LoginSession`，在**同一次** Worker 调用内复用浏览器，并把单次会话内的重试收敛到 Session：

```
LoginOrchestrator.submit()                       ← 仍是单次 submit（不变）
  → Worker._handle_login()
  → LoginSession.run(cancel_event)
        ├── 浏览器就绪（整个 Session 共用，详见 §5 BrowserContextManager 改造）
        ├── Attempt #1 → 失败（RETRYABLE）
        ├── interruptible_sleep(5s) ← 可被 cancel_event 中断
        ├── Attempt #2 → 失败（RETRYABLE）
        ├── interruptible_sleep(5s)
        ├── Attempt #3 → 成功（SUCCESS） / 凭证错误（INVALID_CREDENTIAL） / 取消（CANCELLED）
        └── 关闭浏览器（Session 结束）
```

### 1.3 非目标（Out of Scope）

本次设计**不**做以下事情，避免范围蔓延：

- ❌ 不引入指数退避/随机抖动（保留固定间隔，仅预留接口）
- ❌ 不改动 `LoginOrchestrator` 的去重/抢占/历史记录逻辑
- ❌ 不改动 `MonitoredPolicy` 的引擎长期监控延迟表
- ❌ 不改动 `ScriptTask`（无浏览器任务）的执行路径与重试语义
- ❌ 不改动登录历史记录、`Worker` Actor 模型、命令队列
- ❌ 不改动 UI / API 层

---

## 2. 设计决策记录（ADR-style）

| # | 决策 | 选项 | 选择 | 理由 |
|---|------|------|------|------|
| D1 | 新模型命名 | `LoginResult` / `AttemptOutcome` / `LoginAttemptResult` | **`AttemptOutcome`** + `AttemptOutcomeType` | `app/schemas.py:57` 已存在 `LoginResult(StrEnum)`（进程退出码语义），被 `login_runner.py`、`launcher.py`、5+ 测试文件引用，新名直接冲突 |
| D2 | 浏览器复用实现 | A. 给 `BrowserContextManager` 加 `keep_alive` 模式位 / B. Session 直接持有 Worker 引用 / C. Session 层单 `async with` 包住重试循环 | **C**：Session 用单个 `async with BrowserContextManager(...)` 包住整个重试循环 | 浏览器在 Session 开始时创建一次、所有 Attempt 复用同一 browser 引用、Session 退出（`__aexit__`）自动关闭；BrowserContextManager **零改动**；所有终态（成功/失败/取消/耗尽/异常）都走 `__aexit__` → `worker._close_browser()`，无状态泄漏 |
| D3 | 与 `login_runner` 外层重试的关系 | A. 保留外层重试（乘积放大）/ B. 移除外层重试，由 Session 全权负责 / C. 保留外层但 Session 内 max_retries=1 | **B**：移除 `execute_login_with_retries` 的循环，改为单次 `submit` | 外层重试每次都是新进程级 `submit` + 新浏览器，与 Session 复用目标冲突；保留会导致 5×5=25 次尝试 |
| D4 | `interruptible_sleep` 归宿 | 新建 `app/utils/async_utils.py` / 合并到 `app/utils/concurrent.py` | **合并到 `concurrent.py`** | `concurrent.py` 已是异步并发工具的归属地（`race_first_success`、`cancel_pending`），避免新建碎片化文件 |
| D5 | 重试耗尽的终态 | 复用 `RETRYABLE` / 新增 `EXHAUSTED` | **新增 `EXHAUSTED`** | 复用 `RETRYABLE` 会让 `should_retry` 在耗尽后仍返回 True，逻辑矛盾；新增独立终态使决策表无歧义 |
| D6 | `cancel_event` 类型 | `threading.Event` / `CompositeCancelEvent` | 接受 `threading.Event`，内部按 `CompositeCancelEvent` 语义使用 | `CompositeCancelEvent` 继承自 `threading.Event`，跨线程安全；保留基类签名便于测试 mock |
| D7 | `max_retries` 默认值 | 文档示例 5 / 现有 `RetrySettings` 默认 3 | **从 `RuntimeConfig.retry.max_retries` 读取（默认 3）** | 单一来源；与 `login_runner` 现有 `max(1, min(..., 10))` 一致 |
| D8 | `_delays` 来源 | 硬编码 `[5.0]*5` / 从 `retry_interval` 派生 | **从 `RuntimeConfig.retry.retry_interval` 派生** | `retry_interval` 字段已存在（`Field(default=5, ge=1, le=300)`），配置变更才能真实生效 |

---

## 3. 目录结构

```
app/services/
├── login_orchestrator.py    # 不改动：提交到 Worker，去重/抢占
├── login_models.py          # 【新增】AttemptOutcomeType、AttemptOutcome、LoginRetryPolicy
├── login_session.py         # 【新增】浏览器生命周期 + 重试循环
├── login_attempt.py         # 【重命名自 login_handler.py】单次登录尝试（保留所有现有职责）
├── login_runner.py          # 【修改】移除 execute_login_with_retries 的循环，改为单次 submit
└── retry_policy.py          # 不改动：MonitoredPolicy 仍服务于引擎长期监控

app/utils/
├── concurrent.py            # 【修改】新增 interruptible_sleep
├── browser.py               # 不改动：BrowserContextManager 现有行为已满足 Session 复用需求
└── cancel_token.py          # 不改动：CompositeCancelEvent
```

### 3.1 职责边界

| 类 | 职责 | 不负责 |
|---|------|--------|
| `LoginOrchestrator` | 提交到 Worker、去重/抢占、历史记录、`cancel_event` 生命周期 | retry、浏览器管理 |
| `LoginSession` | 浏览器生命周期、重试循环、失败分类决策 | 具体登录步骤、TaskManager |
| `LoginAttempt` | 任务加载、Script/Browser 分支、`goto/fill/submit/parse`、dialog 监听、登录成功等待 | retry、浏览器创建/关闭 |
| `LoginRetryPolicy` | 单次会话内的延迟表与终态判定 | 引擎级重试（`MonitoredPolicy` 的领域） |
| `MonitoredPolicy` | 引擎长期网络监控的延迟表与状态转换 | 单次会话内重试 |
| `LoginModels` | 数据模型定义 | 业务逻辑 |

### 3.2 调用链路

```
Engine
  │
  ▼
LoginOrchestrator.submit(source, config, cancel_event)
  │   （提交到 login-exec 线程池，跨线程通过 CompositeCancelEvent 联动）
  ▼
Worker._handle_login(data)              ← Worker 事件循环线程内
  │
  ▼
LoginSession(config, cancel_event, retry_policy).run()
  │
  ├── async with BrowserContextManager(config, cancel_event) as browser:
  │       （Session 开始：ensure_browser；Session 退出：_close_browser，覆盖所有终态）
  │
  ├── attempt = LoginAttempt(browser, config, cancel_event)
  │
  ├── for i in range(retry_policy.max_retries):
  │       ├── if cancel_event.is_set(): return CANCELLED        ──┐
  │       ├── outcome = await attempt.execute()                   │
  │       ├── if not outcome.should_retry: return outcome         │ 所有 return
  │       └── if not await interruptible_sleep(delay, ...):       │ 都在 async with 块内
  │              return CANCELLED                                  │ → __aexit__ 必执行
  │                                                               │ → 浏览器必关闭
  └── return EXHAUSTED                                           ──┘
```

---

## 4. 核心数据模型（`app/services/login_models.py`）

### 4.1 `AttemptOutcomeType`

```python
from enum import StrEnum


class AttemptOutcomeType(StrEnum):
    """单次登录尝试的结果分类。"""
    SUCCESS = "success"              # 登录成功
    RETRYABLE = "retryable"          # 网络/临时错误，可重试
    INVALID_CREDENTIAL = "invalid"   # 账号密码错误，不可重试
    CANCELLED = "cancelled"          # 用户取消
    EXHAUSTED = "exhausted"          # 重试次数耗尽（终态，不应再重试）
```

> 使用 `StrEnum` 与 `app/schemas.py` 既有风格一致（项目已统一从 `Enum` 迁移到 `StrEnum`）。

**分类规则**：

| 类型 | 场景 |
|------|------|
| `RETRYABLE` | 浏览器启动失败、DNS 失败、TCP Timeout、Portal 无响应、HTTP 5xx、连接 Reset/Aborted/Refused、Playwright Timeout、页面加载超时、`TargetClosedError`（页面崩溃可重建） |
| `INVALID_CREDENTIAL` | 用户名密码错误、运营商错误、Portal 明确认证失败 |
| `CANCELLED` | `cancel_event.is_set()` 或 `LoginCancelledError` |
| `EXHAUSTED` | 重试次数用尽（由 Session 设置，不由 Attempt 设置） |

**异常处理原则**（与用户偏好一致：明确异常而非通用 try-catch）：

- 程序异常（`TypeError`、`KeyError`、`AttributeError` 等）**不捕获**，直接抛出让 Worker 的外层 except 处理
- 只捕获**明确的可重试网络异常**，见 §6.2 `_RETRYABLE_ERRORS`

### 4.2 `AttemptOutcome`

```python
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AttemptOutcome:
    """单次登录尝试的结果。"""
    type: AttemptOutcomeType
    message: str = ""

    @property
    def should_retry(self) -> bool:
        """是否应该重试。EXHAUSTED/CANCELLED/SUCCESS/INVALID_CREDENTIAL 均为终态。"""
        return self.type == AttemptOutcomeType.RETRYABLE
```

### 4.3 `LoginRetryPolicy`

```python
from dataclasses import dataclass, field


@dataclass
class LoginRetryPolicy:
    """单次登录会话内的重试策略。

    与 app/services/retry_policy.py::MonitoredPolicy 互不重叠：
    - MonitoredPolicy：引擎长期网络监控，含 down→up 状态转换回调
    - LoginRetryPolicy：单次会话内的固定间隔重试，无状态机
    """
    max_retries: int
    interval_seconds: float

    def __post_init__(self) -> None:
        # 与 login_runner 既有约束保持一致：[1, 10]
        self.max_retries = max(1, min(self.max_retries, 10))
        self.interval_seconds = max(1.0, float(self.interval_seconds))

    @classmethod
    def from_runtime_config(cls, retry_settings: "RetrySettings") -> "LoginRetryPolicy":
        """从 RuntimeConfig.retry 构造。单一来源。"""
        return cls(
            max_retries=retry_settings.max_retries,
            interval_seconds=float(retry_settings.retry_interval),
        )

    def next_delay(self, attempt_index: int) -> float | None:
        """返回第 attempt_index 次重试前的延迟（秒），None 表示不再重试。

        attempt_index 从 0 开始（第 0 次重试 = 第 1 次失败后）。
        """
        if attempt_index >= self.max_retries:
            return None
        return self.interval_seconds
```

**设计要点**：

- 不再硬编码 `[5.0]*5`，从 `RetrySettings.retry_interval` 派生（D8）
- `from_runtime_config` 是唯一构造入口，保证配置单一来源
- 预留扩展位：未来支持指数退避只需新增 `backoff_factor` 字段并在 `next_delay` 中计算，调用方不变

### 4.4 关于 `app/schemas.py::RetrySettings` 的现状澄清

**该字段已存在，本次无需新增**（原文档表述有误）：

```python
# app/schemas.py:337（现状，frozen）
class RetrySettings(BaseModel, frozen=True):
    max_retries: int = Field(default=3, ge=0, le=10)        # 默认 3，非 5
    retry_interval: int = Field(default=5, ge=1, le=300)    # 已存在
```

本次仅需在 `LoginRetryPolicy.from_runtime_config` 中消费这两个字段，**不修改 schema**。

---

## 5. BrowserContextManager（不改动）

### 5.1 现状

`app/utils/browser.py::BrowserContextManager`：

- `__aenter__`：调用 `worker.ensure_browser(config)`，获取 `playwright / browser / context / page` 引用
- `__aexit__`：调用 `worker._close_browser()` 关闭整个浏览器，清空引用

### 5.2 复用方案（零改动）

Session 层用**单个** `async with BrowserContextManager(...)` 包住整个重试循环：

```python
async with BrowserContextManager(config, cancel_event) as browser:
    attempt = LoginAttempt(browser, config, cancel_event)
    for i in range(retry_policy.max_retries):
        outcome = await attempt.execute()
        ...  # 所有 return 路径都在 async with 块内
```

浏览器生命周期与 Session 完全对齐：

| Session 退出原因 | 退出路径 | 浏览器是否关闭 |
|------------------|----------|----------------|
| 首试成功 | `return SUCCESS`（块内） | ✅ `__aexit__` |
| 凭证错误 | `return INVALID_CREDENTIAL`（块内） | ✅ `__aexit__` |
| 用户取消 | `return CANCELLED`（块内） | ✅ `__aexit__` |
| 重试耗尽 | `return EXHAUSTED`（块内） | ✅ `__aexit__` |
| Attempt 抛程序异常 | 异常传播出 `async with` | ✅ `__aexit__`（exc_type 非 None） |
| `interruptible_sleep` 被取消 | `return CANCELLED`（块内） | ✅ `__aexit__` |

Python 的 `async with` 语义保证：无论 `return`、`break`、`continue` 还是异常传播，`__aexit__` 都会执行。因此**不需要**任何额外的 `finally` 关闭逻辑，也**不需要** `keep_alive` 参数。

### 5.3 Attempt 间浏览器崩溃的处理

Attempt 之间浏览器可能崩溃（`TargetClosedError`、`browser.is_connected() == False`）。处理策略：

- `LoginAttempt.execute` 捕获 `TargetClosedError` → 返回 `RETRYABLE`（见 §7.5）
- 下一轮 Attempt 执行前，`LoginAttempt` 通过 `worker.ensure_browser()` 刷新 page 引用（幂等：浏览器存活则跳过，崩溃则重建）
- 由于 `BrowserContextManager` 只在 Session 开始时调用一次 `ensure_browser`，Attempt 内部的刷新需要直接访问 worker —— 这属于 `LoginAttempt` 的实现细节，不破坏 Session 的浏览器所有权边界

> **注意**：`worker.ensure_browser()` 是幂等的（源码已确认），Attempt 内部调用不会与 Session 的 `BrowserContextManager` 冲突。

---

## 6. LoginSession（`app/services/login_session.py`）

```python
"""登录会话 — 管理浏览器生命周期和单次会话内的重试循环。"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

from app.services.login_attempt import LoginAttempt
from app.services.login_models import (
    AttemptOutcome,
    AttemptOutcomeType,
    LoginRetryPolicy,
)
from app.utils.browser import BrowserContextManager
from app.utils.concurrent import interruptible_sleep
from app.utils.logging import get_logger

if TYPE_CHECKING:
    from app.schemas import RetrySettings

logger = get_logger("login_session", source="backend")


class LoginSession:
    """登录会话 — 管理浏览器生命周期和重试循环。"""

    def __init__(
        self,
        config: dict[str, Any],
        cancel_event: threading.Event,
        retry_policy: LoginRetryPolicy | None = None,
    ) -> None:
        self._config = config
        self._cancel_event = cancel_event
        self._retry_policy = retry_policy or LoginSession._build_default_policy(config)
        self._logger = logger

    @staticmethod
    def _build_default_policy(config: dict[str, Any]) -> LoginRetryPolicy:
        """从 worker config dict 构造默认策略。"""
        retry_dict = config.get("retry_settings") or {}
        max_retries = int(retry_dict.get("max_retries", 3))
        interval = float(retry_dict.get("retry_interval", 5))
        return LoginRetryPolicy(max_retries=max_retries, interval_seconds=interval)

    async def run(self) -> AttemptOutcome:
        """执行登录会话，含重试循环。

        浏览器生命周期由 async with BrowserContextManager 管理：
        - 进入：创建/复用浏览器（worker.ensure_browser）
        - 退出：关闭浏览器（worker._close_browser）
        所有 return 路径都在 async with 块内，确保任何终态都关闭浏览器。
        """
        async with BrowserContextManager(self._config, self._cancel_event) as browser:
            attempt = LoginAttempt(browser, self._config, self._cancel_event)

            for i in range(self._retry_policy.max_retries):
                # 1. 取消检查
                if self._cancel_event.is_set():
                    return AttemptOutcome(AttemptOutcomeType.CANCELLED, "登录已取消")

                # 2. 执行单次尝试
                self._logger.info(
                    "登录尝试 {}/{}", i + 1, self._retry_policy.max_retries
                )
                outcome = await attempt.execute()

                # 3. 终态（成功/不可重试/取消）直接返回
                if not outcome.should_retry:
                    return outcome

                # 4. 可重试：可中断等待
                delay = self._retry_policy.next_delay(i)
                if delay is None:
                    break  # 理论上不会触发，循环边界已保证
                self._logger.info("等待 {:.1f}s 后重试", delay)
                if not await interruptible_sleep(delay, self._cancel_event):
                    return AttemptOutcome(AttemptOutcomeType.CANCELLED, "登录已取消")

            # 5. 重试耗尽（仍在 async with 内，return 触发 __aexit__ 关闭浏览器）
            return AttemptOutcome(
                AttemptOutcomeType.EXHAUSTED,
                f"重试 {self._retry_policy.max_retries} 次后仍失败",
            )
```

**关键点**：

- `run()` 签名**不**接收 `cancel_event`（与原文档图示不一致的修正）—— `cancel_event` 在 `__init__` 传入并保存为成员
- `attempt.execute()` **不**接收 `cancel_event` —— Attempt 通过 `__init__` 持有引用，避免参数传递链冗余
- `EXHAUSTED` 终态解决原方案"重试耗尽返回 RETRYABLE"的逻辑漏洞（D5）
- 程序异常**不**在 `run` 内捕获，让 Worker 的外层 except 统一记录

---

## 7. LoginAttempt（`app/services/login_attempt.py`，重命名自 `login_handler.py`）

### 7.1 现有职责（必须保留）

`LoginAttemptHandler` 当前的职责远超"goto/fill/submit/parse"四步，**全部保留**：

1. **TaskManager 懒初始化**（`_ensure_task_manager`）
2. **任务加载与分支**：
   - `ScriptTaskInfo` → `_execute_script_task`（无浏览器，调用 `ScriptRunner` + 网络检测）
   - `BrowserTaskInfo` → `_execute_browser_task`（通过 `BrowserTaskRunner.execute` 执行多步骤）
3. **`template_vars` 构建**（`build_login_template_vars`）
4. **dialog 监听与延迟关闭**（`_handle_dialog`）
5. **登录成功等待**（`LOGIN_SUCCESS_SETTLE_SECONDS = 2`）
6. **截图路径日志清洗**（`SCREENSHOT_URL_PATTERN`）
7. **取消检查**（`cancel_event.is_set()`）
8. **浏览器生命周期管理**（当前在 `_execute_browser_task` 内创建/关闭 `BrowserContextManager`）

### 7.2 改造要点

重命名 + 适配 Session 模式后，**仅第 8 项浏览器生命周期管理需要变更**：

| 项 | 现状（`LoginAttemptHandler`） | 改造后（`LoginAttempt`） |
|----|------------------------------|--------------------------|
| 浏览器获取 | 内部 `BrowserContextManager(config, cancel_event)` + `__aenter__` | 接收 Session 传入的 `browser: BrowserContextManager`，**不**自行创建 |
| 浏览器关闭 | `finally: await self.close_browser()` | **不**关闭，由 Session 的 `async with` 负责 |
| ScriptTask 分支 | 不使用浏览器，独立路径 | **不变**：ScriptTask 仍走 `_execute_script_task`，不进入 Session 的浏览器复用循环 |
| 返回类型 | `tuple[bool, str]` | `AttemptOutcome`（新增类型映射层） |

### 7.3 返回类型映射

```python
# 现有 tuple[bool, str] → AttemptOutcome 的映射
def _to_outcome(success: bool, message: str) -> AttemptOutcome:
    if success:
        return AttemptOutcome(AttemptOutcomeType.SUCCESS, message)
    # 失败默认归为 RETRYABLE；INVALID_CREDENTIAL 需要从 message/异常类型识别
    # 详见 §7.4 凭证错误识别
    if _looks_like_invalid_credential(message):
        return AttemptOutcome(AttemptOutcomeType.INVALID_CREDENTIAL, message)
    return AttemptOutcome(AttemptOutcomeType.RETRYABLE, message)
```

### 7.4 凭证错误识别（待实现细节）

`INVALID_CREDENTIAL` 的识别需要 Portal 特定规则，建议在实现阶段根据各 Portal 返回的特征字符串/HTTP 状态码确定。本次设计**仅预留类型**，具体识别规则在 `LoginAttempt._parse_portal_response` 中实现。

> **未决问题**：当前 `BrowserTaskRunner.execute` 返回 `(success, message)`，无法区分"凭证错误"与"临时失败"。需要扩展 BrowserTaskRunner 的返回协议，或在 `LoginAttempt` 层根据 message 模式匹配。**建议**：后者，避免改动 BrowserTaskRunner 影响调试会话等其它调用方。

### 7.5 异常分类（修正原文档遗漏）

```python
from playwright.async_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError


class LoginAttempt:
    # 明确的可重试异常（修正：原文档遗漏 PlaywrightTimeoutError 和 PlaywrightError 子类）
    _RETRYABLE_ERRORS: tuple[type[BaseException], ...] = (
        ConnectionResetError,
        ConnectionAbortedError,
        ConnectionRefusedError,
        TimeoutError,                # Python 内置
        PlaywrightTimeoutError,      # playwright.async_api.TimeoutError
    )

    # PlaywrightError 是基类，TargetClosedError 等是其子类
    # 单独捕获 PlaywrightError 会过宽（含语法错误等），需按 message/类型细分
    _RETRYABLE_PLAYWRIGHT_ERROR_SUBSTRINGS = (
        "Target closed",         # 页面/上下文崩溃，可重建
        "Connection closed",
        "Browser has been closed",
    )

    async def execute(self) -> AttemptOutcome:
        try:
            ...
        except LoginCancelledError:
            return AttemptOutcome(AttemptOutcomeType.CANCELLED, "登录已取消")
        except self._RETRYABLE_ERRORS as exc:
            return AttemptOutcome(AttemptOutcomeType.RETRYABLE, str(exc))
        except PlaywrightError as exc:
            msg = str(exc)
            if any(s in msg for s in self._RETRYABLE_PLAYWRIGHT_ERROR_SUBSTRINGS):
                return AttemptOutcome(AttemptOutcomeType.RETRYABLE, msg)
            raise  # 其他 PlaywrightError 视为程序异常
        # 程序异常不捕获，直接抛出
```

---

## 8. `interruptible_sleep`（合并到 `app/utils/concurrent.py`）

```python
# app/utils/concurrent.py 追加

import asyncio
import time
import threading


async def interruptible_sleep(
    seconds: float, cancel_event: threading.Event, *, poll_interval: float = 0.2
) -> bool:
    """可中断的异步等待。

    Args:
        seconds: 等待秒数
        cancel_event: 取消事件，set 后立即返回 False
        poll_interval: 轮询间隔（秒），决定取消响应延迟上界

    Returns:
        True 表示等待完成；False 表示被 cancel_event 中断
    """
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if cancel_event.is_set():
            return False
        await asyncio.sleep(poll_interval)
    return True
```

**设计要点**：

- 归宿选择 `concurrent.py`（D4），与 `race_first_success` / `cancel_pending` 同模块
- `poll_interval=0.2` 提供 0.2s 取消响应上界，与 `CompositeCancelEvent._POLL_INTERVAL=0.1` 同量级
- 复用方：`LoginSession`（重试等待）、未来 `Engine`、`Scheduler`、`NetworkMonitor` 等
- **为什么不直接用 `CompositeCancelEvent.wait(timeout)`**：`wait` 是同步阻塞，需 `asyncio.to_thread` 包装；轮询版本实现更直观、行为更可预测，且不依赖 `CompositeCancelEvent` 的具体实现

---

## 9. `login_runner.py` 改造（D3）

### 9.1 现状

`execute_login_with_retries` 当前在进程级 `login_once` 模式下做外层重试循环：每次 `orchestrator.submit` → 新 Worker 任务 → 新浏览器。这与 Session 复用目标冲突。

### 9.2 改造

移除外层循环，改为单次 `submit`（重试由 Worker 内的 Session 负责）：

```python
# app/services/login_runner.py

def execute_login_with_retries(runtime_config: RuntimeConfig, logger) -> LoginResult:
    """执行登录（重试由 Worker 内的 LoginSession 负责）。

    Returns:
        LoginResult.SUCCESS — 登录成功
        LoginResult.TEMPORARY_FAILURE — 重试耗尽仍失败
    """
    from app.constants import AUTH_DATA_DIR
    from app.services.login_history_service import LoginHistoryService
    from app.services.login_orchestrator import LoginOrchestrator
    from app.services.profile_service import create_profile_service
    from app.workers.playwright_worker import cleanup_orphan_browsers, get_worker

    profile_service = create_profile_service()
    history = LoginHistoryService(AUTH_DATA_DIR)
    orchestrator = LoginOrchestrator(
        worker_getter=get_worker,
        login_history=history,
        profile_service=profile_service,
    )

    try:
        handle = orchestrator.submit(source="login_once", config=runtime_config)
        ok, msg = handle.result()
        cleanup_orphan_browsers()
        if ok:
            return LoginResult.SUCCESS
        logger.warning("登录失败: {}", msg)
        return LoginResult.TEMPORARY_FAILURE
    finally:
        orchestrator.shutdown(wait=False)
```

**影响**：

- `max_retries` 不再在此处读取，由 `LoginSession` 通过 `runtime_config_to_worker_dict` 注入的 `retry_settings` 读取
- 测试 `tests/test_integration/test_login_once_mode.py`、`tests/test_integration/test_login_integration_extended.py` 需要更新断言（外层不再循环）

---

## 10. Worker._handle_login 改造

```python
# app/workers/playwright_worker.py

async def _handle_login(self, data: dict) -> WorkerResponse:
    """处理登录命令 — 委托给 LoginSession。"""
    from app.services.login_models import AttemptOutcomeType
    from app.services.login_session import LoginSession

    config = data.get("config", {})
    cancel_event: threading.Event | None = data.get("cancel_event")

    if cancel_event is None:
        # 防御性：Worker 不应收到无 cancel_event 的登录命令
        return WorkerResponse(success=False, error="cancel_event 缺失")

    try:
        session = LoginSession(config, cancel_event)
        outcome = await session.run()
        return WorkerResponse(
            success=outcome.type == AttemptOutcomeType.SUCCESS,
            data=outcome.message if outcome.type == AttemptOutcomeType.SUCCESS else None,
            error=outcome.message if outcome.type != AttemptOutcomeType.SUCCESS else None,
        )
    except Exception as e:
        # 程序异常（Attempt 未捕获的）在此兜底，与现有行为一致
        logger.exception("登录执行异常: task_id={}", config.get("task_id", "unknown"))
        return WorkerResponse(success=False, error=str(e))
```

**与原文档差异**：

- 保留外层 `except Exception`（原文档示例丢失，会导致程序异常无响应）
- 增加 `cancel_event is None` 防御性检查
- 保留 `task_id` 日志上下文

---

## 11. 取消事件传递

### 11.1 链路

```
LoginOrchestrator.submit(cancel_event=CompositeCancelEvent)
  → data={"cancel_event": cancel_event}  （跨线程传递，CompositeCancelEvent 基于 threading.Event，安全）
  → Worker._handle_login(data)
  → LoginSession(config, cancel_event)   （Session 持有引用）
  → LoginAttempt(browser, config, cancel_event)  （Attempt 持有引用）
  → BrowserContextManager(config, cancel_event)  ← Session 层单 async with，零改动
```

### 11.2 `CompositeCancelEvent` 语义

- `CompositeCancelEvent` 继承 `threading.Event`，`is_set()` 惰性扫描所有源事件
- `LoginSession` 与 `LoginAttempt` 仅调用 `cancel_event.is_set()`，无需感知组合机制
- `interruptible_sleep` 直接调用 `cancel_event.is_set()`，兼容 `threading.Event` 与 `CompositeCancelEvent`

---

## 12. 与现有代码的关系

### 12.1 `LoginOrchestrator`

**不改动**。仍只负责提交到 Worker、去重/抢占、历史记录。从 Orchestrator 视角，仍是单次 `submit` → 单次 `WorkerResponse`，**不感知** Session 内部重试几次。

### 12.2 `MonitoredPolicy`

**不改动**。仍服务于引擎长期网络监控（`on_network_check` / `on_login_done` 回调）。它看到的"一次登录"= 一次 `submit` = 一次 `WorkerResponse`，与 Session 内部重试次数解耦。

> **注意**：`MonitoredPolicy.on_login_done(success)` 的 `success` 是 Session 最终结果（含 EXHAUSTED）。`MonitoredPolicy.delay_before` 的延迟表与 `LoginRetryPolicy` 的 `interval_seconds` 是**两套独立**的延迟，前者是引擎级、后者是会话级，不叠加。

### 12.3 `BrowserContextManager`

**不改动**。Session 层用单个 `async with BrowserContextManager(...)` 包住重试循环，复用其现有 `__aenter__`（`ensure_browser`）与 `__aexit__`（`_close_browser`）行为。浏览器在 Session 内创建一次、所有 Attempt 复用同一 browser 引用、Session 退出时自动关闭。

### 12.4 `BrowserTaskRunner`

**不改动**。仍由 `LoginAttempt` 调用，返回 `(success, message)`。`LoginAttempt` 负责映射到 `AttemptOutcome`。

### 12.5 `ScriptTask` 路径

**不改动**。`LoginAttempt._execute_script_task` 保持原逻辑，不进入 Session 的浏览器复用循环。

> **设计取舍**：ScriptTask 无浏览器，本就不存在"浏览器创建成本"问题；让 ScriptTask 走 Session 重试会引入不必要的浏览器占位逻辑。ScriptTask 的失败仍由 `login_runner` 外层（移除循环后变为单次）或引擎 `MonitoredPolicy` 处理。

---

## 13. 文件变更与迁移影响

### 13.1 变更表

| 操作 | 文件 | 说明 |
|------|------|------|
| 新增 | `app/services/login_models.py` | `AttemptOutcomeType`、`AttemptOutcome`、`LoginRetryPolicy` |
| 新增 | `app/services/login_session.py` | `LoginSession` |
| 修改 | `app/utils/concurrent.py` | 新增 `interruptible_sleep` |
| 不改动 | `app/utils/browser.py` | `BrowserContextManager` 现有行为已满足 Session 复用（单 `async with` 包住重试循环） |
| 重命名 | `app/services/login_handler.py` → `app/services/login_attempt.py` | `LoginAttemptHandler` → `LoginAttempt`，返回类型改为 `AttemptOutcome` |
| 修改 | `app/services/login_runner.py` | 移除 `execute_login_with_retries` 的外层循环 |
| 修改 | `app/workers/playwright_worker.py` | `_handle_login` 改为调用 `LoginSession` |
| 不改动 | `app/schemas.py` | `RetrySettings.retry_interval` 已存在，无需新增 |
| 不改动 | `app/services/login_orchestrator.py` | 仅 import 路径可能需更新 |
| 不改动 | `app/services/retry_policy.py` | `MonitoredPolicy` 保持不变 |
| 修改 | `tests/` | 更新所有引用 `login_handler` / `LoginAttemptHandler` / 外层重试的测试 |

### 13.2 迁移影响面（已核实）

以下文件引用 `login_handler` / `LoginAttemptHandler`，重命名后**全部需要更新**：

- `app/workers/playwright_worker.py:430` — `from app.services.login_handler import LoginAttemptHandler`
- `app/services/task_executor.py` — 引用 `LoginAttemptHandler`
- `app/utils/browser.py` — 注释中提及
- `tests/test_utils/test_utils.py`
- `tests/test_utils/test_login.py`
- `tests/test_core/test_monitor.py`
- `docs/dev/architecture.md`

以下文件引用 `login_runner` 的外层重试逻辑，**需要更新断言**：

- `app/services/launcher.py:23` — `from app.schemas import ... LoginResult ...`
- `tests/test_app/test_main.py`
- `tests/test_integration/test_login_once_mode.py`
- `tests/test_integration/test_login_integration_extended.py`

### 13.3 迁移路径（建议分 4 步落地，每步可独立验证）

1. **Step 1：基础设施**（无行为变更）
   - 新增 `login_models.py`（`AttemptOutcome` 系列 + `LoginRetryPolicy`）
   - 在 `concurrent.py` 新增 `interruptible_sleep`
   - 单元测试：`AttemptOutcome`、`LoginRetryPolicy.next_delay`、`interruptible_sleep` 取消响应
   - `BrowserContextManager` **不改动**，无需测试改动

2. **Step 2：LoginAttempt 重命名 + 返回类型适配**
   - `login_handler.py` → `login_attempt.py`，`LoginAttemptHandler` → `LoginAttempt`
   - `execute()` 返回 `AttemptOutcome`（内部仍调用原 `attempt_login` 逻辑，包装映射层）
   - 更新所有 import 引用
   - 更新现有测试，确保绿色

3. **Step 3：LoginSession 接入**
   - 新增 `login_session.py`，用单个 `async with BrowserContextManager(...)` 包住重试循环
   - `Worker._handle_login` 改为调用 `LoginSession.run()`
   - 验证所有终态（成功/失败/取消/耗尽/异常）都触发 `__aexit__` → 浏览器关闭
   - 集成测试：mock `LoginAttempt`，验证重试循环、取消响应、EXHAUSTED 终态、浏览器关闭次数

4. **Step 4：login_runner 外层重试移除**
   - 移除 `execute_login_with_retries` 循环
   - 更新 `test_login_once_mode.py` 等测试断言
   - 端到端验证：`login_once` 模式下重试次数 = `RetrySettings.max_retries`（不再乘以外层）

---

## 14. 测试策略

### 14.1 单元测试

**`LoginRetryPolicy`**（`tests/test_services/test_login_models.py`）

- `next_delay(0)` 返回 `interval_seconds`
- `next_delay(max_retries - 1)` 返回 `interval_seconds`
- `next_delay(max_retries)` 返回 `None`
- `from_runtime_config` 正确映射 `RetrySettings`
- `max_retries` 边界裁剪（0 → 1，11 → 10）
- `interval_seconds` 边界裁剪（0 → 1.0）

**`interruptible_sleep`**（`tests/test_utils/test_concurrent.py`）

- 正常等待完成返回 `True`
- 等待中 `set()` cancel_event → 返回 `False`，响应时间 ≤ `poll_interval + ε`
- `seconds=0` 立即返回 `True`
- `seconds` 为负数立即返回 `True`（防御性）

**`AttemptOutcome`**

- `should_retry` 在 `RETRYABLE` 为 `True`，其余终态为 `False`
- `frozen=True` + `slots=True` 不可变

### 14.2 LoginSession 测试（`tests/test_services/test_login_session.py`）

mock `LoginAttempt`，验证：

| 用例 | 期望 |
|------|------|
| 首试即成功 | `SUCCESS`，`attempt.execute` 调用 1 次，`BrowserContextManager.__aexit__` 调用 1 次 |
| 前两次 RETRYABLE，第三次 SUCCESS | `SUCCESS`，调用 3 次，`interruptible_sleep` 调用 2 次，`__aexit__` 调用 1 次 |
| 全部 RETRYABLE，max_retries=3 | `EXHAUSTED`，调用 3 次，`__aexit__` 调用 1 次 |
| 首试 INVALID_CREDENTIAL | `INVALID_CREDENTIAL`，调用 1 次（不重试），`__aexit__` 调用 1 次 |
| 首试 CANCELLED | `CANCELLED`，调用 1 次，`__aexit__` 调用 1 次 |
| 执行中 set cancel_event | `CANCELLED`，`__aexit__` 调用 1 次 |
| 等待中 set cancel_event | `CANCELLED`，`interruptible_sleep` 返回 `False`，`__aexit__` 调用 1 次 |
| `max_retries=1` | 单次尝试，无 `interruptible_sleep` 调用，`__aexit__` 调用 1 次 |
| Attempt 抛出程序异常 | 异常向上传播，不被 Session 捕获，`__aexit__` 仍调用 1 次（exc_type 非 None） |

> **核心断言**：无论哪种终态，`BrowserContextManager.__aexit__`（即 `worker._close_browser`）**必须且仅调用一次**。

### 14.3 LoginAttempt 测试

mock `BrowserContextManager` + `BrowserTaskRunner`，验证：

- BrowserTask 成功 → `SUCCESS`
- BrowserTask 失败（普通 message）→ `RETRYABLE`
- BrowserTask 失败（凭证错误特征）→ `INVALID_CREDENTIAL`（待 §7.4 实现后补充）
- ScriptTask 成功 → `SUCCESS`（不进入浏览器路径）
- ScriptTask 失败 → `RETRYABLE`
- `LoginCancelledError` → `CANCELLED`
- `ConnectionResetError` → `RETRYABLE`
- `PlaywrightTimeoutError` → `RETRYABLE`
- `PlaywrightError("Target closed")` → `RETRYABLE`
- `PlaywrightError("Navigation failed: unknown error")` → 异常向上传播
- `TypeError` → 异常向上传播

### 14.4 集成测试

- **完整链路**：`LoginSession → LoginAttempt → BrowserTaskRunner`（mock Worker）
- **`login_once` 模式**：验证重试次数 = `RetrySettings.max_retries`（不再乘以外层）
- **取消联动**：`CompositeCancelEvent` 在 `LoginOrchestrator` 层 `set()`，Session 在等待中响应

### 14.5 回归测试

- 现有 `tests/test_services/test_login_orchestrator.py` 应保持绿色（Orchestrator 不改动）
- 现有 `tests/test_integration/test_login_flow.py` 应保持绿色
- `tests/test_integration/test_login_once_mode.py` 需更新断言

---

## 15. 风险与权衡

| 风险 | 影响 | 缓解 |
|------|------|------|
| Session 内浏览器崩溃 | Attempt 间状态泄漏 / page 失效 | `TargetClosedError` 捕获为 `RETRYABLE`；下一轮 Attempt 通过 `worker.ensure_browser()`（幂等）刷新 page 引用 |
| 重试次数感知变化 | `MonitoredPolicy` 看到的"一次登录"耗时变长 | 文档说明；`MonitoredPolicy` 的延迟表独立，不叠加 |
| `INVALID_CREDENTIAL` 识别依赖 Portal 特征 | 误判会过早停止重试 | §7.4 预留识别层；保守策略：未识别一律 `RETRYABLE` |
| `login_runner` 外层重试移除 | 旧测试断言失效 | Step 4 集中更新；提供迁移说明 |
| Worker 单例 + 浏览器复用并发安全 | 多 Session 并发时浏览器争用 | `LoginOrchestrator` 已有去重槽（`_slot`），同进程同时只有一个登录会话 |
| 浏览器关闭异常被吞 | `__aexit__` 内 `_close_browser` 抛异常时已 `logger.exception` 记录 | 现有行为，不放大；Session 终态不受关闭异常影响 |

---

## 16. 性能预期

| 场景 | 现状 | 改造后 | 收益 |
|------|------|--------|------|
| 单次登录成功 | 浏览器启动 1–3s + 任务执行 | 同左 | 无变化 |
| 失败重试 3 次 | 3 × (浏览器启动 + 任务) ≈ 9–15s | 1 × 浏览器启动 + 3 × 任务 ≈ 3–6s | **约 50%** |
| `login_once` 失败耗尽 | 外层 3 × 内层 1 = 3 次 | 内层 3 次 | 次数不变，但单次会话内浏览器复用 |

> 实际收益取决于浏览器启动耗时占比；启动越慢收益越大。

---

## 17. 观测性

### 17.1 日志

- `LoginSession`：每次 Attempt 开始 `INFO`（`登录尝试 {i}/{max}`），每次等待 `INFO`（`等待 {delay}s 后重试`），终态 `INFO`/`WARNING`
- `LoginAttempt`：保留现有日志风格（`登录开始`、`登录成功`、`登录失败`、`登录已取消`）
- `EXHAUSTED` 终态：`WARNING` 级别（与用户偏好一致，避免冗余 DEBUG）

### 17.2 状态查询（可选，后续扩展）

`MonitorStatusResponse` 可新增字段：

- `last_session_attempts`：上次会话实际尝试次数
- `last_session_outcome`：上次会话终态类型

本次设计**不**实现，仅预留。

---

## 18. 后续扩展

本架构支持以下扩展，无需改动 Session/Attempt 以外的代码：

- **指数退避**：`LoginRetryPolicy` 新增 `backoff_factor`，`next_delay` 计算调整
- **随机抖动**：`LoginRetryPolicy.next_delay` 内部加随机扰动
- **验证码处理**：在 `LoginAttempt._parse_result` 中识别并返回新终态 `CAPTCHA_REQUIRED`（需扩展 `AttemptOutcomeType`）
- **短信验证**：同上
- **多认证方式**：`LoginSession` 根据 config 选择不同 `LoginAttempt` 子类
- **浏览器跨 Session 复用**：§5.3 选项 2，结合 Worker 常驻浏览器特性

---

## 19. 待确认问题

| # | 问题 | 倾向 |
|---|------|------|
| Q1 | ~~Session 结束是否强制关闭浏览器？~~ | **已决：强制关闭**。Session 层单 `async with BrowserContextManager` 包住重试循环，所有终态（成功/失败/取消/耗尽/异常）都走 `__aexit__` → `worker._close_browser()`。BrowserContextManager 零改动。 |
| Q2 | `INVALID_CREDENTIAL` 识别规则放在 `LoginAttempt` 还是 `BrowserTaskRunner`？ | `LoginAttempt`（避免影响调试会话） |
| Q3 | `interruptible_sleep` 的 `poll_interval` 是否可配置？ | 否，固定 0.2s（足够） |
| Q4 | `AttemptOutcome` 是否需要携带 `attempt_index` 字段供观测？ | 否，日志已包含 |
| Q5 | `LoginSession` 是否需要支持"首试失败后切换任务"（多任务重试）？ | 否，超范围 |
| Q6 | Attempt 间浏览器崩溃重建，刷新 page 引用的逻辑放 `LoginAttempt` 还是 `BrowserContextManager`？ | `LoginAttempt`（Session 持有 browser 引用，Attempt 持有 page 引用，崩溃重建是 Attempt 的执行细节） |
