# Campus-Auth Rust 迁移设计

> 将 Campus-Auth 的**系统职能层**(配置、网络监控、托盘、自启动、任务调度、前端桥接)迁移至 Rust + Tauri 2.0;**浏览器自动化与 OCR 完全保留在 Python Worker**,由 Rust 按需唤醒子进程派发执行。

## 设计原则(关键边界)

本设计把代码库切成两半,边界严格:

- **Rust 负责"何时做、怎么管"**:进程生命周期、配置、调度、监控、UI 桥、系统对接。**不碰**任何 Playwright 调用、DOM 操作、截图、OCR 推理。
- **Python Worker 负责"怎么做登录"**:现有 `app/workers/playwright_worker.py` 的 8 种 `CMD_*` 命令、`app/tasks/` 的 step 引擎(868 行 `step_handlers.py`)、`app/utils/login.py`、OCR step —— **逐行不动**,只把入口从"in-process queue"换成"stdin/stdout 行协议"。

这条边界让最复杂、最容易出错的部分(step 引擎、浏览器生命周期、stealth 脚本、低资源路由、channel 分发)**零迁移成本**,Rust 侧不重新实现任何业务逻辑。

## 背景

当前 Campus-Auth 为 Python 3.12+ 项目,实测核心业务代码约 **7,200 行**(`app/services/` + `app/tasks/` + `app/network/`),加上 `main.py`(660)、`app/utils/`、`app/workers/`、`app/api/`(16 个路由文件、72 个 HTTP 端点 + 1 个 WebSocket)、`app/ui/`,合计 **158 个 .py 文件、44,000+ 行**(含测试与脚手架)。FastAPI + Vue.js 前后端分离。主要痛点:

- Python 运行时内存占用高(实测 ~80-120MB 常驻)
- 分发依赖 Python 环境(现有 `start.go` / `start.sh` 启动器负责下载 uv + Python,逻辑分散在 Go/Bash 两套实现里)
- 启动速度慢(~1-2s import 链)
- `asyncio` + `threading` 混合并发模型:`engine.py` 单文件就有 119 处并发原语,`PlaywrightWorker` 自己跑独立 asyncio loop + 守护线程,维护成本高

## 决策记录

| 决策 | 选择 | 理由 |
|------|------|------|
| 桌面框架 | Tauri 2.0 | 原生窗口、系统托盘、可销毁 WebView 释放内存 |
| 异步运行时 | tokio | 业界标准,Tauri 原生支持 |
| **Worker 调用模型** | **重试驱动保活**:登录成功才销毁,失败保持复用直到重试耗尽;debug 会话独立管理 | 兼顾"空闲 0MB"与"断网连续重试不冷启动";见「Worker 调用模型」 |
| **Worker IPC** | **stdin/stdout**(NDJSON 行协议) | 同机单 Worker 无需端口/鉴权/防火墙;EOF 自动感知崩溃 |
| Python 环境管理 | **Rust 实现下载逻辑**(替代 start.go/start.sh) | 单一实现,带镜像源 fallback + SHA256 校验 |
| **Playwright 浏览器** | **完全由 Python Worker 按 `browser_channel` 配置执行** | Rust 不关心 channel;保留 playwright/firefox/msedge/chrome/custom 全部选项 |
| **OCR (ddddocr)** | **保留在 Python Worker**,启动时 eager import | Worker 销毁即释放;避免每次冷启动重载模型 |
| 前端框架 | 保留现有 CDN Vue 3,**不引入 Vite** | 前端调用改为命名 invoke + `js/api.js` 封装层(见「前端改造」) |
| 前后端契约 | **功能 parity**(非端点 parity) | icons/docs 等用 `convertFileSrc`/静态资源,不镜像成 HTTP 端点 |
| 配置格式 | 复用现有 `~/.campus_network_auth/` JSON | Python 版数据无缝继承 |
| 加密 | 复用 Fernet(SHA256 派生 key)格式 | 密码文件兼容,Python 版可直接读 |

---

## 目标架构

```
┌─────────────────────────────────────────────────────┐
│ Tauri Rust 进程(常驻)                                │
│                                                     │
│   WebView2 (Vue 前端) ──Tauri IPC──► commands/      │
│                                                     │
│   commands → application → domain                   │
│                  │        ◄── infrastructure        │
│                  │                                  │
│                  ├── runtime(网络监控循环)          │
│                  └── worker_manager ──stdio──┐      │
└──────────────────────────────────────────────┼──────┘
                                               │ stdin ▼ stdout
                          ┌────────────────────▼──────────────┐
                          │ Python Worker 子进程              │
                          │ (重试驱动保活:                    │
                          │  登录成功才销毁,失败复用重试;     │
                          │  debug 会话独立管理)              │
                          │                                   │
                          │  PlaywrightWorker (8 种 CMD)      │
                          │  ├── login                        │
                          │  ├── debug_start/step/stop        │
                          │  ├── browser_acquire/release      │
                          │  │   /close/health_check          │
                          │  └── shutdown                     │
                          │  + step 引擎(868 行,不改)        │
                          │  + OCR(ddddocr,eager import)      │
                          │  + Playwright(channel 不变)       │
                          └───────────────────────────────────┘
```

### 内存目标(相对指标优先,绝对值仅参考)

| 场景 | Python 现状 | Rust + Tauri 目标 |
|------|------------|------------------|
| 空闲(托盘驻留) | ~80-120MB | **比 Python 版降低 50% 以上**(参考值 ~15-40MB) |
| 界面打开 | ~80-120MB | 与 Python 版持平或略低(~40-80MB,WebView2 host) |
| 登录中 | ~80-120MB | Rust 主进程 + Python Worker(~80-120MB,临时) |

