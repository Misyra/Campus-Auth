# 代码与提交规范

> 本文档定义 Campus-Auth 项目的代码风格、类型约定、测试准则和 Commit Message 规范。

---

## 1. 代码风格规范

### 1.1 格式化工具

使用 **Ruff**（v0.11.9）统一 lint 和格式，通过 pre-commit hook 自动执行。提交代码前运行：

```bash
# 自动格式化
ruff format .
# 自动修复 lint 问题
ruff check --fix .
```

pre-commit 配置见 `.pre-commit-config.yaml`（仅 Ruff 一个 hook，同时执行 lint auto-fix + format）：

```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.11.9
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format
```

开发者无需手动调整缩进、行宽、引号风格等细节。

### 1.2 命名约定

| 类型 | 风格 | 示例 |
|------|------|------|
| 变量 / 函数 | `snake_case` | `get_profile`, `check_interval` |
| 类名 | `PascalCase` | `RuntimeConfig`, `ScheduleEngine` |
| 常量 | `UPPER_SNAKE_CASE` | `DEFAULT_TIMEOUT`, `PROJECT_ROOT` |
| 私有成员 | 单下划线前缀 | `_internal_state`, `_cleanup()` |
| 模块级私有 | 单下划线前缀 | `_TEMP_MAX_AGE = 7`, `_update_cache` |
| 类型参数 | 单大写字母 | `T`, `R`（泛型函数） |
| 模块级 "私有" 函数 | 单下划线前缀 | `_safe_detect()`, `_flatten_dict()` |

### 1.3 Ruff 规则集

**启用规则（select）：** `E`（pycodestyle）、`F`（pyflakes）、`B`（bugbear）、`SIM`（简化）、`UP`（pyupgrade）、`PT`（pytest 风格）、`RUF`（ruff 特有）、`I`（isort）

**已禁用规则（ignore）及原因：**

| 规则 | 原因 |
|------|------|
| `RUF001/RUF002/RUF003` | 中文项目全角字符正常 |
| `B008` | FastAPI `Depends` 在默认参数中是标准做法 |
| `E501` | 行长度限制，改动量大且收益低 |
| `RUF012` | 类变量 `ClassVar` 注解，改动量大 |
| `PT019` | pytest fixture 参数注入风格 |
| `PT011` | `pytest.raises` 过于宽泛 |
| `PT017` | pytest 断言中使用 `in` |
| `SIM115` | 使用 context manager 打开文件（需要保持引用的场景不适合） |
| `RUF006` | store reference to `create_task`（事件循环退出后自动清理） |

**per-file-ignores：** `app/application.py` 忽略 `E402`（因 `mimetypes.add_type` 需在导入前调用）。

### 1.4 导入排序

三个分组，按空行分隔（Ruff `I` 规则自动处理）：

1. **标准库**（`os`, `time`, `asyncio`, `sys`, `threading` 等）
2. **第三方库**（`fastapi`, `loguru`, `pydantic`, `httpx`, `playwright` 等）
3. **本项目模块**（`app.xxx`）

```python
import asyncio
import threading
import time

from fastapi import APIRouter, HTTPException

from app.deps import MonitorServiceDep
from app.schemas import ApiResponse, LogEntry
from app.utils.logging import get_logger
```

### 1.5 类型注解

- **公共函数**：必须有参数类型和返回值类型注解
- **内部辅助函数**：建议添加，不做强制要求
- 使用 `from __future__ import annotations` 实现延迟注解求值（所有文件均使用）
- 类型检查工具：Pyright（basic 模式）

**正确：**
```python
def resolve_port(config: AppConfig, default: int = 50721) -> int:
    ...
```

**避免（缺少类型注解）：**
```python
def resolve_port(config, default=50721):
    ...
```

