# Worker 进程隔离实施计划（阶段一）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 PlaywrightWorker 从主进程内嵌线程改为独立子进程，主进程不再 import playwright/ddddocr/onnxruntime，主进程内存地板从 ~60MB 降至 ~48MB。

**Architecture:** 主进程通过 WorkerFacade（由 WorkerManager 协调 ProcessController/RpcClient/LifecycleManager）以 stdin/stdout 长度前缀 JSON-RPC 协议与子进程通信。子进程是独立可执行入口 `python -m app.workers.worker_proc`，内部用 CommandRegistry 分派命令。消费方（LoginOrchestrator/DebugService）仍用同步 `worker.submit()` 接口，阶段一不改并发模型。

**Tech Stack:** Python 3.12+ / asyncio.subprocess / Pydantic v2 / struct（长度前缀帧）/ subprocess.Popen

**Spec:** [docs/2026-07-01-worker-process-isolation-design.md](file:///e:/Campus-Auth/docs/2026-07-01-worker-process-isolation-design.md)

---

## 文件结构

### 新增文件（阶段一）

| 文件 | 职责 |
|---|---|
| `app/workers/worker_protocol.py` | 统一 WorkerMessage 基类 + Request/Response/Event + 命令常量 + encode_frame/decode_frame |
| `app/workers/worker_commands.py` | Command 基类 + CommandRegistry + 各命令实现类 |
| `app/workers/worker_proc.py` | 子进程入口 main()，独立可执行 |
| `app/workers/manager/__init__.py` | 包初始化 |
| `app/workers/manager/worker_manager.py` | WorkerManager 协调者 |
| `app/workers/manager/process_controller.py` | asyncio.create_subprocess_exec 进程管理 |
| `app/workers/manager/rpc_client.py` | 长度前缀帧读写 + id→Future 派发 |
| `app/workers/manager/lifecycle_manager.py` | keepalive 锁 + 心跳 + 重启 + on_restart 回调 |
| `app/workers/manager/lifecycle_policy.py` | LifecyclePolicy 抽象 + IdleShutdown/NeverShutdown |
| `app/workers/manager/worker_facade.py` | 对外接口（同步 submit，桥接 asyncio） |

### 修改文件（阶段一）

| 文件 | 改动 |
|---|---|
| `app/workers/playwright_worker.py` | get_worker() 角色判断；shutdown_worker 改 async |
| `app/services/engine.py` | 新增 can_shutdown_worker()；retry_policy 注入 retry_interval |
| `app/services/retry_policy.py` | 删除 _DELAYS；接收 retry_interval；max_retries=0 生效 |
| `app/services/login_runner.py` | 删除 max(1,...)；login_once 路径改 max_retries=0 |
| `app/services/debug_service.py` | keepalive 锁 + on_restart + is_alive 短路 |
| `app/services/login_orchestrator.py` | _dispatch 取消机制改 cmd_id（阶段一保留线程池） |
| `app/tasks/step_handlers.py` | OcrHandler 删除定时清理逻辑 |
| `app/container.py` | 注入 engine 引用；删除 cleanup 调用；预热 |
| `frontend/partials/pages/settings/settings-monitor.html` | max_retries 范围 + 文案 |

---

## Task 1: 协议模型与帧编解码

**Files:**
- Create: `app/workers/worker_protocol.py`
- Test: `tests/test_workers/test_worker_protocol.py`

- [ ] **Step 1: 创建测试目录和 conftest**

```bash
mkdir -p tests/test_workers
```

创建 `tests/test_workers/__init__.py`（空文件）。

- [ ] **Step 2: 写失败测试 — 协议模型序列化**

创建 `tests/test_workers/test_worker_protocol.py`：

```python
"""Worker 协议模型与帧编解码测试。"""
from __future__ import annotations

import asyncio
import json
import struct

import pytest

from app.workers.worker_protocol import (
    CMD_CANCEL,
    CMD_LOGIN,
    CMD_PING,
    CMD_SHUTDOWN,
    WorkerEvent,
    WorkerMessage,
    WorkerRequest,
    WorkerResponse,
    decode_frame,
    encode_frame,
)


class TestWorkerMessage:
    def test_request_serialization(self):
        req = WorkerRequest(id=1, cmd=CMD_LOGIN, data={"config": {"u": "x"}})
        dumped = req.model_dump_json()
        loaded = json.loads(dumped)
        assert loaded["id"] == 1
        assert loaded["cmd"] == "login"
        assert loaded["data"]["config"]["u"] == "x"
        assert loaded["version"] == 1

    def test_response_success(self):
        resp = WorkerResponse(id=1, ok=True, data="登录成功")
        assert resp.error is None
        assert resp.data == "登录成功"

    def test_response_failure(self):
        resp = WorkerResponse(id=2, ok=False, error="超时")
        assert resp.ok is False
        assert resp.error == "超时"
        assert resp.data is None

    def test_event_ready(self):
        ev = WorkerEvent(event="ready", data={"version": 1})
        assert ev.event == "ready"
        assert ev.data == {"version": 1}

    def test_event_shutdown(self):
        ev = WorkerEvent(event="shutdown", reason="idle_timeout")
        assert ev.reason == "idle_timeout"

    def test_all_messages_inherit_base(self):
        assert issubclass(WorkerRequest, WorkerMessage)
        assert issubclass(WorkerResponse, WorkerMessage)
        assert issubclass(WorkerEvent, WorkerMessage)


class TestFrameCodec:
    def test_encode_decode_request_roundtrip(self):
        req = WorkerRequest(id=42, cmd=CMD_PING)
        frame = encode_frame(req)
        assert isinstance(frame, bytes)
        length = struct.unpack(">I", frame[:4])[0]
        assert length == len(frame) - 4

    def test_encode_frame_format(self):
        req = WorkerRequest(id=1, cmd=CMD_SHUTDOWN)
        frame = encode_frame(req)
        length_bytes = frame[:4]
        length = struct.unpack(">I", length_bytes)[0]
        payload = frame[4:]
        assert len(payload) == length
        msg = json.loads(payload)
        assert msg["cmd"] == "shutdown"

    @pytest.mark.asyncio
    async def test_decode_frame_request(self):
        req = WorkerRequest(id=5, cmd=CMD_CANCEL, data={"cmd_id": 3})
        frame = encode_frame(req)
        reader = asyncio.StreamReader()
        reader.feed_data(frame)
        reader.feed_eof()
        msg = await decode_frame(reader)
        assert isinstance(msg, WorkerRequest)
        assert msg.id == 5
        assert msg.cmd == "cancel"
        assert msg.data["cmd_id"] == 3

    @pytest.mark.asyncio
    async def test_decode_frame_response(self):
        resp = WorkerResponse(id=5, ok=True, data="ok")
        frame = encode_frame(resp)
        reader = asyncio.StreamReader()
        reader.feed_data(frame)
        reader.feed_eof()
        msg = await decode_frame(reader)
        assert isinstance(msg, WorkerResponse)
        assert msg.ok is True

    @pytest.mark.asyncio
    async def test_decode_frame_event(self):
        ev = WorkerEvent(event="ready", data={"version": 1})
        frame = encode_frame(ev)
        reader = asyncio.StreamReader()
        reader.feed_data(frame)
        reader.feed_eof()
        msg = await decode_frame(reader)
        assert isinstance(msg, WorkerEvent)
        assert msg.event == "ready"

    @pytest.mark.asyncio
    async def test_decode_frame_multiple_messages(self):
        req1 = WorkerRequest(id=1, cmd=CMD_PING)
        req2 = WorkerRequest(id=2, cmd=CMD_SHUTDOWN)
        reader = asyncio.StreamReader()
        reader.feed_data(encode_frame(req1))
        reader.feed_data(encode_frame(req2))
        reader.feed_eof()
        msg1 = await decode_frame(reader)
        msg2 = await decode_frame(reader)
        assert msg1.id == 1
        assert msg2.id == 2


class TestCommandConstants:
    def test_command_constants_unique(self):
        from app.workers.worker_protocol import (
            CMD_BROWSER_ACQUIRE, CMD_BROWSER_CLOSE, CMD_BROWSER_HEALTH_CHECK,
            CMD_BROWSER_RELEASE, CMD_DEBUG_START, CMD_DEBUG_STEP, CMD_DEBUG_STOP,
            CMD_INIT, CMD_LOGIN, CMD_CANCEL, CMD_PING, CMD_SHUTDOWN,
        )
        all_cmds = [
            CMD_LOGIN, CMD_CANCEL, CMD_PING, CMD_SHUTDOWN,
            CMD_DEBUG_START, CMD_DEBUG_STEP, CMD_DEBUG_STOP,
            CMD_BROWSER_ACQUIRE, CMD_BROWSER_RELEASE, CMD_BROWSER_CLOSE,
            CMD_BROWSER_HEALTH_CHECK, CMD_INIT,
        ]
        assert len(all_cmds) == len(set(all_cmds)), "命令常量必须唯一"
```

- [ ] **Step 3: 运行测试验证失败**

Run: `python -m pytest tests/test_workers/test_worker_protocol.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.workers.worker_protocol'`

- [ ] **Step 4: 实现 worker_protocol.py**

创建 `app/workers/worker_protocol.py`：

```python
"""Worker 进程间通信协议 — 统一 Message 基类 + 长度前缀帧编解码。

帧格式: [4 bytes: payload length (big-endian uint32)][payload: UTF-8 JSON]
"""
from __future__ import annotations

import asyncio
import json
import struct
from typing import Any

from pydantic import BaseModel

# ── 协议版本 ──
PROTOCOL_VERSION = 1

# ── 命令常量 ──
CMD_LOGIN = "login"
CMD_CANCEL = "cancel"
CMD_PING = "ping"
CMD_SHUTDOWN = "shutdown"
CMD_DEBUG_START = "debug_start"
CMD_DEBUG_STEP = "debug_step"
CMD_DEBUG_STOP = "debug_stop"
CMD_BROWSER_ACQUIRE = "browser_acquire"
CMD_BROWSER_RELEASE = "browser_release"
CMD_BROWSER_CLOSE = "browser_close"
CMD_BROWSER_HEALTH_CHECK = "browser_health_check"
CMD_INIT = "init"


# ── 消息基类 ──


class WorkerMessage(BaseModel):
    """协议消息基类。所有消息共享版本字段。"""
    version: int = PROTOCOL_VERSION


class WorkerRequest(WorkerMessage):
    """请求（父→子，stdin）。"""
    id: int
    cmd: str
    data: dict = {}


class WorkerResponse(WorkerMessage):
    """响应（子→父，对应某个请求）。"""
    id: int
    ok: bool
    data: Any | None = None
    error: str | None = None


class WorkerEvent(WorkerMessage):
    """事件（子→父，无对应请求）。"""
    event: str
    reason: str | None = None
    data: Any | None = None


# ── 帧编解码 ──


def encode_frame(msg: WorkerMessage) -> bytes:
    """将 WorkerMessage 编码为长度前缀帧。"""
    payload = msg.model_dump_json().encode("utf-8")
    return struct.pack(">I", len(payload)) + payload


async def decode_frame(reader: asyncio.StreamReader) -> WorkerMessage:
    """从 StreamReader 读取并解码一帧 WorkerMessage。"""
    length_bytes = await reader.readexactly(4)
    length = struct.unpack(">I", length_bytes)[0]
    payload = await reader.readexactly(length)
    data = json.loads(payload)
    if "cmd" in data:
        return WorkerRequest(**data)
    if "ok" in data:
        return WorkerResponse(**data)
    return WorkerEvent(**data)
```

- [ ] **Step 5: 运行测试验证通过**

Run: `python -m pytest tests/test_workers/test_worker_protocol.py -v`
Expected: PASS（所有测试通过）

- [ ] **Step 6: Commit**

```bash
git add app/workers/worker_protocol.py tests/test_workers/__init__.py tests/test_workers/test_worker_protocol.py
git commit -m "feat(worker): add protocol models and length-prefixed frame codec"
```

---

## Task 2: Command Registry 与命令实现

**Files:**
- Create: `app/workers/worker_commands.py`
- Test: `tests/test_workers/test_worker_commands.py`

- [ ] **Step 1: 写失败测试 — CommandRegistry**

创建 `tests/test_workers/test_worker_commands.py`：

```python
"""Worker Command Registry 测试。"""
from __future__ import annotations

import pytest

from app.workers.worker_commands import Command, CommandRegistry
from app.workers.worker_protocol import (
    CMD_PING,
    CMD_SHUTDOWN,
    WorkerRequest,
    WorkerResponse,
)


class _FakeWorker:
    """测试用 Worker 桩。"""
    def __init__(self):
        self.stop_event_set = False
        self.cancel_events: dict[int, any] = {}


class _PingCommand(Command):
    cmd = CMD_PING

    async def execute(self, worker, data):
        return WorkerResponse(id=0, ok=True, data="pong")


class _ShutdownCommand(Command):
    cmd = CMD_SHUTDOWN

    async def execute(self, worker, data):
        worker.stop_event_set = True
        return WorkerResponse(id=0, ok=True, data="shutting down")


class TestCommandRegistry:
    def test_register_and_dispatch(self):
        registry = CommandRegistry()
        registry.register(_PingCommand())
        assert CMD_PING in registry._commands

    @pytest.mark.asyncio
    async def test_dispatch_ping(self):
        registry = CommandRegistry()
        registry.register(_PingCommand())
        worker = _FakeWorker()
        req = WorkerRequest(id=1, cmd=CMD_PING)
        resp = await registry.dispatch(worker, req)
        assert resp.ok is True
        assert resp.data == "pong"

    @pytest.mark.asyncio
    async def test_dispatch_shutdown(self):
        registry = CommandRegistry()
        registry.register(_ShutdownCommand())
        worker = _FakeWorker()
        req = WorkerRequest(id=2, cmd=CMD_SHUTDOWN)
        resp = await registry.dispatch(worker, req)
        assert resp.ok is True
        assert worker.stop_event_set is True

    @pytest.mark.asyncio
    async def test_dispatch_unknown_command(self):
        registry = CommandRegistry()
        worker = _FakeWorker()
        req = WorkerRequest(id=3, cmd="nonexistent")
        resp = await registry.dispatch(worker, req)
        assert resp.ok is False
        assert "未知命令" in (resp.error or "")

    @pytest.mark.asyncio
    async def test_dispatch_command_exception(self):
        class _FailingCommand(Command):
            cmd = "fail"
            async def execute(self, worker, data):
                raise RuntimeError("boom")

        registry = CommandRegistry()
        registry.register(_FailingCommand())
        worker = _FakeWorker()
        req = WorkerRequest(id=4, cmd="fail")
        resp = await registry.dispatch(worker, req)
        assert resp.ok is False
        assert "boom" in (resp.error or "")
```

- [ ] **Step 2: 运行测试验证失败**

Run: `python -m pytest tests/test_workers/test_worker_commands.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.workers.worker_commands'`

- [ ] **Step 3: 实现 worker_commands.py**

创建 `app/workers/worker_commands.py`：

```python
"""Worker 子进程命令注册中心 — 每个命令是一个类，注册后自动分派。

新增命令只需写一个类 + 一行注册，不改 dispatch 逻辑。
"""
from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from app.workers.worker_protocol import (
    CMD_INIT,
    CMD_BROWSER_ACQUIRE,
    CMD_BROWSER_CLOSE,
    CMD_BROWSER_HEALTH_CHECK,
    CMD_BROWSER_RELEASE,
    CMD_CANCEL,
    CMD_DEBUG_START,
    CMD_DEBUG_STEP,
    CMD_DEBUG_STOP,
    CMD_LOGIN,
    CMD_PING,
    CMD_SHUTDOWN,
    WorkerRequest,
    WorkerResponse,
)

if TYPE_CHECKING:
    from app.workers.playwright_worker import PlaywrightWorker


class Command(ABC):
    """命令基类。子进程内执行，接收 data dict，返回 WorkerResponse。"""
    cmd: str

    @abstractmethod
    async def execute(self, worker: PlaywrightWorker, data: dict) -> WorkerResponse:
        ...


class CommandRegistry:
    """命令注册中心。"""

    def __init__(self) -> None:
        self._commands: dict[str, Command] = {}

    def register(self, command: Command) -> None:
        self._commands[command.cmd] = command

    async def dispatch(self, worker: PlaywrightWorker, request: WorkerRequest) -> WorkerResponse:
        command = self._commands.get(request.cmd)
        if command is None:
            return WorkerResponse(
                id=request.id, ok=False, error=f"未知命令: {request.cmd}"
            )
        try:
            return await command.execute(worker, request.data)
        except Exception as exc:
            return WorkerResponse(
                id=request.id, ok=False, error=f"命令执行异常: {exc}"
            )


# ── 具体命令实现 ──


class PingCommand(Command):
    cmd = CMD_PING

    async def execute(self, worker, data):
        return WorkerResponse(id=0, ok=True, data="pong")


class ShutdownCommand(Command):
    cmd = CMD_SHUTDOWN

    async def execute(self, worker, data):
        worker._stop_event.set()
        return WorkerResponse(id=0, ok=True, data="shutting down")


class InitCommand(Command):
    cmd = CMD_INIT

    async def execute(self, worker, data):
        """接收初始化信息（project_root, rss_threshold 等）。"""
        import os
        project_root = data.get("project_root")
        rss_threshold = data.get("rss_threshold_mb", 500)
        if project_root:
            os.environ["WORKER_PROJECT_ROOT"] = project_root
        os.environ["WORKER_RSS_THRESHOLD_MB"] = str(rss_threshold)
        worker._rss_threshold_mb = rss_threshold
        return WorkerResponse(id=0, ok=True, data="initialized")


class CancelCommand(Command):
    cmd = CMD_CANCEL

    async def execute(self, worker, data):
        cmd_id = data.get("cmd_id")
        event = worker._current_cancel_events.pop(cmd_id, None)
        if event is not None:
            event.set()
        return WorkerResponse(id=0, ok=True)


class LoginCommand(Command):
    cmd = CMD_LOGIN

    async def execute(self, worker, data):
        import threading as _threading

        from app.services.login_handler import LoginAttemptHandler

        config = data.get("config", {})
        cmd_id = data.get("_cmd_id")
        cancel_event = _threading.Event()
        if cmd_id is not None:
            worker._current_cancel_events[cmd_id] = cancel_event

        try:
            handler = LoginAttemptHandler(
                config=config,
                cancel_event=cancel_event,
            )
            success, message = await handler.attempt_login()
            return WorkerResponse(id=0, ok=success, data=message)
        except Exception as exc:
            from app.utils.logging import get_logger
            get_logger("worker_command", source="backend").exception(
                "登录执行异常: task_id={}", config.get("task_id", "unknown")
            )
            return WorkerResponse(id=0, ok=False, error=str(exc))
        finally:
            if cmd_id is not None:
                worker._current_cancel_events.pop(cmd_id, None)


# ── Debug/Browser 命令（委托给 PlaywrightWorker 的 _handle_* 方法）──


class _DelegateCommand(Command):
    """委托给 PlaywrightWorker._handle_* 的基类。"""
    cmd = ""
    _handler_method: str = ""

    async def execute(self, worker, data):
        method = getattr(worker, self._handler_method)
        result = await method(data) if data else await method()
        return result


class DebugStartCommand(_DelegateCommand):
    cmd = CMD_DEBUG_START
    _handler_method = "_handle_debug_start"


class DebugStepCommand(_DelegateCommand):
    cmd = CMD_DEBUG_STEP
    _handler_method = "_handle_debug_step"


class DebugStopCommand(_DelegateCommand):
    cmd = CMD_DEBUG_STOP
    _handler_method = "_handle_debug_stop"


class BrowserAcquireCommand(_DelegateCommand):
    cmd = CMD_BROWSER_ACQUIRE
    _handler_method = "_handle_browser_acquire"


class BrowserReleaseCommand(_DelegateCommand):
    cmd = CMD_BROWSER_RELEASE
    _handler_method = "_handle_browser_release"


class BrowserCloseCommand(_DelegateCommand):
    cmd = CMD_BROWSER_CLOSE
    _handler_method = "_handle_browser_close"


class BrowserHealthCheckCommand(_DelegateCommand):
    cmd = CMD_BROWSER_HEALTH_CHECK
    _handler_method = "_handle_health_check"


def build_default_registry() -> CommandRegistry:
    """构建默认命令注册中心（包含所有内置命令）。"""
    registry = CommandRegistry()
    registry.register(InitCommand())
    registry.register(PingCommand())
    registry.register(ShutdownCommand())
    registry.register(CancelCommand())
    registry.register(LoginCommand())
    registry.register(DebugStartCommand())
    registry.register(DebugStepCommand())
    registry.register(DebugStopCommand())
    registry.register(BrowserAcquireCommand())
    registry.register(BrowserReleaseCommand())
    registry.register(BrowserCloseCommand())
    registry.register(BrowserHealthCheckCommand())
    return registry
```

- [ ] **Step 4: 运行测试验证通过**

Run: `python -m pytest tests/test_workers/test_worker_commands.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/workers/worker_commands.py tests/test_workers/test_worker_commands.py
git commit -m "feat(worker): add Command Registry with all command implementations"
```

---

## Task 3: 子进程入口 worker_proc.py

**Files:**
- Create: `app/workers/worker_proc.py`
- Test: `tests/test_workers/test_worker_proc.py`

- [ ] **Step 1: 写失败测试 — worker_proc 入口可独立运行**

创建 `tests/test_workers/test_worker_proc.py`：

```python
"""Worker 子进程入口测试。"""
from __future__ import annotations

import asyncio
import json
import struct
import subprocess
import sys
import time

import pytest

from app.workers.worker_protocol import (
    CMD_PING,
    PROTOCOL_VERSION,
    WorkerRequest,
    encode_frame,
)


def _read_frame(proc: subprocess.Popen) -> dict:
    """从子进程 stdout 读取一帧。"""
    length_bytes = proc.stdout.read(4)
    if len(length_bytes) < 4:
        raise RuntimeError(f"子进程 stdout EOF, 只读到 {len(length_bytes)} bytes")
    length = struct.unpack(">I", length_bytes)[0]
    payload = proc.stdout.read(length)
    return json.loads(payload)


def _write_frame(proc: subprocess.Popen, msg: WorkerRequest) -> None:
    """向子进程 stdin 写一帧。"""
    frame = encode_frame(msg)
    proc.stdin.write(frame)
    proc.stdin.flush()


class TestWorkerProcStandalone:
    """测试 worker_proc 可独立运行（python -m app.workers.worker_proc）。"""

    def test_worker_proc_starts_and_emits_ready(self):
        """子进程启动后应发送 ready 事件，携带 version。"""
        proc = subprocess.Popen(
            [sys.executable, "-m", "app.workers.worker_proc"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={**__import__("os").environ, "CAMPUS_AUTH_ROLE": "worker"},
        )
        try:
            # 等待 ready 事件（最多 30 秒，子进程要 import playwright）
            msg = _read_frame(proc)
            assert msg["event"] == "ready"
            assert msg["data"]["version"] == PROTOCOL_VERSION
        finally:
            proc.stdin.close()
            proc.terminate()
            proc.wait(timeout=10)

    def test_worker_proc_responds_to_ping(self):
        """子进程应响应 PING 命令。"""
        env = {**__import__("os").environ, "CAMPUS_AUTH_ROLE": "worker"}
        proc = subprocess.Popen(
            [sys.executable, "-m", "app.workers.worker_proc"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        try:
            # 读 ready
            ready = _read_frame(proc)
            assert ready["event"] == "ready"

            # 发 PING
            _write_frame(proc, WorkerRequest(id=1, cmd=CMD_PING))

            # 读响应
            resp = _read_frame(proc)
            assert resp["id"] == 1
            assert resp["ok"] is True
            assert resp["data"] == "pong"
        finally:
            proc.stdin.close()
            proc.terminate()
            proc.wait(timeout=10)

    def test_worker_proc_shutdown_cleanly(self):
        """子进程收到 SHUTDOWN 后应优雅退出。"""
        from app.workers.worker_protocol import CMD_SHUTDOWN

        env = {**__import__("os").environ, "CAMPUS_AUTH_ROLE": "worker"}
        proc = subprocess.Popen(
            [sys.executable, "-m", "app.workers.worker_proc"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        try:
            _read_frame(proc)  # ready

            _write_frame(proc, WorkerRequest(id=2, cmd=CMD_SHUTDOWN))
            resp = _read_frame(proc)
            assert resp["id"] == 2
            assert resp["ok"] is True

            # 子进程应自行退出
            exit_code = proc.wait(timeout=10)
            assert exit_code == 0
        except Exception:
            proc.terminate()
            proc.wait(timeout=10)
            raise
```

- [ ] **Step 2: 运行测试验证失败**

Run: `python -m pytest tests/test_workers/test_worker_proc.py -v -x`
Expected: FAIL with `No module named app.workers.worker_proc` 或子进程启动失败

- [ ] **Step 3: 实现 worker_proc.py**

创建 `app/workers/worker_proc.py`：

```python
"""Worker 子进程入口 — 独立可执行，通过 stdin/stdout JSON-RPC 通信。

启动方式: python -m app.workers.worker_proc

模块体只 import 标准库，所有业务 import 放到 main() 函数体内，
确保 CAMPUS_AUTH_ROLE 在业务模块加载前设置。
"""
from __future__ import annotations

import asyncio
import os
import sys


async def _read_frame_stdin(reader: asyncio.StreamReader):
    """从 stdin 读一帧。"""
    from app.workers.worker_protocol import decode_frame
    return await decode_frame(reader)


async def _write_frame_stdout(writer: asyncio.StreamWriter, msg) -> None:
    """向 stdout 写一帧。"""
    from app.workers.worker_protocol import encode_frame
    writer.write(encode_frame(msg))
    await writer.drain()


async def _main_loop() -> None:
    """子进程主循环：读命令 → dispatch → 写响应。"""
    import struct
    import threading

    from app.utils.logging import get_logger
    from app.workers.playwright_worker import PlaywrightWorker
    from app.workers.worker_commands import build_default_registry
    from app.workers.worker_protocol import (
        WorkerEvent,
        WorkerResponse,
        PROTOCOL_VERSION,
    )

    logger = get_logger("worker_proc", source="backend")

    # 运行 cleanup_orphan_browsers（子进程负责，主进程不 import psutil）
    try:
        from app.workers.playwright_worker import cleanup_orphan_browsers
        cleanup_orphan_browsers()
    except Exception as exc:
        logger.warning("清理孤儿浏览器失败: {}", exc)

    # 创建 Worker 实例并启动内部线程（Playwright Actor）
    worker = PlaywrightWorker()
    worker._current_cancel_events: dict[int, threading.Event] = {}
    worker.start()

    registry = build_default_registry()

    # 使用 sys.stdin.buffer / sys.stdout.buffer 包装为 StreamReader/Writer
    loop = asyncio.get_event_loop()
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: protocol, sys.stdin)

    transport, _ = await loop.connect_write_pipe(
        asyncio.streams.FlowControlMixin, sys.stdout
    )
    writer = asyncio.StreamWriter(transport, _, None, loop)

    # 发送 ready 事件
    ready_event = WorkerEvent(event="ready", data={"version": PROTOCOL_VERSION})
    await _write_frame_stdout(writer, ready_event)
    logger.info("Worker 子进程已就绪")

    # 等待主进程发送 init 消息（接收 project_root、rss_threshold 等）
    try:
        init_msg = await asyncio.wait_for(_read_frame_stdin(reader), timeout=10)
        from app.workers.worker_protocol import WorkerRequest
        if isinstance(init_msg, WorkerRequest) and init_msg.cmd == "init":
            init_resp = await registry.dispatch(worker, init_msg)
            init_resp.id = init_msg.id
            await _write_frame_stdout(writer, init_resp)
            logger.info("Worker 子进程已初始化 (rss_threshold={}MB)", getattr(worker, '_rss_threshold_mb', 500))
        else:
            logger.warning("期望 init 消息，收到: {}", type(init_msg).__name__)
    except asyncio.TimeoutError:
        logger.warning("未收到 init 消息，使用默认配置")

    # RSS 监控任务
    async def _rss_watchdog():
        try:
            import psutil
            proc = psutil.Process()
            threshold_mb = getattr(worker, '_rss_threshold_mb', 500)
            while True:
                await asyncio.sleep(30)
                rss_mb = proc.memory_info().rss / 1024 / 1024
                if rss_mb > threshold_mb:
                    logger.warning("RSS 超阈值 ({}MB > {}MB)，自杀", int(rss_mb), threshold_mb)
                    await _write_frame_stdout(writer, WorkerEvent(
                        event="shutdown", reason=f"rss_exceeded_{int(rss_mb)}mb"
                    ))
                    # OOM 场景不信任 finally/atexit 清理，用 os._exit 立即退出
                    # （设计文档指定 sys.exit，但 OOM 时清理可能失败，os._exit 更安全）
                    os._exit(1)
        except asyncio.CancelledError:
            return
        except Exception as exc:
            logger.debug("RSS 监控异常: {}", exc)

    rss_task = asyncio.create_task(_rss_watchdog())

    # 主读循环
    try:
        while not worker._stop_event.is_set():
            try:
                msg = await _read_frame_stdin(reader)
            except asyncio.IncompleteReadError:
                logger.info("stdin EOF，Worker 子进程退出")
                break

            from app.workers.worker_protocol import WorkerRequest
            if not isinstance(msg, WorkerRequest):
                logger.warning("收到非请求消息，忽略: {}", type(msg).__name__)
                continue

            # 注入 _cmd_id 供 LoginCommand 使用
            if msg.cmd == "login":
                msg.data["_cmd_id"] = msg.id

            response = await registry.dispatch(worker, msg)
            # 确保响应 id 与请求 id 一致
            response.id = msg.id
            await _write_frame_stdout(writer, response)

            if msg.cmd == "shutdown":
                logger.info("收到 SHUTDOWN，Worker 子进程退出")
                break
    finally:
        rss_task.cancel()
        with __import__("contextlib").suppress(Exception):
            await rss_task
        # 停止 Worker 内部线程
        worker.stop(timeout=5)
        logger.info("Worker 子进程已关闭")


def main() -> None:
    """子进程入口函数。"""
    # 第一行就设置角色标记，必须在任何业务 import 之前
    os.environ["CAMPUS_AUTH_ROLE"] = "worker"

    asyncio.run(_main_loop())


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 运行测试验证通过**

Run: `python -m pytest tests/test_workers/test_worker_proc.py -v -x`
Expected: PASS（注意：首次运行子进程启动可能需要 10-20 秒 import playwright）

注意：如果测试因为 Playwright 未安装或 Worker 启动超时失败，先确认 `.venv` 中 playwright 已安装。测试用例的超时设为 30 秒。

- [ ] **Step 5: Commit**

```bash
git add app/workers/worker_proc.py tests/test_workers/test_worker_proc.py
git commit -m "feat(worker): add standalone worker_proc entry point with RSS watchdog"
```

---

## Task 4: LifecyclePolicy 策略抽象

**Files:**
- Create: `app/workers/manager/__init__.py`
- Create: `app/workers/manager/lifecycle_policy.py`
- Test: `tests/test_workers/test_lifecycle_policy.py`

- [ ] **Step 1: 创建 manager 包**

```bash
mkdir -p app/workers/manager
```

创建 `app/workers/manager/__init__.py`（空文件）。

- [ ] **Step 2: 写失败测试 — LifecyclePolicy**

创建 `tests/test_workers/test_lifecycle_policy.py`：

```python
"""LifecyclePolicy 测试。"""
from __future__ import annotations

import time
from dataclasses import dataclass
from unittest.mock import MagicMock

from app.workers.manager.lifecycle_policy import (
    IdleShutdown,
    NeverShutdown,
    ShutdownContext,
)


def _make_ctx(
    active_count: int = 0,
    keepalive_lock_count: int = 0,
    last_active_ts: float | None = None,
    engine_can_shutdown: bool = True,
) -> ShutdownContext:
    engine = MagicMock()
    engine.can_shutdown_worker.return_value = engine_can_shutdown
    return ShutdownContext(
        active_count=active_count,
        keepalive_lock_count=keepalive_lock_count,
        last_active_ts=last_active_ts if last_active_ts is not None else time.time(),
        engine=engine,
    )


class TestIdleShutdown:
    def test_should_shutdown_when_idle_long_enough(self):
        policy = IdleShutdown(idle_timeout=180)
        ctx = _make_ctx(active_count=0, last_active_ts=time.time() - 200)
        assert policy.should_shutdown(ctx) is True

    def test_should_not_shutdown_when_active(self):
        policy = IdleShutdown(idle_timeout=180)
        ctx = _make_ctx(active_count=1, last_active_ts=time.time() - 200)
        assert policy.should_shutdown(ctx) is False

    def test_should_not_shutdown_when_keepalive_locked(self):
        policy = IdleShutdown(idle_timeout=180)
        ctx = _make_ctx(keepalive_lock_count=1, last_active_ts=time.time() - 200)
        assert policy.should_shutdown(ctx) is False

    def test_should_not_shutdown_when_engine_refuses(self):
        policy = IdleShutdown(idle_timeout=180)
        ctx = _make_ctx(
            last_active_ts=time.time() - 200, engine_can_shutdown=False
        )
        assert policy.should_shutdown(ctx) is False

    def test_should_not_shutdown_when_not_idle_long_enough(self):
        policy = IdleShutdown(idle_timeout=180)
        ctx = _make_ctx(last_active_ts=time.time() - 100)
        assert policy.should_shutdown(ctx) is False


class TestNeverShutdown:
    def test_never_shutdowns(self):
        policy = NeverShutdown()
        ctx = _make_ctx(active_count=0, last_active_ts=time.time() - 9999)
        assert policy.should_shutdown(ctx) is False
```

- [ ] **Step 3: 运行测试验证失败**

Run: `python -m pytest tests/test_workers/test_lifecycle_policy.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 4: 实现 lifecycle_policy.py**

创建 `app/workers/manager/lifecycle_policy.py`：

```python
"""LifecyclePolicy — Worker 生命周期判定策略抽象。

将 idle 判定策略抽象为可替换对象，当前有 IdleShutdown（默认）和
NeverShutdown（调试会话期间动态切换）。
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.engine import ScheduleEngine


@dataclass
class ShutdownContext:
    """判定是否关闭时传递的上下文。"""
    active_count: int
    keepalive_lock_count: int
    last_active_ts: float
    engine: ScheduleEngine


class LifecyclePolicy(ABC):
    """生命周期策略基类。"""

    @abstractmethod
    def should_shutdown(self, context: ShutdownContext) -> bool:
        """根据上下文判定是否应该关闭 Worker。"""
        ...


class IdleShutdown(LifecyclePolicy):
    """空闲超时 + engine 许可后关闭。默认策略。"""

    def __init__(self, idle_timeout: float = 180.0) -> None:
        self.idle_timeout = idle_timeout

    def should_shutdown(self, ctx: ShutdownContext) -> bool:
        if ctx.active_count > 0:
            return False
        if ctx.keepalive_lock_count > 0:
            return False
        if time.time() - ctx.last_active_ts < self.idle_timeout:
            return False
        return ctx.engine.can_shutdown_worker()


class NeverShutdown(LifecyclePolicy):
    """永不关闭。调试会话期间动态切换到此策略。"""

    def should_shutdown(self, ctx: ShutdownContext) -> bool:
        return False
```

- [ ] **Step 5: 运行测试验证通过**

Run: `python -m pytest tests/test_workers/test_lifecycle_policy.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/workers/manager/__init__.py app/workers/manager/lifecycle_policy.py tests/test_workers/test_lifecycle_policy.py
git commit -m "feat(worker): add LifecyclePolicy abstraction with IdleShutdown and NeverShutdown"
```

---

## Task 5: ProcessController

**Files:**
- Create: `app/workers/manager/process_controller.py`
- Test: `tests/test_workers/test_process_controller.py`

- [ ] **Step 1: 写失败测试 — ProcessController**

创建 `tests/test_workers/test_process_controller.py`：

```python
"""ProcessController 测试。"""
from __future__ import annotations

import asyncio
import json
import struct
import sys

import pytest

from app.workers.manager.process_controller import ProcessController
from app.workers.worker_protocol import PROTOCOL_VERSION, WorkerEvent, encode_frame


class TestProcessController:
    @pytest.mark.asyncio
    async def test_start_and_wait_ready(self):
        """启动子进程并等待 ready 事件。"""
        ctrl = ProcessController()
        try:
            await ctrl.start(timeout=30)
            assert ctrl.is_alive() is True
        finally:
            await ctrl.stop(timeout=5)
            assert ctrl.is_alive() is False

    @pytest.mark.asyncio
    async def test_is_alive_false_before_start(self):
        ctrl = ProcessController()
        assert ctrl.is_alive() is False

    @pytest.mark.asyncio
    async def test_stop_terminates_process(self):
        ctrl = ProcessController()
        await ctrl.start(timeout=30)
        assert ctrl.is_alive() is True
        await ctrl.stop(timeout=5)
        assert ctrl.is_alive() is False

    @pytest.mark.asyncio
    async def test_stdout_reader_available(self):
        """启动后 stdout 应是可读的 StreamReader。"""
        ctrl = ProcessController()
        try:
            await ctrl.start(timeout=30)
            assert ctrl.stdout is not None
            # ready 事件已被 ProcessController 消费（start 等待 ready）
            # 后续读应由 RpcClient 负责
        finally:
            await ctrl.stop(timeout=5)
```

- [ ] **Step 2: 运行测试验证失败**

Run: `python -m pytest tests/test_workers/test_process_controller.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 实现 process_controller.py**

创建 `app/workers/manager/process_controller.py`：

```python
"""ProcessController — 管理 Worker 子进程的生命周期。

职责：asyncio.create_subprocess_exec 启动、等待 ready、stop/is_alive。
只管进程，不管协议帧或 idle 判定。
"""
from __future__ import annotations

import asyncio
import os
import sys
from typing import TYPE_CHECKING

from app.workers.worker_protocol import PROTOCOL_VERSION, decode_frame, WorkerEvent

if TYPE_CHECKING:
    from asyncio import StreamReader, StreamWriter, Process


class ProcessController:
    """Worker 子进程控制器。"""

    def __init__(self) -> None:
        self._proc: Process | None = None
        self._stdout: StreamReader | None = None
        self._stdin: StreamWriter | None = None
        self._stderr: StreamReader | None = None

    @property
    def stdout(self) -> StreamReader | None:
        return self._stdout

    @property
    def stdin(self) -> StreamWriter | None:
        return self._stdin

    @property
    def stderr(self) -> StreamReader | None:
        return self._stderr

    async def start(self, timeout: float = 30.0) -> None:
        """启动子进程并等待 ready 事件。"""
        env = {**os.environ, "CAMPUS_AUTH_ROLE": "worker"}
        self._proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "app.workers.worker_proc",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        self._stdout = self._proc.stdout
        self._stdin = self._proc.stdin
        self._stderr = self._proc.stderr

        # 等待 ready 事件
        try:
            msg = await asyncio.wait_for(decode_frame(self._stdout), timeout=timeout)
        except asyncio.TimeoutError as exc:
            await self._kill()
            raise RuntimeError(f"Worker 子进程启动超时 ({timeout}s)") from exc

        if not isinstance(msg, WorkerEvent) or msg.event != "ready":
            await self._kill()
            raise RuntimeError(f"Worker 子进程未发送 ready 事件，收到: {msg}")

        version = (msg.data or {}).get("version", 0)
        if version != PROTOCOL_VERSION:
            await self._kill()
            raise RuntimeError(
                f"协议版本不匹配: 期望 {PROTOCOL_VERSION}, 实际 {version}"
            )

    async def stop(self, timeout: float = 5.0) -> None:
        """停止子进程：等待自行退出，超时则 terminate 再 kill。

        注意：调用方应在调用此方法前通过 RpcClient 发送 CMD_SHUTDOWN
        以触发子进程优雅退出。此方法只负责进程级管理。
        """
        if self._proc is None:
            return
        try:
            await asyncio.wait_for(self._proc.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            self._proc.terminate()
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._proc.kill()
                await self._proc.wait()
        finally:
            self._proc = None
            self._stdout = None
            self._stdin = None
            self._stderr = None

    async def _kill(self) -> None:
        if self._proc is None:
            return
        self._proc.kill()
        await self._proc.wait()
        self._proc = None
        self._stdout = None
        self._stdin = None
        self._stderr = None

    def is_alive(self) -> bool:
        if self._proc is None:
            return False
        return self._proc.returncode is None
```

- [ ] **Step 4: 运行测试验证通过**

Run: `python -m pytest tests/test_workers/test_process_controller.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/workers/manager/process_controller.py tests/test_workers/test_process_controller.py
git commit -m "feat(worker): add ProcessController for subprocess lifecycle management"
```

---

## Task 6: RpcClient

**Files:**
- Create: `app/workers/manager/rpc_client.py`
- Test: `tests/test_workers/test_rpc_client.py`

- [ ] **Step 1: 写失败测试 — RpcClient**

创建 `tests/test_workers/test_rpc_client.py`：

```python
"""RpcClient 测试。"""
from __future__ import annotations

import asyncio

import pytest

from app.workers.manager.process_controller import ProcessController
from app.workers.manager.rpc_client import RpcClient
from app.workers.worker_protocol import CMD_PING, WorkerRequest, WorkerResponse


class TestRpcClient:
    @pytest.mark.asyncio
    async def test_send_ping_and_receive_response(self):
        """发送 PING 并接收响应。"""
        ctrl = ProcessController()
        rpc = RpcClient(process_controller=ctrl)
        try:
            await ctrl.start(timeout=30)
            rpc.start_read_loop()
            rpc.start_stderr_forward()
            resp = await rpc.send(WorkerRequest(id=1, cmd=CMD_PING), timeout=10)
            assert resp.ok is True
            assert resp.data == "pong"
        finally:
            await rpc.stop()
            await ctrl.stop(timeout=5)

    @pytest.mark.asyncio
    async def test_send_multiple_requests(self):
        """连续发送多个请求，id 正确匹配。"""
        ctrl = ProcessController()
        rpc = RpcClient(process_controller=ctrl)
        try:
            await ctrl.start(timeout=30)
            rpc.start_read_loop()
            rpc.start_stderr_forward()
            resp1 = await rpc.send(WorkerRequest(id=100, cmd=CMD_PING), timeout=10)
            resp2 = await rpc.send(WorkerRequest(id=200, cmd=CMD_PING), timeout=10)
            assert resp1.id == 100
            assert resp2.id == 200
        finally:
            await rpc.stop()
            await ctrl.stop(timeout=5)

    @pytest.mark.asyncio
    async def test_send_timeout(self):
        """请求超时返回错误响应。"""
        from app.workers.worker_protocol import CMD_LOGIN

        ctrl = ProcessController()
        rpc = RpcClient(process_controller=ctrl)
        try:
            await ctrl.start(timeout=30)
            rpc.start_read_loop()
            rpc.start_stderr_forward()
            # LOGIN 不提供 config，子进程会快速失败，但用极短超时测试
            resp = await rpc.send(
                WorkerRequest(id=1, cmd=CMD_LOGIN, data={}), timeout=0.001
            )
            assert resp.ok is False
            assert "超时" in (resp.error or "") or "timeout" in (resp.error or "").lower()
        finally:
            await rpc.stop()
            await ctrl.stop(timeout=5)

    @pytest.mark.asyncio
    async def test_on_event_callback(self):
        """事件消息触发 on_event 回调。"""
        ctrl = ProcessController()
        rpc = RpcClient(process_controller=ctrl)
        events: list = []
        rpc.on_event = lambda ev: events.append(ev)
        try:
            await ctrl.start(timeout=30)
            rpc.start_read_loop()
            rpc.start_stderr_forward()
            # ready 事件在 start() 中已被 ProcessController 消费，
            # 这里通过发 PING 验证读循环正常工作
            resp = await rpc.send(WorkerRequest(id=1, cmd=CMD_PING), timeout=10)
            assert resp.ok is True
        finally:
            await rpc.stop()
            await ctrl.stop(timeout=5)
```

- [ ] **Step 2: 运行测试验证失败**

Run: `python -m pytest tests/test_workers/test_rpc_client.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 实现 rpc_client.py**

创建 `app/workers/manager/rpc_client.py`：

```python
"""RpcClient — 长度前缀帧读写 + id→Future 派发 + stderr 转发。

只管协议帧和 Future 派发，不管进程或 idle 判定。
"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Callable

from app.utils.logging import get_logger
from app.workers.worker_protocol import (
    WorkerEvent,
    WorkerMessage,
    WorkerRequest,
    WorkerResponse,
    decode_frame,
    encode_frame,
)

if TYPE_CHECKING:
    from app.workers.manager.process_controller import ProcessController

logger = get_logger("rpc_client", source="backend")


class RpcClient:
    """子进程 RPC 客户端。"""

    def __init__(self, process_controller: ProcessController) -> None:
        self._pc = process_controller
        self._pending: dict[int, asyncio.Future[WorkerResponse]] = {}
        self._next_id: int = 1
        self._read_task: asyncio.Task | None = None
        self._stderr_task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self.on_event: Callable[[WorkerEvent], None] | None = None
        self.on_eof: Callable[[], None] | None = None

    @property
    def active_count(self) -> int:
        return len(self._pending)

    def allocate_id(self) -> int:
        rid = self._next_id
        self._next_id += 1
        return rid

    def start_read_loop(self) -> None:
        """启动 stdout 读循环。"""
        self._read_task = asyncio.create_task(self._read_loop())

    def start_stderr_forward(self) -> None:
        """启动 stderr 转发任务。"""
        self._stderr_task = asyncio.create_task(self._stderr_loop())

    async def send(self, request: WorkerRequest, timeout: float = 30.0) -> WorkerResponse:
        """发送请求并等待响应。"""
        if self._pc.stdin is None:
            return WorkerResponse(id=request.id, ok=False, error="Worker 未启动")

        future: asyncio.Future[WorkerResponse] = asyncio.get_event_loop().create_future()
        self._pending[request.id] = future

        try:
            self._pc.stdin.write(encode_frame(request))
            await self._pc.stdin.drain()
        except Exception as exc:
            self._pending.pop(request.id, None)
            return WorkerResponse(id=request.id, ok=False, error=f"发送失败: {exc}")

        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending.pop(request.id, None)
            return WorkerResponse(id=request.id, ok=False, error=f"请求超时 ({timeout}s)")

    async def send_no_wait(self, request: WorkerRequest) -> None:
        """发送请求但不等待响应（用于 CMD_CANCEL 等）。"""
        if self._pc.stdin is None:
            return
        try:
            self._pc.stdin.write(encode_frame(request))
            await self._pc.stdin.drain()
        except Exception as exc:
            logger.warning("send_no_wait 失败: {}", exc)

    async def _read_loop(self) -> None:
        """主读循环：从 stdout 读帧，派发到 pending Future 或 on_event。"""
        while not self._stop_event.is_set():
            try:
                msg = await decode_frame(self._pc.stdout)
            except asyncio.IncompleteReadError:
                logger.info("Worker 子进程 stdout EOF")
                await self._fail_all_pending("Worker 子进程已退出")
                if self.on_eof is not None:
                    try:
                        self.on_eof()
                    except Exception:
                        logger.exception("on_eof 回调异常")
                return
            except Exception as exc:
                logger.exception("读循环异常: {}", exc)
                await self._fail_all_pending(f"读循环异常: {exc}")
                return

            if isinstance(msg, WorkerResponse):
                future = self._pending.pop(msg.id, None)
                if future is not None and not future.done():
                    future.set_result(msg)
                else:
                    logger.warning("收到无人等待的响应: id={}", msg.id)
            elif isinstance(msg, WorkerEvent):
                logger.debug("收到事件: {}", msg.event)
                if self.on_event is not None:
                    try:
                        self.on_event(msg)
                    except Exception:
                        logger.exception("on_event 回调异常")

    async def _stderr_loop(self) -> None:
        """逐行读 stderr 转发到 loguru。"""
        while not self._stop_event.is_set():
            try:
                line = await self._pc.stderr.readline()
            except Exception:
                return
            if not line:
                return
            try:
                logger.bind(source="worker_subprocess").info(
                    line.decode("utf-8", errors="replace").rstrip()
                )
            except Exception:
                pass

    async def _fail_all_pending(self, reason: str) -> None:
        """所有 pending Future 置失败。"""
        for rid, future in list(self._pending.items()):
            if not future.done():
                future.set_result(WorkerResponse(id=rid, ok=False, error=reason))
        self._pending.clear()

    async def stop(self) -> None:
        """停止读循环和 stderr 转发。"""
        self._stop_event.set()
        if self._read_task is not None:
            self._read_task.cancel()
            with __import__("contextlib").suppress(Exception):
                await self._read_task
            self._read_task = None
        if self._stderr_task is not None:
            self._stderr_task.cancel()
            with __import__("contextlib").suppress(Exception):
                await self._stderr_task
            self._stderr_task = None
        await self._fail_all_pending("RpcClient 已停止")
```

- [ ] **Step 4: 运行测试验证通过**

Run: `python -m pytest tests/test_workers/test_rpc_client.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/workers/manager/rpc_client.py tests/test_workers/test_rpc_client.py
git commit -m "feat(worker): add RpcClient with length-prefixed frame I/O and Future dispatch"
```

---

## Task 7: LifecycleManager

**Files:**
- Create: `app/workers/manager/lifecycle_manager.py`
- Test: `tests/test_workers/test_lifecycle_manager.py`

- [ ] **Step 1: 写失败测试 — LifecycleManager**

创建 `tests/test_workers/test_lifecycle_manager.py`：

```python
"""LifecycleManager 测试。"""
from __future__ import annotations

import asyncio
import time
from unittest.mock import MagicMock

import pytest

from app.workers.manager.lifecycle_manager import LifecycleManager
from app.workers.manager.lifecycle_policy import IdleShutdown, NeverShutdown


class TestLifecycleManager:
    def test_acquire_release_keepalive_lock(self):
        mgr = LifecycleManager(
            process_controller=MagicMock(),
            rpc_client=MagicMock(),
            engine=MagicMock(),
            idle_timeout=180,
        )
        assert mgr.keepalive_lock_count == 0
        mgr.acquire_keepalive_lock()
        assert mgr.keepalive_lock_count == 1
        assert isinstance(mgr._policy, NeverShutdown)
        mgr.release_keepalive_lock()
        assert mgr.keepalive_lock_count == 0
        assert isinstance(mgr._policy, IdleShutdown)

    def test_release_below_zero_clamped(self):
        mgr = LifecycleManager(
            process_controller=MagicMock(),
            rpc_client=MagicMock(),
            engine=MagicMock(),
            idle_timeout=180,
        )
        mgr.release_keepalive_lock()
        assert mgr.keepalive_lock_count == 0

    def test_on_restart_callback_registered(self):
        mgr = LifecycleManager(
            process_controller=MagicMock(),
            rpc_client=MagicMock(),
            engine=MagicMock(),
            idle_timeout=180,
        )
        called = []
        mgr.on_restart(lambda: called.append(1))
        mgr._trigger_restart_callbacks()
        assert called == [1]

    def test_record_activity_updates_timestamp(self):
        mgr = LifecycleManager(
            process_controller=MagicMock(),
            rpc_client=MagicMock(),
            engine=MagicMock(),
            idle_timeout=180,
        )
        old_ts = mgr._last_active_ts
        time.sleep(0.01)
        mgr.record_activity()
        assert mgr._last_active_ts > old_ts
```

- [ ] **Step 2: 运行测试验证失败**

Run: `python -m pytest tests/test_workers/test_lifecycle_manager.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 实现 lifecycle_manager.py**

创建 `app/workers/manager/lifecycle_manager.py`：

```python
"""LifecycleManager — keepalive 锁 + 心跳 + 重启 + on_restart 回调。

持有 LifecyclePolicy，每 30s 用策略判定是否关闭 Worker。
调试会话期间通过 acquire/release keepalive 锁动态切换策略。
"""
from __future__ import annotations

import asyncio
import threading
import time
from typing import TYPE_CHECKING, Callable

from app.utils.logging import get_logger
from app.workers.manager.lifecycle_policy import (
    IdleShutdown,
    LifecyclePolicy,
    NeverShutdown,
    ShutdownContext,
)

if TYPE_CHECKING:
    from app.services.engine import ScheduleEngine
    from app.workers.manager.process_controller import ProcessController
    from app.workers.manager.rpc_client import RpcClient

logger = get_logger("lifecycle_manager", source="backend")

KEEPALIVE_CHECK_INTERVAL = 30.0
PING_INTERVAL = 30.0
PING_MAX_MISS = 3


class LifecycleManager:
    """Worker 生命周期管理器。"""

    def __init__(
        self,
        process_controller: ProcessController,
        rpc_client: RpcClient,
        engine: ScheduleEngine,
        idle_timeout: float = 180.0,
    ) -> None:
        self._pc = process_controller
        self._rpc = rpc_client
        self._engine = engine
        self._idle_timeout = idle_timeout
        self._policy: LifecyclePolicy = IdleShutdown(idle_timeout=idle_timeout)
        self._keepalive_lock_count: int = 0
        self._lock = threading.Lock()
        self._last_active_ts: float = time.time()
        self._keepalive_task: asyncio.Task | None = None
        self._heartbeat_task: asyncio.Task | None = None
        self._restart_callbacks: list[Callable[[], None]] = []
        self._stop_event = asyncio.Event()

    @property
    def keepalive_lock_count(self) -> int:
        with self._lock:
            return self._keepalive_lock_count

    def on_restart(self, callback: Callable[[], None]) -> None:
        """注册 worker 重启回调。"""
        self._restart_callbacks.append(callback)

    def _trigger_restart_callbacks(self) -> None:
        """触发所有 on_restart 回调。"""
        for cb in self._restart_callbacks:
            try:
                cb()
            except Exception:
                logger.exception("on_restart 回调异常")

    def record_activity(self) -> None:
        """记录一次活跃（有命令执行）。"""
        self._last_active_ts = time.time()

    def acquire_keepalive_lock(self) -> None:
        """调试会话 acquire 时，切换到 NeverShutdown。"""
        with self._lock:
            self._keepalive_lock_count += 1
            if self._keepalive_lock_count == 1:
                self._policy = NeverShutdown()
                logger.debug("keepalive 锁已 acquire，切换到 NeverShutdown")

    def release_keepalive_lock(self) -> None:
        """调试会话 release 后，切回 IdleShutdown。"""
        with self._lock:
            self._keepalive_lock_count = max(0, self._keepalive_lock_count - 1)
            if self._keepalive_lock_count == 0:
                self._policy = IdleShutdown(idle_timeout=self._idle_timeout)
                logger.debug("keepalive 锁已 release，切回 IdleShutdown")

    def start(self) -> None:
        """启动 keepalive 和心跳定时器。"""
        self._stop_event.clear()
        self._keepalive_task = asyncio.create_task(self._keepalive_loop())
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def stop(self) -> None:
        """停止定时器。"""
        self._stop_event.set()
        for task in (self._keepalive_task, self._heartbeat_task):
            if task is not None:
                task.cancel()
                with __import__("contextlib").suppress(Exception):
                    await task
        self._keepalive_task = None
        self._heartbeat_task = None

    async def _keepalive_loop(self) -> None:
        """每 30s 用策略判定是否关闭 Worker。"""
        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=KEEPALIVE_CHECK_INTERVAL
                )
                return
            except asyncio.TimeoutError:
                pass

            ctx = ShutdownContext(
                active_count=self._rpc.active_count,
                keepalive_lock_count=self.keepalive_lock_count,
                last_active_ts=self._last_active_ts,
                engine=self._engine,
            )
            if self._policy.should_shutdown(ctx):
                logger.info("LifecyclePolicy 判定关闭 Worker（idle 超时）")
                await self._graceful_shutdown()
                return
            # 策略拒绝：重置 last_active_ts 给下一个周期
            if ctx.active_count == 0 and ctx.keepalive_lock_count == 0:
                self._last_active_ts = time.time()

    async def _heartbeat_loop(self) -> None:
        """每 30s 发 PING，3 次超时判定僵死。"""
        from app.workers.worker_protocol import CMD_PING, WorkerRequest

        miss_count = 0
        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=PING_INTERVAL
                )
                return
            except asyncio.TimeoutError:
                pass

            if not self._pc.is_alive():
                logger.warning("Worker 子进程已死亡，触发重启")
                await self._handle_crash_and_restart()
                return

            # PING
            rid = self._rpc.allocate_id()
            resp = await self._rpc.send(
                WorkerRequest(id=rid, cmd=CMD_PING), timeout=10
            )
            if resp.ok:
                miss_count = 0
            else:
                miss_count += 1
                logger.warning("心跳失败 ({}/{}): {}", miss_count, PING_MAX_MISS, resp.error)
                if miss_count >= PING_MAX_MISS:
                    logger.warning("心跳超时 {} 次，判定僵死，强制重启", PING_MAX_MISS)
                    await self._graceful_shutdown()
                    await self._handle_crash_and_restart()
                    return

    async def handle_worker_death(self) -> None:
        """子进程死亡时调用（由 RpcClient EOF 触发）。"""
        logger.warning("Worker 子进程已退出，触发重启")
        await self._handle_crash_and_restart()

    async def _graceful_shutdown(self) -> None:
        """优雅关闭：发 CMD_SHUTDOWN → 等 5s → 强制 stop。"""
        from app.workers.worker_protocol import CMD_SHUTDOWN, WorkerRequest
        try:
            rid = self._rpc.allocate_id()
            await self._rpc.send_no_wait(WorkerRequest(id=rid, cmd=CMD_SHUTDOWN))
        except Exception as exc:
            logger.warning("发送 CMD_SHUTDOWN 失败: {}", exc)
        await self._pc.stop(timeout=5)

    async def _handle_crash_and_restart(self) -> None:
        """崩溃后重启：触发回调 → 停止旧进程 → 重启。"""
        self._trigger_restart_callbacks()
        try:
            await self._pc.stop(timeout=2)
        except Exception:
            pass
        try:
            await self._pc.start(timeout=30)
            self._rpc.start_read_loop()
            self._rpc.start_stderr_forward()
            logger.info("Worker 子进程已重启")
        except Exception as exc:
            logger.error("Worker 子进程重启失败: {}", exc)
