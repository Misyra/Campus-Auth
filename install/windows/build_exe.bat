@echo off
chcp 65001 > nul
setlocal enabledelayedexpansion

echo ========================================
echo JCU校园网自动认证工具 - 打包程序
echo ========================================

REM 获取项目根目录
set "SCRIPT_DIR=%~dp0"
set "PROJECT_ROOT=%SCRIPT_DIR%..\.."
cd /d "%PROJECT_ROOT%"

set "ENV_DIR=%PROJECT_ROOT%\environment"
set "PYTHON_DIR=%ENV_DIR%\python"

REM 检查Python环境
if not exist "%PYTHON_DIR%\python.exe" (
    echo 错误: 未找到Python环境，请先运行 install.bat 配置环境
    echo 期望路径: %PYTHON_DIR%\python.exe
    pause
    exit /b 1
)

echo 当前项目目录: %CD%
echo Python环境目录: %ENV_DIR%

REM 检查PyInstaller
"%PYTHON_DIR%\python.exe" -m pip show pyinstaller >nul 2>&1
if !errorlevel! neq 0 (
    echo 错误: 未找到PyInstaller，请先运行 install.bat 安装依赖
    pause
    exit /b 1
)

echo.
echo [1/3] 清理旧的构建文件...
if exist "dist" rmdir /s /q "dist" 2>nul
if exist "build" rmdir /s /q "build" 2>nul
if exist "*.spec" del "*.spec" 2>nul

echo.
echo [2/3] 打包GUI程序 (app.exe)...
"%PYTHON_DIR%\python.exe" -m pyinstaller ^
    --onefile ^
    --noconsole ^
    --name app ^
    --paths "%ENV_DIR%\python\Lib\site-packages" ^
    --add-data ".env.example;." ^
    --hidden-import tkinter ^
    --hidden-import playwright ^
    --hidden-import dotenv ^
    app.py

if !errorlevel! neq 0 (
    echo 错误: GUI程序打包失败
    pause
    exit /b 1
)

echo.
echo [3/3] 打包CLI程序 (app_cli.exe)...
"%PYTHON_DIR%\python.exe" -m pyinstaller ^
    --onefile ^
    --console ^
    --name app_cli ^
    --paths "%ENV_DIR%\python\Lib\site-packages" ^
    --add-data ".env.example;." ^
    --hidden-import playwright ^
    --hidden-import dotenv ^
    app_cli.py

if !errorlevel! neq 0 (
    echo 错误: CLI程序打包失败
    pause
    exit /b 1
)

echo.
echo 复制exe文件到项目根目录...
if exist "dist\app.exe" (
    copy "dist\app.exe" "%PROJECT_ROOT%\" >nul
    echo GUI程序: app.exe ✓
)
if exist "dist\app_cli.exe" (
    copy "dist\app_cli.exe" "%PROJECT_ROOT%\" >nul
    echo CLI程序: app_cli.exe ✓
)

echo.
echo 清理构建文件...
rmdir /s /q "dist" 2>nul
rmdir /s /q "build" 2>nul
del "*.spec" 2>nul

echo.
echo ========================================
echo 打包完成！
echo ========================================
echo.
echo 生成的文件:
if exist "%PROJECT_ROOT%\app.exe" echo   ✓ app.exe - GUI程序
if exist "%PROJECT_ROOT%\app_cli.exe" echo   ✓ app_cli.exe - CLI程序
echo.
echo 发布包结构:
echo   项目根目录/
echo   ├── app.exe              (GUI程序)
echo   ├── app_cli.exe          (CLI程序)  
echo   ├── environment/         (Python环境 - 必需)
echo   ├── run_gui.bat          (GUI启动脚本)
echo   ├── run_cli.bat          (CLI启动脚本)
echo   ├── .env.example         (配置模板)
echo   └── logs/                (日志目录)
echo.
echo 用户使用方法:
echo   1. 双击 run_gui.bat 启动图形界面
echo   2. 双击 run_cli.bat 使用命令行版本
echo   3. 首次运行会提示配置 .env 文件
echo.
echo 注意: exe文件依赖 environment 目录，发布时必须一起打包！
echo.
pause