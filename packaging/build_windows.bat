@echo off
setlocal enabledelayedexpansion

echo Using script: %~f0
cd /d "%~dp0\.."

if "%PYTHON_BIN%"=="" set "PYTHON_BIN=.venv\Scripts\python.exe"
if not exist "%PYTHON_BIN%" (
  echo 未找到可用 Python: %PYTHON_BIN%
  echo 请先创建虚拟环境并安装依赖（例如: uv sync）
  exit /b 1
)

rem 防止外部环境变量注入旧参数（如 --include-package=pip）
set "NUITKA_OPTIONS="
set "NUITKA_EXTRA_OPTIONS="
set "NUITKA_EXTRA_ARGS="

echo 开始构建 Windows 可执行程序...
"%PYTHON_BIN%" -m nuitka ^
  --standalone ^
  --assume-yes-for-downloads ^
  --remove-output ^
  --output-dir=dist ^
  --output-filename=jcu-auto-network ^
  --include-package=ensurepip ^
  --include-package-data=ensurepip ^
  --nofollow-import-to=playwright ^
  --nofollow-import-to=playwright.async_api ^
  --nofollow-import-to=playwright.sync_api ^
  --include-data-dir=frontend=frontend ^
  --include-data-file=.env.example=.env.example ^
  app.py

if errorlevel 1 exit /b %errorlevel%

echo.
echo 构建完成:
echo   dist\app.dist\jcu-auto-network.exe
echo.
echo 说明:
echo   1) playwright 未打包，程序首次启动会自动下载安装
echo   2) .env 文件请放在可执行文件同目录（可先复制 .env.example）
exit /b 0
