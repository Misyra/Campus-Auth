#   JCU_auto_network: Python Environment Setup Script
#   Copyright © 2026

#   This script installs embedded Python and project dependencies
#   参考 AUTO-MAS 项目初始化方案设计

param(
    [string]$PythonVersion = "3.10",
    [string]$PipMirror = "https://pypi.tuna.tsinghua.edu.cn/simple",
    [switch]$ForceReinstall = $false,
    [switch]$Verbose = $false
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

# ==================== 配置 ====================

$ProjectRoot = $PSScriptRoot
$EnvDir = Join-Path $ProjectRoot "environment"
$PythonDir = Join-Path $EnvDir "python"
$PythonExe = Join-Path $PythonDir "python.exe"
$PipExe = Join-Path $PythonDir "Scripts" "pip.exe"
$TempDir = Join-Path $ProjectRoot "temp"
$RequirementsFile = Join-Path $ProjectRoot "requirements.txt"
$HashFile = Join-Path $EnvDir ".requirements_hash"
$LogDir = Join-Path $ProjectRoot "logs"
$LogFile = Join-Path $LogDir "setup_env.log"

# Python 嵌入式版本下载链接 (官方)
$PythonDownloadUrl = "https://www.python.org/ftp/python/${PythonVersion}.0/python-${PythonVersion}.0-embed-amd64.zip"

# ==================== 工具函数 ====================

function Get-Timestamp {
    return Get-Date -Format "yyyy-MM-dd HH:mm:ss"
}

function Write-Log {
    param([string]$Message, [string]$Level = "INFO")
    $timestamp = Get-Timestamp
    $logEntry = "[$timestamp] [$Level] $Message"
    
    if ($Verbose) {
        switch ($Level) {
            "INFO" { Write-Host $logEntry -ForegroundColor Cyan }
            "SUCCESS" { Write-Host $logEntry -ForegroundColor Green }
            "WARNING" { Write-Host $logEntry -ForegroundColor Yellow }
            "ERROR" { Write-Host $logEntry -ForegroundColor Red }
        }
    }
    
    try {
        if (-not (Test-Path $LogDir)) {
            New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
        }
        Add-Content -Path $LogFile -Value $logEntry
    } catch {
        # 忽略日志写入失败
    }
}

function Write-Info {
    param([string]$Message)
    Write-Log $Message "INFO"
}

function Write-Success {
    param([string]$Message)
    Write-Log $Message "SUCCESS"
}

function Write-Warning-Custom {
    param([string]$Message)
    Write-Log $Message "WARNING"
}

function Write-Error-Custom {
    param([string]$Message)
    Write-Log $Message "ERROR"
}

function Write-Progress-Stage {
    param([string]$Stage, [string]$Message, [int]$Percent)
    $timestamp = Get-Timestamp
    Write-Host "[$timestamp] [$Stage] $Message ($Percent%)" -ForegroundColor Yellow
    Write-Log "[$Stage] $Message ($Percent%)" "PROGRESS"
}

# ==================== 步骤 1: 环境检查 ====================

function Test-PythonEnvironment {
    Write-Info "=== 检查 Python 环境 ==="
    
    # 检查 exe 文件是否存在
    $exeExists = Test-Path $PythonExe
    Write-Info "Python 可执行文件存在：$exeExists"
    
    if (-not $exeExists) {
        return @{
            exeExists = $false
            canRun = $false
            version = $null
        }
    }
    
    # 检查能否正常运行
    try {
        $version = & $PythonExe -Version 2>&1
        Write-Success "Python 版本：$version"
        return @{
            exeExists = $true
            canRun = $true
            version = $version.ToString()
        }
    } catch {
        Write-Warning-Custom "Python 无法正常运行：$_"
        return @{
            exeExists = $true
            canRun = $false
            version = $null
            error = $_
        }
    }
}

function Test-PipEnvironment {
    Write-Info "=== 检查 Pip 环境 ==="
    
    # 检查 pip.exe 是否存在
    $exeExists = Test-Path $PipExe
    Write-Info "Pip 可执行文件存在：$exeExists"
    
    if (-not $exeExists) {
        return @{
            exeExists = $false
            canRun = $false
            version = $null
        }
    }
    
    # 检查能否正常运行
    try {
        $version = & $PythonExe -m pip --version 2>&1
        Write-Success "Pip 版本：$version"
        return @{
            exeExists = $true
            canRun = $true
            version = $version.ToString()
        }
    } catch {
        Write-Warning-Custom "Pip 无法正常运行：$_"
        return @{
            exeExists = $true
            canRun = $false
            version = $null
            error = $_
        }
    }
}

function Test-Dependencies {
    Write-Info "=== 检查依赖状态 ==="
    
    # 检查 requirements.txt 是否存在
    if (-not (Test-Path $RequirementsFile)) {
        Write-Warning-Custom "requirements.txt 不存在"
        return @{
            requirementsExists = $false
            needsInstall = $false
            currentHash = $null
            lastHash = $null
        }
    }
    
    # 计算当前哈希
    $currentHash = Get-FileHash $RequirementsFile -Algorithm SHA256
    Write-Info "当前哈希：$($currentHash.Hash.Substring(0, 8))..."
    
    # 读取上次安装的哈希
    $lastHash = $null
    if (Test-Path $HashFile) {
        try {
            $lastHash = Get-Content $HashFile -Raw
            Write-Info "上次哈希：$($lastHash.Substring(0, 8))..."
        } catch {
            Write-Warning-Custom "读取哈希文件失败：$_"
        }
    }
    
    # 判断是否需要安装
    $needsInstall = ($null -eq $lastHash) -or ($currentHash.Hash -ne $lastHash) -or $ForceReinstall
    
    return @{
        requirementsExists = $true
        needsInstall = $needsInstall
        currentHash = $currentHash.Hash
        lastHash = $lastHash
    }
}

# ==================== 步骤 2: 下载 Python ====================

function Install-Python {
    Write-Info "=== 安装 Python 嵌入式环境 ==="
    
    $zipPath = Join-Path $TempDir "python.zip"
    
    try {
        # 确保 Python 目录存在
        Write-Progress-Stage "Python" "创建 Python 目录..." 10
        if (-not (Test-Path $PythonDir)) {
            New-Item -ItemType Directory -Path $PythonDir -Force | Out-Null
            Write-Info "创建目录：$PythonDir"
        }
        if (-not (Test-Path $TempDir)) {
            New-Item -ItemType Directory -Path $TempDir -Force | Out-Null
            Write-Info "创建目录：$TempDir"
        }
        
        # 下载 Python
        Write-Progress-Stage "Python" "下载 Python 嵌入式版本..." 30
        Write-Info "下载地址：$PythonDownloadUrl"
        
        try {
            Invoke-WebRequest -Uri $PythonDownloadUrl -OutFile $zipPath -UseBasicParsing
            Write-Success "Python 下载完成"
        } catch {
            Write-Error-Custom "Python 下载失败：$_"
            return @{success = $false; error = $_}
        }
        
        # 解压 Python
        Write-Progress-Stage "Python" "正在解压 Python..." 60
        Write-Info "解压到：$PythonDir"
        
        try {
            Expand-Archive -Path $zipPath -DestinationPath $PythonDir -Force
            Write-Success "Python 解压完成"
        } catch {
            Write-Error-Custom "Python 解压失败：$_"
            return @{success = $false; error = $_}
        }
        
        # 启用 site-packages
        Write-Progress-Stage "Python" "配置 Python 环境..." 80
        $pthFile = Join-Path $PythonDir "python${PythonVersion.Replace('.', '')}._pth"
        
        if (Test-Path $pthFile) {
            Write-Info "配置文件：$pthFile"
            $content = Get-Content $pthFile -Raw
            $content = $content -replace '^#import site', 'import site'
            Set-Content -Path $pthFile -Value $content -NoNewline
            Write-Success "已启用 site-packages 支持"
        } else {
            Write-Warning-Custom "未找到 .pth 配置文件"
        }
        
        # 清理临时文件
        Write-Progress-Stage "Python" "清理临时文件..." 95
        if (Test-Path $zipPath) {
            Remove-Item $zipPath -Force
            Write-Info "清理临时文件：$zipPath"
        }
        
        Write-Progress-Stage "Python" "Python 安装完成" 100
        return @{success = $true}
    } catch {
        $errorMsg = "Python 安装失败：$_"
        Write-Error-Custom $errorMsg
        return @{success = $false; error = $errorMsg}
    }
}

# ==================== 步骤 3: 安装 Pip ====================

function Install-Pip {
    Write-Info "=== 安装 Pip ==="
    
    $getPipPath = Join-Path $PythonDir "get-pip.py"
    
    try {
        # 下载 get-pip.py
        Write-Progress-Stage "Pip" "下载 get-pip.py..." 20
        Write-Info "下载地址：https://bootstrap.pypa.io/get-pip.py"
        
        try {
            Invoke-WebRequest -Uri "https://bootstrap.pypa.io/get-pip.py" -OutFile $getPipPath -UseBasicParsing
            Write-Success "get-pip.py 下载完成"
        } catch {
            Write-Error-Custom "get-pip.py 下载失败：$_"
            return @{success = $false; error = $_}
        }
        
        # 执行安装
        Write-Progress-Stage "Pip" "安装 Pip..." 50
        Write-Info "使用镜像源：$PipMirror"
        
        try {
            $hostname = [System.Uri]::new($PipMirror).Host
            Write-Info "镜像源主机：$hostname"
            
            # 执行安装并捕获输出
            $installOutput = & $PythonExe $getPipPath -i $PipMirror --trusted-host $hostname 2>&1
            
            if ($LASTEXITCODE -eq 0) {
                Write-Success "Pip 安装成功"
                if ($Verbose -and $installOutput) {
                    $installOutput | ForEach-Object { Write-Info $_ }
                }
            } else {
                Write-Warning-Custom "Pip 安装退出码：$LASTEXITCODE"
            }
        } catch {
            Write-Error-Custom "Pip 安装失败：$_"
            return @{success = $false; error = $_}
        }
        
        # 清理临时文件
        Write-Progress-Stage "Pip" "清理临时文件..." 90
        if (Test-Path $getPipPath) {
            Remove-Item $getPipPath -Force
            Write-Info "清理临时文件：$getPipPath"
        }
        
        Write-Progress-Stage "Pip" "Pip 安装完成" 100
        return @{success = $true}
    } catch {
        $errorMsg = "Pip 安装失败：$_"
        Write-Error-Custom $errorMsg
        return @{success = $false; error = $errorMsg}
    }
}

# ==================== 步骤 4: 安装依赖 ====================

function Install-Dependencies {
    Write-Info "=== 安装项目依赖 ==="
    
    try {
        # 安装基础工具
        Write-Progress-Stage "依赖" "安装基础工具 (setuptools, wheel)..." 10
        Write-Info "升级 setuptools 和 wheel..."
        
        try {
            $hostname = [System.Uri]::new($PipMirror).Host
            $installOutput = & $PythonExe -m pip install --upgrade setuptools wheel -i $PipMirror --trusted-host $hostname 2>&1
            
            if ($LASTEXITCODE -eq 0) {
                Write-Success "基础工具安装完成"
                if ($Verbose -and $installOutput) {
                    $installOutput | ForEach-Object { Write-Info $_ }
                }
            } else {
                Write-Warning-Custom "基础工具安装退出码：$LASTEXITCODE"
            }
        } catch {
            Write-Warning-Custom "基础工具安装失败：$_，但继续执行"
        }
        
        # 安装 requirements.txt
        Write-Progress-Stage "依赖" "安装项目依赖..." 40
        Write-Info "安装依赖包..."
        
        try {
            $hostname = [System.Uri]::new($PipMirror).Host
            Write-Info "使用镜像源：$PipMirror (主机：$hostname)"
            
            $installOutput = & $PythonExe -m pip install -r $RequirementsFile -i $PipMirror --trusted-host $hostname --no-warn-script-location 2>&1
            
            if ($LASTEXITCODE -eq 0) {
                Write-Success "项目依赖安装完成"
                if ($Verbose -and $installOutput) {
                    # 解析 pip 输出，显示重要信息
                    $installOutput | ForEach-Object {
                        if ($_ -match "Successfully installed|Requirement already satisfied|Collecting") {
                            Write-Info $_
                        }
                    }
                }
            } else {
                Write-Error-Custom "项目依赖安装退出码：$LASTEXITCODE"
                if ($installOutput) {
                    $installOutput | ForEach-Object { Write-Error-Custom $_ }
                }
                return @{success = $false; error = "pip install 失败，退出码：$LASTEXITCODE"}
            }
        } catch {
            Write-Error-Custom "项目依赖安装失败：$_"
            return @{success = $false; error = $_}
        }
        
        # 保存哈希
        Write-Progress-Stage "依赖" "保存哈希值..." 95
        $currentHash = Get-FileHash $RequirementsFile -Algorithm SHA256
        $currentHash.Hash | Set-Content $HashFile -NoNewline
        Write-Success "哈希值已保存：$($currentHash.Hash.Substring(0, 8))..."
        
        Write-Progress-Stage "依赖" "依赖安装完成" 100
        return @{success = $true}
    } catch {
        $errorMsg = "依赖安装失败：$_"
        Write-Error-Custom $errorMsg
        return @{success = $false; error = $errorMsg}
    }
}

# ==================== 主流程 ====================

function Main {
    Write-Info "========================================"
    Write-Info "  JCU_auto_network 环境初始化脚本"
    Write-Info "  参考 AUTO-MAS 项目方案设计"
    Write-Info "========================================"
    Write-Info "  Python 版本：$PythonVersion"
    Write-Info "  Pip 镜像源：$PipMirror"
    Write-Info "  项目根目录：$ProjectRoot"
    Write-Info "========================================"
    Write-Info ""
    
    # 阶段 1: 检查 Python 环境
    Write-Info ">>> 阶段 1/3: 检查 Python 环境"
    $pythonResult = Test-PythonEnvironment
    
    if (-not $pythonResult.exeExists -or -not $pythonResult.canRun -or $ForceReinstall) {
        Write-Info ">>> 开始安装 Python..."
        $installResult = Install-Python
        if (-not $installResult.success) {
            Write-Error-Custom "Python 安装失败：$($installResult.error)"
            exit 1
        }
    } else {
        Write-Success "Python 已就绪 (版本：$($pythonResult.version))，跳过安装"
    }
    Write-Info ""
    
    # 阶段 2: 检查 Pip 环境
    Write-Info ">>> 阶段 2/3: 检查 Pip 环境"
    $pipResult = Test-PipEnvironment
    
    if (-not $pipResult.exeExists -or -not $pipResult.canRun -or $ForceReinstall) {
        Write-Info ">>> 开始安装 Pip..."
        $installResult = Install-Pip
        if (-not $installResult.success) {
            Write-Error-Custom "Pip 安装失败：$($installResult.error)"
            exit 1
        }
    } else {
        Write-Success "Pip 已就绪 (版本：$($pipResult.version))，跳过安装"
    }
    Write-Info ""
    
    # 阶段 3: 检查并安装依赖
    Write-Info ">>> 阶段 3/3: 检查依赖状态"
    $depResult = Test-Dependencies
    
    if (-not $depResult.requirementsExists) {
        Write-Error-Custom "requirements.txt 不存在，无法安装依赖"
        exit 1
    }
    
    if ($depResult.needsInstall -or $ForceReinstall) {
        Write-Info ">>> 开始安装依赖..."
        $installResult = Install-Dependencies
        if (-not $installResult.success) {
            Write-Error-Custom "依赖安装失败：$($installResult.error)"
            exit 1
        }
    } else {
        Write-Success "依赖已是最新，跳过安装"
    }
    Write-Info ""
    
    # 完成
    Write-Info "========================================"
    Write-Success "环境初始化完成！"
    Write-Info "========================================"
    Write-Info ""
    Write-Info "Python 路径：$PythonExe"
    Write-Info "Pip 路径：$PipExe"
    Write-Info ""
    Write-Info "使用方法:"
    Write-Info "  运行项目：& $PythonExe app.py"
    Write-Info "  安装新依赖：& $PythonExe -m pip install <包名> -i $PipMirror"
    Write-Info "  查看已安装包：& $PythonExe -m pip list"
    Write-Info ""
    Write-Info "日志文件：$LogFile"
    Write-Info ""
}

# 执行主流程
try {
    Main
} catch {
    Write-Error-Custom "初始化过程中发生未处理的错误：$_"
    exit 1
}
