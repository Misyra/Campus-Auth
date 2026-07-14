param(
    [string]$OutputDir = "release",
    [string]$Version = "",
    [switch]$IncludeExe,
    [switch]$KeepStaging = $false
)

$ErrorActionPreference = "Stop"

$ProjectRoot = $PSScriptRoot
$StageRoot = Join-Path $ProjectRoot "build\zip-staging"
$StageDir = Join-Path $StageRoot "Campus-Auth"
$OutputPath = Join-Path $ProjectRoot $OutputDir
$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"

if (-not $PSBoundParameters.ContainsKey("IncludeExe")) {
    $IncludeExe = $true
}

function Resolve-ProjectVersion {
    param([string]$Root)

    $pyprojectPath = Join-Path $Root "pyproject.toml"
    if (-not (Test-Path $pyprojectPath)) {
        return ""
    }

    $inProjectBlock = $false
    foreach ($line in (Get-Content -Path $pyprojectPath -Encoding UTF8)) {
        $trimmed = $line.Trim()
        if ($trimmed.StartsWith("[")) {
            $inProjectBlock = $trimmed -eq "[project]"
            continue
        }
        if (-not $inProjectBlock) {
            continue
        }

        $match = [regex]::Match($trimmed, '^version\s*=\s*"([^"]+)"\s*$')
        if ($match.Success) {
            return $match.Groups[1].Value
        }
    }

    return ""
}

$ResolvedVersion = if ($Version) { $Version } else { Resolve-ProjectVersion -Root $ProjectRoot }
$ZipName = if ($ResolvedVersion) { "Campus-Auth-$ResolvedVersion.zip" } else { "Campus-Auth.zip" }
$ZipPath = Join-Path $OutputPath $ZipName
$ResolvedExes = @()

$ExeCandidates = @(
    "start.exe",
    "update.exe"
)

$IncludeItems = @(
    "main.py",
    "app",
    "frontend",
    "tasks/browser/default.json",
    "tasks/browser/hidden_input.json",
    "tasks/scripts/test_http_login.json",
    "resources",
    "docs",
    "pyproject.toml",
    "uv.lock",
    "README.md",
    "启动请看我.md",
    "LICENSE",
    "start.sh",
    "resources/tools/start/start.go",
    "resources/tools/update/main.go"
)

if ($IncludeExe) {
    foreach ($candidate in $ExeCandidates) {
        $fullCandidate = Join-Path $ProjectRoot $candidate
        if (Test-Path $fullCandidate) {
            $ResolvedExes += $fullCandidate
            Write-Host "检测到可执行文件: $fullCandidate" -ForegroundColor Cyan
        }
    }

    if ($ResolvedExes.Count -eq 0) {
        Write-Host "未找到可执行文件（已检查 start.exe、update.exe）" -ForegroundColor Yellow
        Write-Host "如需打包 exe，请先构建：" -ForegroundColor Yellow
        Write-Host "  go build -ldflags=`"-s -w`" -o start.exe resources/tools/start/start.go" -ForegroundColor Yellow
        Write-Host "  go build -ldflags=`"-s -w`" -o update.exe resources/tools/git-puller/main.go" -ForegroundColor Yellow
    }
}

function Write-Info {
    param([string]$Message)
    Write-Host $Message -ForegroundColor Cyan
}

function Write-Warn {
    param([string]$Message)
    Write-Host $Message -ForegroundColor Yellow
}

function Remove-IfExists {
    param([string]$Path)
    if (Test-Path $Path) {
        Remove-Item $Path -Recurse -Force
    }
}

function Copy-ItemToStage {
    param([string]$SourcePath)

    $fullSource = Join-Path $ProjectRoot $SourcePath
    if (-not (Test-Path $fullSource)) {
        Write-Warn "跳过不存在的项目项: $SourcePath"
        return
    }

    $destination = Join-Path $StageDir $SourcePath
    $destinationParent = Split-Path $destination -Parent
    if (-not (Test-Path $destinationParent)) {
        New-Item -ItemType Directory -Path $destinationParent -Force | Out-Null
    }

    Copy-Item -Path $fullSource -Destination $destination -Recurse -Force
}

Write-Info "开始准备 Zip 打包"
Write-Info "项目根目录: $ProjectRoot"
Write-Info "输出目录: $OutputPath"
if ($ResolvedVersion) {
    Write-Info "使用版本号: $ResolvedVersion"
}

Remove-IfExists $StageRoot
New-Item -ItemType Directory -Path $StageDir -Force | Out-Null
New-Item -ItemType Directory -Path $OutputPath -Force | Out-Null

foreach ($item in $IncludeItems) {
    Copy-ItemToStage $item
}

# 清理 __pycache__ 和 .pyc 文件
Write-Info "清理缓存文件..."
Get-ChildItem -Path $StageDir -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force
Get-ChildItem -Path $StageDir -Recurse -File -Filter "*.pyc" | Remove-Item -Force

# 清理所有 AGENTS.md 文件
Get-ChildItem -Path $StageDir -Recurse -File -Filter "AGENTS.md" | Remove-Item -Force

# 清理 superpowers 目录（内部设计文档，不发布）
$superpowersDir = Join-Path $StageDir "docs\superpowers"
if (Test-Path $superpowersDir) {
    Remove-Item $superpowersDir -Recurse -Force
}

foreach ($exePath in $ResolvedExes) {
    $exeName = Split-Path $exePath -Leaf
    Copy-Item -Path $exePath -Destination (Join-Path $StageDir $exeName) -Force
}

if (Test-Path $ZipPath) {
    Remove-Item $ZipPath -Force
}

Write-Info "开始压缩: $ZipName"
Compress-Archive -Path (Join-Path $StageDir '*') -DestinationPath $ZipPath -Force

if (-not $KeepStaging) {
    Remove-IfExists $StageRoot
}

Write-Host "打包完成: $ZipPath" -ForegroundColor Green
