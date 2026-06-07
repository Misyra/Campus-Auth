@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion

:: Campus-Auth 启动器 — 自动下载 uv、安装依赖、启动应用
set "PROJECT_ROOT=%~dp0"
set "UV_DIR=%PROJECT_ROOT%.uv"
set "UV_VERSION=0.7.3"
set "UV_FILENAME=uv-x86_64-pc-windows-msvc.zip"

:: ── 查找 uv ──────────────────────────────────────────────

:: 1. 检查 PATH 中是否有 uv
where uv >nul 2>&1
if %errorlevel% equ 0 (
    set "UV_CMD=uv"
    goto :found_uv
)

:: 2. 检查本地 .uv 目录
if exist "%UV_DIR%\uv.exe" (
    set "UV_CMD=%UV_DIR%\uv.exe"
    goto :found_uv
)

:: 3. 下载 uv
call :download_uv
if %errorlevel% neq 0 (
    echo 错误：uv 下载失败
    pause
    exit /b 1
)
set "UV_CMD=%UV_DIR%\uv.exe"

:found_uv
echo 使用 uv: %UV_CMD%

:: ── 安装依赖 ─────────────────────────────────────────────

echo.
echo [1/3] 安装依赖...
"%UV_CMD%" sync
if %errorlevel% neq 0 (
    echo 错误：依赖安装失败（退出码 %errorlevel%）
    echo 请尝试手动运行: uv sync
    echo 如 uv.lock 损坏，可运行: uv lock --upgrade
    pause
    exit /b 1
)

:: ── 安装 Playwright Chromium ─────────────────────────────

echo.
echo [2/3] 安装 Playwright Chromium...
"%UV_CMD%" run playwright install chromium
if %errorlevel% neq 0 (
    echo 警告：Playwright Chromium 安装失败
    echo 如已安装可忽略，否则手动运行: uv run playwright install chromium
)

:: ── 启动应用 ─────────────────────────────────────────────

:: --install-only 模式：只安装依赖，不启动应用
if "%1"=="--install-only" (
    echo.
    echo 环境准备完成
    exit /b 0
)

echo.
echo [3/3] 启动 Campus-Auth...
"%UV_CMD%" run main.py %*
exit /b 0

:: ── 下载 uv 函数 ─────────────────────────────────────────

:download_uv
echo 正在下载 uv %UV_VERSION%...

if not exist "%UV_DIR%" mkdir "%UV_DIR%"
set "ARCHIVE=%UV_DIR%\uv.zip"
set "GITHUB_URL=https://github.com/astral-sh/uv/releases/download/%UV_VERSION%/%UV_FILENAME%"

:: 尝试镜像站（使用 curl，Windows 10+ 自带）
set "MIRRORS=https://ghfast.top/ https://gh-proxy.com/ https://ghproxy.net/"

for %%M in (%MIRRORS%) do (
    echo   尝试: %%M
    curl -fsSL --connect-timeout 10 --max-time 120 -o "%ARCHIVE%" "%%M%GITHUB_URL%" >nul 2>&1
    if exist "%ARCHIVE%" (
        :: 校验是否为有效的 zip 文件（防止下载到 HTML 错误页）
        tar -tf "%ARCHIVE%" >nul 2>&1
        if !errorlevel! equ 0 (
            goto :extract_uv
        ) else (
            echo   ⚠️ 下载的文件无效，尝试下一个源...
            del "%ARCHIVE%" >nul 2>&1
        )
    )
)

:: 回退到 GitHub
echo   尝试: GitHub 直连
curl -fsSL --connect-timeout 10 --max-time 120 -o "%ARCHIVE%" "%GITHUB_URL%" >nul 2>&1
if not exist "%ARCHIVE%" (
    echo 错误：所有下载源均失败
    echo 请手动安装 uv: https://docs.astral.sh/uv/
    exit /b 1
)
tar -tf "%ARCHIVE%" >nul 2>&1
if !errorlevel! neq 0 (
    echo 错误：GitHub 直连下载的文件无效
    del "%ARCHIVE%" >nul 2>&1
    exit /b 1
)

:extract_uv
echo 正在解压...
tar -xf "%ARCHIVE%" -C "%UV_DIR%"
del "%ARCHIVE%" >nul 2>&1

if not exist "%UV_DIR%\uv.exe" (
    echo 错误：解压失败
    exit /b 1
)

echo uv 下载完成
exit /b 0
