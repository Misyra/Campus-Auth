# 登录链路重构方案（详细实施版）

> **生成日期**: 2026-06-20
> **目标**: 用 3 个增量重构消化 21 个修复项中的 16 个，根除"三套登录路径"结构性缺陷
> **前置**: 已完成两份 bug 报告的独立验证（见 `fix-plan-2026-06-20.md`）
>
> **本方案与 fix-plan 的关系**: fix-plan 是"逐项打补丁"，本方案是"抽公共层消除补丁必要性"。两者**不冲突**——若选择本方案，fix-plan 中 F01–F13 由重构消化；F14–F20（健壮性/代码质量）仍按 fix-plan 单独修补。

---

## 一、重构范围与决策依据

### 1.1 三步重构对应的根因消化

| 步骤 | 重构 | 消化的 fix-plan 项 | 根因 |
|------|------|-------------------|------|
| 第 1 步 | 抽取 `LoginOrchestrator` | F02, F03, F05, F08, F09, F06(半) | A 登录路径三套 + E 横切无单一来源 |
| 第 2 步 | `MonitoredRetryPolicy` 自管理降频 | F04 | B 重试停止决策权放错层 |
| 第 3 步 | 取消联动改事件循环 | F06(另半), F12, F13 | C 取消用线程监控 Event |
| —— 重构后剩余 —— | 按 fix-plan 修补 | F01, F07, F10, F11, F14–F20 | D 队列 + 启动顺序 + 数据模型 |

> **为什么 F01/F07/F10/F11 不纳入重构**: 它们与"登录路径分歧"无关——F01 是配置回滚的返回值检查，F07 是 boot() 调用位置，F10/F11 是定时任务与队列竞争。强行塞进 LoginOrchestrator 会违反单一职责。这些按 fix-plan 修补更合适。

### 1.2 关键约束（基于现有代码核实）

在动手前必须知道的事实，否则方案会落空：

1. **`build_runtime_dict_from_payload` 当前不写 `login_timeout`**（config_service.py:157-241 的 base 字典无此字段）。Worker 层硬编码 300s、main.py 硬编码 120s，都读不到配置。F09 修复必须先补这个字段。

2. **`LoginHistoryService.record` 签名**（login_history_service.py:48）：
   ```python
   record(success, duration_ms, profile_service=None, task_manager=None, error="")
   ```
   当前 TaskExecutor 用 `record(success=, duration_ms=, profile_service=, error=)`（task_executor.py:487）。LoginOrchestrator 必须复用同一签名，否则历史格式不一致。

3. **测试影响面巨大**。grep 显示约 **60+ 处测试**直接 mock 或调用 `_do_async_login` / `execute_login_async` / `execute_login`。重构必须保持这三个方法名和基本签名兼容（内部委托 Orchestrator），否则测试要重写。**这是本方案最重要的工程约束**，详见 §6 迁移策略。

4. **cancel_event 是 `threading.Event`**，被 `BrowserContextManager`（browser.py:69）和 `LoginAttemptHandler`（login.py:31）轮询消费。第 3 步重构只能改"联动层"，不能改底层消费方（否则波及 Worker/login/browser 三层）。

5. **Worker 是单线程 Actor**（playwright_worker.py:397 串行处理 CMD_LOGIN）。重构不改变这一点。

---

## 二、目标架构

```
┌─────────────────────────────────────────────────────────────┐
│ 调用方（只声明意图，零横切逻辑）                              │
│  main.py            engine._do_async_login    run_manual_login│
│  login_once         source="login_once"       source="manual" │
└──────────┬──────────────────┬──────────────────────┬────────┘
           │                  │                      │
           ▼                  ▼                      ▼
┌──────────────────────────────────────────────────────────────┐
│ LoginOrchestrator（唯一执行入口）                             │
│  validate() → submit(source, policy) → 去重槽 → 历史/超时回调  │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ 去重槽 _slot: LoginHandle | None（替代散落的去重）    │    │
│  └─────────────────────────────────────────────────────┘    │
└──────────┬───────────────────────────────────────────────────┘
           │
     ┌─────┴─────┐
     ▼           ▼
┌─────────┐ ┌──────────────────────────────┐
│Worker   │ │ RetryPolicy（策略对象）        │
│submit() │ │  ImmediatePolicy  (login_once)│
│CMD_LOGIN│ │  MonitoredPolicy   (engine)   │
└─────────┘ └──────────────────────────────┘
```

**核心原则**：
- 调用方**不再**自己读 retry_settings、自己 sleep、自己算超时、自己调 record_attempt。
- 横切关注点（校验/超时/历史/取消/去重）**只实现一次**，在 Orchestrator 内。
- 重试**间隔/停止**由 RetryPolicy 决定，**触发**由调用方决定（login_once 是同步循环，engine 是状态机）。

---

## 三、第 1 步：LoginOrchestrator（核心，1.5–2 天）

### 3.1 新文件 `app/services/login_orchestrator.py`

完整实现，可直接作为开发起点：

