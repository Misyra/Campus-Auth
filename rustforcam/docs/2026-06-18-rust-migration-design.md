# Campus-Auth Rust 迁移设计

> 将 Campus-Auth 的**系统职能层**(配置、网络监控、托盘、自启动、任务调度、前端桥接)迁移至 Rust + Tauri 2.0;**浏览器自动化与 OCR 完全保留在 Python Worker**,由 Rust 按需唤醒子进程派发执行。

## 设计原则(关键边界)

本设计把代码库切成两半,边界严格:

- **Rust 负责"何时做、怎么管"**:进程生命周期、配置、调度、监控、UI 桥、系统对接。**不碰**任何 Playwright 调用、DOM 操作、截图、OCR 推理。
- **Python Worker 负责"怎么做登录"**:现有 `app/workers/playwright_worker.py` 的 8 种 `CMD_*` 命令、`app/tasks/` 的 step 引擎(868 行 `step_handlers.py`)、`app/utils/login.py`、OCR step —— **逐行不动**,只把入口从"in-process queue"换成"TCP socket"。

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
| **Worker 调用模型** | **会话级子进程**(Idle 不存在,Running 才占内存) | 满足"空闲 0MB"目标;debug 期间保活不影响该模型 |
| Python 环境管理 | **Rust 实现下载逻辑**(替代 start.go/start.sh) | 单一实现,带镜像源 fallback + SHA256 校验 |
| **Playwright 浏览器** | **完全由 Python Worker 按 `browser_channel` 配置执行** | Rust 不关心 channel;保留 playwright/firefox/msedge/chrome/custom 全部选项 |
| **OCR (ddddocr)** | **保留在 Python Worker**,启动时 eager import | Worker 销毁即释放;避免每次冷启动重载模型 |
| 前端框架 | 保留现有 CDN Vue 3,**不引入 Vite** | 改造点集中在 1 个 axios shim 文件 |
| 配置格式 | 复用现有 `~/.campus_network_auth/` JSON | Python 版数据无缝继承 |
| 加密 | 复用 Fernet(SHA256 派生 key)格式 | 密码文件兼容,Python 版可直接读 |

---

## 目标架构

```
┌─────────────────────────────────────────────────────┐
│ Tauri Rust 进程(常驻,~5-15MB)                      │
│                                                     │
│   WebView2 (Vue 前端) ──Tauri IPC──► commands/      │
│                                                     │
│   commands → application → domain                   │
│                  │        ◄── infrastructure        │
│                  │                                  │
│                  ├── runtime(网络监控循环)          │
│                  └── worker_manager ──TCP──┐        │
└──────────────────────────────────────────┼──────────┘
                                           │
                          ┌────────────────▼──────────────┐
                          │ Python Worker 子进程          │
                          │ (会话级:debug 期间常驻,       │
                          │  登录执行完即销毁;空闲时不存在)│
                          │                              │
                          │  PlaywrightWorker (8 种 CMD) │
                          │  ├── login                   │
                          │  ├── debug_start/step/stop   │
                          │  ├── browser_acquire/release │
                          │  │   /close/health_check     │
                          │  └── shutdown                │
                          │  + step 引擎(868 行,不改)   │
                          │  + OCR(ddddocr,eager import) │
                          │  + Playwright(channel 不变)  │
                          └──────────────────────────────┘
```

### 内存目标(待实测验证,非断言)

| 场景 | Python 现状 | Rust + Tauri 目标 |
|------|------------|------------------|
| 空闲(托盘驻留) | ~80-120MB | **~5-15MB**(WebView 销毁后) |
| 界面打开 | ~80-120MB | ~40-80MB(WebView2 host) |
| 界面关闭 | ~80-120MB | ~5-15MB(主动销毁 WebView2 渲染进程) |
| 登录中 | ~80-120MB | Rust ~10MB + Python ~80-120MB(临时) |
| Debug 中 | ~80-120MB | Rust ~10MB + Python ~80-120MB(会话期间) |

