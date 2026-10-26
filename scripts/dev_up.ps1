# 一键启动本地开发环境：后端 (python -m app.main) + 前端 (npx vite)。
#
# 用法:
#   powershell -ExecutionPolicy Bypass -File scripts/dev_up.ps1
#
# 行为：
#   - 后端工作目录 server/，端口 8000；前端工作目录 web/，端口 5173。
#   - 两个进程都后台启动，日志写入 .runtime/dev/*.log。
#   - 就绪探测：GET /api/v1/health 返回 200、http://127.0.0.1:5173 返回 200。
#   - 已在运行则跳过对应进程（幂等）。
#   - 停止用 scripts/dev_down.ps1。
$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $RepoRoot '.runtime\dev'
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Test-HttpOk([string]$Url) {
    try {
        $resp = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3
        return ($resp.StatusCode -eq 200)
    } catch { return $false }
}

function Wait-HttpOk([string]$Url, [int]$Seconds) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-HttpOk $Url) { return $true }
        Start-Sleep -Milliseconds 800
    }
    return $false
}

# ---------- 后端 ----------
if (Test-HttpOk 'http://127.0.0.1:8000/api/v1/health') {
    Write-Host "[dev] 后端已在运行 (http://127.0.0.1:8000)"
} else {
    $serverDir = Join-Path $RepoRoot 'server'
    Write-Host "[dev] 启动后端 python -m app.main ..."
    Start-Process -FilePath "python" -ArgumentList '-m', 'app.main' `
        -WorkingDirectory $serverDir `
        -RedirectStandardOutput (Join-Path $LogDir 'backend.log') `
        -RedirectStandardError (Join-Path $LogDir 'backend.err.log') `
        -WindowStyle Hidden
    if (-not (Wait-HttpOk 'http://127.0.0.1:8000/api/v1/health' 60)) {
        throw "后端 60s 内未就绪，查看 $LogDir\backend.err.log"
    }
    Write-Host "[dev] 后端就绪: http://127.0.0.1:8000"
}

# ---------- 前端 ----------
$webDir = Join-Path $RepoRoot 'web'
if (-not (Test-Path $webDir)) {
    Write-Host "[dev] 未找到 web/ 目录，跳过前端"
    return
}
if (Test-HttpOk 'http://127.0.0.1:5173/') {
    Write-Host "[dev] 前端已在运行 (http://127.0.0.1:5173)"
} else {
    if (-not (Test-Path (Join-Path $webDir 'node_modules'))) {
        Write-Host "[dev] web/node_modules 缺失，先执行 npm ci ..."
        Push-Location $webDir
        try { npm ci } finally { Pop-Location }
    }
    Write-Host "[dev] 启动前端 npx vite ..."
    Start-Process -FilePath "cmd.exe" -ArgumentList '/c', 'npx vite' `
        -WorkingDirectory $webDir `
        -RedirectStandardOutput (Join-Path $LogDir 'frontend.log') `
        -RedirectStandardError (Join-Path $LogDir 'frontend.err.log') `
        -WindowStyle Hidden
    if (-not (Wait-HttpOk 'http://127.0.0.1:5173/' 90)) {
        throw "前端 90s 内未就绪，查看 $LogDir\frontend.err.log"
    }
    Write-Host "[dev] 前端就绪: http://127.0.0.1:5173"
}

Write-Host "[dev] 全部就绪。停止: powershell -File scripts/dev_down.ps1"