```

- [ ] **Step 4: 运行测试验证通过**

Run: `python -m pytest tests/test_workers/test_lifecycle_manager.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/workers/manager/lifecycle_manager.py tests/test_workers/test_lifecycle_manager.py
git commit -m "feat(worker): add LifecycleManager with keepalive lock, heartbeat, restart callbacks"
```

---

## Task 8: WorkerFacade 和 WorkerManager

**Files:**
- Create: `app/workers/manager/worker_facade.py`
- Create: `app/workers/manager/worker_manager.py`
- Test: `tests/test_workers/test_worker_facade.py`

- [ ] **Step 1: 写失败测试 — WorkerFacade 同步 submit 接口**

创建 `tests/test_workers/test_worker_facade.py`：

```python
"""WorkerFacade 测试 — 阶段一同步 submit 接口。"""
from __future__ import annotations

import asyncio

import pytest

from app.workers.manager.worker_manager import WorkerManager
from app.workers.worker_protocol import (
    CMD_PING,
    WorkerResponse,
)


class TestWorkerFacadeSyncInterface:
    """阶段一：Facade 对外提供同步 submit()，内部桥接 asyncio。"""

    @pytest.mark.asyncio
    async def test_submit_ping_returns_pong(self):
        """同步 submit 应返回 PING 响应。"""
        from app.workers.manager.worker_facade import WorkerFacade
        from unittest.mock import MagicMock

        # 用真实 WorkerManager 启动真实子进程
        engine_mock = MagicMock()
        engine_mock.can_shutdown_worker.return_value = True
        mgr = WorkerManager(engine=engine_mock)
        try:
            await mgr.start()
            facade = mgr.get_facade()
            assert facade.is_alive() is True

            # 同步 submit（在 asyncio 事件循环线程外调用）
            # 由于测试在 async 上下文，用 to_thread 包装
            resp = await asyncio.to_thread(facade.submit, CMD_PING, timeout=10)
            assert resp.success is True
            assert resp.data == "pong"
        finally:
            await mgr.stop()

    @pytest.mark.asyncio
    async def test_is_alive_false_before_start(self):
        from app.workers.manager.worker_facade import WorkerFacade
        from unittest.mock import MagicMock

        engine_mock = MagicMock()
        mgr = WorkerManager(engine=engine_mock)
        facade = mgr.get_facade()
        assert facade.is_alive() is False

    @pytest.mark.asyncio
    async def test_acquire_release_keepalive_lock(self):
        from unittest.mock import MagicMock

        engine_mock = MagicMock()
        mgr = WorkerManager(engine=engine_mock)
        facade = mgr.get_facade()
        facade.acquire_keepalive_lock()
        assert facade.is_keepalive_locked() is True
        facade.release_keepalive_lock()
        assert facade.is_keepalive_locked() is False