> ⚠️ 这些是**目标值**。Phase 1 结束时必须实测确认,若 WebView2 host 进程稳态远超 15MB,需调整"关闭窗口即销毁 WebView"的策略。Windows 上 Tauri 的 WebView2 host 通常 20-40MB,文档承认这一不确定性。

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
│   ├── config.rs                    # /api/config*(5 端点)
│   ├── monitor.rs                   # /api/monitor*, /api/status, /api/logs, /api/health(8)
│   ├── tasks.rs                     # /api/tasks*(7)
│   ├── scheduled_tasks.rs           # /api/scheduled-tasks*(7)
│   ├── profiles.rs                  # /api/profiles*(7)
│   ├── scripts.rs                   # /api/scripts*(6)
│   ├── autostart.rs                 # /api/autostart*(5)
│   ├── ocr.rs                       # /api/ocr*(3)
│   ├── browsers.rs                  # /api/browsers, /api/browsers/install-playwright(2)
│   ├── debug.rs                     # /api/debug*(4)
│   ├── repo.rs                      # /api/repo/*(2)
│   ├── tools.rs                     # /api/tools/*, /api/docs/*(3 端点;userscript/文档)
│   ├── background.rs                # /api/background/*(4 端点;文件上传/URL 抓取代理)
│   ├── system.rs                    # /api/system, /api/shutdown, /api/uninstall*(6)
│   ├── history.rs                   # /api/login-history(2)
│   └── icons.rs                     # /api/icons/{filename}(1)
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
│   ├── manager.rs                   # **会话状态机**:Idle ↔ Running{child, stream}
│   ├── process.rs                   # 子进程启动/健康检查/强制销毁
│   ├── protocol.rs                  # JSON over TCP 编解码(长度前缀 + 鉴权)
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
    ├── platform.rs                  # 平台检测
    └── ports.rs                     # 端口管理
```

### Python Worker 侧(改动极小)

```
worker/                              # 从 app/workers/ 抽出,作为独立可执行单元
├── pyproject.toml                   # 依赖:playwright, ddddocr, onnxruntime, cryptography
├── uv.lock
├── main.py                          # 【新增】TCP 服务器入口(替换 in-process queue)
├── _dispatch_adapter.py             # 【新增】TCP 消息 → WorkerCommand → 现有 _dispatch()
├── playwright_worker.py             # 【几乎不动】PlaywrightWorker + 8 种 CMD_*
├── step_handlers.py                 # 【不动】868 行 step 引擎(INPUT/CLICK/.../OCR)
├── browser_runner.py                # 【不动】
├── login.py                         # 【不动】LoginAttemptHandler
├── script_runner.py                 # 【不动】
├── playwright_bootstrap.py          # 【不动】channel 配置 + Playwright 环境检查
└── ocr_handler.py                   # 【不动】OCR step 处理(主循环启动时 eager import ddddocr)
```

**Python 侧总改动量:2 个新文件(main.py + adapter)+ 现有文件零修改。** 现有 `_dispatch()` 方法(`playwright_worker.py:386`)已经是"按 `cmd.type` 路由到 `_handle_*`"的纯派发器,只要把"命令从哪来"从 `queue.Queue` 换成"TCP 流",派发逻辑原样复用。

---

## Worker 调用模型(核心设计)

### 会话级生命周期状态机

```
        ensure_started()                send(shutdown) / 会话结束
Idle ────────────────────► Running{child, stream} ───────────────────► Idle
 ▲                              │
 │                              │ login: send(login)→recv→**立即 stop**
 │                              │ debug: start→step→...→stop
 │                              │ 任何异常/Rust 退出: 强制 stop
 └──────────────────────────────┘
```

**关键:进程生命周期由 Rust 按"会话"管理,不是按"全局"管理。**

| 场景 | 子进程行为 | 内存 |
|------|-----------|------|
| 空闲(托盘驻留) | **不存在** | 0MB |
| 登录 | start → login → **立即 stop** | 临时 ~80-120MB |
| Debug | start → 逐步 step → stop(用户点停止) | debug 期间常驻 |
| 断网重连 | 每次 start → login → stop(冷启动) | 临时 |

**Debug 不需要特殊模式**:debug 会话本身就是一个"会话",会话期间 Python 子进程不退出是自然的——这和"空闲时不存在"完全不冲突。Python 侧 `_handle_debug_start` 已经是"保持 page 直到 debug_stop"的逻辑,无需改动。

### Rust 侧 `worker/manager.rs` 接口

```rust
pub enum WorkerState {
    Idle,
    Running { child: Child, stream: TcpStream },
}