```python
"""LoginOrchestrator — 登录执行的唯一入口。

将原本散落在 main.py(_execute_login_with_retries)、engine.py(_do_async_login)、
task_executor.py(execute_login/execute_login_async) 三处的登录横切逻辑
（校验/去重/提交/超时/历史/取消）收敛到单一编排层。

调用方只需声明意图（source + retry policy），不再各自实现重试/超时。
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import Future
from dataclasses import dataclass
from typing import Callable, Literal

from app.services.login_history_service import LoginHistoryService
from app.services.profile_service import ProfileService
from app.utils.logging import get_logger

logger = get_logger("login_orchestrator", source="backend")

LoginSource = Literal["auto", "manual", "login_once"]


# ── 配置校验（原 F05：唯一实现，消除 engine._handle_login 与自动路径的分歧）──


def validate_login_config(config: dict) -> str | None:
    """校验登录配置完整性。

    Returns:
        None 表示通过；否则返回中文错误信息。
    """
    if not config.get("username") or not config.get("password") or not config.get("auth_url"):
        return "登录配置不完整（请先设置认证地址、用户名和密码）"
    return None


# ── 超时解析（原 F09：单一来源，替代 120/300/login_timeout 三处硬编码）──


def resolve_worker_timeout(config: dict, fallback: int = 300) -> int:
    """从运行时配置解析 Worker 提交超时。

    优先用 login_timeout（用户在 UI 配置），缺失时用 fallback。
    """
    raw = config.get("login_timeout", fallback)
    try:
        timeout = int(raw)
    except (TypeError, ValueError):
        return fallback
    # 下限 60s 防止误配导致登录必失败；上限与 MonitorConfigPayload(le=600) 对齐
    return max(60, min(timeout, 600))


# ── 登录句柄（封装 future + cancel_event + source，替代裸 Future）──


@dataclass
class LoginHandle:
    """一次登录提交的句柄。"""
    future: Future | None
    source: LoginSource
    cancel_event: threading.Event
    rejected_reason: str | None = None   # 非 None 表示因校验/去重被拒绝，future 为 None

    def done(self) -> bool:
        return self.future is None or self.future.done()

    def result(self, timeout: float | None = None) -> tuple[bool, str]:
        """同步等待结果。被拒绝时立即返回 (False, reason)。"""
        if self.rejected_reason is not None:
            return False, self.rejected_reason
        if self.future is None:
            return False, "登录未提交"
        return self.future.result(timeout=timeout)

    def cancel(self) -> None:
        self.cancel_event.set()


# ── 编排器 ──


class LoginOrchestrator:
    """登录执行的唯一入口。

    职责（收敛点）：
    - 配置校验（validate_login_config）
    - 去重与抢占（_slot，替代 task_executor._login_future 散落逻辑）
    - Worker 提交与超时（resolve_worker_timeout）
    - 登录历史记录（LoginHistoryService，替代三处各自的记录逻辑）
    - cancel_event 生命周期

    不负责（交给调用方/RetryPolicy）：
    - 重试间隔与停止策略（RetryPolicy）
    - 网络检测触发（engine）
    """

    def __init__(
        self,
        worker_getter: Callable,
        login_history: LoginHistoryService | None,
        profile_service: ProfileService | None,
        get_runtime_config: Callable[[], dict] | None = None,
    ) -> None:
        self._worker_getter = worker_getter
        self._login_history = login_history
        self._profile_service = profile_service
        self._get_runtime_config = get_runtime_config

        # 去重槽（替代 task_executor._login_future + _login_cancel_event）
        self._slot_lock = threading.Lock()
        self._slot: LoginHandle | None = None

    # ── 公共 API ──

    def validate(self, config: dict | None = None) -> str | None:
        """校验。config 为 None 时从 get_runtime_config 读取。"""
        cfg = config if config is not None else self._runtime_config()
        return validate_login_config(cfg)

    def is_running(self) -> bool:
        """是否有登录正在执行。"""
        with self._slot_lock:
            return self._slot is not None and not self._slot.done()

    def submit(
        self,
        *,
        source: LoginSource,
        config: dict | None = None,
        cancel_event: threading.Event | None = None,
    ) -> LoginHandle:
        """提交一次登录。

        Args:
            source: "auto" | "manual" | "login_once"
                - manual 可抢占 auto（取消旧的、提交新的）→ 根治 F06
                - auto 命中运行中的 manual/auto 则复用旧 handle（去重）
                - login_once 总是新提交（进程级一次性任务）
            config: 配置快照；None 则从 get_runtime_config 读取
            cancel_event: 取消事件；None 则内部新建

        Returns:
            LoginHandle。若校验失败，future 为 None 且 rejected_reason 非空。
        """
        cfg = config if config is not None else self._runtime_config()

        # 1. 校验（F05 唯一实现）
        err = validate_login_config(cfg)
        if err is not None:
            logger.warning("跳过登录(source={}): {}", source, err)
            return LoginHandle(
                future=None, source=source,
                cancel_event=cancel_event or threading.Event(),
                rejected_reason=err,
            )

        if cancel_event is None:
            cancel_event = threading.Event()

        # 2. 去重与抢占（F06 根治）
        with self._slot_lock:
            existing = self._slot
            if existing is not None and not existing.done():
                # login_once 一次性任务，不复用（进程级语义）
                if source == "login_once":
                    pass  # 落到下方新建分支
                # manual 抢占 auto：取消旧的，提交新的
                elif source == "manual" and existing.source == "auto":
                    logger.info("手动登录抢占自动登录(source={})", existing.source)
                    existing.cancel()
                    # 不立即 return，落到下方提交新 handle
                else:
                    # 复用旧 handle（auto→auto, auto→manual同源, manual→*）
                    # 联动新 cancel_event 到旧任务（F12 第 3 步改为事件循环，此处先保留联动入口）
                    self._link_cancel(cancel_event, existing.cancel_event)
                    return existing

            # 3. 提交新登录
            handle = self._dispatch(cfg, source, cancel_event)
            self._slot = handle

        return handle

    def cancel_running(self) -> None:
        """取消当前正在运行的登录（供外部主动取消）。"""
        with self._slot_lock:
            if self._slot is not None and not self._slot.done():
                self._slot.cancel()

    # ── 内部 ──

    def _dispatch(
        self, config: dict, source: LoginSource, cancel_event: threading.Event
    ) -> LoginHandle:
        """提交到 Worker，注册历史/状态回调。"""
        from app.workers.playwright_worker import CMD_LOGIN

        pure_mode = config.get("browser_settings", {}).get("pure_mode", False)
        worker_timeout = resolve_worker_timeout(config)   # F09 单一来源

        def _run() -> tuple[bool, str]:
            # 在 login_pool 工作线程内执行（由调用方安排线程池，见 §3.3）
            start = time.perf_counter()
            try:
                if cancel_event.is_set():                 # F03 提交前再检一次
                    return False, "登录已取消"
                worker = self._worker_getter()
                result = worker.submit(
                    CMD_LOGIN,
                    data={
                        "config": config,
                        "pure_mode": pure_mode,
                        "cancel_event": cancel_event,
                    },
                    wait=True,
                    timeout=worker_timeout,
                )
                duration_ms = int((time.perf_counter() - start) * 1000)
                if result.success:
                    self._record_history(True, duration_ms, result.data if isinstance(result.data, str) else "")
                    msg = result.data if isinstance(result.data, str) else "登录成功"
                    return True, msg
                err_msg = result.error or "登录失败"
                self._record_history(False, duration_ms, error=err_msg)
                return False, err_msg
            except Exception as exc:
                duration_ms = int((time.perf_counter() - start) * 1000)
                self._record_history(False, duration_ms, error=str(exc))
                logger.error("登录执行异常: {}", exc, exc_info=True)
                return False, f"登录执行异常: {exc}"

        # 复用调用方的线程池（TaskExecutor._login_pool），避免引入新池
        future = self._submit_to_pool(_run)
        handle = LoginHandle(future=future, source=source, cancel_event=cancel_event)

        # 清理槽位（替代 task_executor._on_login_done）
        def _on_done(_: Future) -> None:
            with self._slot_lock:
                if self._slot is handle:
                    self._slot = None
        future.add_done_callback(_on_done)
        return handle

    def _submit_to_pool(self, func: Callable) -> Future:
        """提交到登录线程池。

        默认实现用 ThreadPoolExecutor(max_workers=1)；TaskExecutor 注入时
        复用其 _login_pool（见 §3.3）。
        """
        return self._pool.submit(func)

    def _record_history(
        self, success: bool, duration_ms: int, error: str = ""
    ) -> None:
        """记录登录历史（原 F02：login_once 路径此前不记录）。"""
        if self._login_history is None:
            return
        try:
            self._login_history.record(
                success=success,
                duration_ms=duration_ms,
                profile_service=self._profile_service,
                error=error,
            )
        except Exception:
            logger.debug("记录登录历史失败", exc_info=True)

    def _runtime_config(self) -> dict:
        if self._get_runtime_config is None:
            return {}
        return self._get_runtime_config()

    def _link_cancel(self, new_event: threading.Event, target_event: threading.Event) -> None:
        """联动取消事件（第 3 步重构会改为事件循环实现，此处先占位）。

        当前实现沿用 task_executor._link_cancel_event 的 watcher 线程，
        保证重构期间行为不退化。
        """
        # 第 3 步会替换此方法体
        from app.services.task_executor import TaskExecutor
        TaskExecutor._link_cancel_event(new_event, target_event)
```