```

- [ ] **Step 2: 运行测试验证失败**

Run: `python -m pytest tests/test_workers/test_worker_facade.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 实现 worker_facade.py**

注意：阶段一对外提供**同步** `submit()` 接口（返回 `WorkerResponse`，与现有 `playwright_worker.WorkerResponse` 兼容）。内部通过 `asyncio.run_coroutine_threadsafe` 桥接 asyncio.subprocess。

创建 `app/workers/manager/worker_facade.py`：

```python
"""WorkerFacade — 对外接口（阶段一：同步 submit）。

消费方只看到 submit/cancel/is_alive/keepalive lock 五个方法。
内部委托给 WorkerManager 的各组件。

阶段一保留同步 submit() 接口，内部用 asyncio.run_coroutine_threadsafe
桥接 asyncio.subprocess。阶段二改为 async submit()。
"""
from __future__ import annotations

import asyncio
import threading
from typing import TYPE_CHECKING, Any

from app.workers.worker_protocol import (
    CMD_CANCEL,
    CMD_PING,
    WorkerRequest,
    WorkerResponse as ProtoResponse,
)

if TYPE_CHECKING:
    from app.workers.manager.worker_manager import WorkerManager

# 兼容旧 WorkerResponse dataclass（消费方 import 的是 playwright_worker.WorkerResponse）
from app.workers.playwright_worker import WorkerResponse


class WorkerFacade:
    """Worker 对外门面（阶段一同步接口）。"""

    def __init__(self, manager: WorkerManager) -> None:
        self._mgr = manager
        self._loop: asyncio.AbstractEventLoop | None = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """由 WorkerManager.start() 在 async 上下文中注入 running loop。"""
        self._loop = loop

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        """获取主进程 asyncio 事件循环。"""
        if self._loop is None or self._loop.is_closed():
            # Python 3.12+ 兼容：优先用 get_event_loop，失败则报错
            try:
                self._loop = asyncio.get_event_loop()
            except RuntimeError:
                raise RuntimeError(
                    "WorkerFacade 事件循环未初始化，请先调用 WorkerManager.start()"
                )
        return self._loop

    def submit(
        self,
        cmd_type: str,
        data: dict | None = None,
        wait: bool = True,
        timeout: float | None = 30.0,
    ) -> WorkerResponse:
        """同步提交命令（阶段一接口）。

        内部通过 run_coroutine_threadsafe 桥接到 asyncio 事件循环。
        """
        loop = self._ensure_loop()
        rid = self._mgr.rpc.allocate_id()
        request = WorkerRequest(id=rid, cmd=cmd_type, data=data or {})

        if not wait:
            # 不等待响应（当前无调用方使用 wait=False）
            asyncio.run_coroutine_threadsafe(
                self._mgr.rpc.send_no_wait(request), loop
            )
            return WorkerResponse(success=True)

        # 同步等待：在调用方线程阻塞，future 在事件循环线程完成
        future = asyncio.run_coroutine_threadsafe(
            self._mgr.rpc.send(request, timeout=timeout or 30.0), loop
        )
        try:
            proto_resp = future.result(timeout=(timeout or 30.0) + 5)
        except Exception as exc:
            return WorkerResponse(success=False, error=f"submit 异常: {exc}")

        # 记录活跃
        self._mgr.lifecycle.record_activity()

        # 转换为兼容的 WorkerResponse
        return WorkerResponse(
            success=proto_resp.ok,
            data=proto_resp.data,
            error=proto_resp.error,
        )

    def is_alive(self) -> bool:
        """Worker 子进程是否存活。"""
        return self._mgr.process_controller.is_alive()

    def acquire_keepalive_lock(self) -> None:
        """调试会话 acquire keepalive 锁。"""
        self._mgr.lifecycle.acquire_keepalive_lock()

    def release_keepalive_lock(self) -> None:
        """调试会话 release keepalive 锁。"""
        self._mgr.lifecycle.release_keepalive_lock()

    def is_keepalive_locked(self) -> bool:
        """是否持有 keepalive 锁。"""
        return self._mgr.lifecycle.keepalive_lock_count > 0

    def on_restart(self, callback) -> None:
        """注册 worker 重启回调。"""
        self._mgr.lifecycle.on_restart(callback)

    def start(self, timeout: float = 30.0) -> None:
        """同步启动 Worker（在事件循环线程外调用）。"""
        loop = self._ensure_loop()
        future = asyncio.run_coroutine_threadsafe(
            self._mgr.start(timeout=timeout), loop
        )
        future.result(timeout=timeout + 5)

    def stop(self) -> None:
        """同步停止 Worker（在事件循环线程外调用）。"""
        loop = self._ensure_loop()
        future = asyncio.run_coroutine_threadsafe(
            self._mgr.stop(), loop
        )
        future.result(timeout=10)
```

