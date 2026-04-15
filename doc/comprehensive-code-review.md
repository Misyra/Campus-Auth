# Campus-Auth v3.0.1 全面代码审查报告

> **审查日期**: 2026-04-15  
> **审查范围**: 全部源码文件（Python 后端 + 前端 JS/CSS/HTML + 配置/测试）  
> **项目规模**: ~5000 行 Python 代码，~1500 行前端代码

---

## 一、项目架构概览

```
Campus-Auth/
├── app.py              # CLI 入口 + PID 管理 + 服务启动（318行）
├── launcher.py         # 环境自举启动器（676行）
├── backend/
│   ├── main.py         # FastAPI 路由 + Uvicorn 启动（335行）
│   ├── monitor_service.py  # 监控服务编排 + WebSocket 日志（240行）
│   ├── config_service.py   # 配置读写 .env 文件（209行）
│   ├── autostart_service.py # 三平台开机自启动（280行）
│   ├── task_service.py     # 任务 CRUD API（92行）
│   └── schemas.py          # Pydantic 模型定义（60行）
├── src/
│   ├── campus_login.py     # 认证核心类（537行）
│   ├── monitor_core.py     # 监控循环核心逻辑（223行）
│   ├── task_executor.py    # 任务模板执行引擎（447行）
│   ├── network_test.py     # 网络连通性检测（90行）
│   ├── playwright_bootstrap.py # Chromium 自检安装（133行）
│   ├── system_tray.py      # 系统托盘封装（76行）
│   └── utils/             # 工具模块集合（8个子模块）
└── frontend/             # Vue 3 SPA 前端（多文件组件化）
```

**技术栈**: FastAPI + Playwright + Vue 3 + WebSocket + pystray

---

## 二、严重问题 (Critical / P0)

### 2.1 ✅ ~~`.env` 凭据问题~~ （已确认安全）

**状态**: 经核实，`.env` 已在 `.gitignore:23` 中被正确排除，`git log --all -- .env` 无记录，
`git check-ignore .env` 返回确认忽略。**凭据未暴露到版本库中**，此项原判定为**误报**。

> **遗留建议**: 虽然凭据未被提交，但 `.env` 本身仍以明文存储密码。
> 对于多成员团队或共享开发机场景，建议后续考虑使用加密凭证存储（如 keyring）
> 或至少确保文件系统权限为 600（当前单用户使用可接受）。

---

### 2.2 🔴 浏览器启动参数存在安全隐患

**位置**: `src/utils/browser.py` 第92-106行 (`_get_browser_args` 方法)

```python
args = [
    "--no-sandbox",
    "--disable-web-security",        # ← 禁用同源策略！
    "--disable-dev-shm-usage",
    "--disable-gpu",
]
```

**风险分析**:
- `--disable-web-security`: 完全禁用浏览器的同源策略，使认证过程容易受到 XSS 攻击
- `--no-sandbox`: 在生产环境使用无沙箱模式有被利用风险

**建议**: 仅在认证页面需要时通过 `--host-rules` 或代理方式绕过限制，而非全局禁用安全特性。

---

### 2.3 🔴 关闭 API 无任何鉴权机制

**位置**: `backend/main.py` — 所有 API 端点

当前所有 API 端点（包括 `/api/shutdown`, `/api/config` 写入等敏感操作）均**无需任何身份验证**即可访问。由于服务绑定在 `127.0.0.1`，攻击面有限于本地用户，但仍存在风险：

1. `/api/shutdown` 可被任意本地程序调用关闭服务
2. `/api/config` PUT 可修改包含密码的配置
3. `/api/actions/login` 可触发登录操作

**建议**: 添加简单的 API Token 鉴权或至少对写操作添加确认机制。

---

### 2.4 🔴 密码明文存储并通过网络传输

**完整链路**:
1. `.env` 明文存储密码
2. `backend/config_service.py` 将密码写入响应模型 `MonitorConfigPayload`
3. `GET /api/config` 返回密码给前端（可在浏览器开发者工具查看）
4. WebSocket 日志推送可能泄露上下文信息

**建议**: 
- 后端不应将完整密码返回给前端（可返回掩码如 `***`）
- 敏感字段在网络传输时应做脱敏处理

---

## 三、逻辑错误与潜在漏洞 (High / P1)

### 3.1 🟠 `monitor_core.py` 同步阻塞异步事件循环