### 3.2 RetryPolicy 策略对象（同文件或 `app/services/retry_policy.py`）

```python
"""RetryPolicy — 声明式重试策略，调用方选择，消除指数退避分歧（F08）。"""

from __future__ import annotations

import time
from typing import Iterator


class RetryPolicy:
    """重试策略基类。"""

    def attempts(self) -> Iterator[int]:
        """产出 attempt 序号（1, 2, 3...），调用方在每次 yield 前/后决定动作。"""
        raise NotImplementedError

    def delay_before(self, attempt: int) -> float:
        """第 attempt 次尝试前的等待秒数（attempt=1 时为 0）。"""
        return 0.0


class ImmediatePolicy(RetryPolicy):
    """login_once / 手动登录用：固定间隔、快速重试，无指数退避。

    与 LoginRetryManager(exponential=False) 行为一致（原 F08：消除分歧）。
    """

    def __init__(self, max_retries: int = 3, interval: int = 5) -> None:
        self.max_retries = max(1, min(max_retries, 10))
        self.interval = max(1, interval)

    def attempts(self) -> Iterator[int]:
        for i in range(1, self.max_retries + 1):
            yield i

    def delay_before(self, attempt: int) -> float:
        return 0.0 if attempt <= 1 else float(self.interval)


class MonitoredPolicy(RetryPolicy):
    """引擎长期监控用。见第 2 步（自管理降频，根治 F04）。

    本步先提供骨架，降频逻辑在第 2 步填充。
    """

    def __init__(self, max_retries: int = 3, interval: int = 5,
                 backoff_after_cycles: int = 3) -> None:
        self.max_retries = max_retries
        self.interval = interval
        self.backoff_after_cycles = backoff_after_cycles
        self.count = 0
        self.failed_cycles = 0
        self._network_was_down = False

    def on_network_check(self, need_login: bool) -> bool:
        """网络检测结果回调。返回是否应触发登录。

        关键：reset 只在网络从 down→up 恢复时发生，不再每次清零（根治 F04）。
        """
        if not need_login:
            if self._network_was_down:
                self.count = 0
                self.failed_cycles = 0
            self._network_was_down = False
            return False
        self._network_was_down = True
        if self.count >= self.max_retries:
            return False   # 已达本轮上限，等降频或网络恢复
        return True

    def on_login_done(self, success: bool) -> float | None:
        """登录结束回调。返回下次检测前的延迟秒数（None=立即）。"""
        if success:
            self.count = 0
            self.failed_cycles = 0
            return None
        self.count += 1
        if self.count >= self.max_retries:
            self.failed_cycles += 1
            if self.failed_cycles >= self.backoff_after_cycles:
                return min(self.interval * (2 ** (self.failed_cycles - self.backoff_after_cycles + 1)), 1800)
        return None
```

