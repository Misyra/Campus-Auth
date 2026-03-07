@echo off
setlocal enabledelayedexpansion

echo Using script: %~f0
cd /d "%~dp0\.."

if "%PYTHON_BIN%"=="" set "PYTHON_BIN=.venv\Scripts\python.exe"
if not exist "%PYTHON_BIN%" (
  echo Python not found: %PYTHON_BIN%
  echo Please create venv and install deps first.
  exit /b 1
)

rem prevent external env injecting old args
set "NUITKA_OPTIONS="
set "NUITKA_EXTRA_OPTIONS="
set "NUITKA_EXTRA_ARGS="

rem ensure pip exists in build interpreter, otherwise install from ensurepip
"%PYTHON_BIN%" -c "import importlib.util,sys;sys.exit(0 if importlib.util.find_spec('pip') else 1)"
if errorlevel 1 (
  echo pip not found in build python, bootstrapping pip...
  "%PYTHON_BIN%" -m ensurepip --upgrade
  if errorlevel 1 (
    echo Failed to bootstrap pip in build environment.
    exit /b 1
  )
)

echo Building Windows executable...
"%PYTHON_BIN%" -m nuitka ^
  --standalone ^
  --assume-yes-for-downloads ^
  --remove-output ^
  --output-dir=dist ^
  --output-filename=jcu-auto-network ^
  --include-package=pip ^
  --include-package-data=pip ^
  --include-package=ensurepip ^
  --include-package-data=ensurepip ^
  --include-module=optparse ^
  --nofollow-import-to=playwright ^
  --nofollow-import-to=playwright.async_api ^
  --nofollow-import-to=playwright.sync_api ^
  --include-data-dir=frontend=frontend ^
  --include-data-file=.env.example=.env.example ^
  app.py

if errorlevel 1 exit /b %errorlevel%

echo.
echo Build completed:
echo   dist\app.dist\jcu-auto-network.exe
echo.
echo Notes:
echo   1) playwright is not bundled; it will be installed on first start.
echo   2) put .env next to the executable (copy from .env.example).
exit /b 0