**位置**: `src/monitor_core.py` 第79-86行, `src/monitor_core.py` 第210-222行

```python
class NetworkMonitorCore:
    def start_monitoring(self) -> None:
        try:
            self.monitor_network()        # 同步阻塞调用！
        except KeyboardInterrupt:
            ...

    def attempt_login(self) -> tuple[bool, str]:
        handler = LoginAttemptHandler(self.config)
        success, message = asyncio.run(handler.attempt_login(skip_pause_check=True))  # 每次 run 新事件循环！
```

**问题描述**:
1. `start_monitoring()` 是同步方法，内部 `time.sleep()` 阻塞线程
2. `attempt_login()` 在已有 asyncio 事件循环运行时调用 `asyncio.run()` 会抛出 **RuntimeError: This event loop is already running**
3. 监控线程中每次登录都创建/销毁新的事件循环，开销大且不稳定

**修复方向**: 
- 要么整个监控核心改为 `async def` 并在后台线程中以单一事件循环运行
- 要么确保 `asyncio.run()` 不在嵌套场景下调用

---

### 3.2 🟠 `retry.py` 重试次数边界错误

**位置**: `src/utils/retry.py` 第39行

```python
for attempt in range(max_retries):  # max_retries=3 时 → attempt ∈ {0,1,2}，只执行3次但最后一次不等待
```

当 `max_retries=3` 时:
- 实际重试次数 = 3 次（attempt 0, 1, 2），而非"尝试1次+重试3次"
- 最后一次失败后直接跳出循环，不会进入 `if attempt < max_retries - 1` 分支
- 这本身不算 bug 但语义可能不符合直觉：注释说"最大重试3次"，实际是"总共最多3次"

**建议**: 改为 `for attempt in range(1, max_retries + 1)` 使语义更清晰，或调整文档说明为"总尝试次数"。

---

### 3.3 🟠 `_push_log` 中 JSON 构造语法错误

**位置**: `backend/monitor_service.py` 第97-107行

```python
data = json.dumps(
    {
        "type": "log",
        "data": {                          # ← 注意这里的结构
            "timestamp": stamp,
            "level": level_name,
            "source": source_name,
            "message": message,
        },
    }
)
```

这段代码的 JSON 结构看起来正确，但实际生成的字符串会被解析为：
```json
{"type":"log","data":{"timestamp":"...","level":"INFO",...}}
```

前端 `lifecycle.js` 第63行的解析逻辑期望的是 `data.data.timestamp`，这是匹配的。**此条目经核实无问题**，标记降级为 Info。

---

### 3.4 🟠 `config_service.py` 默认值不一致

**位置**: 多个文件的默认值对比

| 配置项 | `src/utils/config.py` | `backend/schemas.py` | `.env.example` |
|--------|----------------------|---------------------|----------------|
| `MONITOR_INTERVAL` | **300** 秒 | 5 分钟 (=300秒) ✅ | 240 秒 ❌ |
| `PING_TARGETS` | 带**端口号** (`8.8.8.8:53`) | 带**端口号** ✅ | **不带端口号** (`8.8.8.8`) ❌ |
| `BROWSER_LOW_RESOURCE_MODE` | **false** | false | **true** ❌ |

**影响**: 用户按 `.env.example` 配置后可能与实际行为不符。

---

### 3.5 🟠 `shutdown_server` 创建无用 SystemTray 实例

**位置**: `backend/main.py` 第265-295行

```python
def shutdown_server() -> ActionResponse:
    ...
    try:
        from src.system_tray import SystemTray
        tray = SystemTray(port=_resolve_port())  # 创建全新实例
        tray.stop()                              # 对空实例调用 stop（无效）
    except Exception:
        pass
```

**问题**: `SystemTray(port=_resolve_port())` 创建的是一个**全新的托盘实例**（icon=None），对其调用 `stop()` 不会有任何效果。应该保存并停止**正在运行的**托盘实例引用。

---

### 3.6 🟠 `launcher.py` 与 `app.py` 的端口解析逻辑重复

**位置**: 
- `launcher.py` 第32-58行 `resolve_port()`
- `app.py` → `backend/main.py` 第302-310行 `_resolve_port()`

两处实现功能相同但不一致：
- `launcher.py` 支持 `.env` 文件解析和默认值 50721
- `backend/main.py` 仅从环境变量读取，硬编码默认 50721