> ⚠️ **不设 ≤15MB 硬指标**。Windows 上 Tauri 主进程 + WebView2 runtime + 辅助进程的统计口径因任务管理器而异,实测可能 30-60MB。真正的验收标准是**"空闲稳态比 Python 版低 50%+"**,这是用户能感知的差异。绝对内存优化(销毁 WebView2 渲染进程)作为可选项,见「WebView 销毁策略」章节,推迟到全部功能完成后再决定。

---

## 模块结构

### Rust 侧

```
src-tauri/src/
├── main.rs                          # Tauri 入口
├── lib.rs
│
├── commands/                        # Tauri 命令层(薄壳,参数校验 + 调用 application)
│   ├── mod.rs
│   ├── config.rs                    # get_config / save_config / ...
│   ├── monitor.rs                   # get_status / start_monitor / ... (8)
│   ├── tasks.rs                     # list_tasks / save_task / ... (7)
│   ├── scheduled_tasks.rs           # list_scheduled / ... (7)
│   ├── profiles.rs                  # list_profiles / ... (7)
│   ├── scripts.rs                   # list_scripts / ... (6)
│   ├── autostart.rs                 # get_autostart / enable / ... (5)
│   ├── ocr.rs                       # ocr_status / ocr_install / ... (3)
│   ├── browsers.rs                  # get_browsers / install_playwright (2)
│   ├── debug.rs                     # debug_start / debug_step / stop (4)
│   ├── repo.rs                      # repo_fetch / repo_get_task (2)
│   ├── tools.rs                     # get_task_recorder / get_docs (3)
│   ├── background.rs                # upload_background / fetch_url / ... (4)
│   ├── system.rs                    # get_system_info / shutdown / uninstall (6)
│   └── history.rs                   # get_login_history / clear_history (2)
│
├── application/                     # 应用服务层(编排 domain + infrastructure + worker)
│   ├── mod.rs
│   ├── monitor_service.rs           # 网络监控编排(对应 app/services/monitor_service.py)
│   ├── login_service.rs             # 登录编排:检测→派发 Worker→重试→记历史
│   ├── profile_service.rs           # 配置方案编排
│   ├── task_service.rs              # 定时任务 CRUD + 调度
│   ├── debug_service.rs             # Debug 会话编排(对应 app/services/debug_service.py)
│   └── repo_service.rs              # 自更新
│
├── domain/                          # 领域层(纯数据 + 规则,无外部依赖)
│   ├── mod.rs
│   ├── config.rs                    # AppConfig + Profile 模型 + 校验
│   ├── network_state.rs             # NetworkState 枚举(UNKNOWN/CONNECTED/DISCONNECTED/PORTAL)
│   ├── state_machine.rs             # 状态转换规则(对应 app/network/decision.py)
│   ├── task.rs                      # ScheduledTask / ScriptTask 模型(不含 step 引擎)
│   └── crypto_spec.rs               # 加密格式规约(Fernet 兼容)
│
├── infrastructure/                  # 基础设施层
│   ├── mod.rs
│   ├── persistence/
│   │   ├── config_store.rs          # ~/.campus_network_auth/ JSON 读写
│   │   ├── history_store.rs         # 登录历史 + 任务执行历史
│   │   └── task_store.rs            # tasks/ + scripts/ 目录管理
│   ├── network_probe.rs             # TCP/HTTP/Ping 探测(对应 app/network/probes.py, 232 行)
│   ├── autostart.rs                 # 开机自启动:winreg / plist(LaunchAgents) / xdg
│   ├── process_lock.rs              # PID 文件 + create_time 校验 + 端口检测
│   ├── crypto.rs                    # Fernet 兼容加解密(SHA256 派生 key)
│   ├── python_bootstrap.rs          # **uv + Python 下载**(替代 start.go/start.sh)
│   ├── shell_executor.rs            # Shell 命令执行(对应 ScriptRunner + ShellCommandPolicy)
│   └── update.rs                    # git/zip 自更新(对应 app/services/...)
│
├── worker/                          # Python Worker 子进程管理(核心新增)
│   ├── mod.rs
│   ├── manager.rs                   # **重试驱动保活**:Idle ↔ Alive{child, stdin, stdout}
│   ├── process.rs                   # 子进程启动/EOF 感知/强制 kill
│   ├── protocol.rs                  # NDJSON 编解码(行协议,stdin/stdout)
│   └── bootstrap.rs                 # uv sync + Playwright 环境检查
│
├── runtime/                         # 运行时(仅事件循环)
│   ├── mod.rs
│   └── monitor_loop.rs              # tokio::select! 网络检测循环
│
├── tray/                            # 系统托盘
│   └── mod.rs                       # pystray → tauri-plugin-tray 迁移
│
├── frontend_bridge/                 # 前端桥接(WebSocket → Tauri 事件)
│   └── mod.rs                       # emit("log-message"), emit("status-update")
│
└── utils/
    ├── mod.rs
    ├── logging.rs                   # tracing 初始化 + 文件输出
    └── platform.rs                  # 平台检测
```

### Python Worker 侧(核心业务不动,外围适配)

```
worker/                              # 从 app/workers/ 抽出,作为独立可执行单元
├── pyproject.toml                   # 依赖:playwright, ddddocr, onnxruntime, cryptography
├── uv.lock
├── main.py                          # 【新增】stdin/stdout 主循环,命令分发
├── playwright_worker.py             # 【不动】PlaywrightWorker + 8 种 CMD_* + submit()
├── step_handlers.py                 # 【不动】868 行 step 引擎(INPUT/CLICK/.../OCR)
├── browser_runner.py                # 【不动】
├── login.py                         # 【不动】LoginAttemptHandler
├── script_runner.py                 # 【不动】
├── playwright_bootstrap.py          # 【不动】channel 配置 + Playwright 环境检查
└── ocr_handler.py                   # 【不动】OCR step 处理(主循环启动时 eager import ddddocr)
```

