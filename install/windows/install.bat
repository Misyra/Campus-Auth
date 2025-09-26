@echo off
chcp 65001 > nul
setlocal enabledelayedexpansion

echo ========================================
echo JCU校园网自动认证工具 - Windows环境配置
echo ========================================

REM 获取当前脚本目录和项目根目录
set "SCRIPT_DIR=%~dp0"
set "PROJECT_ROOT=%SCRIPT_DIR%..\.."
cd /d "%PROJECT_ROOT%"

echo 当前项目目录: %CD%
echo Python环境目录: %ENV_DIR%

REM 配置Python版本和环境目录
set "PYTHON_VERSION=3.11.7"
set "ENV_DIR=%PROJECT_ROOT%\environment"
set "PYTHON_DIR=%ENV_DIR%\python"

echo.
echo [1/5] 检查Python环境...

REM 创建environment目录
if not exist "%ENV_DIR%" mkdir "%ENV_DIR%"

REM 检查是否已有Python目录
if exist "%PYTHON_DIR%" (
    echo 发现已有Python目录，检查版本...
    if exist "%PYTHON_DIR%\python.exe" (
        "%PYTHON_DIR%\python.exe" --version 2>nul | findstr "Python %PYTHON_VERSION%" >nul
        if !errorlevel! equ 0 (
            echo Python %PYTHON_VERSION% 已存在，跳过下载
            goto :install_pip
        )
    )
    echo 清理旧版本Python目录...
    rmdir /s /q "%PYTHON_DIR%" 2>nul
)

echo 下载Python %PYTHON_VERSION% 嵌入式版本...
mkdir "%PYTHON_DIR%" 2>nul

REM 使用镜像源下载Python（优先使用华为云镜像）
set "PYTHON_FILENAME=python-%PYTHON_VERSION%-embed-amd64.zip"
set "MIRROR_URLS[0]=https://mirrors.huaweicloud.com/python/%PYTHON_VERSION%/%PYTHON_FILENAME%"
set "MIRROR_URLS[1]=https://mirrors.aliyun.com/python-release/windows/%PYTHON_FILENAME%"
set "MIRROR_URLS[2]=https://www.python.org/ftp/python/%PYTHON_VERSION%/%PYTHON_FILENAME%"

set "DOWNLOAD_SUCCESS=0"
for /l %%i in (0,1,2) do (
    if !DOWNLOAD_SUCCESS! equ 0 (
        echo 尝试镜像源 %%i...
        powershell -Command "& { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; try { Invoke-WebRequest -Uri '!MIRROR_URLS[%%i]!' -OutFile '%PYTHON_DIR%\python.zip' -TimeoutSec 30; exit 0 } catch { exit 1 } }" 2>nul
        if !errorlevel! equ 0 (
            set "DOWNLOAD_SUCCESS=1"
            echo 下载成功！
        ) else (
            echo 镜像源 %%i 下载失败，尝试下一个...
        )
    )
)

if !DOWNLOAD_SUCCESS! equ 0 (
    echo 错误: 所有镜像源下载失败，请检查网络连接
    pause
    exit /b 1
)

echo 解压Python...
powershell -Command "Expand-Archive -Path '%PYTHON_DIR%\python.zip' -DestinationPath '%PYTHON_DIR%' -Force"
del "%PYTHON_DIR%\python.zip"

REM 验证Python安装
if not exist "%PYTHON_DIR%\python.exe" (
    echo 错误: Python解压失败
    pause
    exit /b 1
)

echo Python %PYTHON_VERSION% 安装完成！

:install_pip
echo.
echo [2/5] 配置pip...

REM 启用pip（取消注释python311._pth中的import site）
set "PTH_FILE=%PYTHON_DIR%\python311._pth"
if exist "%PTH_FILE%" (
    powershell -Command "(Get-Content '%PTH_FILE%') -replace '^#import site', 'import site' | Set-Content '%PTH_FILE%'"
)

REM 检查pip是否可用
"%PYTHON_DIR%\python.exe" -m pip --version >nul 2>&1
if !errorlevel! neq 0 (
    echo 安装pip...
    REM 下载get-pip.py（使用镜像源）
    powershell -Command "& { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri 'https://mirrors.aliyun.com/pypi/get-pip.py' -OutFile '%PYTHON_DIR%\get-pip.py' }" 2>nul
    if !errorlevel! neq 0 (
        powershell -Command "& { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri 'https://bootstrap.pypa.io/get-pip.py' -OutFile '%PYTHON_DIR%\get-pip.py' }"
    )
    "%PYTHON_DIR%\python.exe" "%PYTHON_DIR%\get-pip.py"
    del "%PYTHON_DIR%\get-pip.py" 2>nul
)