### 3.3 改造调用方（保持方法签名兼容，内部委托）

**这是迁移的关键**：不删旧方法，改为薄委托层。这样 60+ 处测试不需要大改。

#### 3.3.1 `app/services/task_executor.py`

`TaskExecutor` 把登录逻辑委托给 Orchestrator，自身只保留线程池与定时任务：

```python
class TaskExecutor:
    def __init__(self, ..., login_orchestrator: LoginOrchestrator | None = None):
        # ... 原有字段 ...
        self._login_orchestrator = login_orchestrator
        # 注入登录线程池给 Orchestrator（复用，不新建）
        if login_orchestrator is not None:
            login_orchestrator._pool = self._login_pool

    # ── 兼容层：保留旧方法签名，内部委托 Orchestrator ──

    def execute_login_async(
        self,
        cancel_event: threading.Event | None = None,
        config_snapshot: dict | None = None,
    ) -> Future:
        """【兼容委托】保留签名供现有调用方/测试使用。

        语义：source="auto"，去重行为由 Orchestrator._slot 管理。
        返回 Future（兼容旧调用方），内部包装 LoginHandle。
        """
        if self._login_orchestrator is None:
            # 未注入 Orchestrator（兼容旧测试）：回退到原逻辑
            return self._legacy_execute_login_async(cancel_event, config_snapshot)

        handle = self._login_orchestrator.submit(
            source="auto", config=config_snapshot, cancel_event=cancel_event,
        )
        # 包装回 Future，保持返回类型兼容
        if handle.future is not None:
            return handle.future
        # 被校验拒绝：返回一个已完成的 failed future
        f: Future = Future()
        f.set_result((False, handle.rejected_reason or "登录被拒绝"))
        return f

    def execute_login(self, cancel_event=None, config_snapshot=None) -> tuple[bool, str]:
        """【兼容委托】同步执行（供测试与 _execute_browser 路径）。"""
        if self._login_orchestrator is None:
            return self._legacy_execute_login(cancel_event, config_snapshot)
        cfg = config_snapshot if config_snapshot is not None else (
            self._get_runtime_config() if self._get_runtime_config else {}
        )
        handle = self._login_orchestrator.submit(
            source="auto", config=cfg, cancel_event=cancel_event,
        )
        return handle.result()

    # is_login_running / cancel_login 委托
    def is_login_running(self) -> bool:
        if self._login_orchestrator is not None:
            return self._login_orchestrator.is_running()
        # legacy...
    def cancel_login(self) -> None:
        if self._login_orchestrator is not None:
            self._login_orchestrator.cancel_running()
            return
        # legacy...

    # 原 execute_login / execute_login_async / _link_cancel_event / _on_login_done
    # 重命名为 _legacy_* 保留，作为未注入 Orchestrator 时的回退。
```