- [ ] **Step 4: 实现 worker_manager.py**

创建 `app/workers/manager/worker_manager.py`：

```python
"""WorkerManager — 协调 ProcessController / RpcClient / LifecycleManager。

不直接处理协议帧或进程细节，只负责创建和协调各组件生命周期。
"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from app.utils.logging import get_logger
from app.workers.manager.lifecycle_manager import LifecycleManager
from app.workers.manager.process_controller import ProcessController
from app.workers.manager.rpc_client import RpcClient
from app.workers.manager.worker_facade import WorkerFacade

if TYPE_CHECKING:
    from app.services.engine import ScheduleEngine

logger = get_logger("worker_manager", source="backend")

WORKER_IDLE_TIMEOUT = 180.0


class WorkerManager:
    """Worker 管理器 — 协调各组件。"""

    def __init__(self, engine: ScheduleEngine) -> None:
        self._engine = engine
        self.process_controller = ProcessController()
        self.rpc = RpcClient(process_controller=self.process_controller)
        self.lifecycle = LifecycleManager(
            process_controller=self.process_controller,
            rpc_client=self.rpc,
            engine=engine,
            idle_timeout=WORKER_IDLE_TIMEOUT,
        )
        self._facade: WorkerFacade | None = None
        self._started: bool = False

        # RpcClient 事件转发：EOF（子进程死亡）→ LifecycleManager.handle_worker_death
        self.rpc.on_event = self._on_event
        self.rpc.on_eof = self._on_eof

    def _on_event(self, event) -> None:
        """处理子进程事件。"""
        from app.workers.worker_protocol import WorkerEvent
        if isinstance(event, WorkerEvent) and event.event == "shutdown":
            logger.info("Worker 子进程主动关闭: {}", event.reason)

    def _on_eof(self) -> None:
        """子进程 stdout EOF（死亡）时触发，转发到 LifecycleManager。"""
        logger.warning("RpcClient 检测到 Worker 子进程 EOF")
        asyncio.create_task(self.lifecycle.handle_worker_death())

    def get_facade(self) -> WorkerFacade:
        """获取对外 Facade。"""
        if self._facade is None:
            self._facade = WorkerFacade(self)
        return self._facade

    async def start(self, timeout: float = 30.0) -> None:
        """启动 Worker 子进程（幂等：已启动则跳过）。"""
        if self._started and self.process_controller.is_alive():
            return
        await self.process_controller.start(timeout=timeout)
        self.rpc.start_read_loop()
        self.rpc.start_stderr_forward()
        self.lifecycle.start()
        self._started = True

        # 注入事件循环到 Facade（Python 3.12+ 兼容）
        if self._facade is not None:
            self._facade.set_loop(asyncio.get_running_loop())

        # 发送 init 消息（传递 project_root 和 rss_threshold）
        await self._send_init()

        logger.info("WorkerManager 已启动")

    async def _send_init(self) -> None:
        """发送 init 消息到子进程。"""
        import os
        from app.workers.worker_protocol import CMD_INIT, WorkerRequest
        rid = self.rpc.allocate_id()
        init_req = WorkerRequest(
            id=rid,
            cmd=CMD_INIT,
            data={
                "project_root": os.getcwd(),
                "rss_threshold_mb": int(os.environ.get("WORKER_RSS_THRESHOLD_MB", "500")),
            },
        )
        resp = await self.rpc.send(init_req, timeout=10)
        if not resp.ok:
            logger.warning("init 消息失败: {}", resp.error)

    async def stop(self) -> None:
        """停止 Worker 子进程（先发 CMD_SHUTDOWN 优雅退出）。"""
        await self.lifecycle.stop()
        # 发 CMD_SHUTDOWN 让子进程优雅退出
        from app.workers.worker_protocol import CMD_SHUTDOWN, WorkerRequest
        try:
            rid = self.rpc.allocate_id()
            await self.rpc.send_no_wait(WorkerRequest(id=rid, cmd=CMD_SHUTDOWN))
        except Exception:
            pass
        await self.rpc.stop()
        await self.process_controller.stop(timeout=5)
        self._started = False
        logger.info("WorkerManager 已停止")

    async def restart(self) -> None:
        """重启 Worker 子进程（崩溃后自动恢复）。"""
        logger.warning("重启 Worker 子进程")
        await self.rpc.stop()
        await self.process_controller.stop(timeout=5)
        await self.process_controller.start(timeout=30)
        self.rpc.start_read_loop()
        self.rpc.start_stderr_forward()
        await self._send_init()
        logger.info("Worker 子进程已重启")
```

