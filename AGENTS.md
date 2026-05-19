# PROJECT KNOWLEDGE BASE

**Generated:** 2026-05-19
**Commit:** adae5ff
**Branch:** main

## OVERVIEW

Campus-Auth (v3.6.6) — 校园网自动认证工具。FastAPI 后端 + Vue 3 单页前端，使用 Playwright 浏览器自动化执行校园网登录流程。支持多网络配置方案、自动监控断线重连、系统托盘、开机自启动。

## STRUCTURE

```
Campus-Auth/
├── app.py                  # 统一启动入口（包含启动、停止、状态查询、自启动管理）
├── launcher.py             # Windows 启动器（自动准备 Python 环境）
├── pyproject.toml          # 项目元数据 + uv 依赖配置
├── backend/                # FastAPI 后端（无路由前缀，直接 /api/*）
│   ├── main.py             # FastAPI 应用，路由注册，WebSocket
│   └── *_service.py        # 各业务模块（配置/监控/任务/方案/自启动/卸载）
├── src/                    # 核心逻辑（无框架依赖，可独立测试）
│   ├── task_executor.py    # 任务执行器：按 JSON 步骤驱动 Playwright
│   ├── monitor_core.py     # 监控核心：定时网络探测 + Profile 自动切换
│   ├── network_test.py     # TCP/HTTP 网络连通性检测
│   ├── utils/              # 工具模块（浏览器管理/配置/加密/日志/重试）
│   └── version.py          # 版本号读取
├── frontend/               # Vue 3 单页应用（无构建工具，纯 CDN 加载）
│   ├── index.html          # 入口页面
│   ├── app.js              # Vue 应用主文件
│   ├── template-loader.js  # HTML 模板加载器
│   ├── partials/pages/     # 页面模板（仪表盘/设置/任务/方案/关于）
│   ├── js/methods/         # 业务方法（按功能拆分：配置/监控/任务等）
│   └── styles/             # 样式文件
├── tasks/                  # 任务模板（JSON 格式定义认证步骤）
├── tests/                  # pytest 单元测试
├── doc/                    # 文档（任务编写指南等）
└── tools/                  # Tampermonkey 任务录制脚本
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| 认证登录流程 | `src/utils/login.py` | LoginAttemptHandler，统一登录逻辑 |
| 浏览器自动化 | `src/task_executor.py` | 按 JSON 步骤逐条执行 Playwright 操作 |
| 配置读写 | `backend/config_service.py` | .env + settings.json 读写 |
| 多网络方案 | `backend/profile_service.py` | 网关/SSID 检测 + 自动切换 |
| 监控循环 | `src/monitor_core.py` | 定时探测 + 触发认证 |
| 网络检测 | `src/network_test.py` | TCP 探测 + HTTP 探测，自动降级 |
| 浏览器实例 | `src/utils/browser.py` | BrowserContextManager 生命周期 |
| API 路由注册 | `backend/main.py` | FastAPI 应用，所有 API 端点 |
| 前端页面 | `frontend/partials/pages/` | 每个 HTML 文件对应一个页面 |
| 前端业务逻辑 | `frontend/js/methods/` | 按功能拆分的 JS 模块 |
| 任务 JSON 模板 | `tasks/` | JSON 格式认证步骤定义 |
| 密码加密 | `src/utils/crypto.py` | cryptography 加密/解密 |
| 日志系统 | `src/utils/logging.py` | 文件 + 内存缓冲区 + WebSocket 推送 |
| 测试 | `tests/` | pytest，按模块命名 test_*.py |

## CONVENTIONS

- **类型注解**: 所有 Python 代码必须使用类型注解（typing + `| None` 语法）
- **异步**: I/O 操作使用 `async/await`；Playwright 调用必须 await
- **日志**: 使用 `setup_logger()` / `get_logger()` 统一日志接口，禁止 `print()`
- **配置优先级**: 环境变量 → `.env` → `settings.json` → 代码默认值
- **错误处理**: 返回 `tuple[bool, str]` 模式；(False, "错误信息") 表示失败
- **导入风格**: 绝对导入，禁止 `sys.path` 修改；使用 `from .utils import X` 相对导入
- **F-strings**: 日志消息使用 f-string 或 % 格式化，**禁止** format()

## ANTI-PATTERNS

- 禁止 `sys.path.append` / `sys.path.insert` 修改模块搜索路径
- 禁止 `print()` 输出（必须用 logger）
- 禁止直接 `os.environ.__setitem__` 覆盖关键环境变量（PATH 等受保护）
- 禁止在非任务执行器代码中直接调用 Playwright API
- 禁止在 `src/utils/` 模块中导入 backend 模块（避免循环依赖）

## COMMANDS

```txt
# 安装依赖
uv sync

# 启动服务
uv run app.py
uv run app.py --no-browser
uv run app.py --tray

# 运行测试
uv run pytest
uv run pytest tests/test_task_executor.py -v

# 代码检查
uv run ruff check .
uv run ruff format .
```

## NOTES

- Playwright 浏览器实例通过 `BrowserContextManager` 管理生命周期，使用 `__aenter__`/`__aexit__` 协议
- 登录流程中的 `browser_manager` 变量类型为 `BrowserContextManager | None`，使用前需先断言非空
- 监控核心和任务执行器之间通过 `cancel_event` (threading.Event) 协调取消
- 配置方案（Profiles）支持按网关 IP 和 WiFi SSID 匹配，自动切换配置
- 前端使用原生 Vue 3 CDN + HTML 模板加载，无构建工具，无 npm