**常见模式：**
```python
# 集合类型
def list_tasks() -> list[dict[str, str]]: ...
def get_names() -> list[str]: ...

# 可选类型
def find_user(id: str | None = None) -> User | None: ...

# 集合 + 可选
def get_active() -> dict[str, str]: ...

# Callable
def bind_runtime_config(getter: Callable[[], RuntimeConfig]) -> None: ...
```

### 1.6 Pyright 配置

在 `pyrightconfig.json` 中配置：

```json
{
  "include": ["app", "main.py", "tests"],
  "pythonVersion": "3.12",
  "typeCheckingMode": "basic",
  "reportMissingImports": true
}
```

`basic` 模式下，以下报告全部关闭：`reportMissingTypeStubs`、`reportUnknownMemberType`、`reportUnknownParameterType`、`reportUnknownVariableType`、`reportUnknownArgumentType`、`reportPrivateUsage`、`reportUntypedFunctionDecorator`、`reportUntypedClassDecorator`、`reportUntypedBaseClass`、`reportMissingModuleSource`。

### 1.7 字符串风格

- 普通字符串：双引号（Ruff format 默认）
- Docstring：三双引号 `"""..."""`
- 包含双引号的字符串：使用单引号或转义
- 正则表达式：使用原始字符串 `r"..."`

```python
name = "校园网认证"
docstring = """模块说明"""
pattern = r"^https?://"
```

### 1.8 from **future** import annotations

**所有 `.py` 文件的第一个非注释行**（除模块级 docstring 外）必须为：

```python
from __future__ import annotations
```

这启用 **PEP 604** 联合类型写法（`str | None` 而非 `Optional[str]`）和 **PEP 563** 延迟注解求值。

### 1.9 日志方式

所有模块使用 `app.utils.logging.get_logger` 获取 logger：

```python
from app.utils.logging import get_logger

logger = get_logger("module_name", source="backend")
```

- `source` 参数：后端日志标记为 `"backend"`，前端日志标记为 `"frontend"`
- 日志级别：`logger.debug()`、`logger.info()`、`logger.warning()`、`logger.error()`
- 使用 loguru 风格的 `{}` 占位符（非 `%s`）：`logger.info("用户 {} 登录成功", username)`
- 异常记录用 `exc_info=True`：`logger.warning("操作失败: {}", exc, exc_info=True)`
- API 路由层统一使用 `api_logger`：`api_logger = get_logger("api", source="backend")`

### 1.10 异常处理模式

**API 路由层：**
```python
@contextmanager
def _handle_config_error(operation: str, *, log_warning: bool = False):
    """统一配置端点的 ValueError / 通用异常处理。"""
    try:
        yield
    except ValueError as exc:
        if log_warning:
            api_logger.warning("配置更新被拒绝: {}", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        api_logger.warning("{}失败: {}", operation, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"{operation}失败: {exc}") from exc
```

**Service 层：**
- 返回值约定：`(ok: bool, message: str)` 二元组
- 异常直接抛出，由 API 层捕获转换

### 1.11 配置模型风格

- 所有配置子模型使用 `frozen=True`（线程安全，无需 deepcopy）
- 字段使用 `Field()` 统一设置默认值、校验范围和验证规则
- 使用 `field_validator` 和 `model_validator` 进行自定义校验

```python
class BrowserSettings(BaseModel, frozen=True):
    headless: bool = True
    timeout: int = Field(default=8, ge=1, le=60)
    browser_channel: BrowserChannel = BrowserChannel.MSEdge
```

---

## 2. 注释与文档规范

### 2.1 语言

所有注释、docstring、文档均使用 **中文**。

### 2.2 模块级 docstring

每个 `.py` 文件的**第一行**必须是模块摘要，用一句话说明该模块的用途。格式为 `"""一句话说明。"""` 或 `"""说明 — 详细职责。"""`。

```python
"""FastAPI 应用入口 — 工厂模式：create_app() 延迟加载 FastAPI。"""

"""任务路由 — 任务的 CRUD、活动任务管理。"""

"""ScheduleEngine — 统一的后台服务引擎。

合并 MonitorService 和 SchedulerService 的全部功能，
使用 Actor 模型（asyncio loop 线程 + asyncio.Queue）进行命令派发。
"""
```