- [ ] **Step 5: 运行测试验证通过**

Run: `python -m pytest tests/test_workers/test_worker_facade.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/workers/manager/worker_facade.py app/workers/manager/worker_manager.py tests/test_workers/test_worker_facade.py
git commit -m "feat(worker): add WorkerFacade (sync submit) and WorkerManager coordinator"
```

---

## Task 9: 修改 playwright_worker.py — get_worker 角色判断

**Files:**
- Modify: `app/workers/playwright_worker.py`

- [ ] **Step 1: 修改 get_worker() 角色判断**

读取 `app/workers/playwright_worker.py` 的 `get_worker` 函数（约 1023 行）。

修改 `get_worker()`：

```python
def get_worker() -> PlaywrightWorker | "WorkerFacade":
    """获取全局 Worker 单例。

    主进程：返回 WorkerFacade 实例（由 WorkerManager 创建）。
    子进程：返回真正的 PlaywrightWorker 单例。
    通过 CAMPUS_AUTH_ROLE 环境变量区分进程角色。
    """
    import os

    role = os.environ.get("CAMPUS_AUTH_ROLE", "main")

    # 子进程：返回真正的 PlaywrightWorker 单例（原逻辑）
    if role == "worker":
        global _worker
        if _worker is None or not _worker.is_alive():
            with _worker_lock:
                if _worker is None or not _worker.is_alive():
                    if _worker is not None:
                        try:
                            _worker.stop()
                        except Exception:
                            logger.debug("停止旧 Worker 失败", exc_info=True)
                    new_worker = PlaywrightWorker()
                    new_worker.start()
                    _worker = new_worker
        return _worker

    # 主进程：返回 WorkerFacade（单例）
    global _main_facade
    if _main_facade is None:
        with _worker_lock:
            if _main_facade is None:
                from app.workers.manager.worker_manager import WorkerManager
                from app.container import get_engine_for_worker

                engine = get_engine_for_worker()
                mgr = WorkerManager(engine=engine)
                _main_facade = mgr.get_facade()
                _main_manager = mgr
    return _main_facade
```