改动量估计:新增 `main.py`(~40 行)作为 stdin/stdout 主循环,直接调用现有 `PlaywrightWorker.submit()` 入口。`_dispatch`、所有 `_handle_*`、step 引擎、浏览器生命周期全部不动。进度回调需 stdout 适配(约 10 行),cancel_event 需进程内 Event 桥接(约 10 行)。**核心业务零改动,外围适配预计 5-15% 胶水代码**。

---

## Worker 调用模型(核心设计)

### 重试驱动保活(按登录成败决定销毁)

核心规则:**登录成功才销毁 Worker,失败保持复用直到重试耗尽。**

```
登录请求到达
    │
    ▼
Worker 不存在? ──是──► 启动 Worker(冷启动 3-5s)
    │否                    │
    ▼                       ▼
复用已有 Worker ◄───────────┘
    │
    ▼
发送 login 命令
    │
    ▼
┌─ 成功 ──► 销毁 Worker ◄───────── 空闲时 0MB
│   │
│   ▼
│   返回结果
│
└─ 失败 ──► 重试计数 +1
        │
        ▼
    重试次数 < 上限? ──是──► (复用同一 Worker)重新 login ──► 回到上面分支
        │否                              ▲
        ▼                                │
    销毁 Worker,返回最终失败             │
                                         │
   注:重试期间 Worker 不重启,Playwright  ┘
       浏览器 context 复用,重试仅 0.1-1s
```

**对比两种销毁策略:**

| 策略 | 连续重试 N 次的总耗时 | 实现 |
|---|---|---|
| ❌ 每次登录后销毁 | N × (冷启动 3-5s + 登录) | 断网场景体验差 |
| ✅ **成功才销毁(本方案)** | 冷启动 1 次 + N × (复用重试 0.1-1s) | 断网场景可接受 |

校园网断流一天 3-4 次,断流后常需连续重试 2-3 次才成功。"成功才销毁"让首次冷启动后,后续重试复用浏览器 context,**单次重试从 3-5s 降到 0.1-1s**。

### 生命周期状态机

```
                    login 请求
                        │
         ┌──────────────▼──────────────┐
         │  ensure_worker_alive()       │
         │  (若 Idle 则启动)            │
         └──────────────┬──────────────┘
                        │
              ┌─────────▼─────────┐
              │  login(cmd)        │
              └─────────┬─────────┘
                        │
              ┌─────────▼─────────┐
         ┌────┤  success?          │
         │    └─────────┬─────────┘
         │              │
    yes  │         no   ▼
         │    ┌──────────────────┐
         │    │ retry < max?     │
         │    └────┬─────────┬───┘
         │     yes │         │ no
         │         │         │
         ▼         ▼         ▼
   stop_worker  (loop)   stop_worker
   → Idle                → Idle
```

### Debug 会话(独立生命周期)

Debug 与登录的保活逻辑**解耦**——Debug 是显式会话,有自己的起止:

```
debug_start  → 启动/复用 Worker,进入 DebugSession
debug_step   → 要求 DebugSession 存活(否则报错)
debug_stop   → 结束会话,销毁 Worker
```

Debug 会话期间 Worker 不因登录成败销毁。Python 侧 `_handle_debug_start` 已是"保持 page 直到 debug_stop"的逻辑,无需改动。

### Rust 侧 `worker/manager.rs` 接口

```rust
pub enum WorkerState {
    Idle,
    Alive { child: Child, stdin: ChildStdin, stdout: BufReader<ChildStdout> },
}

pub struct WorkerManager {
    state: Mutex<WorkerState>,
    retries: u32,
}

impl WorkerManager {
    /// 登录:带重试。成功则销毁 Worker,失败重试到上限才销毁
    pub async fn login(&self, config: LoginConfig, max_retries: u32) -> Result<LoginResult>;

    /// Debug 会话:显式起止
    pub async fn debug_start(&self, ...) -> Result<DebugSession>;
    pub async fn debug_step(&self, ..., step_index: usize) -> Result<StepResult>;
    pub async fn debug_stop(&self, ...) -> Result<()>;

    /// 兜底:Rust 退出 / stdout EOF(Worker 崩溃)时强制 kill
    async fn force_cleanup(&self);
}
```

**崩溃检测**:`stdout` 读到 EOF 即 Worker 死亡,自动从 `Alive` 回到 `Idle`,下次调用重新冷启动。无需心跳。

---

## IPC 协议(Rust ↔ Python Worker)

### Transport:stdin/stdout NDJSON(非 TCP)

**用 stdin/stdout 而非 TCP**,理由:

| 维度 | TCP | **stdin/stdout(本方案)** |
|---|---|---|
| 端口占用 | 随机端口需管理 | 无 |
| 鉴权 | 需 token 防本机注入 | 父子进程管道天然隔离,**无需鉴权** |
| 防火墙 | 可能弹窗 | 不涉及 |
| 崩溃检测 | 需心跳 | **EOF = 进程死亡**,自动感知 |
| 关闭语义 | 需双方 close | 关闭 stdin / kill child 即可 |

同机、单 Worker、无多客户端场景下,stdio 是最简方案。

### 帧格式

- 每条消息一行 JSON(NDJSON,Newline-Delimited JSON)
- UTF-8,以 `\n` 分隔
- 单行最大 16 MB(对齐现有 WebSocket size 预检,`application.py:337`)
- **Rust → Worker**:写 child.stdin
- **Worker → Rust**:读 child.stdout(stderr 单独分流到日志,不混入协议)