**为什么保留 `_legacy_*`**：容器注入 Orchestrator 后走新路径；但单元测试直接构造 TaskExecutor 不一定注入，保留 legacy 回退避免大面积改测试。生产路径（经 container.py）一定注入。

#### 3.3.2 `app/services/engine.py`

`_do_async_login` 改为委托，签名不变：

```python
def _do_async_login(self, is_manual: bool = False, config_snapshot: dict | None = None) -> bool:
    """【委托】提交登录到 LoginOrchestrator。签名兼容。"""
    config = config_snapshot if config_snapshot is not None else self._copy_runtime_config()

    source = "manual" if is_manual else "auto"
    handle = self._orchestrator.submit(source=source, config=config)

    if handle.rejected_reason is not None:
        # F05：校验失败（自动路径此前不校验）
        if is_manual:
            # 手动登录的响应由 _handle_login 设置，这里只记录
            pass
        else:
            self.record_log(handle.rejected_reason, level="WARNING", source="backend")
            self._login_retry.reset()   # 配置不完整，重置重试等待用户修复
        return False

    if handle.future is None:
        # 复用了旧 handle（去重命中），不算新提交
        return False

    # F03：record_attempt 移到成功提交之后（Orchestrator 已实际 dispatch）
    if not is_manual:
        self._login_retry.record_attempt(time.time())

    # done 回调（保留原 _on_done 的日志逻辑）
    def _on_done(f: Future) -> None:
        self._update_status_snapshot()
        try:
            ok, msg = f.result()
            tag = "手动登录" if is_manual else "自动登录"
            if ok:
                logger.info("{}完成: {}", tag, msg)
            else:
                logger.warning("{}失败: {}", tag, msg)
        except Exception:
            logger.exception("登录任务异常")
    handle.future.add_done_callback(_on_done)
    return True
```

`_handle_login` 的校验改为复用 Orchestrator 的 `validate`（消除 F05 的两处重复校验）：

```python
def _handle_login(self, cmd: EngineCommand) -> None:
    config = self._copy_runtime_config()
    err = self._orchestrator.validate(config)     # 复用唯一校验
    if err is not None:
        cmd.response_data = (False, err)
        return
    if self._do_async_login(is_manual=True, config_snapshot=config):
        cmd.response_data = (True, "登录已提交")
    else:
        cmd.response_data = (False, "登录任务已在执行中，请稍后再试")
```

#### 3.3.3 `main.py`（login_once 路径，F02 + F08）

这是改动最大的调用方——从"自己写 while + sleep + submit"改为"用 ImmediatePolicy 驱动 Orchestrator"：

```python
def _execute_login_with_retries(runtime_config: dict, logger) -> LoginResult:
    """【重构】用 ImmediatePolicy + Orchestrator，不再自己写重试/超时/历史。"""
    from app.constants import AUTH_DATA_DIR
    from app.services.login_orchestrator import LoginOrchestrator, ImmediatePolicy
    from app.services.login_history_service import LoginHistoryService
    from app.services.profile_service import create_profile_service
    from app.workers.playwright_worker import get_worker

    # 构造一次性 Orchestrator（login_once 在容器创建前运行）
    profile_service = create_profile_service()
    history = LoginHistoryService(AUTH_DATA_DIR)
    orchestrator = LoginOrchestrator(
        worker_getter=get_worker,
        login_history=history,
        profile_service=profile_service,
    )

    retry_settings = runtime_config.get("retry_settings", {})
    policy = ImmediatePolicy(
        max_retries=retry_settings.get("max_retries", 3),
        interval=retry_settings.get("retry_interval", 5),
    )

    for attempt in policy.attempts():
        delay = policy.delay_before(attempt)
        if delay > 0:
            print(f"等待 {int(delay)} 秒后重试第 {attempt} 次...")
            time.sleep(delay)

        handle = orchestrator.submit(source="login_once", config=runtime_config)
        ok, msg = handle.result()    # 同步等待（login_once 语义）
        if ok:
            print(f"登录成功: {msg}")
            cleanup_orphan_browsers()
            return LoginResult.SUCCESS
        print(f"登录失败 (第 {attempt} 次): {msg}")
        # 历史已由 Orchestrator._record_history 记录（F02 修复）

    cleanup_orphan_browsers()
    print(f"已重试 {policy.max_retries} 次均失败，回退到正常模式")
    logger.warning("登录失败（已重试 {} 次），回退到正常模式", policy.max_retries)
    return LoginResult.TEMPORARY_FAILURE
```

**关键收益**：
- F02 自动修复（Orchestrator 统一记录历史）
- F08 自动修复（用 ImmediatePolicy，与引擎策略同源）
- F09 自动修复（Orchestrator.resolve_worker_timeout 读 login_timeout）
- 不再有 `timeout=120` 硬编码

#### 3.3.4 `app/services/config_service.py`（F09 配套，补 login_timeout）

