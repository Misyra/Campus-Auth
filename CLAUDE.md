# Campus-Auth 校园网自动认证工具

## 项目概述

Campus-Auth 是一个基于 Playwright、FastAPI 和 Vue 3 的校园网自动认证工具。通过 Web 控制台管理配置和任务，定时探测网络状态，断网时自动触发浏览器认证流程重连。支持多网络配置方案自动切换、系统托盘、开机自启动和实时日志推送。

当前版本：v4.1.0

## 技术栈

| 层级 | 技术 |
|------|------|
| 运行时 | Python 3.12（严格版本约束，不支持 3.13+） |
| Web 框架 | FastAPI + Uvicorn |
| 浏览器自动化 | Playwright（Chromium） |
| 数据校验 | Pydantic v2 |
| 前端 | Vue 3 SPA（单文件，无构建步骤，原生 ES Module） |
| 包管理 | uv（镜像源：清华 PyPI + npmmirror Python） |
| 代码检查 | Ruff（lint + format） |
| 测试 | pytest + pytest-asyncio |
| 日志 | loguru |
| 密码加密 | cryptography（Fernet） |

## 开发命令

```bash
# 安装依赖
uv sync

# 安装 pre-commit hook
uvx pre-commit install

# 安装 Playwright 浏览器
uv run playwright install chromium

# 启动服务
python main.py

# 运行全部测试
uv run pytest

# 运行指定测试文件
uv run pytest tests/test_task_executor.py -v

# 代码检查（lint）
uv run ruff check .

# 代码检查并自动修复
uv run ruff check --fix .

# 代码格式化
uv run ruff format .

# 完整检查流程（pre-commit 自动执行）
uvx pre-commit run --all-files
```

## 代码规范

### 命名约定

| 类型 | 风格 | 示例 |
|------|------|------|
| 变量/函数 | `snake_case` | `get_profile`, `check_interval` |
| 类名 | `PascalCase` | `RuntimeConfig`, `ScheduleEngine` |
| 常量 | `UPPER_SNAKE_CASE` | `DEFAULT_TIMEOUT`, `PROJECT_ROOT` |
| 私有成员 | 单下划线前缀 | `_internal_state`, `_cleanup()` |
| 模块级私有 | 单下划线前缀 | `_TEMP_MAX_AGE = 7` |

### Ruff 规则集

启用规则：`E`（pycodestyle 错误）、`F`（pyflakes）、`B`（bugbear）、`SIM`（简化）、`UP`（pyupgrade）、`PT`（pytest 风格）、`RUF`（ruff 特有）、`I`（isort）

已忽略规则及原因：
- `RUF001/RUF002/RUF003`：中文项目全角字符正常
- `B008`：FastAPI `Depends` 在默认参数中是标准做法
- `E501`：行长度不强制（改动量大）
- `PT019`：pytest fixture 参数注入风格

### 注释与文档

- 所有注释、docstring、文档均使用**中文**
- 每个 `.py` 文件必须有模块级 docstring（一行摘要）
- 公共 API（类和函数）必须有 docstring
- 行内注释解释"为什么"而非"是什么"，写在代码上方
- 标记约定：`TODO:`、`FIXME:`、`HACK:`（全大写 + 冒号）

### 字符串风格

- 普通字符串：双引号（Ruff format 默认）
- Docstring：三双引号 `"""..."""`

## 项目结构