`launcher.py` 还手动解析 `.env` 文件的 `APP_PORT` 键，而 `app.py` 通过 `ConfigLoader.load_config_from_env()` 加载。两套路径可能导致行为差异。

---

### 3.7 🟠 `campus_login.py` 的 `main()` 函数与项目主流程冗余

**位置**: `src/campus_login.py` 第497-536行

```python
async def main():
    config = ConfigLoader.load_config_from_env()
    if not config["username"] or ...:
        print("❌ 错误: 请在 .env 文件中配置 CAMPUS_USERNAME")
        return
    auth = EnhancedCampusNetworkAuth(config)
    success, message = await auth.authenticate()
```

这个 `main()` 函数是一个独立的 CLI 入口，但在项目中：
- 实际入口是 `app.py` → `backend/main.py` → `LoginAttemptHandler` → 任务系统
- `EnhancedCampusNetworkAuth` 仅作为任务系统未配置时的**回退路径**使用
- 直接运行 `python -m src.campus_login` 绕过了 FastAPI 服务层

**风险**: 该函数输出中包含 emoji 和中文格式化，在某些终端环境下可能显示乱码；且它独立于监控系统，不具备自动重连能力。

**建议**: 标记为 deprecated 或移除，统一走 `LoginAttemptHandler` 路径。

---

## 四、中等问题 (Medium / P2)

### 4.1 🟡 `setup_logger` 反复重新配置根日志器

**位置**: `src/utils/logging.py` 第127-135行

```python
def setup_logger(name: str, config: Dict[str, Any] | None = None) -> logging.Logger:
    config = config or {}
    configure_root_logger(config, side="BACKEND")  # 每次调用都重新配置根 logger!
    logger = get_logger(name, side="BACKEND")
    logger.handlers.clear()                         # 清除刚添加的 handlers?
    logger.propagate = True
    return logger
```

**问题**: 每次实例化 `EnhancedCampusNetworkAuth` 或 `SimpleRetryHandler` 都会调用 `LoggerSetup.setup_logger()`，这会反复重新配置全局根 logger，导致重复添加 handler 或清除已有 handler。

`BrowserContextManager.__init__`、`EnhancedCampusNetworkAuth.__init__`、`SimpleRetryHandler.__init__`、`LoginAttemptHandler.__init__` 各调用一次，意味着一次认证流程可能触发 4 次根日志器重配置。

---

### 4.2 🟡 `WebSocketManager` 使用 `list` 而非线程安全集合

**位置**: `backend/monitor_service.py` 第24-25行

```python
class WebSocketManager:
    def __init__(self):
        self._connections: list[WebSocket] = []
        self._lock = asyncio.Lock()
```

虽然使用了 `asyncio.Lock` 保护列表操作，但 `broadcast()` 方法先 copy 再发送的设计在高并发下仍可能有竞态。对于当前场景（单用户工具）足够，但若扩展需改进。

---

### 4.3 🟡 前端外部资源依赖 CDN 无本地回退

**位置**: `frontend/index.html` 第7-12行

```html
<link href="https://fonts.googleapis.com/css2?family=Inter:..." rel="stylesheet">
<script src="https://unpkg.com/vue@3/dist/vue.global.prod.js"></script>
<script src="https://cdn.jsdelivr.net/npm/axios@1.8.4/dist/axios.min.js"></script>
```

**问题**: 
- 如果用户网络无法访问 Google Fonts / unpkg / jsdelivr，UI 完全不可用
- Vue 和 Axios 版本锁定在外部 CDN，没有完整性校验 (SRI hash)
- 对于校园网认证工具而言，目标用户可能在**未联网状态**下打开控制台

**建议**: 将 Vue 和 Axios 内置到 `frontend/static/vendor/` 目录，或提供离线模式支持。

---

### 4.4 🟡 浏览器实例每次认证都重新创建销毁

**位置**: `src/campus_login.py` 第352-374行, `src/utils/login.py` 第114行

每次 `authenticate_once()` 调用都会:
1. 创建新的 Playwright 实例
2. 启动新的 Chromium 进程
3. 创建新的浏览器上下文
4. 执行认证后全部关闭

对于监控场景（每 5 分钟检测一次，掉线就认证），这意味着频繁的进程启停开销。

**建议**: 考虑实现浏览器实例池或长生命周期浏览器复用机制。

---

### 4.5 🟡 `task_executor.py` 截图路径硬编码相对路径