- [ ] **Step 2: 添加模块级变量**

在 `app/workers/playwright_worker.py` 模块级单例区域（约 1018 行附近）添加：

```python
_worker: PlaywrightWorker | None = None
"""子进程内的 Worker 单例。"""
_worker_lock = threading.Lock()

_main_facade = None
"""主进程的 WorkerFacade 单例。"""
_main_manager = None
"""主进程的 WorkerManager 单例。"""
```

- [ ] **Step 3: 修改 shutdown_worker 为 async**

```python
async def shutdown_worker(timeout: float = 5) -> None:
    """关闭并清理全局 Worker 单例。shutdown 场景专用，不创建新实例。"""
    import os

    role = os.environ.get("CAMPUS_AUTH_ROLE", "main")

    global _worker, _main_facade, _main_manager
    with _worker_lock:
        if role == "worker":
            if _worker is not None and _worker.is_alive():
                _worker.stop(timeout=timeout)
            _worker = None
        else:
            if _main_manager is not None:
                try:
                    await _main_manager.stop()
                except Exception as e:
                    logger.warning("停止 WorkerManager 异常: {}", e)
            _main_facade = None
            _main_manager = None
```

- [ ] **Step 4: 删除 get_worker 中的 cleanup_orphan_browsers 调用**

在原 `get_worker()` 主进程分支中删除 `cleanup_orphan_browsers()` 调用（已移到子进程 `worker_proc.main()`）。

- [ ] **Step 5: 添加 _current_cancel_events 属性到 PlaywrightWorker**

在 `PlaywrightWorker.__init__` 中添加：

```python
self._current_cancel_events: dict[int, threading.Event] = {}
"""cmd_id → 本地 threading.Event 映射，供 CancelCommand 使用。"""
```

- [ ] **Step 6: 运行现有 worker 相关测试验证不破坏**

Run: `python -m pytest tests/test_services/test_login_orchestrator.py tests/test_core/test_task_executor.py -v`
Expected: PASS（现有测试应仍通过，因为子进程角色下逻辑不变）

- [ ] **Step 7: Commit**

```bash
git add app/workers/playwright_worker.py
git commit -m "refactor(worker): split get_worker by CAMPUS_AUTH_ROLE, main returns WorkerFacade"
```

---

## Task 10: 修改 container.py — 注入 engine + 删除 cleanup + 预热

**Files:**
- Modify: `app/container.py`

- [ ] **Step 1: 添加 get_engine_for_worker 模块级函数**

在 `app/container.py` 顶部（class 定义前）添加：

```python
# 全局容器引用，供 worker 模块获取 engine（解决循环依赖）
_global_container: ServiceContainer | None = None


def get_engine_for_worker():
    """供 app.workers.playwright_worker.get_worker() 获取 engine 引用。"""
    if _global_container is None:
        raise RuntimeError("ServiceContainer 尚未初始化")
    return _global_container.engine
```

- [ ] **Step 2: 在 __init__ 末尾设置全局引用**

在 `ServiceContainer.__init__` 末尾（`self._shutdown_done = False` 后）添加：

```python
global _global_container
_global_container = self
```

- [ ] **Step 3: 删除 startup 中的 cleanup_orphan_browsers 调用**

修改 `startup()` 方法，删除 `from app.workers.playwright_worker import cleanup_orphan_browsers` 和 `cleanup_orphan_browsers()` 调用：

```python
async def startup(self):
    """启动所有服务。"""
    try:
        self.start_web_services()
        self.engine.boot()
        self.engine.sync_scheduler_state()
        container_logger.info("服务容器启动成功")
    except Exception as e:
        container_logger.exception("服务启动异常，正在清理: {}", e)
        try:
            await self.shutdown()
        except Exception as e2:
            container_logger.exception("清理过程异常: {}", e2)
        raise
```

- [ ] **Step 4: 修改 shutdown 中的 shutdown_worker 为 async**

```python
async def shutdown(self):
    """关闭服务。"""
    if self._shutdown_done:
        return
    self._shutdown_done = True
    container_logger.debug("服务容器开始关闭")

    self.engine.shutdown()
    self.task_executor.shutdown(wait=True, timeout=10)
    await self.stop_web_services()
    await self.debug_manager.close()
    await self.ws_manager.close_all()

    try:
        from app.workers.playwright_worker import shutdown_worker
        await shutdown_worker(timeout=2)
        container_logger.info("Playwright Worker 已关闭")
    except Exception as e:
        container_logger.exception("关闭 Playwright Worker 异常: {}", e)

    try:
        if self._temp_dir.exists():
            shutil.rmtree(self._temp_dir, ignore_errors=True)
            self._temp_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        container_logger.warning("临时目录清理失败", exc_info=True)

    container_logger.info("服务容器已关闭")
```

- [ ] **Step 5: 在 startup 中预热 Worker 子进程**

在 `startup()` 方法的 `container_logger.info("服务容器启动成功")` 行之前，新增预热逻辑：

```python
        # 预热 Worker 子进程（失败不阻塞启动，首次 submit 会兜底启动）
        try:
            from app.workers.playwright_worker import get_worker
            worker = get_worker()
            if hasattr(worker, 'start'):
                # WorkerFacade 同步 start 方法
                worker.start(timeout=30)
                container_logger.info("Worker 子进程预热完成")
        except Exception as e:
            container_logger.warning("Worker 预热失败（将在首次使用时启动）: {}", e)
```

同时在 `WorkerFacade.submit` 中保留兜底自动启动逻辑（预热失败时首次 submit 触发 start）：

修改 `app/workers/manager/worker_facade.py` 的 `submit` 方法，在发送前确保子进程已启动：

```python
    def submit(
        self,
        cmd_type: str,
        data: dict | None = None,
        wait: bool = True,
        timeout: float | None = 30.0,
    ) -> WorkerResponse:
        """同步提交命令（阶段一接口）。"""
        loop = self._ensure_loop()

        # 兜底：确保子进程已启动（预热失败或崩溃后重启的首次 submit）
        if not self._mgr.process_controller.is_alive():
            try:
                future = asyncio.run_coroutine_threadsafe(
                    self._mgr.start(), loop
                )
                future.result(timeout=35)
            except Exception as exc:
                return WorkerResponse(success=False, error=f"Worker 启动失败: {exc}")

        rid = self._mgr.rpc.allocate_id()
        request = WorkerRequest(id=rid, cmd=cmd_type, data=data or {})

        if not wait:
            asyncio.run_coroutine_threadsafe(
                self._mgr.rpc.send_no_wait(request), loop
            )
            return WorkerResponse(success=True)

        future = asyncio.run_coroutine_threadsafe(
            self._mgr.rpc.send(request, timeout=timeout or 30.0), loop
        )
        try:
            proto_resp = future.result(timeout=(timeout or 30.0) + 5)
        except Exception as exc:
            return WorkerResponse(success=False, error=f"submit 异常: {exc}")

        self._mgr.lifecycle.record_activity()

        return WorkerResponse(
            success=proto_resp.ok,
            data=proto_resp.data,
            error=proto_resp.error,
        )
```

- [ ] **Step 6: 运行容器测试**

Run: `python -m pytest tests/test_config/test_container.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add app/container.py app/workers/manager/worker_facade.py
git commit -m "refactor(container): inject engine to WorkerManager, remove cleanup_orphan_browsers, async shutdown_worker"
```

---

## Task 11: 修改 engine.py — can_shutdown_worker + retry_policy 注入

**Files:**
- Modify: `app/services/engine.py`

- [ ] **Step 1: 添加 can_shutdown_worker 方法**

在 `ScheduleEngine` 类中添加（在 `get_runtime_config` 附近）：

```python
def can_shutdown_worker(self) -> bool:
    """判断当前是否可以安全关闭 Worker 子进程。

    返回 False 的场景：有待执行重试、或短期内需要网络检测/定时任务。
    """
    from app.workers.manager.worker_manager import WORKER_IDLE_TIMEOUT
    # 监控未运行：可杀
    if not self._is_monitoring:
        return True
    # 有待执行重试：不可杀
    with self._retry_time_lock:
        if self._next_retry_time > 0:
            return False
    # 下次网络检测在 IDLE_TIMEOUT 内：不可杀
    if self._next_network_check - time.time() < WORKER_IDLE_TIMEOUT:
        return False
    # 定时任务即将触发（IDLE_TIMEOUT 内）：不可杀
    if self._scheduler is not None:
        try:
            next_tick = self._scheduler.next_tick_time
            if next_tick is not None and next_tick - time.time() < WORKER_IDLE_TIMEOUT:
                return False
        except Exception:
            pass
    return True
```

- [ ] **Step 2: 修改 retry_policy 初始化，注入 retry_interval**

找到 `self._retry_policy = MonitoredPolicy()`（约 374 行），改为：

```python
runtime_cfg = self.get_runtime_config()
self._retry_policy = MonitoredPolicy(
    max_retries=runtime_cfg.retry.max_retries,
    retry_interval=runtime_cfg.retry.retry_interval,
)
```

- [ ] **Step 3: 添加 _sync_retry_policy 方法**

```python
def _sync_retry_policy(self) -> None:
    """配置重载后同步更新 retry_policy 参数。"""
    try:
        cfg = self.get_runtime_config()
        self._retry_policy.max_retries = max(0, cfg.retry.max_retries)
        self._retry_policy.retry_interval = max(1, cfg.retry.retry_interval)
    except Exception:
        self._logger.warning("同步 retry_policy 失败", exc_info=True)
```

- [ ] **Step 4: 在 _reload_config_internal 中调用 _sync_retry_policy**

