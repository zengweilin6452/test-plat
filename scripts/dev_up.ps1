# 一键启动 TestDock（正式 / 演示均可）：后端 (python -m app.main) + 前端 (vite)。
#
# 用法:
#   powershell -ExecutionPolicy Bypass -File scripts/dev_up.ps1
#   $env:TESTDOCK_API_PORT=8010; $env:TESTDOCK_WEB_PORT=5174; ...
#
# 统一配置（环境变量，默认值与 config.py / vite.config.ts 一致）:
#   TESTDOCK_HOST              API 绑定地址（默认 127.0.0.1）
#   TESTDOCK_API_PORT          API 端口（默认 8000）
#   TESTDOCK_WEB_PORT          Vite 端口（默认 5173）
#   TESTDOCK_WEB_HOST          Vite 绑定地址（默认 127.0.0.1）
#   TESTDOCK_PYTHON            Python 解释器（默认 python，可含空格路径）
#   TESTDOCK_WEB_DIR           web 目录（默认安装目录下 web）
#   TESTDOCK_RUNTIME_DIR       PID 记录与日志目录（默认安装目录下 .runtime/dev）
#   TESTDOCK_DEMO_MODE         1 = 显式演示环境（需另配独立库与产物目录）
#
# 健康检查只认本实例：探测 URL 带平台标识，且先校验端口未被陌生进程占用。
# 停止脚本只作用于本脚本写下的 PID 文件，不会误杀其他服务。
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot "load_env.ps1")
$RepoRoot = Split-Path -Parent $PSScriptRoot
$HostAddr = if ($env:TESTDOCK_HOST) { $env:TESTDOCK_HOST } else { '127.0.0.1' }
$WebHost = if ($env:TESTDOCK_WEB_HOST) { $env:TESTDOCK_WEB_HOST } else { '127.0.0.1' }
$ApiPort = if ($env:TESTDOCK_PORT) { [int]$env:TESTDOCK_PORT } elseif ($env:TESTDOCK_API_PORT) { [int]$env:TESTDOCK_API_PORT } else { 8000 }
$WebPort = if ($env:TESTDOCK_WEB_PORT) { [int]$env:TESTDOCK_WEB_PORT } else { 5173 }
$Python = if ($env:TESTDOCK_PYTHON) { $env:TESTDOCK_PYTHON } else { 'python' }
$WebDir = if ($env:TESTDOCK_WEB_DIR) { $env:TESTDOCK_WEB_DIR } else { Join-Path $RepoRoot 'web' }
$RunDir = if ($env:TESTDOCK_RUNTIME_DIR) { $env:TESTDOCK_RUNTIME_DIR } else { Join-Path $RepoRoot '.runtime\dev' }
if (-not [IO.Path]::IsPathRooted($RunDir)) { $RunDir = Join-Path $RepoRoot $RunDir }
$ServerDir = Join-Path $RepoRoot 'server'
$ApiUrl = "http://${HostAddr}:${ApiPort}"
$WebUrl = "http://${WebHost}:${WebPort}"
& $Python (Join-Path $PSScriptRoot "deployment_env.py") --validate-demo
if ($LASTEXITCODE -ne 0) { throw "演示部署隔离校验失败。" }
New-Item -ItemType Directory -Force -Path $RunDir | Out-Null

function Test-PortInUse([int]$Port, [string]$BindHost) {
    $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Where-Object { $_.LocalAddress -in @($BindHost, '0.0.0.0', '::') }
    return [bool]$conn
}

function Get-PlatformHealth([string]$Url) {
    try {
        $resp = Invoke-RestMethod -Uri "$Url/api/v1/health" -TimeoutSec 3
        # 只认 TestDock 自己的健康响应：陌生进程返回 200 不算本平台就绪
        return ($resp.version -and $resp.db -and $resp.vendor)
    } catch { return $false }
}

function Wait-Ready([scriptblock]$Probe, [int]$Seconds, [string]$Label) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        if (& $Probe) { return $true }
        Start-Sleep -Milliseconds 800
    }
    Write-Host "[dev] $Label 在 ${Seconds}s 内未就绪"
    return $false
}

function Save-Pid([string]$Name, [int]$ProcessId) {
    Set-Content -Path (Join-Path $RunDir "$Name.pid") -Value "$ProcessId" -Encoding ASCII
}

if (Test-PortInUse $WebPort $WebHost) {
    # 端口被占用时不做「200 就当作已经启动」的误判
    throw "前端端口 $WebPort 已被占用；请更换 TESTDOCK_WEB_PORT 或停止占用进程。"
}

if (Get-PlatformHealth $ApiUrl) {
    Write-Host "[dev] 后端已在运行 ($ApiUrl)"
} elseif (Test-PortInUse $ApiPort $HostAddr) {
    throw "端口 $ApiPort 已被其他服务占用，且不是 TestDock API；请更换 TESTDOCK_API_PORT 或停止该进程。"
} else {
    Write-Host "[dev] 启动后端 $Python -m app.main ..."
    $env:TESTDOCK_HOST = $HostAddr
    $env:TESTDOCK_PORT = "$ApiPort"
    $env:TESTDOCK_API_PORT = "$ApiPort"
    $env:PYTHONUTF8 = '1'
    $proc = Start-Process -FilePath $Python -ArgumentList '-m', 'app.main' `
        -WorkingDirectory $ServerDir `
        -RedirectStandardOutput (Join-Path $RunDir 'backend.log') `
        -RedirectStandardError (Join-Path $RunDir 'backend.err.log') `
        -PassThru -WindowStyle Hidden
    Save-Pid 'backend' $proc.Id
    if (-not (Wait-Ready { Get-PlatformHealth $ApiUrl } 60 "后端 $ApiUrl")) {
        throw "后端 60s 内未就绪，查看 $RunDir\backend.err.log"
    }
    Write-Host "[dev] 后端就绪: $ApiUrl"
}

if (-not (Test-Path $WebDir)) {
    Write-Host "[dev] 未找到 web/ 目录，跳过前端"
    return
}
if (-not (Test-Path (Join-Path $WebDir 'node_modules'))) {
    Write-Host "[dev] web/node_modules 缺失，先执行 npm ci ..."
    Push-Location $WebDir
    try { npm ci } finally { Pop-Location }
}
Write-Host "[dev] 启动前端 npx vite --port $WebPort ..."
# 后端已由其它方式启动时也要把同一端口注入 Vite，避免代理落到默认 8000
$env:TESTDOCK_PORT = "$ApiPort"
$env:TESTDOCK_API_PORT = "$ApiPort"
$env:TESTDOCK_WEB_PORT = "$WebPort"
$env:TESTDOCK_WEB_HOST = $WebHost
$env:TESTDOCK_HOST = $HostAddr
$webProc = Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', 'npx vite --port', "$WebPort" `
    -WorkingDirectory $WebDir `
    -RedirectStandardOutput (Join-Path $RunDir 'frontend.log') `
    -RedirectStandardError (Join-Path $RunDir 'frontend.err.log') `
    -PassThru -WindowStyle Hidden
Save-Pid 'frontend' $webProc.Id
if (-not (Wait-Ready { try { (Invoke-WebRequest -Uri "$WebUrl/" -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200 } catch { $false } } 90 "前端 $WebUrl")) {
    throw "前端 90s 内未就绪，查看 $RunDir\frontend.err.log"
}
Write-Host "[dev] 前端就绪: $WebUrl"
Write-Host "[dev] 全部就绪。停止: powershell -File scripts/dev_down.ps1"