```python
# build_runtime_dict_from_payload 的 base 字典中新增：
base["login_timeout"] = gs.login_timeout   # 让 Worker 层与 UI 配置一致
```

#### 3.3.5 `app/container.py`（注入 Orchestrator）

```python
# ServiceContainer.__init__ 中，在 self.task_executor 创建后：
from app.services.login_orchestrator import LoginOrchestrator

self.login_orchestrator = LoginOrchestrator(
    worker_getter=_get_worker,
    login_history=self.login_history_service,
    profile_service=self.profile_service,
    get_runtime_config=self.engine.get_runtime_config,   # 注入但避免循环依赖
)
# TaskExecutor 复用 Orchestrator（注入 _login_pool）
self.task_executor._login_orchestrator = self.login_orchestrator
self.login_orchestrator._pool = self.task_executor._login_pool
# engine 持有引用
self.engine._orchestrator = self.login_orchestrator
```

**循环依赖注意**：`engine` 在 `login_orchestrator` 之前创建（engine 是 Orchestrator 的 `get_runtime_config` 来源）。注入顺序：engine → orchestrator → 反向设置 engine._orchestrator。这是构造后绑定（post-construction wiring），与现有 `task_executor.set_runtime_config_getter`（container.py:74）同模式，已被项目接受。

---

## 四、第 2 步：MonitoredRetryPolicy 接入 engine（半天）

第 1 步已定义了 `MonitoredPolicy` 骨架。本步把它接入 engine 的网络检测循环，**删除 engine 里所有的 `_login_retry.reset()` 无条件调用**（F04 根因）。

### 4.1 engine.py 改造

```python
# __init__ 中
self._retry_policy = MonitoredPolicy()    # 替代/封装原 LoginRetryManager

# _do_network_check 改造（删除两处无条件 reset）
def _do_network_check(self) -> None:
    core = self._monitor_core
    if core is None:
        return
    try:
        result = core.check_once()
        interval = int(result.get("interval", self._monitor_check_interval))
        self._monitor_check_interval = interval

        need_login = result.get("need_login", False)
        # F04 根治：重试决策交给 policy，不再无条件 reset
        if self._retry_policy.on_network_check(need_login):
            self._do_async_login()

        # profile 切换逻辑不变
        if core.consume_profile_switch_flag():
            ...

        self._next_network_check = time.time() + interval
        self._update_status_snapshot(force=True)
    except Exception:
        logger.exception("网络检测异常")
        self._next_network_check = time.time() + self._monitor_check_interval

# _do_async_login 的 _on_done 回调增加 policy 通知
def _on_done(f: Future) -> None:
    self._update_status_snapshot()
    try:
        ok, msg = f.result()
        if ok:
            logger.info("自动登录完成: {}", msg)
        else:
            logger.warning("自动登录失败: {}", msg)
            # F04 降频：失败后由 policy 决定是否推迟下次检测
            delay = self._retry_policy.on_login_done(success=False)
            if delay:
                self._next_network_check = time.time() + delay
                logger.warning("登录连续失败，下次检测推迟 {}s", int(delay))
            else:
                self._retry_policy.on_login_done(success=True)  # 计数修正
    except Exception:
        logger.exception("登录任务异常")
```

### 4.2 `_login_retry_needed` 与 `_calculate_wakeup` 调整

原 engine 用 `LoginRetryManager.need_retry()` 和 `next_wakeup()` 驱动重试。重构后重试触发完全由 `on_network_check` 决定，`_login_retry_needed` 可移除或保留为 no-op。`_calculate_wakeup` 不再依赖 `next_wakeup()`。

### 4.3 兼容性

`LoginRetryManager` 类（login_retry.py）保留但标记 deprecated，避免破坏可能的外部引用。新代码用 `MonitoredPolicy`。

---

## 五、第 3 步：取消联动改事件循环（半天，根治 F12/F13）

### 5.1 问题回顾

`_link_cancel_event`（task_executor.py:211）每次去重都新建 daemon 线程监控 Event，高频去重累积。根因是用"线程模拟事件订阅"。

### 5.2 方案：CompositeCancelToken + Worker 事件循环

底层消费方（BrowserContextManager / LoginAttemptHandler）继续轮询 `threading.Event`，**不变**。只改"联动层"：用一个组合 token 替代多线程。