**注意：** 当前部分文件（如 `app/system_tray.py`、`app/monitor_service.py`）缺少模块级 docstring，新文件**必须添加**，旧文件建议补全。

### 2.3 类 / 函数 docstring

公共 API（被其他模块调用的类和函数）**必须**有 docstring，说明用途和关键参数语义。内部辅助函数可以省略。

```python
class RuntimeConfig(BaseModel, frozen=True):
    """运行时配置根模型 — 替代旧 dict[str, Any]。

    组合所有子集模型。
    frozen=True 保证线程安全，无需 deepcopy。
    """

class LoginOrchestrator:
    """登录执行的唯一入口。

    职责：
    - 配置校验（validate_login_config）
    - 去重与抢占（_slot）
    - Worker 提交与超时（resolve_worker_timeout）
    - 登录历史记录（LoginHistoryService）
    - cancel_event 生命周期
    """
```

### 2.4 行内注释

- 解释 **"为什么"** 而非 "是什么"
- 写在代码 **上方**，不要写在行尾（除非极短的标注）

```python
# 正确：解释原因
# Windows 上 mimetypes 模块可能无法正确识别 .js 的 MIME 类型
mimetypes.add_type("application/javascript", ".js")

# 避免：描述代码本身
mimetypes.add_type("application/javascript", ".js")  # 添加 JS MIME 类型
```

### 2.5 标记约定

使用全大写关键字 + 冒号，便于全局搜索：

```python
# TODO: 支持自定义检测目标
# FIXME: 并发场景下偶现竞态条件
# HACK: 绕过 Playwright 的可见性检查
```

### 2.6 章节分隔注释

长文件中使用 `# ── 章节名 ──` 格式分隔逻辑段落，前后空一行：

```python
# ── 健康检查 / 更新检测 ──

# ── 初始化状态 ──

# ── 关机 ──
```

---

## 3. Commit Message 约定

### 3.1 格式

```
<type>: <中文描述>
```

- `type`：变更类型（全小写）
- `subject`：中文描述，句末**不加句号**
- 一次 commit 只做一件事，保持原子性
- **不得添加** Claude 署名、Co-authored-by 或任何 AI 相关标记

### 3.2 Type 列表

| Type | 含义 | 示例 |
|------|------|------|
| `feat` | 新功能 | `feat: 新增定时任务调度模块` |
| `fix` | 缺陷修复 | `fix: 修复监控循环退出后重试策略未重置` |
| `refactor` | 重构（不改变外部行为） | `refactor: 提取公共启动逻辑为独立函数` |
| `docs` | 文档变更 | `docs: 补充 API 接口文档` |
| `style` | 代码格式调整（不影响逻辑） | `style: 统一导入排序` |
| `test` | 测试相关 | `test: 补充网络检测模块测试` |
| `chore` | 构建 / 工具链 / 依赖 | `chore: 升级 ruff 至 0.11.9` |
| `perf` | 性能优化 | `perf: 优化配置加载减少重复 IO` |
| `ci` | CI 配置变更 | `ci: 添加 Python 3.13 测试矩阵` |
| `build` | 构建系统变更 | `build: 迁移到 uv 包管理器` |

### 3.3 BREAKING CHANGE

在 type 后加 `!` 后缀：

```
feat!: 重构配置结构，移除旧版 dict 兼容层
```

---

## 4. 项目结构与模块约定

### 4.1 完整目录映射