**位置**: `src/task_executor.py` 第224-228行

```python
os.makedirs("debug", exist_ok=True)
stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
filename = f"task_failure_{stamp}.png"
local_path = os.path.join("debug", filename)
```

使用相对路径 `"debug"` 依赖工作目录 (CWD)。当从不同目录启动时（如 `launcher.py` 使用 `subprocess` 启动），截图可能写入非预期位置。

应使用 `PROJECT_ROOT` 绝对路径基准。

---

### 4.6 🟡 `_find_first_visible_locator` 轮询效率低

**位置**: `src/task_executor.py` 第242-273行

```python
async def _find_first_visible_locator(self, page, selector, timeout):
    deadline = time.monotonic() + max(0.2, timeout / 1000)
    while time.monotonic() < deadline:       # 忙等待循环!
        for candidate in candidates:
            locator = page.locator(candidate)
            count = await locator.count()
            for i in range(count):
                element = locator.nth(i)
                if await element.is_visible(timeout=50):
                    return element
        await page.wait_for_timeout(100)      # 固定 100ms 间隔
```

每 100ms 轮询一次所有候选选择器，对于短超时（如 1000ms）只有约 10 次迭代机会。Playwright 内置的 `locator.wait_for()` 使用更高效的事件驱动机制。

---

### 4.7 🟡 `autostart_service.py` Windows VBS 代码重复

**位置**: `backend/autostart_service.py` 第206-256行

`_enable_windows()` 方法中 Python 嵌入的 VBScript 代码块完全重复了两次（针对 `python_exe.exists()` 和 else 分支），仅一行命令不同。应提取公共部分。

---

## 五、低优先级 / 代码质量 (Low / P3)

### 5.1 废弃/冗余代码

#### 5.1.1 `src/utils.py` 兼容性重导出层

**位置**: `src/utils.py` (23行)

这是一个纯重导出文件，目的是向后兼容旧导入路径 `from src.utils import Xxx`。当前代码库已经全部迁移到 `from src.utils.xxx import Xxx` 的导入风格。可以逐步清理此兼容层。

#### 5.1.2 `src/__init__.py` 空包声明

仅有文档字符串，无实质作用。

#### 5.1.3 未使用的配置项

`.env` 文件中的以下配置项在后端代码中**从未被读取和使用**:
```env
BROWSER_LOCALE=zh-CN           # 从未被读取
BROWSER_TIMEZONE=Asia/Shanghai # 从未被读取
BROWSER_DISGUISE_ENABLED=true  # 从未被读取
BROWSER_EXTRA_HTTP_HEADERS=    # 注意：实际使用的是 BROWSER_EXTRA_HEADERS_JSON
BROWSER_DISABLE_WEB_SECURITY=false  # 从未被读取
BROWSER_DISABLE_IMAGES=false   # 从未被读取
LOG_RETENTION_DAYS=7            # 从未被读取
FRONTEND_LOG_RETENTION_DAYS=7   # 从未被读取
SCREENSHOT_RETENTION_DAYS=7    # 从未被读取
```

这些可能是早期版本的遗留配置，应清理或在代码中补充对应逻辑。

#### 5.1.4 `release/stage-win-full/` 目录过时

`release/stage-win-full/` 下的文件版本明显旧于主分支代码（对比 `backend/config_service.py` 和 `release/stage-win-full/backend/config_service.py`）。该发布 staging 目录可能不再需要，或应重新构建同步。

---

### 5.2 异常处理过于宽泛

多处使用裸 `except Exception:` 或 `except:` 捕获所有异常：

| 文件 | 行号 | 问题 |
|------|------|------|
| `src/campus_login.py` | 94, 136, 277 | 吞掉了所有异常仅 continue |
| `src/campus_login.py` | 333, 341 | 截图失败的异常被静默忽略 |
| `src/monitor_core.py` | 141 | 网络检测异常仅记录为 network_ok=False |
| `backend/monitor_service.py` | 278-289 | shutdown 时所有异常被忽略 |

**建议**: 至少记录 `exception` 信息到日志，便于调试排查。

---

### 5.3 类型注解不一致

- 部分代码使用 `Dict`, `List`, `Tuple`（from `typing`），另一部分使用 `dict`, `list`（内置泛型，Python 3.9+）
- `src/monitor_core.py` 第8行: `from typing import Any, Callable, Dict, Optional` — `Dict` 已被使用
- `src/network_test.py` 第6行: `from typing import Iterable, Sequence` — 正确使用现代注解