### 协议版本与错误分类

- 每条消息带 `"v": 1`
- 错误:`{"id": "...", "success": false, "error": {"code": "TIMEOUT|CRASH|BROWSER_FAIL|OCR_NOT_INSTALLED|PROTOCOL|UNKNOWN", "message": "..."}}`

### 消息格式(保留现有 CMD_* 语义)

```jsonc
// Rust → Python(stdin):命令(对应 WorkerCommand)
{
  "v": 1, "id": "cmd_001",
  "type": "login",                       // 或 debug_start / debug_step / debug_stop
                                         //    / browser_acquire / browser_release
                                         //    / browser_close / browser_health_check
                                         //    / shutdown / cancel
  "data": {                              // 对应现有 WorkerCommand.data
    "config": {...},                     //   登录:完整 AppConfig(含 browser_channel)
    "cancel_token": "xxx",               //   取消标识(替代 threading.Event)
    "task_data": {...}                   //   debug 用
  }
}

// Python → Rust(stdout):结果(对应 WorkerResponse)
{"v": 1, "id": "cmd_001", "success": true, "data": "登录成功"}

// Python → Rust(stdout):进度推送(对应现有进度回调)
{"v": 1, "id": "cmd_001", "type": "progress", "step": "打开浏览器", "percent": 30}

// Python → Rust(stdout):日志推送(替代现有 ws_manager.emit_log)
{"v": 1, "id": "cmd_001", "type": "log", "level": "info", "message": "..."}
```

### cancel_event 的处理

现有 `WorkerCommand.cancel_event` 是 `threading.Event`,跨进程不能传。改为:
- Rust 侧维护 `HashMap<cmd_id, CancellationToken>`
- 取消时 Rust 往 stdin 写一条 `{"type": "cancel", "id": "cmd_001"}`
- Python 侧 `main.py` 收到 cancel 命令后设置一个进程内 `threading.Event`,现有 `LoginAttemptHandler` 检查 cancel_event 的逻辑不变

> 这是 Python 侧少数需要适配的点之一(见「Python Worker 改动边界」)。

### Python 主循环(`worker/main.py`,新增)

```python
# 伪代码
import sys, json, asyncio, threading
from playwright_worker import PlaywrightWorker, WorkerCommand

worker = PlaywrightWorker()
worker.start()
cancel_events: dict[str, threading.Event] = {}

async def main():
    loop = asyncio.get_event_loop()
    # 从 stdin 逐行读,丢到 executor 避免阻塞 asyncio
    for raw_line in sys.stdin:
        msg = json.loads(raw_line)
        cmd_id = msg["id"]
        if msg["type"] == "shutdown":
            worker.stop(); return
        if msg["type"] == "cancel":
            if cmd_id in cancel_events: cancel_events[cmd_id].set()
            continue
        # 构造进程内 Event(供 cancel 用),复用现有 submit/queue 入口
        ev = threading.Event()
        cancel_events[cmd_id] = ev
        result = await loop.run_in_executor(
            None, lambda: worker.submit(
                msg["type"], data={**msg["data"], "cancel_event": ev},
                wait=True, timeout=300,
            )
        )
        print(json.dumps({"v":1,"id":cmd_id,"success":result.success,"data":result.data}))
        sys.stdout.flush()
        cancel_events.pop(cmd_id, None)
```

关键:`worker.submit(...)` 是现有 `PlaywrightWorker` 的公开入口(`playwright_worker.py:226`),**完全复用**——它内部把命令塞进 queue、唤醒 `_async_run`、走 `_dispatch` → `_handle_login` 等现有路径。`main.py` 只是把 stdin/stdout 接到这个入口上。

### Python Worker 改动边界(诚实评估)

**核心业务零改动**:`_dispatch`、`_handle_login`、`_handle_debug_*`、step 引擎、浏览器生命周期、OCR handler 全部不动。

**外围适配需要小改(预计 5-15% 的胶水代码)**:

| 点 | 现状 | 适配方式 |
|---|---|---|
| 命令入口 | `submit()` + `queue.Queue` | `main.py` 包装 stdin→submit,不改 submit 本身 |
| `cancel_event` | `threading.Event` 跨进程序列化 | adapter 维护 `dict[cmd_id, Event]`,cancel 命令置位 |
| 进度回调 | 回调函数直接调 ws_manager | adapter 把回调输出改成 stdout JSON |
| 日志输出 | loguru 写文件 + ws | loguru 加一个 stdout sink(协议帧),文件 sink 保留 |
| 孤儿浏览器清理 | `cleanup_orphan_browsers()` 用 psutil | 保留(Worker 启动时调一次) |

**不改动**:`_dispatch`、所有 `_handle_*`、`_start_browser`、`_launch_browser`、`_build_launch_args`、step_handlers 全部、LoginAttemptHandler、ScriptRunner、playwright_bootstrap。

---

## OCR 处理(关键决策)

### 现状

任务 step 类型里有 `OCR`(`step_handlers.py:724`),依赖 `ddddocr + onnxruntime`,模型加载冷启动 1-3 秒。

### 设计

- OCR step 处理**完全保留在 Python Worker**,代码不动
- **Worker 启动时 eager import ddddocr**:在 `main.py` 主循环启动前 `import ddddocr`,模型在进程启动时就加载
- Worker 销毁(ddddocr 随进程退出)→ 内存释放

这样:
- 登录任务含 OCR step:Worker 启动时已加载模型,执行 OCR step 零延迟
- Worker 用完销毁:模型内存一起释放,空闲 0MB
- 冷启动成本固定 = 进程启动成本,不再因"用完销毁"而放大

### OCR 安装管理(用户按需安装)