echo 配置pip镜像源...
mkdir "%USERPROFILE%\.pip" 2>nul
(
echo [global]
echo index-url = https://mirrors.aliyun.com/pypi/simple/
echo trusted-host = mirrors.aliyun.com
echo [install]
echo trusted-host = mirrors.aliyun.com
) > "%USERPROFILE%\.pip\pip.conf"

echo.
echo [3/5] 安装项目依赖...

REM 升级pip
"%PYTHON_DIR%\python.exe" -m pip install --upgrade pip

REM 安装核心依赖
echo 安装python-dotenv...
"%PYTHON_DIR%\python.exe" -m pip install python-dotenv>=1.0.0

echo 安装playwright...
"%PYTHON_DIR%\python.exe" -m pip install playwright>=1.55.0

echo 安装pyinstaller...
"%PYTHON_DIR%\python.exe" -m pip install pyinstaller>=6.15.0

echo.
echo [4/5] 安装Playwright浏览器引擎...
"%PYTHON_DIR%\python.exe" -m playwright install chromium

if !errorlevel! neq 0 (
    echo 警告: Playwright浏览器安装可能失败，请稍后手动运行:
    echo "%PYTHON_DIR%\python.exe" -m playwright install chromium
)

echo.
echo [5/5] 创建便捷脚本...

REM 创建Python启动脚本
(
echo @echo off
echo set "PYTHON_DIR=%%~dp0environment\python"
echo "%%PYTHON_DIR%%\python.exe" %%*
) > "%PROJECT_ROOT%\python_run.bat"

REM 创建GUI启动脚本
(
echo @echo off
echo set "PYTHON_DIR=%%~dp0environment\python"
echo cd /d "%%~dp0"
echo if exist "app.exe" (
echo     echo 启动GUI程序...
echo     app.exe
echo ^) else (
echo     echo 启动GUI源码模式...
echo     "%%PYTHON_DIR%%\python.exe" app.py
echo ^)
echo pause
) > "%PROJECT_ROOT%\run_gui.bat"

REM 创建CLI启动脚本
(
echo @echo off
echo set "PYTHON_DIR=%%~dp0environment\python"
echo cd /d "%%~dp0"
echo if exist "app_cli.exe" (
echo     app_cli.exe %%*
echo ^) else (
echo     "%%PYTHON_DIR%%\python.exe" app_cli.py %%*
echo ^)
) > "%PROJECT_ROOT%\run_cli.bat"

REM 创建测试脚本
(
echo @echo off
echo set "PYTHON_DIR=%%~dp0environment\python"
echo cd /d "%%~dp0"
echo echo 测试Python环境...
echo "%%PYTHON_DIR%%\python.exe" --version
echo echo.
echo echo 测试依赖包...
echo "%%PYTHON_DIR%%\python.exe" -c "import playwright; import dotenv; print('依赖包导入成功！')"
echo echo.
echo echo 检查exe文件...
echo if exist "app.exe" (
echo     echo 发现 app.exe - GUI程序已就绪
echo ^) else (
echo     echo 未发现 app.exe - 将使用源码模式
echo ^)
echo if exist "app_cli.exe" (
echo     echo 发现 app_cli.exe - CLI程序已就绪
echo ^) else (
echo     echo 未发现 app_cli.exe - 将使用源码模式
echo ^)
echo echo.
echo echo 环境配置完成！可以运行 run_gui.bat 启动程序
echo pause
) > "%PROJECT_ROOT%\test_env.bat"

echo.
echo ========================================
echo 环境配置完成！
echo ========================================
echo.
echo 已安装:
echo   - Python %PYTHON_VERSION% 嵌入式版本
echo   - python-dotenv (环境变量管理)
echo   - playwright (浏览器自动化)
echo   - pyinstaller (打包工具)
echo   - Chromium 浏览器引擎
echo.
echo 便捷脚本:
echo   run_gui.bat    - 启动GUI界面
echo   run_cli.bat    - 启动命令行版本
echo   test_env.bat   - 测试环境配置
echo   python_run.bat - 直接使用Python
echo.
echo 打包命令示例（在项目根目录执行）:
echo   python_run.bat -m pyinstaller app.py --onefile --python-option u --paths environment\python\Lib\site-packages
echo   python_run.bat -m pyinstaller app_cli.py --onefile --python-option u --paths environment\python\Lib\site-packages
echo.
echo 注意：exe文件会依赖 environment 目录中的Python环境和依赖包
echo.
echo 现在可以运行 test_env.bat 测试环境，或开始打包程序！
echo.
pause