```
Campus-Auth/
├── main.py                    # 统一启动入口（CLI + 启动编排）
├── pyproject.toml             # 项目元数据、依赖、工具配置
├── app/
│   ├── application.py         # FastAPI 主应用（工厂模式 create_app()）
│   ├── container.py           # ServiceContainer 依赖注入容器
│   ├── deps.py                # FastAPI Annotated 类型别名依赖注入
│   ├── schemas.py             # Pydantic 数据模型
│   ├── constants.py           # 共享常量（路径、超时、容量）
│   ├── version.py             # 版本读取（从 pyproject.toml）
│   ├── api/                   # API 路由层（16+ 个模块）
│   │   ├── monitor.py         # 监控控制
│   │   ├── config.py          # 配置管理
│   │   ├── tasks.py           # 任务管理
│   │   ├── profiles.py        # 配置方案
│   │   ├── debug.py           # 调试会话
│   │   ├── ws.py              # WebSocket 处理
│   │   └── ...                # 其他路由
│   ├── services/              # 业务服务层
│   │   ├── engine.py          # ScheduleEngine 统一后台引擎
│   │   ├── task_executor.py   # 任务执行器（双线程池）
│   │   ├── login_orchestrator.py # 登录编排
│   │   ├── login_handler.py   # 登录尝试处理
│   │   ├── login_runner.py    # 登录执行（login_once 模式）
│   │   ├── scheduler_service.py  # 定时调度
│   │   ├── monitor_service.py    # 网络监控核心
│   │   ├── profile_service.py    # 配置方案管理
│   │   ├── websocket_manager.py  # WebSocket 管理
│   │   ├── config_builder.py  # 配置构建
│   │   ├── debug_service.py   # 调试会话管理
│   │   ├── debug_session.py   # 调试会话状态
│   │   ├── retry_policy.py    # 重试策略
│   │   ├── autostart.py       # 自启动服务
│   │   ├── login_history_service.py # 登录历史
│   │   ├── task_registry.py   # 定时任务注册表
│   │   ├── launcher.py        # 启动器
│   │   └── uninstall.py       # 卸载功能
│   ├── network/               # 网络检测（独立模块）
│   │   ├── probes.py          # TCP/HTTP/URL 探测
│   │   ├── decision.py        # 网络决策层
│   │   └── detect.py          # 网关/SSID 检测
│   ├── tasks/                 # 任务模型
│   │   ├── __init__.py        # TaskManager
│   │   └── models.py          # TaskConfig, StepConfig 等
│   ├── workers/               # Playwright 工作线程
│   │   ├── playwright_worker.py    # Actor 模型工作线程
│   │   ├── playwright_bootstrap.py # 环境准备
│   │   └── script_runner.py       # 脚本执行器
│   ├── system_tray.py         # 系统托盘
│   └── utils/                 # 工具模块
│       ├── logging.py         # 日志系统（loguru 封装）
│       ├── crypto.py          # 密码加密（Fernet）
│       ├── browser.py         # 浏览器上下文管理
│       └── ...                # 其他工具（cancel_token, concurrent, files 等）
├── frontend/                  # Vue 3 SPA（无构建步骤）
├── config/                    # 运行时配置
│   ├── settings.json          # 主配置文件
│   └── profiles/              # 配置方案文件
├── tasks/                     # 任务定义（JSON 驱动）
│   ├── browser/               # 浏览器任务
│   ├── scripts/               # 脚本任务
│   └── scheduled/             # 定时任务
├── tests/                     # pytest 测试
├── docs/                      # 文档
├── resources/                 # 资源文件（图标、背景）
├── debug/                     # 日志与截图（按日期归档）
└── temp/                      # 临时文件（启动时自动清理）
```

## 架构要点

### 分层架构

```
API 层（app/api/）
  ↓ 通过 FastAPI Depends 获取服务
Services 层（app/services/）
  ↓ 调用
Workers 层（app/workers/）
```

- **API 层**：纯路由定义，无业务逻辑，通过 `deps.py` 中的 Annotated 类型别名注入服务
- **Services 层**：核心业务逻辑，由 ServiceContainer 统一管理生命周期
- **Workers 层**：Playwright Actor 模型工作线程，所有浏览器操作统一收归

### ServiceContainer 依赖注入

`app/container.py` 中的 `ServiceContainer` 是整个后端的 DI 容器：

1. 接收 `project_root` 和 `mode` 参数
2. 按依赖顺序创建所有服务实例（WebSocketManager → ProfileService → TaskManager → LoginOrchestrator → TaskExecutor → SchedulerService → ScheduleEngine）
3. 处理循环依赖：延迟绑定（`bind_runtime_config`）和 getter 函数（`worker_getter`）
4. 提供 `startup()` / `shutdown()` 生命周期管理
5. 通过 `app.state.services` 暴露给 FastAPI 路由

FastAPI 路由层通过 `app/deps.py` 中的 `_get(attr)` 工厂函数从 `request.app.state.services` 取服务：

```python
MonitorServiceDep = Annotated[ScheduleEngine, Depends(_get("engine"))]
```

### 网络检测模块独立

`app/network/` 是独立模块，不依赖 services 层：
- `probes.py`：并发执行 TCP/HTTP/URL 探测
- `decision.py`：封装暂停检查、网络状态判断、登录前置检查
- `detect.py`：跨平台网关 IP 和 WiFi SSID 检测（Windows/macOS/Linux）

### 任务系统 JSON 驱动

任务定义存储在 `tasks/` 目录下，按类型分：
- `tasks/browser/`：浏览器自动化任务
- `tasks/scripts/`：Python/PowerShell/cmd 脚本任务
- `tasks/scheduled/`：定时任务（含 history 子目录）

任务通过 `TaskManager` 管理，`TaskExecutor` 使用双线程池执行。

### Playwright Worker Actor 模型

`app/workers/playwright_worker.py` 实现 Actor 模型：
- 单一工作线程接收命令队列
- 所有浏览器操作通过队列串行化，避免并发冲突
- 提供 `get_worker()` 获取实例、`shutdown_worker()` 关闭、`cleanup_orphan_browsers()` 清理残留

### 前端无构建步骤

`frontend/` 目录直接包含 Vue 3 单文件组件（ES Module），由 FastAPI 静态文件服务托管，无需 Node.js 或构建工具。

## 测试规范

### 配置

```toml
# pyproject.toml
[tool.pytest.ini_options]
asyncio_mode = "auto"       # 自动模式，async 函数自动识别为异步测试
testpaths = ["tests"]
pythonpath = ["."]
addopts = "--strict-markers --tb=short"
```