现有 `/api/ocr/status|install|uninstall` 通过 `uv add/remove ddddocr` 动态管理依赖。迁移后:

- `infrastructure/python_bootstrap.rs` 实现等价的 `uv add/remove` 调用
- Worker `main.py` 启动时 eager import ddddocr —— **若 ddddocr 未安装,import 抛 ImportError,Worker 进程退出并返回错误码 `OCR_NOT_INSTALLED`**
- Rust 侧 `commands/ocr.rs` 在执行含 OCR 的任务前先检查依赖状态(installed?);已安装才启动 Worker,eager import 才会成功
- 即:ocr 模块管理的是"是否安装 ddddocr 依赖",Worker 启动逻辑只关心"装了就 import,没装就别启动含 OCR 任务的会话"

---

## Playwright 浏览器策略

**完全由 Python Worker 按现有 `browser_channel` 配置执行,Rust 不关心。**

现有 `playwright_bootstrap.py:139` 支持 5 种 channel:`playwright`(下载 Chromium)/ `firefox` / `msedge` / `chrome` / `custom`。全部保留,由 Worker 内部 `_launch_browser()`(`playwright_worker.py:803`)处理。

Rust 侧只做一件事:首次启动 Worker 前,检查 Worker 目录是否 `uv sync` 完成(对应现有 `ensure_playwright_ready`)。下载哪种浏览器由 `browser_channel` 决定,逻辑在 Python 侧不变。

> 文档早期版本写"固定 msedge"是错误的——这会丢失 Linux 支持(Linux 无 Edge)和用户已配置的 firefox/chrome/custom 选项。已修正。

---

## Python 环境管理(Rust 实现)

**替代现有 `start.go`(Windows)+ `start.sh`(macOS/Linux)两套下载逻辑**,统一为 Rust 实现。

### 现有逻辑(需移植)

`start.go` / `start.sh` 各自实现:
- uv 下载(版本 `0.11.21`,带各架构 SHA256 校验)
- 多镜像源 fallback(`ghfast.top` / `gh-proxy.com` / `ghproxy.net` / GitHub 官方)
- `uv sync` 触发 Python 3.12 + 依赖安装

`pyproject.toml` 配置:
- `python-install-mirror = https://registry.npmmirror.com/.../python-build-standalone/`
- `[[tool.uv.index]] url = https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple`

### Rust 实现(`infrastructure/python_bootstrap.rs`)

- **首次启动**:Rust 检查 `worker/.python/` 是否存在
- 不存在 → Rust 实现 uv 下载(多镜像 fallback + SHA256 + 架构分发)→ 调用 `uv sync`
- 镜像源、SHA256、版本号从配置读取,不硬编码
- 下载失败/校验失败:明确的错误 UX + 重试
- **离线安装包**(可选):`.msi` 内嵌 uv + Python 3.12 + 依赖,跳过下载

### 安装包体积估算

| 组件 | 体积 |
|------|------|
| Tauri Rust 二进制 | ~5-10MB |
| WebView2 bootstrapper(微软官方,系统已有则跳过) | ~2MB |
| Vue 前端(静态资源) | ~1MB |
| Python Worker 源码 | ~1MB |
| **小计(不含运行时)** | **~10-15MB** |
| 首次运行时下载(uv + Python 3.12 + 依赖 + 可选 Playwright Chromium) | ~60-150MB |

---

## 前端改造

### 现状评估(实测)

- **Vue 3.5.34,CDN 全局引入**(`index.html:58` `<script src="/static/vendor/vue.global.prod.js">`,`app.js:4` `const { createApp } = window.Vue`)
- **无构建工具**(无 package.json / vite / webpack)
- **axios 封装高度集中**:`js/constants.js:1` 创建唯一 `api` 实例,`app-options.js:260` `this.$api = api` 注入,所有 ~70 个 API 调用走 `this.$api.get/post/put/delete`
- 裸 fetch 仅 4 处:2 个模板加载器 + 2 个漏网 API 调用(`ui.js:104` browsers、`ui.js:200` install-playwright)
- WebSocket 单一入口(`lifecycle.js:208`),承载 status 推送 + log 流 + 前端日志回传

### 改造方案(不引入 Vite)

**命名 invoke + 手写 `js/api.js` 封装层。** 每个后端能力对应一个语义化的 invoke 名,而非统一的 `http_request` + URL match(后者会在 Rust 侧长出 500 行 match 地狱,形成"前端假装 HTTP、Rust 假装 FastAPI"的历史包袱)。

#### 1. 新建 `js/api.js` — 语义化封装层(替代 `js/constants.js` 的 axios 实例)

把现有 ~70 个 `this.$api.get('/api/xxx')` 调用,集中映射到命名 invoke:

```javascript
// js/api.js(新文件,手写,~150 行)
import { invoke } from '@tauri-apps/api/core'

export const api = {
  // 配置
  getConfig:        ()           => invoke('get_config'),
  saveConfig:       (payload)    => invoke('save_config', { payload }),
  // 监控
  getStatus:        ()           => invoke('get_status'),
  startMonitor:     ()           => invoke('start_monitor'),
  stopMonitor:      ()           => invoke('stop_monitor'),
  login:            ()           => invoke('login'),
  // 任务
  listTasks:        ()           => invoke('list_tasks'),
  saveTask:         (id, config) => invoke('save_task', { id, config }),
  deleteTask:       (id)         => invoke('delete_task', { id }),
  // ... 其余 ~60 个方法,一一对应语义
}
```

`app-options.js:260` 把 `this.$api = api` 改为指向新 `api.js`。各 `methods/*.js` 调用点把 `this.$api.get('/api/config')` 改为 `this.$api.getConfig()` —— **一次性全局重构**,工作量集中、可机械替换,但比"假装 HTTP"干净得多。

