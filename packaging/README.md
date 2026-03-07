# 打包与分发说明

本项目使用 Nuitka 打包 `app.py`，产物为独立可执行目录（`standalone`）。

## 目标

- 输出可执行程序（无需用户自行安装 Python）
- 支持开机自启动（通过 Web 控制台或 CLI 启用）
- 不打包 Playwright，首次启动后自动下载安装 Playwright + Chromium
- 打包内置 `pip/ensurepip`，确保首次自动安装可用

## 目录约定

打包后可执行文件位于：

- macOS: `dist/app.dist/jcu-auto-network`
- Windows: `dist\app.dist\jcu-auto-network.exe`

`frontend/` 与 `.env.example` 会被一并打包到同目录结构中。

## 构建

### macOS

```bash
bash packaging/build_macos.sh
```

### Windows

```bat
packaging\build_windows.bat
```

## 运行与首次初始化

1. 将 `.env.example` 复制为 `.env` 并填写账号密码（放在可执行文件同目录）。
2. 启动可执行文件。
3. 首次启动会自动安装：
- `playwright` Python 包
- Chromium 浏览器内核

如果你在受限网络环境下，可通过环境变量覆盖下载源：

- `PIP_INDEX_URL`（Python 包源）
- `PLAYWRIGHT_DOWNLOAD_HOST`（浏览器下载源）

## 开机自启动适配说明

程序在“打包运行模式”下会自动设置：

- `JCU_START_EXECUTABLE` 为当前可执行文件路径
- `JCU_PROJECT_ROOT` 为可执行文件所在目录
- `JCU_ENV_FILE` 为同目录下 `.env`

因此启用开机自启动后，会直接拉起该可执行文件，而不是依赖 `uv run`。