```
app/
├── api/                    # API 路由层（16 个路由模块 + ws.py）
│   ├── monitor.py          # 监控启停、状态、日志、纯净模式
│   ├── config.py           # 配置 CRUD + 日志级别控制
│   ├── tasks.py            # 任务 CRUD + 排序
│   ├── profiles.py         # 配置方案 CRUD + 自动切换
│   ├── debug.py            # 调试会话
│   ├── repo.py             # 远程仓库代理
│   ├── system.py           # 健康检查、关机、卸载
│   ├── autostart.py        # 自启动管理
│   ├── ocr.py              # OCR 依赖管理
│   ├── tools.py            # 文档下载、背景图片管理
│   ├── scripts.py          # 脚本任务 CRUD + 执行
│   ├── scheduled_tasks.py  # 定时任务 CRUD + 历史
│   ├── history.py          # 登录历史
│   ├── browsers.py         # 浏览器检测
│   ├── icons.py            # SVG 图标服务
│   ├── install_playwright.py # Playwright 浏览器安装
│   └── ws.py               # WebSocket 日志推送处理器
├── services/               # 业务服务层（21 个模块）
│   ├── engine.py           # ScheduleEngine — Actor 模型引擎
│   ├── task_executor.py    # TaskExecutor — 任务执行器
│   ├── login_orchestrator.py  # 登录编排
│   ├── login_attempt.py       # 登录尝试
│   ├── login_runner.py        # 登录执行
│   ├── scheduler_service.py   # 定时调度
│   ├── monitor_service.py     # 网络监控核心
│   ├── profile_service.py     # 配置方案管理
│   ├── websocket_manager.py   # WebSocket 管理
│   ├── config_builder.py      # 配置构建
│   ├── debug_service.py       # 调试会话管理
│   ├── debug_session.py       # 调试会话状态
│   ├── retry_policy.py        # 重试策略
│   ├── autostart.py           # 自启动服务
│   ├── login_history_service.py  # 登录历史
│   ├── task_registry.py       # 定时任务注册表
│   ├── launcher.py            # 启动器
│   └── uninstall.py           # 卸载功能
├── workers/                # Playwright 工作线程
│   ├── playwright_worker.py      # Actor 模型工作线程
│   ├── playwright_bootstrap.py   # 环境准备
│   └── script_runner.py       # 脚本执行器
├── network/                # 网络检测（独立模块，无 services 依赖）
│   ├── probes.py           # TCP/HTTP/URL 并发探测
│   ├── decision.py         # 网络决策层
│   ├── detect.py           # 网关/SSID 检测
│   ├── interfaces.py       # 网卡管理
│   ├── parsers.py          # 探测目标字符串解析
│   ├── proxy.py            # SOCKS5 代理
│   └── utils.py            # IP 地址分类工具
├── tasks/                  # 任务系统
│   ├── manager.py          # TaskManager
│   ├── models.py           # StepConfig, TaskConfig, ScriptTaskInfo
│   ├── browser_runner.py   # 浏览器任务执行器
│   ├── step_handlers.py    # 步骤处理器
│   ├── validator.py        # 任务校验
│   └── variable_resolver.py # 变量解析器
├── utils/                  # 工具模块（20 个）
│   ├── logging.py          # 日志系统（loguru + DashboardSink）
│   ├── browser.py          # 浏览器上下文
│   ├── browser_registry.py # 浏览器检测
│   ├── crypto.py           # 密码加密（Fernet）
│   ├── env.py              # 环境变量模板替换
│   ├── exceptions.py       # 异常类
│   ├── files.py            # 文件操作
│   ├── platform.py         # 平台检测
│   ├── ports.py            # 端口工具
│   ├── process.py          # 进程管理
│   ├── repo_proxy.py       # 仓库代理
│   ├── shell_policy.py     # Shell 命令策略
│   ├── shell_utils.py      # Shell 工具
│   ├── shutdown.py         # 关闭工具
│   ├── time_utils.py       # 时间工具
│   ├── concurrent.py       # 并发工具
│   ├── config_utils.py     # 配置工具
│   ├── cancel_token.py     # 取消令牌
│   └── ...
├── application.py          # FastAPI 工厂（create_app）
├── container.py            # ServiceContainer DI 容器
├── deps.py                 # FastAPI Annotated 依赖注入别名
├── schemas.py              # Pydantic 模型（661 行）
├── constants.py            # 共享常量
└── system_tray.py          # 系统托盘
```