建议统一使用内置泛型类型（Python >= 3.10）。

---

### 5.4 缺少输入校验的 API 端点

| 端点 | 问题 |
|------|------|
| `PUT /api/tasks/{task_id}` | `payload` 接收原始 `dict`，未做 schema 校验 |
| `POST /api/tasks/active/{task_id}` | task_id 格式仅做基础正则校验 |
| `PUT /api/config` | 依赖 Pydantic 模型校验 ✅（做得好）|

---

### 5.5 测试覆盖率不足

当前测试文件:
- `tests/test_config_loader.py` — 仅 1 个测试用例
- `tests/test_task_executor.py` — 4 个测试用例（变量解析 + TaskManager 安全）

**缺失的关键测试**:
- 认证流程模拟测试（可用 Playwright mock）
- 网络检测逻辑测试
- 配置验证边界值测试
- API 端点集成测试
- WebSocket 连接管理测试
- `TimeUtils.is_in_pause_period` 边界时间测试（跨天场景）

---

## 六、性能优化建议

### 6.1 高优先级

| 编号 | 优化项 | 预期收益 | 复杂度 |
|------|--------|----------|--------|
| P-1 | **浏览器实例复用**：实现浏览器池，避免每次认证都启动/销毁 Chromium | 减少 CPU/内存峰值约 60% | 中 |
| P-2 | **前端静态资源本地化**：Vue/Axios/Fonts 内嵌到项目 | 消除外网依赖，首次加载速度提升 80%+ | 低 |
| P-3 | **日志去重**：避免 `setup_logger()` 重复配置根 logger | 减少不必要的 I/O 开销 | 低 |

### 6.2 中优先级

| 编号 | 优化项 | 预期收益 | 复杂度 |
|------|--------|----------|--------|
| P-4 | **网络检测并行化**：`is_network_available_socket` 和 `_http` 可并发执行 | 检测延迟降低约 50% | 低 |
| P-5 | **WebSocket 消息批量推送**：高频日志时合并推送 | 减少 WebSocket 帧数 | 中 |
| P-6 | **`_find_first_visible_locator` 使用 Playwright 内置 wait** | 更稳定高效的选择器等待 | 中 |

### 6.3 低优先级

| 编号 | 优化项 | 预期收益 | 复杂度 |
|------|--------|----------|--------|
| P-7 | 配置文件变化监听（watchdog）：替代当前重启监控的方式 | 配置热更新体验提升 | 中 |
| P-8 | 日志文件压缩归档：超过保留期的日志自动 gzip | 磁盘空间节省 | 低 |

---

## 七、可读性与可维护性评估

### 7.1 做得好的方面 ✅

1. **清晰的分层架构**: `src/`(业务) → `backend/`(API) → `frontend/`(视图)，职责分明
2. **完善的工具类拆分**: `utils/` 下按职责分为 8 个子模块，符合单一职责原则
3. **任务系统的变量展开引擎**: 支持循环检测、深度限制，设计稳健
4. **安全的任务 ID 校验**: 路径遍历防护（`relative_to` 检查）、ID 白名单正则
5. **渐进式启动器**: SHA256 哈希比对依赖变更，避免不必要的重装
6. **三平台开机自启动**: macOS(launchd) + Linux(systemd) + Windows(VBS) 完整覆盖
7. **Pydantic 模型驱动的 API 校验**: `MonitorConfigPayload` 字段级约束完善
8. **WebSocket 日志实时推送**: 前端用户体验良好

### 7.2 需要改进的方面 ⚠️

| 维度 | 当前状态 | 建议 |
|------|----------|------|
| **文档字符串** | 大部分有中文 docstring，但部分缺失（如 `browser.py` 部分方法） | 补全所有 public 方法的 docstring |
| **类型注解** | 混合使用 `typing.Dict` 和 `dict` | 统一为现代注解 |
| **常量管理** | User-Agent 在 3 个地方各自定义 | 提取到 `constants.py` 统一管理 |
| **错误码体系** | 仅使用 success bool + message string | 定义标准错误码枚举 |
| **日志规范** | 混合使用 emoji 前缀 (✅❌🚀📝⚠️) 与纯文本 | 统一风格，考虑去除 console emoji |
| **前端代码组织** | 多文件模块化设计良好 ✅ | 可引入 TypeScript 或至少 JSDoc 注释 |

