@echo off
setlocal enabledelayedexpansion

chcp 65001 >nul 2>nul

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
cd /d "%ROOT%"

set "UV_INDEX_URL=https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple"
if not defined PLAYWRIGHT_DOWNLOAD_HOST set "PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright"

set "UV_BIN="
where uv >nul 2>nul
if not errorlevel 1 set "UV_BIN=uv"

if not defined UV_BIN (
  echo [1/4] Installing uv...
  set "UV_UNMANAGED_INSTALL=%ROOT%\.uv"
  powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$ErrorActionPreference='Stop'; irm https://astral.sh/uv/install.ps1 | iex"
  if exist "%UV_UNMANAGED_INSTALL%\uv.exe" set "UV_BIN=%UV_UNMANAGED_INSTALL%\uv.exe"
  if not defined UV_BIN if exist "%UV_UNMANAGED_INSTALL%\bin\uv.exe" set "UV_BIN=%UV_UNMANAGED_INSTALL%\bin\uv.exe"
  if not defined UV_BIN (
    echo Failed to install uv.
    exit /b 1
  )
) else (
  echo [1/4] Using uv from PATH...
)

echo [2/4] Syncing dependencies with mirror...
"%UV_BIN%" sync
if errorlevel 1 (
  echo uv sync failed.
  exit /b 1
)

echo [3/4] Installing Playwright Chromium...
"%UV_BIN%" run playwright install chromium
if errorlevel 1 (
  echo playwright install chromium failed.
  exit /b 1
)

echo [4/4] Starting web app...
set "JCU_PROJECT_ROOT=%ROOT%"
set "JCU_ENV_FILE=%ROOT%\.env"
set "JCU_AUTO_OPEN_BROWSER=true"
"%UV_BIN%" run app.py

endlocal
