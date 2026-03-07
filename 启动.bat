@echo off
setlocal enabledelayedexpansion

chcp 65001 >nul 2>nul

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
cd /d "%ROOT%"

set "PY_DIR=%ROOT%\.jcu_python"
set "PY_EXE=%PY_DIR%\python.exe"
set "PY_ZIP=%PY_DIR%\python-embed.zip"
set "PY_VER=3.10.11"
set "PY_ARCH=amd64"
set "PIP_INDEX_URL=https://mirrors.tuna.tsinghua.edu.cn/pypi/simple"
if not defined PLAYWRIGHT_DOWNLOAD_HOST set "PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright"

echo [1/6] Preparing portable Python...
if not exist "%PY_EXE%" (
  if not exist "%PY_DIR%" mkdir "%PY_DIR%"

  powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$ErrorActionPreference='Stop';" ^
    "$u='https://mirrors.tuna.tsinghua.edu.cn/python-release/windows/python-%PY_VER%-embed-%PY_ARCH%.zip';" ^
    "Invoke-WebRequest -UseBasicParsing -Uri $u -OutFile '%PY_ZIP%'" >nul 2>nul
  if errorlevel 1 (
    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
      "$ErrorActionPreference='Stop';" ^
      "$u='https://www.python.org/ftp/python/%PY_VER%/python-%PY_VER%-embed-%PY_ARCH%.zip';" ^
      "Invoke-WebRequest -UseBasicParsing -Uri $u -OutFile '%PY_ZIP%'" >nul 2>nul
    if errorlevel 1 (
      echo Failed to download portable Python.
      exit /b 1
    )
  )

  powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$ErrorActionPreference='Stop';" ^
    "Expand-Archive -Path '%PY_ZIP%' -DestinationPath '%PY_DIR%' -Force"
  if errorlevel 1 (
    echo Failed to extract portable Python.
    exit /b 1
  )

  del /f /q "%PY_ZIP%" >nul 2>nul

  powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$p=Get-ChildItem '%PY_DIR%' -Filter 'python*._pth' | Select-Object -First 1;" ^
    "if($p){" ^
    "  $c=Get-Content $p.FullName;" ^
    "  if($c -notcontains 'Lib'){ Add-Content $p.FullName 'Lib' };" ^
    "  if($c -notcontains 'Lib\site-packages'){ Add-Content $p.FullName 'Lib\site-packages' };" ^
    "  if($c -notcontains 'import site'){ Add-Content $p.FullName 'import site' }" ^
    "}"
)

if not exist "%PY_EXE%" (
  echo Portable Python is not ready: %PY_EXE%
  exit /b 1
)

echo [2/6] Ensuring pip...
"%PY_EXE%" -c "import pip" >nul 2>nul
if errorlevel 1 (
  powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$ErrorActionPreference='Stop';" ^
    "$u='https://mirrors.aliyun.com/pypi/get-pip.py';" ^
    "Invoke-WebRequest -UseBasicParsing -Uri $u -OutFile '%PY_DIR%\get-pip.py'" >nul 2>nul
  if errorlevel 1 (
    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
      "$ErrorActionPreference='Stop';" ^
      "$u='https://bootstrap.pypa.io/get-pip.py';" ^
      "Invoke-WebRequest -UseBasicParsing -Uri $u -OutFile '%PY_DIR%\get-pip.py'" >nul 2>nul
    if errorlevel 1 (
      echo Failed to download get-pip.py.
      exit /b 1
    )
  )

  "%PY_EXE%" "%PY_DIR%\get-pip.py" --disable-pip-version-check --no-warn-script-location
  if errorlevel 1 (
    echo Failed to install pip.
    exit /b 1
  )
)

echo [3/6] Installing Python dependencies...
"%PY_EXE%" -m pip install --upgrade --disable-pip-version-check --no-warn-script-location --index-url "%PIP_INDEX_URL%" -r "%ROOT%\requirements.txt"
if errorlevel 1 (
  echo Failed to install requirements.
  exit /b 1
)

echo [4/6] Installing Playwright Chromium...
"%PY_EXE%" -m playwright install chromium
if errorlevel 1 (
  echo Failed to install Playwright Chromium.
  exit /b 1
)

echo [5/6] Starting web app...
set "JCU_PROJECT_ROOT=%ROOT%"
set "JCU_ENV_FILE=%ROOT%\.env"
set "JCU_AUTO_OPEN_BROWSER=true"
"%PY_EXE%" "%ROOT%\app.py"

endlocal