### 4.2 测试配套

新增模块必须配套测试文件，路径映射规则：

```
app/<模块>/<文件>.py → tests/test_<模块>/test_<文件>.py
```

**示例：**
- `app/services/engine.py` → `tests/test_services/test_engine.py`
- `app/utils/crypto.py` → `tests/test_utils/test_crypto.py`
- `app/network/decision.py` → `tests/test_network/test_decision.py`

**测试配置：**
```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"       # async 函数自动识别为异步测试
testpaths = ["tests"]
pythonpath = ["."]
addopts = "--strict-markers --tb=short"
filterwarnings = [
    "ignore:.*AsyncMockMixin.*:RuntimeWarning",
    "ignore:.*httpx.*:UserWarning",
]
```

**关键点：** `asyncio_mode = "auto"` 意味着所有 `async def test_*` 函数自动作为异步测试运行，**无需** `@pytest.mark.asyncio` 装饰器。

**测试目录结构：**
```
tests/
├── conftest.py              # 全局 fixture（pystray mock、路径注册）
├── test_runtime_config_models.py
├── test_api/                # API 路由层测试
├── test_services/           # services 层测试
├── test_utils/              # utils 层测试
├── test_network/            # network 层测试
├── test_config/             # 配置相关测试
├── test_tasks/              # 任务系统测试
├── test_workers/            # 工作线程测试
├── test_integration/        # 集成测试
└── test_core/               # 核心模块测试
```

**conftest.py 关键 fixture：**
- `mock_pystray`：function-scoped opt-in fixture，Windows 上 no-op，Linux/macOS mock pystray.Icon

### 4.3 前端资源

前端静态资源统一放在 `frontend/` 目录，由 FastAPI 静态文件服务托管：

```
frontend/
├── index.html              # 入口 HTML（单页应用）
├── app.js                  # Vue 3 应用主文件
├── template-loader.js      # 模板加载器
├── js/                     # JavaScript 模块
├── partials/               # HTML 模板片段（页面组件）
├── styles/                 # CSS 样式文件
├── vendor/                 # 第三方库
└── *.svg                   # 图标素材
```

**特点：** 无构建步骤的 Vue 3 SPA，ES Module 直接加载，不依赖 Node.js。

---

## 5. 架构模式

### 5.1 分层架构

```
API 层（app/api/）
  ↓ 通过 FastAPI Depends 获取服务实例
Services 层（app/services/）
  ↓ 调用
Workers 层（app/workers/） — Playwright Actor 模型
```

- **API 层**：纯路由定义，无业务逻辑，通过 deps.py 中的 Annotated 类型别名注入服务
- **Services 层**：核心业务逻辑，由 ServiceContainer 统一管理生命周期
- **Workers 层**：所有浏览器操作统一收归 Playwright Worker 队列

### 5.2 API 路由函数风格

```python
"""监控路由 — 监控启停、状态查询、日志、网络测试、纯净模式。"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.deps import MonitorServiceDep
from app.schemas import ApiResponse, MonitorStatusResponse
from app.utils.logging import get_logger

router = APIRouter()
api_logger = get_logger("api", source="backend")


@router.get("/api/status", response_model=MonitorStatusResponse)
def get_status(svc: MonitorServiceDep) -> MonitorStatusResponse:
    return svc.get_status()


@router.post("/api/monitor/start", response_model=ApiResponse)
def start_monitoring(svc: MonitorServiceDep) -> ApiResponse:
    ok, message = svc.start_monitoring()
    if ok:
        api_logger.info("启动监控成功")
    else:
        api_logger.warning("启动监控失败: {}", message)
    return ApiResponse(success=ok, message=message)
```

