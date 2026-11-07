# 停止由 scripts/dev_up.ps1 启动的**本次实例**（按 PID 文件，不按进程名全局匹配）。
# 用法: powershell -ExecutionPolicy Bypass -File scripts/dev_down.ps1
param([switch]$KeepPg)
$ErrorActionPreference = 'Continue'
. (Join-Path $PSScriptRoot "load_env.ps1")
$RepoRoot = Split-Path -Parent $PSScriptRoot
$RunDir = if ($env:TESTDOCK_RUNTIME_DIR) { $env:TESTDOCK_RUNTIME_DIR } else { Join-Path $RepoRoot '.runtime\dev' }
if (-not [IO.Path]::IsPathRooted($RunDir)) { $RunDir = Join-Path $RepoRoot $RunDir }

foreach ($Name in @('frontend', 'backend')) {
    $pidFile = Join-Path $RunDir "$Name.pid"
    if (-not (Test-Path $pidFile)) { continue }
    $raw = (Get-Content $pidFile -First 1).Trim()
    $targetPid = 0
    if (-not [int]::TryParse($raw, [ref]$targetPid)) { continue }
    $proc = Get-Process -Id $targetPid -ErrorAction SilentlyContinue
    if ($proc) {
        Write-Host "[down] 停止 $Name PID=$targetPid"
        # 先优雅终止（不带 /F），超时后强制；不含通配，不误杀其他服务
        taskkill /PID $targetPid /T 2>$null | Out-Null
        Start-Sleep -Milliseconds 700
        if (Get-Process -Id $targetPid -ErrorAction SilentlyContinue) {
            Stop-Process -Id $targetPid -Force -ErrorAction SilentlyContinue
        }
    }
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
}

# cmd 包装层被终止后，npx 拉起的 node/vite 会成为孤儿继续占用端口。
# 按端口反查，且只停命令行同时包含本项目 web 目录与 vite 的进程，避免误杀其他服务。
$WebPort = if ($env:TESTDOCK_WEB_PORT) { [int]$env:TESTDOCK_WEB_PORT } else { 5173 }
$viteRoot = Join-Path $RepoRoot 'web'
Get-NetTCPConnection -LocalPort $WebPort -State Listen -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique |
    ForEach-Object {
        $orphanPid = $_
        $orphan = Get-CimInstance Win32_Process -Filter "ProcessId=$orphanPid" -ErrorAction SilentlyContinue
        if ($orphan -and $orphan.CommandLine -and
            $orphan.CommandLine -like "*$viteRoot*" -and $orphan.CommandLine -like '*vite*') {
            Write-Host "[down] 停止孤儿 vite PID=$orphanPid"
            Stop-Process -Id $orphanPid -Force -ErrorAction SilentlyContinue
        }
    }

if (-not $KeepPg) {
    Write-Host "[down] 如需停 PG：powershell -File scripts/pg_portable_setup.ps1 stop"
}
Write-Host "[down] 完成"