> 为什么不用 axios 兼容 shim:短期省事,但 Rust 侧会留下一个按 URL 分发的巨型 match,且前端代码风格停留在 FastAPI 时代,后续每加一个功能都要同时改前端 URL 字符串 + Rust match。命名 invoke 让前后端契约显式、可搜索、可手写 TS 类型。

#### 2. 收编漏网 fetch(2 处)

- `ui.js:104` `/api/browsers` → `api.getBrowsers()`
- `ui.js:200` `/api/browsers/install-playwright` → `api.installPlaywright()`

#### 3. WebSocket → Tauri 事件系统

现有 WS 三类消息,全部替换为 Tauri 事件:

| 现有 WS 消息 | 方向 | 替换为 |
|---|---|---|
| `{"type": "status", ...}` | backend→frontend | `listen('status-update', ...)` |
| `{"type": "log", ...}` | backend→frontend | `listen('log-message', ...)` |
| `{"type": "frontend_log", ...}` | frontend→backend | `invoke('log_frontend', { ... })` |
| `{"type": "ping"}` | frontend→backend | 不需要(Tauri IPC 无需心跳) |

改造集中在 `lifecycle.js:191-287`(WS 生命周期)和 `logger.js:21-30`(日志回传)两处。

#### 4. 静态资源路径

`/static/...` → Tauri 的 `convertFileSrc()` 或 `tauri.conf.json` 配置 `assetProtocol`。涉及 `index.html` + 所有 `data-include` + CSS link。**这是改造里最琐碎的部分**(21 个 partial HTML 片段含嵌套 include),但不涉及逻辑改动。

---

## WebView 销毁策略(风险后置)

**目标里"关闭窗口即销毁 WebView2 渲染进程降内存"是可选项,不是 Phase 1 的必做项。**

理由:Tauri 的 WebView2 生命周期管理涉及窗口状态恢复、前端状态恢复、事件监听恢复等连锁问题,贸然做容易花两周解决非核心的状态丢失 bug。

### 实施策略

- **Phase 1-6:关闭窗口只 `hide()`(隐藏)**,不销毁 WebView。简单、零风险。
- **全部功能完成(Phase 7)后**:单独一个优化阶段评估销毁/重建 WebView2 的收益与成本,实测内存降幅是否值得。
- 若不值得:维持隐藏策略,空闲内存靠"Worker 不常驻"这一条已经达标(降 50%+)。

这一条避免在迁移过程中陷入"窗口关闭后状态丢失"这种与核心目标无关的泥潭。

---

## 技术栈

| 组件 | 选型 | 用途 |
|------|------|------|
| 桌面框架 | tauri 2.0 | 窗口、IPC、托盘、打包 |
| 异步运行时 | tokio | 异步 IO、定时器、通道 |
| HTTP 客户端 | reqwest | 网络探测、自更新检查 |
| 序列化 | serde + serde_json | 配置、IPC 协议 |
| 日志 | tracing + tracing-subscriber | 结构化日志(替代 loguru) |
| 加密 | cryptography-rs Fernet 实现 | 兼容 Python 版密码文件 |
| 平台 API | windows-sys / objc2 / nix | 注册表 / plist / xdg |
| 子进程 | tokio::process + portable-pty | Python Worker 管理 |
| 系统信息 | sysinfo | 进程检测、孤儿清理 |

---

## 配置与数据迁移

### 目录(复用,零迁移成本)

```
~/.campus_network_auth/
├── config.json              # 主配置(AppConfig)
├── profiles/                # 配置方案
├── tasks/                   # browser 任务
├── scripts/                 # script 任务
├── history/                 # 登录历史 + 任务执行历史
├── pid                      # PID 文件
└── encryption.key           # (派生,不直接存)
```

Rust 复用现有格式,Python 版用户升级后配置/方案/任务/历史**全部继承**。

### 加密兼容

现有 `crypto.py` 用 Fernet,key 由机器特征 SHA256 派生(`_derive_fernet_key`,SHA256 → 拆分 signing/encryption 两段)。Rust 侧 `infrastructure/crypto.rs` 实现等价派生 + Fernet 解密,**保证 Python 版加密的密码文件 Rust 能读**(反之亦然)。

---

## 分阶段实施计划

### Phase 0:技术验证(3-5 天)

**目标:排除三个可能翻车的硬风险,确认可行后再启动正式迁移。**

> 评审意见:"真正可能翻车的只有 Fernet 兼容、IPC 稳定性、WebView 生命周期这三个。先验证通过,后面基本就是体力活。"

- **P0-1 Fernet 兼容**:Rust 实现 `crypto.py` 的 `_derive_fernet_key`(SHA256 → signing+encryption 两段) + Fernet 解密,用 Python 版加密的真实密码文件 fixture 做测试
- **P0-2 stdio IPC 原型**:最小 PoC — Rust 启动 Python 子进程,stdin 写 NDJSON 命令,stdout 读结果,验证 EOF 感知(kill 子进程后 Rust 读到 EOF)
- **P0-3 Tauri 托盘 + 自启动**:最小 Tauri 项目,验证 winreg 写入、`hide()` 策略(不做 WebView 销毁)

**验收:三项全部通过,进入 Phase 1。任何一项失败则重新评估方案。**

### Phase 1:基础设施(1-2 周)

**目标:能启动、托盘、读写配置、单实例**

- Tauri 项目初始化 + 目录结构
- `domain/config.rs` + `domain/network_state.rs`(4 态枚举)
- `infrastructure/persistence/config_store.rs`(JSON 读写,兼容现有格式)
- `infrastructure/crypto.rs`(Fernet 兼容,**用真实 fixture 密码文件测试**)
- `infrastructure/process_lock.rs`(PID + create_time)
- `infrastructure/autostart.rs`(winreg/plist/xdg 三平台)
- `tray/`(图标 + 菜单)
- `utils/`(logging, platform)
- `commands/config.rs` + `commands/system.rs` + `commands/autostart.rs`
- **窗口策略:关闭 = `hide()`,不销毁 WebView**