pub struct WorkerManager {
    state: Mutex<WorkerState>,
    port: u16,  // 随机分配的 loopback 端口
}

impl WorkerManager {
    /// 登录:短命会话。start → login → stop
    pub async fn login(&self, config: LoginConfig) -> Result<LoginResult>;

    /// Debug 会话:start 后保持 Running
    pub async fn debug_start(&self, config, task_data) -> Result<DebugSession>;
    pub async fn debug_step(&self, session, step_index) -> Result<StepResult>;  // 要求 Running
    pub async fn debug_stop(&self, session) -> Result<()>;  // 销毁子进程

    /// 兜底:Rust 退出时强制销毁所有子进程
    async fn force_cleanup(&self);
}
```

---

## IPC 协议(Rust ↔ Python Worker)

### Transport

- TCP Socket,loopback(`127.0.0.1:随机端口`)
- 帧格式:`[4 字节长度 u32 BE][UTF-8 JSON payload]`
- 最大 payload:16 MB(对齐现有 WebSocket 的 size 预检,见 `application.py:337`)
- **loopback 鉴权**:Python 子进程启动时由 Rust 传入一个随机 token,每条命令必须带 `auth` 字段匹配;防止本机其他进程注入命令触发 Playwright

### 协议版本与错误分类

- 每条消息带 `"v": 1`(协议版本号)
- 错误结构:`{"id": "...", "success": false, "error": {"code": "TIMEOUT|CRASH|BROWSER_FAIL|PROTOCOL|UNKNOWN", "message": "..."}}`

### 消息格式(保留现有 CMD_* 语义)

```jsonc
// Rust → Python:命令(对应 WorkerCommand)
{
  "v": 1, "id": "cmd_001", "auth": "<token>",
  "type": "login",                       // 或 debug_start / debug_step / debug_stop
                                         //    / browser_acquire / browser_release
                                         //    / browser_close / browser_health_check
                                         //    / shutdown
  "data": {                              // 对应现有 WorkerCommand.data
    "config": {...},                     //   登录:完整 AppConfig(含 browser_channel)
    "cancel_token": "xxx",               //   取消信号(替代 threading.Event)
    "task_data": {...}                   //   debug 用
  }
}

// Python → Rust:结果(对应 WorkerResponse)
{"v": 1, "id": "cmd_001", "success": true, "data": "登录成功"}

// Python → Rust:进度推送(对应现有进度回调)
{"v": 1, "id": "cmd_001", "type": "progress", "step": "打开浏览器", "percent": 30}

// Python → Rust:日志推送(替代现有 ws_manager.emit_log)
{"v": 1, "id": "cmd_001", "type": "log", "level": "info", "message": "..."}
```

### cancel_event 的处理

现有 `WorkerCommand.cancel_event` 是 `threading.Event`,跨进程不能传。改为:
- Rust 侧维护 `HashMap<cmd_id, CancellationToken>`
- 取消时 Rust 发一条 `{"type": "cancel", "id": "cmd_001"}`
- Python `_dispatch_adapter` 收到后设置一个进程内 Event,现有 `LoginAttemptHandler` 检查 cancel_event 的逻辑不变

### Python 主循环(`worker/main.py`,新增)

```python
# 伪代码
server = listen(127.0.0.1, port_from_argv)
token = argv[1]
worker = PlaywrightWorker()
worker.start()

async def handle_conn(conn):
    while True:
        msg = read_frame(conn)            # 长度前缀解析
        if msg["auth"] != token: reject
        if msg["type"] == "shutdown":
            worker.stop(); conn.close(); sys.exit(0)
        # 关键:复用现有 _dispatch,只把 queue 换成直接 await
        result = await dispatch_to_worker(worker, msg)  # adapter
        write_frame(conn, result)
```

`dispatch_to_worker` 是一个薄 adapter,把 TCP 消息转成 `WorkerCommand` 喂给现有 `_dispatch()` —— `_dispatch` 内部的 `CMD_LOGIN → _handle_login` 路由**一行不改**。

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

**最小侵入:替换 1 个文件 + 收编 2 处 + 改 WS 通道。**

#### 1. `js/constants.js` — axios 实例替换为 Tauri invoke shim

保留 `this.$api.get/post/put/delete` 全部签名,底层换成 Tauri IPC:

```javascript
// 改造后(constants.js)
import { invoke } from '@tauri-apps/api/core'