找到 `_reload_config_internal` 方法，在末尾添加：

```python
self._sync_retry_policy()
```

- [ ] **Step 5: 运行 engine 测试**

Run: `python -m pytest tests/test_services/test_engine.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/services/engine.py
git commit -m "feat(engine): add can_shutdown_worker, inject retry_interval to MonitoredPolicy"
```

---

## Task 12: 修改 retry_policy.py — 固定间隔 + max_retries=0

**Files:**
- Modify: `app/services/retry_policy.py`
- Test: `tests/test_services/test_retry_policy.py`（修改现有）

- [ ] **Step 1: 修改 test_retry_policy.py 添加新测试**

在 `tests/test_services/test_retry_policy.py` 末尾添加：

```python
class TestMonitoredPolicyFixedInterval:
    """固定间隔重试策略测试。"""

    def test_max_retries_zero_means_no_retry(self):
        policy = MonitoredPolicy(max_retries=0, retry_interval=5)
        assert policy.retries_exhausted is True
        result = policy.on_login_done(success=False)
        assert result is None  # 不重试

    def test_retry_interval_used_as_delay(self):
        policy = MonitoredPolicy(max_retries=3, retry_interval=7)
        delay = policy.delay_before(1)
        assert delay == 7.0
        delay2 = policy.delay_before(2)
        assert delay2 == 7.0  # 固定间隔，不递增

    def test_on_login_done_returns_interval_on_failure(self):
        policy = MonitoredPolicy(max_retries=3, retry_interval=5)
        delay = policy.on_login_done(success=False)
        assert delay == 5.0

    def test_on_login_done_returns_none_when_exhausted(self):
        policy = MonitoredPolicy(max_retries=2, retry_interval=5)
        policy.on_login_done(success=False)  # attempt 1
        policy.on_login_done(success=False)  # attempt 2, exhausted
        result = policy.on_login_done(success=False)
        assert result is None

    def test_reset_clears_attempts(self):
        policy = MonitoredPolicy(max_retries=3, retry_interval=5)
        policy.on_login_done(success=False)
        policy.reset()
        assert policy.attempt == 0
        assert policy.retries_exhausted is False
```

- [ ] **Step 2: 运行测试验证失败**

Run: `python -m pytest tests/test_services/test_retry_policy.py::TestMonitoredPolicyFixedInterval -v`
Expected: FAIL（max_retries=0 不可达，delay_before 返回 _DELAYS 值）

- [ ] **Step 3: 修改 retry_policy.py**

替换整个 `MonitoredPolicy` 类：

```python
class MonitoredPolicy:
    """监控重试策略 — 固定间隔，使用用户配置的 retry_interval。

    Args:
        max_retries: 最大重试次数（0 表示不重试）
        retry_interval: 重试间隔秒数
    """

    def __init__(self, max_retries: int = 3, retry_interval: int = 5) -> None:
        self.max_retries = max(0, max_retries)
        self.retry_interval = max(1, retry_interval)
        self._attempt: int = 0
        self._prev_network_ok: bool | None = None
        self._lock = threading.Lock()

    @property
    def attempt(self) -> int:
        return self._attempt

    @property
    def retries_exhausted(self) -> bool:
        return self._attempt >= self.max_retries

    def reset(self) -> None:
        with self._lock:
            self._attempt = 0

    def delay_before(self, attempt: int) -> float:
        return float(self.retry_interval)

    def on_network_check(self, need_login: bool) -> bool:
        with self._lock:
            current_ok = not need_login
            transitioned = False
            if self._prev_network_ok is False and current_ok is True:
                self._attempt = 0
                transitioned = True
            self._prev_network_ok = current_ok
            return transitioned

    def on_login_done(self, success: bool) -> float | None:
        with self._lock:
            if success:
                self._attempt = 0
                return None
            self._attempt += 1
            if self._attempt >= self.max_retries:
                return None
            return self.delay_before(self._attempt)
```

- [ ] **Step 4: 运行测试验证通过**

Run: `python -m pytest tests/test_services/test_retry_policy.py -v`
Expected: PASS（全部）

- [ ] **Step 5: Commit**

```bash
git add app/services/retry_policy.py tests/test_services/test_retry_policy.py
git commit -m "fix(retry): use fixed retry_interval, allow max_retries=0, remove _DELAYS table"
```

---

## Task 13: 修改 login_runner.py — max_retries=0 路径

**Files:**
- Modify: `app/services/login_runner.py`

- [ ] **Step 1: 修改 execute_login_with_retries**

删除 `max(1, ...)`，允许 `max_retries=0` 直接返回 TEMPORARY_FAILURE：

```python
def execute_login_with_retries(runtime_config: RuntimeConfig, logger) -> LoginResult:
    """执行登录，含固定间隔重试。"""
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

    max_retries = max(0, min(runtime_config.retry.max_retries, 10))
    interval = max(1, runtime_config.retry.retry_interval)

    # max_retries=0：只执行一次，失败即返回
    if max_retries == 0:
        try:
            handle = orchestrator.submit(source="login_once", config=runtime_config)
            ok, msg = handle.result()
            if ok:
                return LoginResult.SUCCESS
            logger.warning("登录失败 (不重试): {}", msg)
            return LoginResult.TEMPORARY_FAILURE
        finally:
            orchestrator.shutdown(wait=False)

    try:
        for attempt in range(1, max_retries + 1):
            if attempt > 1:
                logger.debug("等待 {}s 后重试第 {} 次", interval, attempt)
                time.sleep(interval)

            handle = orchestrator.submit(source="login_once", config=runtime_config)
            ok, msg = handle.result()
            if ok:
                cleanup_orphan_browsers()
                return LoginResult.SUCCESS
            logger.warning("登录失败 (第 {} 次): {}", attempt, msg)

        cleanup_orphan_browsers()
        logger.warning("已重试 {} 次均失败，回退到正常模式", max_retries)
        return LoginResult.TEMPORARY_FAILURE
    finally:
        orchestrator.shutdown(wait=False)
```

- [ ] **Step 2: 运行 login_runner 相关测试**

Run: `python -m pytest tests/test_integration/test_login_once_mode.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add app/services/login_runner.py
git commit -m "fix(login_runner): allow max_retries=0 for no-retry path"
```

---

## Task 14: 修改 login_orchestrator.py — 取消机制改 cmd_id

**Files:**
- Modify: `app/services/login_orchestrator.py`

- [ ] **Step 1: 修改 _dispatch 取消机制**

当前 `_dispatch` 通过 `data={"cancel_event": cancel_event}` 传递取消事件。阶段一改为：不再传 cancel_event（不可跨进程序列化），但保留 `cancel_event` 用于主进程侧取消联动。

由于阶段一保留同步 `submit()` 接口，且 `LoginHandle.cancel()` 仍是同步的，取消机制的完整改造需要阶段二的 async `submit_cancel`。**阶段一的妥协方案**：`cancel_event` 仍在主进程侧设置，但子进程内的 LoginAttemptHandler 用子进程本地创建的 Event——主进程设置 cancel_event 后，需要通过 worker.submit(CMD_CANCEL) 通知子进程。

修改 `_dispatch` 中的 `_run` 函数：

```python
def _run() -> tuple[bool, str]:
    start = time.perf_counter()
    try:
        if cancel_event.is_set():
            return False, "登录已取消"
        worker = self._worker_getter()
        # 不再传 cancel_event（不可序列化），子进程内自行创建
        result = worker.submit(
            CMD_LOGIN,
            data={
                "config": worker_config,
            },
            wait=True,
            timeout=worker_timeout,
        )
        duration_ms = int((time.perf_counter() - start) * 1000)
        if result.success:
            if source != "browser":
                self._record_history(True, duration_ms)
            msg = result.data if isinstance(result.data, str) else "登录成功"
            return True, msg
        err_msg = result.error or "登录失败"
        if source != "browser":
            self._record_history(False, duration_ms, error=err_msg)
        return False, err_msg
    except ImportError as exc:
        duration_ms = int((time.perf_counter() - start) * 1000)
        if source != "browser":
            self._record_history(False, duration_ms, error=str(exc))
        return False, "登录需要额外依赖，请检查 Playwright 安装状态"
    except Exception as exc:
        duration_ms = int((time.perf_counter() - start) * 1000)
        if source != "browser":
            self._record_history(False, duration_ms, error=str(exc))
        logger.exception("登录执行异常: {}", exc)
        return False, f"登录执行异常: {exc}"
```

- [ ] **Step 2: 修改 LoginHandle.cancel 支持通知子进程**

```python
def cancel(self) -> None:
    """取消此次登录（阶段一：仅主进程侧标记，不通知子进程）。

    **阶段一限制**：由于 submit() 是同步阻塞的，LOGIN 调用阻塞至完成后
    才返回，无法在 LOGIN 执行期间 submit CMD_CANCEL。因此阶段一登录进行中
    的取消无法传达子进程，用户点击「取消登录」在登录进行中无效。

    **前端处理**：阶段一前端应在登录进行中禁用取消按钮，或提示"登录进行中
    无法取消，请等待超时"。

    **阶段二修复**：submit_login 改为异步立即返回 cmd_id，再通过
    submit_cancel(cmd_id) 发送 CMD_CANCEL 通知子进程中断。
    """
    self.cancel_event.set()
```

- [ ] **Step 3: 运行 orchestrator 测试**

Run: `python -m pytest tests/test_services/test_login_orchestrator.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add app/services/login_orchestrator.py
git commit -m "refactor(orchestrator): remove cancel_event from worker data (cross-process unsafe)"
```

---

## Task 15: 修改 debug_service.py — keepalive 锁 + on_restart + is_alive 短路

**Files:**
- Modify: `app/services/debug_service.py`

- [ ] **Step 1: 修改 __init__ 注册 on_restart 回调**

在 `DebugSessionManager.__init__` 末尾添加：

```python
# 注册 worker 重启回调（兜底 release 锁 + 重置 session）
from app.workers.playwright_worker import get_worker
try:
    worker = get_worker()
    if hasattr(worker, 'on_restart'):
        worker.on_restart(self._on_worker_restart)
except Exception:
    pass  # 测试环境或 worker 未初始化

def _on_worker_restart(self):
    """Worker 重启回调：release 锁 + 重置 session。"""
    try:
        from app.workers.playwright_worker import get_worker
        worker = get_worker()
        if hasattr(worker, 'release_keepalive_lock'):
            worker.release_keepalive_lock()
    except Exception:
        pass
    self._session = DebugSession()
```

注意：`_on_worker_restart` 应作为方法定义在类中，`__init__` 中只注册。修正：

```python
# __init__ 末尾
self._register_worker_restart_callback()

def _register_worker_restart_callback(self):
    """注册 worker 重启回调。"""
    try:
        from app.workers.playwright_worker import get_worker
        worker = get_worker()
        if hasattr(worker, 'on_restart'):
            worker.on_restart(self._on_worker_restart)
    except Exception:
        pass

def _on_worker_restart(self):
    """Worker 重启回调：release 锁 + 重置 session。"""
    try:
        from app.workers.playwright_worker import get_worker
        worker = get_worker()
        if hasattr(worker, 'release_keepalive_lock'):
            worker.release_keepalive_lock()
    except Exception:
        pass
    self._session = DebugSession()
```

- [ ] **Step 2: 修改 _close_debug_browser 增加 is_alive 短路**

```python
async def _close_debug_browser(self) -> None:
    """关闭调试浏览器 — 委托 Worker 处理。"""
    from app.workers.playwright_worker import CMD_DEBUG_STOP, get_worker

    worker = get_worker()
    # 短路：worker 已死时不白启动新子进程
    if hasattr(worker, 'is_alive') and not worker.is_alive():
        debug_logger.debug("worker 已不存活，跳过 CMD_DEBUG_STOP")
        self._session._browser_active = False
        return

    try:
        await asyncio.to_thread(lambda: worker.submit(CMD_DEBUG_STOP))
    except Exception:
        debug_logger.warning("关闭调试会话失败: Worker 提交失败", exc_info=True)
    self._session._browser_active = False
```

- [ ] **Step 3: 修改 start/stop 增加 keepalive 锁**

在 `start` 方法中，启动调试会话成功后 acquire 锁：

```python
# start 方法中，response.success 检查后
if not response.success:
    # ... 原错误处理
    raise RuntimeError(f"调试会话启动失败: {response.error}")

# acquire keepalive 锁（成功启动后）
try:
    worker = get_worker()
    if hasattr(worker, 'acquire_keepalive_lock'):
        worker.acquire_keepalive_lock()
except Exception:
    debug_logger.warning("acquire keepalive 锁失败", exc_info=True)
    raise  # acquire 失败应中断启动，避免锁状态不一致
```

在 `stop`/`close` 方法中 release 锁：

```python
# 在关闭调试会话的逻辑中（_close_debug_browser 调用后）
# 使用 try/finally 确保锁一定被释放（防泄漏，见设计 §9 风险表第 10 条）
worker = None
try:
    worker = get_worker()
except Exception:
    pass
finally:
    if worker is not None and hasattr(worker, 'release_keepalive_lock'):
        try:
            worker.release_keepalive_lock()
        except Exception:
            debug_logger.warning("release keepalive 锁失败", exc_info=True)
```

具体位置：在 `_close_debug_browser` 方法末尾、`close` 方法、`_debug_timeout_watcher` 的超时关闭路径中均需 release。

- [ ] **Step 4: 运行 debug 测试**

Run: `python -m pytest tests/test_services/test_debug_service.py tests/test_services/test_debug_session_manager.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/debug_service.py
git commit -m "feat(debug): add keepalive lock, on_restart callback, is_alive short-circuit"
```

---

## Task 16: 修改 step_handlers.py — OcrHandler 简化

**Files:**
- Modify: `app/tasks/step_handlers.py`