**验收:安装 → 开机启动 → 托盘运行 → 配置保存/恢复 → Python 版密码能解密 → 关闭窗口 = 隐藏到托盘**

### Phase 2:Python 环境管理 + Worker IPC(2-3 周)

**目标:Rust 能下载 uv、启动 Worker、执行登录、重试失败时复用、成功后销毁**

- `infrastructure/python_bootstrap.rs`(uv 下载,多镜像 fallback,SHA256)—— **移植 start.go/start.sh 全部逻辑**
- `worker/bootstrap.rs`(uv sync + Playwright 环境检查)
- `worker/protocol.rs`(NDJSON 行协议,stdin/stdout)
- `worker/process.rs`(子进程启动/EOF 感知/强制 kill)
- `worker/manager.rs`(重试驱动保活:成功销毁,失败复用)
- `worker/main.py`(Python 侧 stdin→submit 桥接,**playwright_worker.py 不动**)

**验收:Rust 调用 → Python 启动 → 登录失败 → 重试复用同一 Worker → 登录成功 → Worker 销毁 → 空闲 0MB**

### Phase 3:登录闭环 + 配置方案(1-2 周)

**目标:完整登录流程 + 方案管理**

- `application/login_service.rs`(检测 → 派发 Worker → 重试 → 记历史)
- `application/profile_service.rs`
- `infrastructure/persistence/history_store.rs`
- `commands/tasks.rs` + `commands/profiles.rs` + `commands/history.rs`
- OCR eager import 验证(含 OCR step 的登录能跑通)

**验收:含 OCR step 的任务 → Worker eager import ddddocr → 登录成功 → 历史写入**

### Phase 4:Debug 会话 + 调度(2 周)

**目标:任务编辑器逐步调试 + 定时任务**

- `application/debug_service.rs`(start→step→stop,会话期间子进程不销毁)
- `commands/debug.rs`(4 端点)
- `application/task_service.rs`(定时任务 CRUD + cron 调度)
- `commands/scheduled_tasks.rs`(7 端点)+ `commands/scripts.rs`(6 端点)

**验收:Debug start → 逐步 step 截图 → stop 销毁子进程;定时任务到点触发登录**

### Phase 5:网络监控 + 自动重连(2 周)

**目标:断网自动检测并重连**

- `infrastructure/network_probe.rs`(TCP/HTTP/Ping,对应 `probes.py` 232 行)
- `domain/state_machine.rs`(UNKNOWN/CONNECTED/DISCONNECTED/PORTAL 转换,对应 `decision.py` 290 行)
- `runtime/monitor_loop.rs`(tokio::select! 循环)
- `application/monitor_service.rs`
- `commands/monitor.rs`(8 端点)

**验收:断网 → 自动检测 → 冷启动 Worker 登录(失败重试复用)→ 恢复 → 成功后 Worker 销毁**

### Phase 6:剩余功能 + 自更新(1-2 周)

**目标:功能 parity(非端点 parity)**

- `commands/ocr.rs` + `commands/browsers.rs` + `commands/repo.rs` + `commands/tools.rs` + `commands/background.rs`
- `infrastructure/shell_executor.rs` + `infrastructure/update.rs`
- **功能 parity checklist** 逐项核对(见下方),而非按端点数数

#### 功能 parity checklist(部分功能不需要 Rust 端点)

| 功能 | Python 现状 | Rust 实现 | 备注 |
|------|------------|----------|------|
| 配置 CRUD | `/api/config*`(5) | 命名 invoke | ✅ |
| 监控启停 + 状态 | `/api/monitor*`(8) | 命名 invoke | ✅ |
| 登录 + 网络测试 | `/api/actions/*`(2) | 命名 invoke | ✅ |
| 配置方案 CRUD | `/api/profiles*`(7) | 命名 invoke | ✅ |
| 定时任务 CRUD | `/api/scheduled-tasks*`(7) | 命名 invoke | ✅ |
| 脚本任务 CRUD | `/api/scripts*`(6) | 命名 invoke | ✅ |
| 调试 start/step/stop | `/api/debug*`(4) | 命名 invoke | ✅ |
| 登录历史 | `/api/login-history`(2) | 命名 invoke | ✅ |
| 自启动 | `/api/autostart*`(5) | 命名 invoke | ✅ |
| OCR 安装/卸载 | `/api/ocr*`(3) | 命名 invoke | ✅ |
| 浏览器管理 | `/api/browsers*`(2) | 命名 invoke | ✅ |
| 自更新 | `/api/repo/*`(2) | 命名 invoke | ✅ |
| 文件上传/URL 抓取 | `/api/background/*`(4) | 命名 invoke | ✅ |
| 系统信息/关机/卸载 | `/api/system*`(6) | 命名 invoke | ✅ |
| 日志推送 | WS `/ws/logs` | Tauri 事件 | ✅ |
| **图标文件** | `/api/icons/*`(1) | **`convertFileSrc()`** | ❌ 不做端点,前端直接读静态文件 |
| **任务录制脚本** | `/api/tools/task-recorder.user.js`(1) | **`convertFileSrc()`** | ❌ 不做端点,静态文件 |
| **文档** | `/api/docs/*`(2) | **静态资源** | ❌ 不做端点,直接嵌入前端 |
| **健康检查** | `/api/health`(1) | **Tauri 进程存活即健康** | ❌ 不需要,Rust 进程活着 = 健康 |
| **OpenAPI** | `/openapi.json`(1) | **不需要** | ❌ Tauri 无 HTTP server |
| **check-update** | `/api/check-update`(1) | 后台静默检查 | ✅ 但不需要前端端点 |

