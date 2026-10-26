# 一键停止开发环境：后端（python -m app.main）与前端（vite）。
# 用法: powershell -ExecutionPolicy Bypass -File scripts/dev_down.ps1 [-KeepPg]
param([switch]$KeepPg)
$ErrorActionPreference = 'Continue'

function Stop-Matching([string]$Pattern, [string]$Label) {
    Get-CimInstance Win32_Process -Filter "Name LIKE '%' OR Name LIKE '%.exe'" |
        Where-Object { $_.CommandLine -and $_.CommandLine -match $Pattern } |
        ForEach-Object {
            Write-Host "[down] 停止 $Label PID=$($_.ProcessId)"
            try { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue } catch {}
        }
}

Stop-Matching 'python.* -m app\.main|python\.exe.*-m app\.main' '后端'
Stop-Matching 'vite' '前端(vite)'

if (-not $KeepPg) {
    Write-Host "[down] 如需停 PG：powershell -File scripts/pg_portable_setup.ps1 stop"
}
Write-Host "[down] 完成"