// axios 兼容 shim,签名完全对齐现有调用
const api = {
  async get(url, config)    { return { data: await invoke('http_request', { url, method: 'GET',    ...config }) } },
  async post(url, data, c)  { return { data: await invoke('http_request', { url, method: 'POST',   body: data, ...c }) } },
  async put(url, data, c)   { return { data: await invoke('http_request', { url, method: 'PUT',    body: data, ...c }) } },
  async delete(url, config) { return { data: await invoke('http_request', { url, method: 'DELETE', ...config }) } },
}
```

`http_request` 是 Rust 侧一个统一的 `#[tauri::command]`,**内部按 URL 路径匹配到对应的 application service 方法**(不是 Rust 跑一个 HTTP server,而是把前端假装还在发的 HTTP 请求转成直接的方法调用)。拦截器(重试逻辑)在此文件一并迁移。

#### 2. 收编漏网 fetch(2 处)

- `ui.js:104` `/api/browsers` → `this.$api.get('/api/browsers')`
- `ui.js:200` `/api/browsers/install-playwright` → `this.$api.post(...)`

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

### Phase 1:基础设施(1-2 周)

**目标:能启动、托盘、读写配置、单实例**

- Tauri 项目初始化 + 目录结构
- `domain/config.rs` + `domain/network_state.rs`(4 态枚举)
- `infrastructure/persistence/config_store.rs`(JSON 读写,兼容现有格式)
- `infrastructure/crypto.rs`(Fernet 兼容,**重点测试:Python 加密的文件 Rust 能解**)
- `infrastructure/process_lock.rs`(PID + create_time + 端口)
- `infrastructure/autostart.rs`(winreg/plist/xdg 三平台)
- `tray/`(图标 + 菜单)
- `utils/`(logging, platform, ports)
- `commands/config.rs` + `commands/system.rs` + `commands/autostart.rs`

**验收:安装 → 开机启动 → 托盘运行 → 配置保存/恢复 → Python 版密码能解密**

### Phase 2:Python 环境管理 + Worker IPC(2-3 周)

**目标:Rust 能下载 uv、启动 Worker、执行登录、销毁**

- `infrastructure/python_bootstrap.rs`(uv 下载,多镜像 fallback,SHA256)—— **移植 start.go/start.sh 全部逻辑**
- `worker/bootstrap.rs`(uv sync + Playwright 环境检查)
- `worker/protocol.rs`(TCP + 长度前缀 + token 鉴权)
- `worker/process.rs`(子进程生命周期)
- `worker/manager.rs`(会话状态机)
- `worker/main.py` + `_dispatch_adapter.py`(Python 侧,**现有 playwright_worker.py 零改动**)

**验收:Rust 调用 → Python 启动 → Playwright 执行(任意 channel)→ 返回结果 → 子进程销毁 → 空闲 0MB**

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
- `commands/monitor.rs`(8 端点)+ `commands/icons.rs`(1)

**验收:断网 → 自动检测 → 冷启动 Worker 登录 → 恢复 → Worker 销毁**

### Phase 6:剩余命令 + 自更新(1-2 周)

**目标:API parity**

- `commands/ocr.rs` + `commands/browsers.rs` + `commands/repo.rs` + `commands/tools.rs` + `commands/background.rs`
- `infrastructure/shell_executor.rs` + `infrastructure/update.rs`
- API parity checklist 逐项核对(72 个 HTTP 端点 + 1 WS 全部覆盖)

### Phase 7:前端迁移 + 打包(2-3 周)

**目标:前端完全适配 Tauri**

- `js/constants.js` axios shim 替换
- `lifecycle.js` + `logger.js` WS → Tauri 事件
- `ui.js` 2 处漏网 fetch 收编
- 静态资源路径 `/static/` → `convertFileSrc`(21 个 partial,纯路径替换)
- WebView2 销毁策略验证(关闭窗口即销毁渲染进程)
- 打包(.msi)+ WebView2 bootstrapper 内嵌
- 回归测试