**路由函数规范：**
- 短小，仅调用服务层方法并记录日志
- 同步调用为主（部分 `async` 用于 IO 操作或 `asyncio.to_thread`）
- 使用 `response_model` 指定响应模型
- 操作成功/失败均记录日志

### 5.3 ServiceContainer 依赖注入

`app/container.py` 中的 `ServiceContainer` 是整个后端的 DI 容器。服务创建顺序（根据依赖关系）：

```
WebSocketManager（无依赖）
  → ProfileService + LoginHistoryService + TaskManager + AutoStartService + DebugSessionManager
  → TaskRegistry + TaskHistoryStore
  → TaskExecutor（依赖 registry, history_store, worker_getter, task_manager）
  → LoginOrchestrator（依赖 worker_getter, executor, login_history, profile_service）
  → TaskExecutor.bind_login_orchestrator()  ← 反向绑定打破循环引用
  → SchedulerService（依赖 registry, executor）
  → ScheduleEngine（依赖以上所有）
  → 延迟绑定：login_orchestrator / task_executor ← engine.get_runtime_config
```

**生命周期方法：**
- `startup()`：清理孤儿浏览器 → `start_web_services()` → `engine.boot()` → `engine.sync_scheduler_state()`
- `shutdown()`：`engine.shutdown()` → `wait_for_callbacks()` → `shutdown_probes()` → `task_executor.shutdown()` → `stop_web_services()` → `debug_manager.close()` → `ws_manager.close_all()` → `shutdown_worker()` → 清理 temp 目录

### 5.4 依赖注入类型别名

在 `app/deps.py` 中定义，统一通过 `request.app.state.services` 获取服务实例：

```python
def _get(attr: str):
    """生成从 request.app.state.services 取属性的 Depends 工厂。"""
    def _dep(request: Request):
        return getattr(request.app.state.services, attr)
    return _dep

MonitorServiceDep   = Annotated[ScheduleEngine, Depends(_get("engine"))]
ProfileServiceDep   = Annotated[ProfileService, Depends(_get("profile_service"))]
TaskManagerDep      = Annotated[TaskManager, Depends(_get("task_manager"))]
AutoStartServiceDep = Annotated[AutoStartService, Depends(_get("autostart_service"))]
DebugManagerDep     = Annotated[DebugSessionManager, Depends(_get("debug_manager"))]
LoginHistoryDep     = Annotated[LoginHistoryService, Depends(_get("login_history_service"))]
```

### 5.5 Actor 模型引擎

`ScheduleEngine` 使用 Actor 模型：

- 单一后台线程运行 `asyncio` 事件循环
- 通过 `asyncio.Queue` 接收 `EngineCommand`（类型化命令派发）
- 命令类型：`START`、`STOP`、`LOGIN`、`SHUTDOWN`、`RELOAD`、`APPLY_PROFILE`、`TEST_NETWORK`、`NOOP`
- 支持 `response_future` 实现调用方 await 执行结果
- WS 广播委托给 `WebSocketManager`

### 5.6 网络检测模块独立性

`app/network/` 是**独立模块**，不依赖 services 层，仅依赖 `app/schemas.py` 和 `app/utils/`：

- `probes.py`：并发执行 TCP/HTTP/URL 探测（asyncio 版）
- `decision.py`：封装暂停检查、网络状态判断、登录前置检查
- `detect.py`：跨平台网关 IP 和 WiFi SSID 检测

---

## 6. 版本号管理

版本号存储在 `pyproject.toml` 的 `[project]` 段，由 `app/version.py` 中的 `get_project_version()` 读取。升级版本号时需同步修改以下位置：

1. `pyproject.toml` — `version = "x.x.x"`
2. `resources/tools/task-recorder.user.js` — 第 4 行 `@version` 和第 22 行 `const VERSION`
3. `docs/changelog.md` — 新增版本条目
4. `.claude/change.md` — 新增修改记录

### 修改日志

每次修改都要同步到 `.claude/change.md` 修改日志文件。