> "不需要端点" ≠ "不支持"。这些功能在 Tauri 架构下有更自然的实现方式(静态文件、进程存活判断),强行镜像成 HTTP 端点是"为了兼容而兼容"。

### Phase 7:前端迁移 + 打包(2-3 周)

**目标:前端完全适配 Tauri + 打包发布**

- 新建 `js/api.js` 语义化封装层(~150 行),替代 `js/constants.js` 的 axios 实例
- 各 `methods/*.js` 调用点改写:~70 处 `this.$api.get('/api/...')` → `this.$api.xxx()`
- `lifecycle.js` + `logger.js`:WS → Tauri 事件
- `ui.js` 2 处漏网 fetch 收编
- 静态资源路径 `/static/` → `convertFileSrc`(21 个 partial,纯路径替换)
- 打包(.msi)+ WebView2 bootstrapper 内嵌
- 回归测试

**验收:发布候选版,功能 parity 全绿,空闲内存比 Python 版降低 50%+**

### 工期预估

| 阶段 | 工期 | 累计 |
|------|------|------|
| Phase 0 技术验证 | 3-5 天 | 0.5 周 |
| Phase 1-7 | 11-16 周 | 11.5-16.5 周 |
| **乐观** | **12 周** | |
| **正常** | **14-16 周** | |
| **保守** | **20 周+** | |

---

## 风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| **Fernet 跨语言解密失败** | Python 版密码无法继承 | **Phase 0 验证**,用 Python 版加密的真实密码文件做 Rust 解密测试 |
| **stdio IPC 稳定性** | Worker 卡死/消息丢失 | **Phase 0 验证**,EOF 感知 + 强制 kill + 超时兜底 |
| **Worker 子进程僵尸** | 内存泄漏 | `worker/process.rs` 强制 kill + Rust 退出时 `force_cleanup` + stdin EOF 自动感知 |
| **冷启动延迟(连续重试)** | 重连慢 | **成功才销毁,失败复用** — 首次 3-5s,后续重试 0.1-1s |
| **WebView2 在老 Win10 缺失** | 应用无法启动 | `.msi` 内嵌 WebView2 bootstrapper,首次启动自动安装 |
| **uv 下载失败(国内网络)** | 首次启动卡住 | 多镜像 fallback + SHA256 校验 + 明确重试 UX + 可选离线包 |
| **Python Worker 改动超预期** | 延期 | 核心业务不动,外围适配已识别(cancel_event/progress/stdin 桥接) |
| **前端 `api.js` 重构工作量大** | 延期 | ~70 处调用改写是机械替换,可写脚本半自动化 |
| 跨平台托盘/自启动差异 | Linux/macOS 体验差 | 优先 Windows,其他平台 Phase 7 之后 |

---

## 测试策略

- **Phase 0 验证测试**:Fernet 解密 fixture、stdio IPC PoC、Tauri 托盘最小 app — 三项硬门禁
- **IPC 协议**:Phase 2 写 protocol.rs 的测试(NDJSON 编解码、EOF 处理、超时)
- **Worker 生命周期**:Phase 2 测试 Idle↔Alive 状态机、成功销毁/失败复用、异常退出 force_cleanup
- **加密兼容**:Phase 1 用 Python 版加密的 fixture 密码文件,Rust 解密测试(Phase 0 先验证可行性)
- **功能 parity**:Phase 6 按功能 parity checklist 逐项写 happy path 测试
- **前端**:Phase 7 现有 `tests/` 目录的测试尽量移植
- **现有 Python 测试**:Worker 侧(`playwright_worker.py` 等)不动,现有测试继续跑

---

## 新项目结构

新 Rust 项目与现有 Python 项目并存:

```
Campus-Auth/                        # 现有 Python 项目(保留,作为 Worker 源)
rustforcam/                         # 新 Rust 项目(当前文档所在)
├── docs/                           # 设计文档
├── src-tauri/                      # Tauri Rust 代码
│   ├── src/                        # Rust 源码(上文模块结构)
│   ├── Cargo.toml
│   └── tauri.conf.json
├── worker/                         # Python Playwright Worker(从 app/workers/ 抽出)
│   ├── pyproject.toml
│   ├── uv.lock
│   └── src/
│       ├── main.py                 # 【新】stdin/stdout 主循环
│       └── ...(现有文件平移,核心业务零改动)
├── frontend/                       # Vue.js 前端(从现有 frontend/ 迁移 + 改造)
└── README.md
```

### 迁移完成判定

- **功能 parity**:上方 checklist 全绿(含"不需要端点"的合理替代)
- **配置兼容**:Python 版用户升级后配置/方案/任务/历史/密码全部可读
- **内存达标**:空闲稳态比 Python 版降低 50%+(实测,非硬指标)
- **稳定运行**:连续 48 小时无崩溃(托盘驻留 + 断网重连 + 定时任务)

满足以上后,Python 项目(`app/`、`main.py`、`start.go`、`start.sh`)归档保留,Rust 项目成为主版本。

---

## 开放问题(需后续确认)

1. **`repo/` 自更新机制**:现有 `/api/repo/fetch|task` 是 git clone 还是 zip 下载?Rust 侧用 git2-rs 还是纯 HTTP?——Phase 6 探索现有实现后定。
2. **`background/` 文件上传代理**:`/api/background/upload|fetch-url` 是给前端绕过 CORS 用的代理,Tauri 模式下是否还需要?——倾向 Rust(reqwest)直接实现,Phase 6 定。

