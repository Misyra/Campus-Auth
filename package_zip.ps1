param(
    [string]$OutputDir = "release",
    [string]$Version = "",
    [switch]$IncludeExe = $true,
    [switch]$KeepStaging = $false
)

$ErrorActionPreference = "Stop"

$ProjectRoot = $PSScriptRoot
$StageRoot = Join-Path $ProjectRoot "build\zip-staging"
$StageDir = Join-Path $StageRoot "Campus-Auth"
$OutputPath = Join-Path $ProjectRoot $OutputDir
$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"

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
$ZipName = if ($ResolvedVersion) { "Campus-Auth-$ResolvedVersion-$Timestamp.zip" } else { "Campus-Auth-$Timestamp.zip" }
$ZipPath = Join-Path $OutputPath $ZipName
$ResolvedExePath = $null

$ExeCandidates = @(
    "dist/Campus-Auth-Setup.exe",
    "Campus-Auth-Setup.exe"
)

$IncludeItems = @(
    "app.py",
    "launcher.py",
    "bootstrap",
    "backend",
    "frontend",
    "src",
    "tasks",
    "doc",
    "requirements.txt",
    "pyproject.toml",
    "README.md",
    "LICENSE",
    ".env.example",
    "setup_env.ps1",
    "setup_env.sh",
    "Campus-Auth-Setup.spec"
)

if ($IncludeExe) {
    foreach ($candidate in $ExeCandidates) {
        $fullCandidate = Join-Path $ProjectRoot $candidate
        if (Test-Path $fullCandidate) {
            $ResolvedExePath = $fullCandidate
            break
        }
    }

    if ($ResolvedExePath) {
        Write-Host "检测到可执行文件: $ResolvedExePath" -ForegroundColor Cyan
    } else {
        Write-Host "未找到可执行文件（已检查 dist/Campus-Auth-Setup.exe 和 Campus-Auth-Setup.exe）" -ForegroundColor Yellow
        Write-Host "如需打包 exe，请先构建：pyinstaller Campus-Auth-Setup.spec" -ForegroundColor Yellow
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

if ($ResolvedExePath) {
    Copy-Item -Path $ResolvedExePath -Destination (Join-Path $StageDir "Campus-Auth-Setup.exe") -Force
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