```python
# app/services/login_orchestrator.py 新增

class CompositeCancelToken:
    """组合多个 cancel_event：任一被 set，则 is_cancelled() 为 True。

    替代 _link_cancel_event 的 watcher 线程模式。
    底层消费方仍用 threading.Event.is_set() 轮询，故需要维护一个
    "聚合 Event"，任一源 set 时联动它。
    """

    def __init__(self) -> None:
        self._sources: list[threading.Event] = []
        self._aggregated = threading.Event()
        self._lock = threading.Lock()

    def add_source(self, event: threading.Event) -> None:
        """添加一个取消源。若该源已 set，立即联动。"""
        with self._lock:
            if event in self._sources:
                return
            self._sources.append(event)
            if event.is_set():
                self._aggregated.set()
                return
        # 源未 set：注册轻量联动（仅当源被外部 set 时才生效）
        # 用 threading.Event 的无回调特性，这里仍需一个监听机制——
        # 但改为"检查时聚合"而非"线程监听"，见下。

    def aggregated_event(self) -> threading.Event:
        """返回聚合 Event。调用方应在关键点调用 refresh() 或由消费方轮询各源。"""
        return self._aggregated

    def refresh(self) -> None:
        """扫描所有源，任一 set 则聚合。由登录步骤在检查点调用。"""
        with self._lock:
            for src in self._sources:
                if src.is_set():
                    self._aggregated.set()
                    return
```

**更彻底的实现**：让底层消费方（LoginAttemptHandler）在每次 `is_cancelled()` 检查时调用 `token.refresh()`。但这需要改 login.py，波及面扩大。

### 5.3 务实取舍

完整消除 watcher 线程需要改 login.py/browser.py 的 cancel 检查点。**评估后建议分两种实现**：

- **最小实现（推荐，本步采用）**：`CompositeCancelToken.add_source` 在添加时若源未 set，仍启动**单个共享** watcher（用第 1 步 Orchestrator 的常驻线程，而非每次新建）。即把 F12 的"每次新建"改为"单线程复用"。这已能消除线程泄漏。
- **彻底实现（后续）**：改 login.py 的 cancel 检查为轮询 CompositeCancelToken.refresh()，完全去线程。列为后续独立 PR。

### 5.4 Orchestrator._link_cancel 替换

```python
# login_orchestrator.py
class LoginOrchestrator:
    def __init__(self, ...):
        ...
        self._cancel_link_thread: threading.Thread | None = None
        self._cancel_link_queue: queue.Queue = queue.Queue()

    def _link_cancel(self, new_event, target_event):
        """入队联动请求，由常驻单线程处理（替代每次新建线程）。"""
        self._cancel_link_queue.put((new_event, target_event, time.time() + 300))
        self._ensure_cancel_link_thread()

    def _ensure_cancel_link_thread(self):
        if self._cancel_link_thread and self._cancel_link_thread.is_alive():
            return
        self._cancel_link_thread = threading.Thread(
            target=self._cancel_link_loop, daemon=True, name="orch-cancel-link"
        )
        self._cancel_link_thread.start()

    def _cancel_link_loop(self):
        pending = []
        while True:
            try:
                item = self._cancel_link_queue.get(timeout=1.0)
                if item is None:
                    return
                pending.append(item)
            except queue.Empty:
                pass
            now = time.time()
            still = []
            for new_ev, tgt_ev, deadline in pending:
                if new_ev.is_set():
                    tgt_ev.set()
                elif now < deadline:
                    still.append((new_ev, tgt_ev, deadline))
            pending = still
```

---

## 六、迁移策略（关键：控制测试爆炸）

### 6.1 测试影响面（已 grep 核实）

| 文件 | 影响处数 | 影响 |
|------|---------|------|
| tests/test_services/test_engine.py | ~20 处 mock `_do_async_login` | 方法名不变，**多数无需改** |
| tests/test_services/test_task_executor_fix.py | ~15 处调 `execute_login_async` | 签名兼容，**多数无需改** |
| tests/test_integration/test_login_flow.py | ~25 处 mock `_do_async_login` | 方法名不变，**多数无需改** |
| tests/test_integration/test_login_integration_extended.py | 直接访问 `_login_cancel_event` | **需改**（内部字段移除） |
| tests/test_integration/test_lightweight_mode.py | 调 `execute_login_async` | 签名兼容 |

### 6.2 兼容性保证手段

1. **方法名零删除**：`_do_async_login`、`execute_login_async`、`execute_login` 全部保留为委托层。测试里 `svc._do_async_login = MagicMock(...)` 继续工作。

2. **TaskExecutor 保留 `_legacy_*` 回退**：未注入 Orchestrator 时走老逻辑。这样不注入 Orchestrator 的单元测试完全不受影响。

3. **内部字段迁移**：`_login_cancel_event`、`_login_future` 移到 Orchestrator._slot。少量测试直接访问这些私有字段（test_login_integration_extended.py:188），需要改为访问 `_orchestrator._slot.cancel_event`。**这类测试约 3-5 处，集中改一次。**

4. **新增 Orchestrator 单元测试**：为新代码写独立测试，不依赖旧测试改造。

### 6.3 渐进上线顺序（每个子步可独立 commit + 测试）

