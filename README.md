# JCU 校园网自动认证（前后端分离版）

基于 `Playwright + FastAPI + Vue` 的校园网自动认证工具。

## 架构

- 后端：`FastAPI` 提供配置、监控、手动登录、网络测试 API
- 前端：`Vue 3 + Axios` 单页控制台（更美观、响应式布局）
- 核心：`src/monitor_core.py` 统一监控逻辑，CLI/API 复用

## 目录

```text
.
├── app.py                  # Web 入口（uv run app.py）
├── app_cli.py              # CLI 入口
├── backend/
│   ├── main.py             # FastAPI 应用
│   ├── monitor_service.py  # 后端运行时服务
│   ├── config_service.py   # 配置读写与映射
│   └── schemas.py          # API 数据模型
├── frontend/
│   ├── index.html          # 控制台页面
│   ├── style.css           # UI 样式
│   └── app.js              # 前端逻辑
└── src/
    ├── monitor_core.py     # 监控核心（重构后）
    ├── campus_login.py
    ├── network_test.py     # 重构为 httpx + socket
    └── utils.py
```

## 快速开始（uv）

1. 安装依赖

```bash
uv sync
```

2. 安装 Playwright 浏览器

```bash
uv run playwright install chromium
```

3. 启动 Web 控制台

```bash
uv run app.py
```

启动后打开 [http://127.0.0.1:50721](http://127.0.0.1:50721)

## CLI 使用

```bash
# 前台运行
uv run app_cli.py

# 后台守护模式
uv run app_cli.py --daemon

# 查看状态
uv run app_cli.py --status

# 停止后台服务
uv run app_cli.py --stop

# 开机自启动状态
uv run app_cli.py --autostart-status

# 启用开机自启动
uv run app_cli.py --autostart-enable

# 关闭开机自启动
uv run app_cli.py --autostart-disable
```

## 主要优化点

- 前后端分离，避免 Tk GUI 与业务代码强耦合
- 监控核心抽离到 `src/monitor_core.py`，删除重复逻辑
- 网络检测从 `curl 子进程` 改为 `httpx`，开销更低
- 新前端支持实时日志、状态面板、配置热更新
- 配置保存后自动重启监控流程，减少手工操作

## 配置

复制 `.env.example` 为 `.env` 后填写：

- `CAMPUS_USERNAME`
- `CAMPUS_PASSWORD`
- `CAMPUS_AUTH_URL`
- `APP_PORT`（可选，默认 `50721`）

其余配置可在 Web 控制台直接修改并保存。

## Nuitka 分发（无 Python 环境）

已提供整项目打包方案：
- 直接打包 `app.py`（后端 + 前端）
- 不内置 `playwright`，首次启动自动安装并下载 Chromium
- 启动后自动打开 Web UI（默认 `50721`）

构建命令：

```bash
# macOS
./packaging/build_macos.sh

# Windows
packaging\\build_windows.bat
```

详细说明见：
[packaging/README.md](/Users/misyra/JCU_auto_network/packaging/README.md)