**验收:发布候选版,API parity 全绿,空闲内存实测达标**

### 工期预估

| 场景 | 工期 |
|------|------|
| 乐观 | 11 周 |
| 正常 | 14-16 周 |
| 保守 | 20 周+ |

> 注:相比早期版本的 10-18 周,因 step 引擎/OCR/浏览器逻辑零迁移(省下最大一块),但 Python 环境下载移植、72 端点 parity、前端 WS 改造新增工作量,整体基本持平。

---

## 风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| **Fernet 跨语言解密失败** | Python 版密码无法继承 | Phase 1 优先验证,用 Python 版加密的真实密码文件做 Rust 解密测试 |
| **Worker 子进程僵尸/端口占用** | 内存泄漏、登录失败 | `worker/process.rs` 强制 kill + 端口随机分配 + Rust 退出时 `force_cleanup` |
| **TCP IPC 鉴权缺失** | 本机任意进程可触发 Playwright(安全) | 每条命令强制 token 校验,token 随进程启动随机生成 |
| **冷启动延迟(断网重连)** | 重连慢于 Python 版 | 校园网断流一天 3-4 次,冷启动几秒可接受;不做常驻优化 |
| **WebView2 在老 Win10 缺失** | 应用无法启动 | `.msi` 内嵌 WebView2 bootstrapper,首次启动自动安装 |
| **uv 下载失败(国内网络)** | 首次启动卡住 | 多镜像 fallback + SHA256 校验 + 明确重试 UX + 可选离线包 |
| **API parity 遗漏** | 功能回退 | Phase 6 强制核对 72 端点 checklist,逐个写集成测试 |
| **Python Worker eager import 拖慢启动** | 每次登录慢 1-3s | 可接受;若不可接受改为"首次 OCR step 时 lazy import + 缓存" |
| 跨平台托盘/自启动差异 | Linux/macOS 体验差 | 优先 Windows,其他平台 Phase 7 之后 |
| Tauri 生命周期管理 | 窗口关闭/打开状态丢失 | Phase 1 充分验证 WebView 销毁/重建 |

---

## 测试策略

- **IPC 协议**:Phase 2 写 protocol.rs 的集成测试(帧编解码、粘包、token 校验、超时)
- **加密兼容**:Phase 1 用 Python 版加密的 fixture 密码文件,Rust 解密测试
- **Worker 生命周期**:Phase 2 测试 Idle↔Running 状态机、异常退出、force_cleanup
- **API parity**:Phase 6 对 72 个端点逐个写 happy path 测试
- **前端**:Phase 7 现有 `tests/` 目录的测试尽量移植
- **现有 Python 测试**:Worker 侧(`playwright_worker.py` 等)零改动,现有测试继续跑

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
│       ├── main.py                 # 【新】TCP 服务器
│       ├── _dispatch_adapter.py    # 【新】TCP → _dispatch
│       └── ...(现有文件平移,零修改)
├── frontend/                       # Vue.js 前端(从现有 frontend/ 迁移 + 改造)
└── README.md
```

### 迁移完成判定

- API parity:72 HTTP 端点 + WebSocket 全部覆盖,集成测试绿
- 配置兼容:Python 版用户升级后配置/方案/任务/历史/密码全部可读
- 功能等价:登录/Debug/OCR/定时任务/网络监控/自更新全部可用
- 内存达标:空闲稳态 ≤15MB(实测)

满足以上后,Python 项目(`app/`、`main.py`、`start.go`、`start.sh`)归档保留,Rust 项目成为主版本。

---

## 开放问题(需后续确认)

1. **`repo/` 自更新机制**:现有 `/api/repo/fetch|task` 是 git clone 还是 zip 下载?Rust 侧用 git2-rs 还是纯 HTTP?——Phase 6 探索现有实现后定。
2. **`background/` 文件上传代理**:`/api/background/upload|fetch-url` 是给前端绕过 CORS 用的代理,Rust 侧直接实现还是 Worker 侧?——倾向 Rust(reqwest),Phase 6 定。
3. **icons 路由**:`/api/icons/{filename}` 读取图标文件,Tauri 侧用 `convertFileSrc` 还是 command 返回 base64?——Phase 7 定。