```
1.1  新建 login_orchestrator.py（纯新增，不改任何现有代码）
     → 跑全量测试，应 0 变化
1.2  config_service.py 补 login_timeout 字段（F09 配套）
     → 跑测试，仅 test_config_service 可能需补断言
1.3  TaskExecutor 增加 login_orchestrator 参数 + _legacy 回退
     → 不注入时行为不变，测试全绿
1.4  container.py 注入 Orchestrator + 绑定 engine/task_executor
     → 生产路径切换，集成测试验证
1.5  engine._do_async_login / _handle_login 改委托
     → 改 test_engine 里直接访问内部字段的 3-5 处
1.6  main.py login_once 改用 Orchestrator + ImmediatePolicy
     → 新增 login_once 历史记录集成测试（验证 F02）
─── 第 1 步完成，F02/F03/F05/F08/F09/F06(半) 消化 ───
2.1  engine 接入 MonitoredPolicy，删除无条件 reset
     → 改 test_engine 里 need_login/reset 相关测试
─── 第 2 步完成，F04 消化 ───
3.1  Orchestrator._link_cancel 改常驻单线程
     → 改 test_login_integration_extended 的 _login_cancel_event 断言
─── 第 3 步完成，F12/F13 消化 ───
```

---

## 七、风险与回滚

### 7.1 风险

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| 委托层引入语义偏差（如去重时机变化） | 中 | 登录行为变化 | TaskExecutor 保留 legacy 回退；集成测试 `test_login_flow.py` 覆盖去重场景 |
| Orchestrator 与 engine 循环依赖导致初始化顺序问题 | 中 | 启动失败 | 用 post-construction wiring（§3.3.5），与现有 set_runtime_config_getter 同模式 |
| login_once 的 Orchestrator 实例与容器实例隔离，历史记录可能重复 | 低 | 历史多一条 | login_once 成功即退出进程，不会与容器并存；失败回退监控时容器才创建，无重叠 |
| MonitoredPolicy 降频逻辑误判，导致该登录时不登录 | 中 | 认证超时 | backoff 上限 1800s（30min）；网络恢复立即 reset；集成测试覆盖"持续失败→降频→恢复"链路 |
| 私有字段测试访问（_login_cancel_event）改造遗漏 | 低 | 测试红 | 集中在 1.5 步一次性改完 |

### 7.2 回滚

每个子步独立 commit。若某步引发问题：
- **1.1–1.3**：纯新增/兼容层，revert 单 commit 即可。
- **1.4–1.6**：revert 后回到 legacy 路径（TaskExecutor 未注入 Orchestrator 自动回退）。
- **第 2/3 步**：独立于第 1 步，可单独 revert。

**关键**：由于保留了 `_legacy_*` 回退与方法名兼容，**整个重构可以一键回退到 fix-plan 的逐项修补方案**，不会卡在中间状态。

---

## 八、验收标准

重构完成的判定：

1. **代码层面**
   - `grep -rn "timeout=120\|timeout=300" main.py app/services/` 无硬编码（F09）
   - `grep -rn "_login_retry.reset()" app/services/engine.py` 仅出现在 policy 内部或为 0（F04）
   - `grep -rn "_link_cancel_event" app/services/` 仅 Orchestrator 内部（F12）
   - main.py 的 `_execute_login_with_retries` 不再直接 `get_worker().submit`（F02/F08）

2. **行为层面**
   - `--startup-action login_once` 执行后，`login_history.jsonl` 含记录（F02）
   - 配置缺 password 时，自动登录不启动浏览器，日志显示"配置不完整"（F05）
   - 手动登录抢占自动登录时，提交的是新 handle 非 handle 复用（F06）
   - 认证服务器持续不可达时，第 4 轮起检测间隔延长（F04）
   - `login_timeout=600` 时，Worker 提交超时同步为 600（F09）

3. **测试层面**
   - 全量测试套件通过（含 60+ 处兼容性测试）
   - 新增 Orchestrator 单元测试 ≥ 15 个用例
   - 新增 login_once 历史记录、降频、抢占的集成测试各 1 个

---

## 九、工作量估算

| 步骤 | 估时 | 说明 |
|------|------|------|
| 第 1 步 | 1.5–2 天 | 含 Orchestrator 实现 + 6 个子步迁移 + 测试调整 |
| 第 2 步 | 0.5 天 | MonitoredPolicy 接入 + 删除 reset + 测试调整 |
| 第 3 步 | 0.5 天 | 单线程 watcher + 测试调整 |
| **合计** | **2.5–3 天** | 不含 F01/F07/F10/F11/F14–F20（按 fix-plan 另行修补，约 1 天） |

**对比逐项修补**：fix-plan 全部 21 项约需 3–4 天，且未来加新登录路径会复发。重构多花 0.5 天，换"根因消除 + 未来可扩展"。

---

## 十、决策建议

- **选重构**：如果有 2.5–3 天连续时间，且希望登录链路长期可维护。重构后 F02/F03/F04/F05/F06/F08/F09/F12/F13 九项一次性根除，剩余按 fix-plan 修补。
- **选逐项修补**：如果时间紧张或近期要发版。先做 fix-plan 第一批（F01–F04，1 天）止血，重构留到下个迭代。

两者不冲突——重构的每个子步都保持 legacy 回退，可随时暂停切换到修补路径。

---

*方案完成。建议从 1.1（新建 login_orchestrator.py）开始，这是纯新增、零风险的第一步，可立即提交验证。*