---

## 八、后续开发路线图

### Phase 1: 安全加固（建议 1-2 周）

| 序号 | 任务 | 优先级 |
|------|------|--------|
| 1.1 | 为写操作 API 添加简易 token 鉴权中间件 | P0 |
| 1.2 | `GET /api/config` 返回密码掩码（当前明文返回给前端） | P0 |
| 1.3 | 移除或限定 `--disable-web-security` 参数 | P1 |
| 1.4 | 添加 CORS 配置（即使当前仅 localhost） | P1 |

### Phase 2: 稳定性提升（建议 2-3 周）

| 序号 | 任务 | 优先级 |
|------|------|--------|
| 2.1 | 修复 `monitor_core.py` 的 asyncio 嵌套问题 | P1 |
| 2.2 | 清理未使用的 `.env` 配置项 | P2 |
| 2.3 | 统一 `resolve_port` 实现（消除 launcher/app 双份代码） | P2 |
| 2.4 | 修复 `shutdown_server` 的托盘实例问题 | P2 |
| 2.5 | 清理废弃的 `campus_login.main()` 入口或标记 deprecated | P2 |
| 2.6 | 统一各处默认值（monitor_interval, low_resource_mode 等） | P2 |

### Phase 3: 性能与体验优化（建议 2-3 周）

| 序号 | 任务 | 优先级 |
|------|------|--------|
| 3.1 | 浏览器实例池/长生命周期复用 | P1 |
| 3.2 | 前端依赖本地化（Vue/Axixs 内嵌） | P1 |
| 3.3 | 修复 `setup_logger` 重复配置根 logger 问题 | P2 |
| 3.4 | 网络检测 Socket + HTTP 并行化 | P2 |
| 3.5 | 任务编辑器增加 JSON Schema 校验与语法高亮 | P3 |

### Phase 4: 功能扩展（建议 4-6 周）

| 序号 | 任务 | 优先级 | 说明 |
|------|------|--------|------|
| 4.1 | **多账号支持** | P2 | 支持配置多个认证账号，轮切或故障转移 |
| 4.2 | **认证结果通知** | P2 | 登录成功/失败时推送桌面通知（Windows Toast / macOS Notification） |
| 4.3 | **流量/时长统计** | P3 | 记录每次认证后的在线时长、流量使用量（需解析运营商页面） |
| 4.4 | **移动端适配** | P3 | 响应式布局优化，支持手机查看状态 |
| 4.5 | **认证日志持久化** | P3 | 将关键认证事件写入 SQLite，提供历史查询 UI |
| 4.6 | **插件化认证适配器** | P3 | 不同学校使用不同认证页面，抽象出适配器接口 |
| 4.7 | **i18n 国际化** | P3 | 支持英文界面，方便非中文用户 |

### Phase 5: 工程化完善（持续进行）

| 序号 | 任务 | 优先级 |
|------|------|--------|
| 5.1 | 补充单元测试，目标覆盖率 > 60% | P1 |
| 5.2 | 引入 CI/CD（GitHub Actions 自动化测试 + 打包） | P2 |
| 5.3 | 代码风格检查（ruff formatter + lint） | P2 |
| 5.4 | 自动化 release 构建（PyInstaller/Nuitka 多平台打包） | P2 |
| 5.5 | API 文档自动生成（FastAPI OpenAPI schema） | P3 |

---

## 九、总结指标

| 维度 | 评分 (1-5) | 说明 |
|------|:-----------:|------|
| **功能完整性** | 4 | 核心认证、监控、任务系统齐全 |
| **代码质量** | 3.5 | 结构清晰，但有历史债务和冗余 |
| **安全性** | 3 | 凭据未暴露(已确认)，但API无鉴权、安全参数宽松等问题仍需关注 |
| **性能** | 3 | 可用但浏览器频繁启停是瓶颈 |
| **可维护性** | 3.5 | 分层清晰，但缺测试和文档 |
| **测试覆盖** | 1.5 | 仅有 5 个测试用例，大量核心逻辑无测试 |
| **综合评分** | **3.5** | 项目处于"可用但需加固"阶段（凭据安全已确认） |

---

*报告完毕。以上分析基于 v3.0.1 源码快照，建议按 Phase 顺序逐步推进改进。*