关键点：`asyncio_mode = "auto"` 意味着所有 `async def test_*` 函数自动作为异步测试运行，无需 `@pytest.mark.asyncio` 装饰器。

### 测试目录结构

```
tests/
├── conftest.py              # 全局 fixture（pystray mock、临时目录等）
├── test_services/           # services 层测试
├── test_utils/              # utils 层测试
├── test_network/            # network 层测试
├── test_config/             # 配置相关测试
└── test_tasks/              # 任务相关测试
```

路径映射规则：`app/<模块名>/<文件>.py` → `tests/test_<模块名>/test_<文件>.py`

### 运行测试

```bash
# 全部测试
uv run pytest

# 指定文件
uv run pytest tests/test_services/test_engine.py -v

# 带覆盖率
uv run pytest --cov=app
```

## Git 规范

### 分支策略

| 分支 | 用途 |
|------|------|
| `main` | 主分支，稳定版本 |
| `dev` | 开发分支，功能分支从此创建 |

### 功能分支命名

```bash
git checkout dev
git checkout -b feat/my-feature
```

### Commit Message 格式

使用 Conventional Commits，描述使用中文：

```
<type>: <中文描述>
```

Type 列表：

| Type | 含义 | 示例 |
|------|------|------|
| `feat` | 新功能 | `feat: 新增定时任务调度模块` |
| `fix` | 缺陷修复 | `fix: 修复监控循环退出后重试策略未重置` |
| `refactor` | 重构 | `refactor: 提取公共启动逻辑为独立函数` |
| `docs` | 文档变更 | `docs: 补充 API 接口文档` |
| `style` | 代码格式调整 | `style: 统一导入排序` |
| `test` | 测试相关 | `test: 补充网络检测模块测试` |
| `chore` | 构建/工具链/依赖 | `chore: 升级 ruff 至 0.12.0` |
| `perf` | 性能优化 | `perf: 优化配置加载减少重复 IO` |
| `ci` | CI 配置变更 | `ci: 添加 Python 3.13 测试矩阵` |

规则：
- 一次 commit 只做一件事
- 句末不加句号
- BREAKING CHANGE 加 `!`：`feat!: 重构配置结构`
- 不得添加 Claude 署名、Co-authored-by 或任何 AI 相关标记

### PR 规范

- 从 `dev` 分支创建功能分支，PR 提交到 `dev`
- 使用 PR 模板填写变更说明
- 确保 CI 全部通过
- 一个 PR 聚焦一个功能或修复
- 关联相关 Issue（如有）

## 常见陷阱

### 环境与依赖

- Python 版本严格约束 `>=3.12,<3.13`，不要尝试用 3.13+
- uv 镜像源配置在 `pyproject.toml` 的 `[tool.uv]` 中，国内开发者无需额外配置
- Playwright 需要单独安装浏览器：`uv run playwright install chromium`

### 服务生命周期

- `ServiceContainer` 的服务创建有严格顺序依赖，新增服务注意插入位置
- `engine.start_thread()` 和 `engine.boot()` 是不同操作：`start_thread` 启动后台线程，`boot` 启动监控
- `shutdown()` 流程有顺序要求：先关闭引擎（停止提交任务），再关闭线程池，最后关闭 Playwright Worker

### Playwright Worker

- 所有浏览器操作必须通过 Worker 队列，不能直接操作 Playwright 对象
- `cleanup_orphan_browsers()` 在启动时调用，清理上次崩溃残留的浏览器进程
- Worker 命令有超时限制（默认 300 秒），参见 `constants.py` 中的 `WORKER_SUBMIT_TIMEOUT`

### 网络与配置

- `config/settings.json` 是运行时配置的唯一来源，路径由 `app/constants.py` 中的 `PROJECT_ROOT` 决定
- `AUTH_DATA_DIR`（`~/.campus_network_auth`）存储 PID 文件和登录历史
- 配置方案文件存储在 `config/profiles/` 目录

### 测试

- `asyncio_mode = "auto"` 已启用，无需手动添加 `@pytest.mark.asyncio`
- 无显示服务器环境（CI）下 pystray 会被自动 mock（`conftest.py` 中的 session 级 fixture）
- 测试文件路径映射：`app/<模块名>/<文件>.py` → `tests/test_<模块名>/test_<文件>.py`

### 版本号

版本号存储在 `pyproject.toml` 的 `[project]` 段，由 `app/version.py` 中的 `get_project_version()` 读取。升级版本号时需同步修改以下位置：

1. `pyproject.toml` — `version = "x.x.x"`
2. `resources/tools/task-recorder.user.js` — 第 4 行 `@version` 和第 22 行 `const VERSION`
3. `docs/changelog.md` — 新增版本条目
4. `.claude/change.md` — 新增修改记录

### 修改日志

每次修改都要同步到 `.claude/change.md` 修改日志文件。