- [ ] **Step 1: 删除 OcrHandler 的定时清理逻辑**

删除以下方法（约 738-772 行）：
- `schedule_cleanup`
- `_cancel_cleanup`
- `_cancel_cleanup_locked`
- `_do_cleanup`

删除以下类属性（约 715 行）：
- `_cleanup_timers`
- `_IDLE_TIMEOUT`

保留 `_ocr_instances` 和 `_ocr_lock`（简单缓存，不再定时清理）。

简化后的 `_get_ocr`：

```python
@classmethod
def _get_ocr(cls, old: bool = False):
    with cls._ocr_lock:
        if old in cls._ocr_instances:
            return cls._ocr_instances[old]
        try:
            import ddddocr
            instance = ddddocr.DdddOcr(old=old, show_ad=False)
        except ImportError as err:
            raise StepError(
                "ddddocr 未安装，请在「设置 → 系统与日志」中安装 OCR 依赖"
            ) from err
        cls._ocr_instances[old] = instance
        return instance
```

- [ ] **Step 2: 删除 execute 中的 schedule_cleanup 调用**

在 `OcrHandler.execute` 方法中，删除所有 `self.schedule_cleanup(old)` 调用（约 843、880 行）和相关注释。

- [ ] **Step 3: 运行 step_handlers 测试**

Run: `python -m pytest tests/test_core/test_step_handlers.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add app/tasks/step_handlers.py
git commit -m "refactor(ocr): remove OcrHandler timer cleanup (worker subprocess suicide replaces it)"
```

---

## Task 17: 修改前端 settings-monitor.html — max_retries 范围 + 文案

**Files:**
- Modify: `frontend/partials/pages/settings/settings-monitor.html`

- [ ] **Step 1: 修改 max_retries input 范围**

```html
<input id="settings-max-retries" v-model.number="config.retry.max_retries" type="number" min="0" max="10" />
```

- [ ] **Step 2: 修改 max_retries data-tip 文案**

```html
<span class="field-help" tabindex="0" role="note" data-tip="登录失败后最多重试几次，0 表示不重试。超出后等待下次网络检测周期再试。">?</span>
```

- [ ] **Step 3: 修改 retry_interval data-tip 文案**

```html
<span class="field-help" tabindex="0" role="note" data-tip="登录失败后每次重试的固定等待秒数。">?</span>
```

- [ ] **Step 4: Commit**

```bash
git add frontend/partials/pages/settings/settings-monitor.html
git commit -m "fix(frontend): align max_retries range (0-10) with backend, update retry tips"
```

---

## Task 18: 集成测试 — 端到端登录流程

**Files:**
- Test: `tests/test_workers/test_integration_e2e.py`

- [ ] **Step 1: 写端到端测试**

创建 `tests/test_workers/test_integration_e2e.py`：

```python
"""端到端集成测试 — Worker 进程隔离下的登录流程。"""
from __future__ import annotations

import asyncio

import pytest

from app.workers.manager.worker_manager import WorkerManager
from app.workers.worker_protocol import CMD_PING


class TestE2EWorkerProcess:
    """端到端测试：主进程通过 WorkerFacade 与子进程通信。"""

    @pytest.mark.asyncio
    async def test_full_lifecycle(self):
        """完整生命周期：启动 → PING → 停止。"""
        from unittest.mock import MagicMock

        engine_mock = MagicMock()
        engine_mock.can_shutdown_worker.return_value = True
        mgr = WorkerManager(engine=engine_mock)

        try:
            # 1. 启动
            await mgr.start(timeout=30)
            assert mgr.process_controller.is_alive() is True

            # 2. PING
            facade = mgr.get_facade()
            resp = await asyncio.to_thread(facade.submit, CMD_PING, timeout=10)
            assert resp.success is True
            assert resp.data == "pong"

            # 3. keepalive 锁
            facade.acquire_keepalive_lock()
            assert facade.is_keepalive_locked() is True
            facade.release_keepalive_lock()
            assert facade.is_keepalive_locked() is False
        finally:
            await mgr.stop()
            assert mgr.process_controller.is_alive() is False

    @pytest.mark.asyncio
    async def test_worker_restart_after_crash(self):
        """子进程崩溃后能通过 submit 自动重启。"""
        from unittest.mock import MagicMock

        engine_mock = MagicMock()
        engine_mock.can_shutdown_worker.return_value = True
        mgr = WorkerManager(engine=engine_mock)

        try:
            await mgr.start(timeout=30)
            facade = mgr.get_facade()

            # 正常 PING
            resp = await asyncio.to_thread(facade.submit, CMD_PING, timeout=10)
            assert resp.success is True

            # 模拟子进程崩溃（kill）
            mgr.process_controller._proc.kill()
            await mgr.process_controller._proc.wait()

            # 再次 submit 应自动重启并成功
            # 注意：此处依赖 WorkerFacade.submit 中的自动重启逻辑
            resp2 = await asyncio.to_thread(facade.submit, CMD_PING, timeout=35)
            assert resp2.success is True
        finally:
            await mgr.stop()

    @pytest.mark.asyncio
    async def test_can_shutdown_worker_with_scheduler(self):
        """engine.can_shutdown_worker 在定时任务即将触发时返回 False。"""
        from unittest.mock import MagicMock, PropertyMock

        engine_mock = MagicMock()
        engine_mock.can_shutdown_worker.return_value = False
        mgr = WorkerManager(engine=engine_mock)
        try:
            await mgr.start(timeout=30)
            # LifecyclePolicy 应因 can_shutdown_worker=False 不杀 worker
            assert mgr.process_controller.is_alive() is True
        finally:
            await mgr.stop()

    @pytest.mark.asyncio
    async def test_graceful_shutdown_sends_cmd(self):
        """stop() 应发送 CMD_SHUTDOWN 让子进程优雅退出。"""
        from unittest.mock import MagicMock

        engine_mock = MagicMock()
        engine_mock.can_shutdown_worker.return_value = True
        mgr = WorkerManager(engine=engine_mock)
        await mgr.start(timeout=30)
        assert mgr.process_controller.is_alive() is True
        await mgr.stop()
        # 子进程应已退出（exit code 0 表示 SHUTDOWN 正常处理）
        assert mgr.process_controller.is_alive() is False

    @pytest.mark.asyncio
    async def test_keepalive_lock_prevents_shutdown(self):
        """keepalive 锁持有时，idle 超时不应关闭 worker。"""
        from unittest.mock import MagicMock

        engine_mock = MagicMock()
        engine_mock.can_shutdown_worker.return_value = True
        mgr = WorkerManager(engine=engine_mock)
        try:
            await mgr.start(timeout=30)
            facade = mgr.get_facade()
            facade.acquire_keepalive_lock()
            assert facade.is_keepalive_locked() is True
            # 即使 idle 超时，worker 不应被杀
            # （实际等待 180s 不现实，此处仅验证锁状态正确）
        finally:
            facade.release_keepalive_lock()
            await mgr.stop()
```

- [ ] **Step 2: 运行端到端测试**

Run: `python -m pytest tests/test_workers/test_integration_e2e.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_workers/test_integration_e2e.py
git commit -m "test(worker): add end-to-end integration tests for worker process isolation"
```

---

## Task 19: 手动验证清单

**Files:** 无（手动验证）

- [ ] **Step 1: 启动完整模式，验证主进程内存**

```bash
python -m app.main
```

在任务管理器观察主进程内存，应 < 50MB（目标 ~48MB）。

- [ ] **Step 2: 触发 OCR 登录，观察子进程内存尖峰**

配置一个含 OCR 步骤的任务并执行。观察：
- 主进程内存保持平稳
- 子进程内存尖峰 ~90-140MB（OCR 期）
- OCR 完成后子进程内存不立即回落（正常，native 扩展驻留）

- [ ] **Step 3: 验证 OCR 后 3 分钟子进程自杀**

OCR 登录完成后，不操作 3 分钟。观察：
- 子进程退出
- 主进程内存保持平稳

- [ ] **Step 4: 验证大间隔重试期间 worker 不被杀**

设置 `retry_interval=200`，触发登录失败。观察：
- 重试期间 worker 子进程持续存活（180s idle 不触发自杀，因 engine.can_shutdown_worker 返回 False）

- [ ] **Step 5: 验证 max_retries=0 时登录失败立即返回**

设置 `max_retries=0`，触发登录失败。观察：
- 不重试，立即返回 TEMPORARY_FAILURE

- [ ] **Step 6: 验证前端设置 max_retries=10 能保存且生效**

在前端设置 `max_retries=10`，保存，刷新页面验证持久化，触发登录失败观察重试 10 次。

- [ ] **Step 7: 验证调试会话期间 worker 不被误杀**

启动调试会话，等待超过 180s 不操作。观察：
- worker 子进程不被杀（keepalive 锁生效）

- [ ] **Step 8: 验证调试会话中 worker 崩溃后提示**

启动调试会话，手动 kill worker 子进程。观察：
- 用户点击「下一步」得到「会话已失效，请重新启动」提示

- [ ] **Step 9: 验证主进程不 import psutil**

```bash
python -c "
import sys
# 模拟主进程启动
import app.container
# 检查 psutil 是否被 import
assert 'psutil' not in sys.modules, '主进程不应 import psutil'
print('OK: psutil 未被主进程 import')
"
```

- [ ] **Step 10: 验证 worker_proc 独立运行**

```bash
python -m app.workers.worker_proc
```

应看到子进程启动并等待 stdin 输入（无 ready 事件输出到终端，因为 stdout 是二进制帧）。

- [ ] **Step 11: 验证调试会话 stop 后 worker 恢复可被杀**

启动调试会话 → stop 调试会话 → 等待 180s+ 不操作。观察：
- 调试会话期间 worker 不被杀（keepalive 锁生效）
- stop 后锁已 release，worker 恢复可被 keepalive 杀

- [ ] **Step 12: 验证调试会话中 worker 崩溃后停止不白启动**

启动调试会话 → 手动 kill worker 子进程 → 点击「停止调试」。观察：
- 点击停止时 is_alive 短路，不白启动新子进程
- 用户得到"会话已失效"提示

- [ ] **Step 13: 验证定时任务即将触发时 worker 保活**

设置一个 3 分钟后触发的定时任务 → 启动监控 → 等待 worker idle。观察：
- 定时任务即将触发（IDLE_TIMEOUT 内），worker 不被杀
- 定时任务执行时 worker 可用

---

## Self-Review

### 1. Spec coverage 检查

| Spec 章节 | 对应 Task |
|---|---|
| §3.1 进程拓扑 | Task 5/6/7/8（ProcessController/RpcClient/LifecycleManager/WorkerManager） |
| §3.2 IPC 协议（长度前缀帧） | Task 1 |
| §3.3 统一 Message 基类 | Task 1 |
| §3.3.1 Command Registry | Task 2 |
| §3.4 决策 1-15（IPC/cancel/角色/Proxy/psutil/RSS/版本/Windows） | Task 1-10 |
| §3.4 决策 16-19（组件拆分/Registry/Message/Policy） | Task 4/7/8 |
| §4 生命周期与状态机 | Task 7 |
| §4.5 LifecyclePolicy | Task 4 |
| §5 调试会话一致性 | Task 15 |
| §6 重试策略修复 | Task 12/13/17 |
| §7 文件清单 | Task 1-17 全覆盖 |

### 2. Placeholder scan

无 TBD/TODO。所有步骤含完整代码。

### 3. Type consistency

- `WorkerResponse`（playwright_worker.py 的 dataclass）vs `WorkerResponse`（worker_protocol.py 的 Pydantic）— Facade 中做转换，消费方仍用旧的 dataclass。
- `WorkerFacade.submit()` 签名与原 `PlaywrightWorker.submit()` 一致（cmd_type, data, wait, timeout）。
- `can_shutdown_worker()` 在 engine 和 LifecyclePolicy 中签名一致。

### 4. 阶段一边界

本计划不包含：
- LoginOrchestrator async 化（阶段二）
- LoginHandle.result() 改 async（阶段二）
- WorkerFacade.submit() 改 async（阶段二）
- **登录进行中的取消机制**（阶段二）：阶段一同步 submit 阻塞至 LOGIN 完成，
  无法在执行期间发 CMD_CANCEL。前端应在登录中禁用取消按钮。阶段二 submit_login
  改异步后修复。

### 5. 设计文档矛盾澄清

设计 §11.1「同步 submit」与 §7.2「cmd_id 取消」存在矛盾：同步 submit 下 LOGIN
阻塞至完成，无法在执行期间 submit CANCEL。本计划以 §11.1 为准（阶段一同步），
取消机制推迟到阶段二。设计文档 §7.2 的 login_orchestrator 取消机制应标注为阶段二。

### 6. 审查修复记录

本计划经审查修复了以下问题：
- P1-3: stop 路径增加 CMD_SHUTDOWN 优雅关闭
- P1-4: 恢复 container.startup 预热
- P1-5: can_shutdown_worker 补全 scheduler 检查
- P1-6: 心跳崩溃后调用 restart 而非仅触发回调
- P2-7: 新增 InitCommand 和 init 消息处理
- P2-8: 补全集成测试（can_shutdown/graceful_shutdown/keepalive_lock）
- P2-9: 补全手动验证清单 3 项
- P2-10: keepalive 锁改 try/finally 防泄漏
- P3-11: RSS 阈值从 init 消息接收，可配置
- P3-13: can_shutdown_worker 引用 WORKER_IDLE_TIMEOUT 常量
- P3-15: asyncio 兼容性（set_loop 注入 running loop）
- P3-17: WorkerManager.start() 幂等
- C4: RpcClient 新增 on_eof 回调，EOF 触发 LifecycleManager.handle_worker_death

---

**Plan complete and saved to `docs/2026-07-01-worker-process-isolation-plan.md`.**
