# EDB 便携版 PostgreSQL 17.6 初始化/起停（无需管理员权限）。
#
# 用法:
#   powershell -ExecutionPolicy Bypass -File scripts/pg_portable_setup.ps1 init     # 下载+解压+initdb+createdb
#   powershell -ExecutionPolicy Bypass -File scripts/pg_portable_setup.ps1 start
#   powershell -ExecutionPolicy Bypass -File scripts/pg_portable_setup.ps1 stop
#   powershell -ExecutionPolicy Bypass -File scripts/pg_portable_setup.ps1 status
#
# 端口 55432（避开本机默认 5432）；用户 testdock；trust 认证（仅回环，首期无登录 D5）。
param(
    [Parameter(Position = 0)]
    [ValidateSet('init', 'start', 'stop', 'status', 'reset')]
    [string]$Action = 'status',
    [string]$PgVersion = '17.6-1',
    [int]$Port = 55432,
    [string]$DbUser = 'testdock'
)

$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot
$Runtime = Join-Path $RepoRoot '.runtime'
$PgHome = Join-Path $Runtime "pg$($PgVersion.Split('.')[0].Split('-')[0])"  # 目录名只取主版本号: pg17
$PgData = Join-Path $Runtime 'pg17\data'
$Bin = Join-Path $PgHome 'pgsql\bin'
$LogFile = Join-Path $Runtime 'pg.log'
$DownloadDir = Join-Path $Runtime 'downloads'

function Get-PgBin([string]$name) {
    $p = Join-Path $Bin "$name.exe"
    if (-not (Test-Path $p)) { throw "找不到 $p，先执行 init" }
    return $p
}

function Invoke-PgCtl([string[]]$Extra) {
    # 沙箱环境下 pg_ctl 会被 restricted token 拦截（Win32 error 87），尽量不要依赖它；
    # 这里保留函数仅为兼容 status 的本地探测，start/stop 都已改为不经过 pg_ctl。
    $pgctl = Get-PgBin 'pg_ctl'
    & $pgctl -D $PgData @Extra
    return $LASTEXITCODE
}

$RunDir = Join-Path $Runtime 'pg17\run'
$DataDir = Join-Path $Runtime 'pg17\data'

function Wait-PgReady {
    # 就绪探测：重试 pg_isready，直到成功或超时（约 30s）
    $isready = Join-Path $Bin 'pg_isready.exe'
    for ($i = 0; $i -lt 30; $i++) {
        & $isready -h 127.0.0.1 -p $Port 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) { return $true }
        Start-Sleep -Milliseconds 1000
    }
    return $false
}

function Start-PgDirect {
    # 直接启动 postgres.exe（不经 pg_ctl）：pg_ctl 在沙箱/restricted token 下会失败。
    if (-not (Test-Path (Join-Path $PgData 'PG_VERSION'))) { throw "数据目录未初始化：先执行 init" }
    New-Item -ItemType Directory -Force -Path $RunDir | Out-Null
    $stdoutLog = Join-Path $RunDir 'postgres-stdout.log'
    $stderrLog = Join-Path $RunDir 'postgres-stderr.log'
    $proc = Start-Process -FilePath (Join-Path $Bin 'postgres.exe') `
        -ArgumentList '-D', $PgData, '-p', "$Port", '-c', 'listen_addresses=127.0.0.1' `
        -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog -PassThru -WindowStyle Hidden
    Write-Host "[pg] postgres.exe PID=$($proc.Id)，日志: $stdoutLog / $stderrLog"
    if (-not (Wait-PgReady)) { throw "postgres 启动后 30s 内未就绪，查看 $stderrLog" }
    Write-Host "[pg] 已就绪: 127.0.0.1:$Port"
}

function Stop-PgByPid {
    # 通过 postmaster.pid 里的 PID 停库（fast 停机）。pg_ctl stop 同样受沙箱限制，故直接 kill。
    $pidFile = Join-Path $PgData 'postmaster.pid'
    if (-not (Test-Path $pidFile)) { Write-Host "[pg] 未在运行"; return }
    $pgPid = (Get-Content $pidFile -First 1).Trim()
    try {
        $p = Get-Process -Id $pgPid -ErrorAction Stop
        if ($p.ProcessName -ne 'postgres') { throw "PID $pgPid 不是 postgres，拒绝停止" }
        # 先发正常终止信号（Windows 无 SIGTERM，用 taskkill 不带 /F 再兜底 /F）
        taskkill /PID $pgPid 2>$null | Out-Null
        for ($i = 0; $i -lt 20; $i++) {
            if (-not (Get-Process -Id $pgPid -ErrorAction SilentlyContinue)) { break }
            Start-Sleep -Milliseconds 500
        }
        if (Get-Process -Id $pgPid -ErrorAction SilentlyContinue) {
            Write-Host "[pg] 优雅停止超时，强制结束 PID $pgPid"
            taskkill /F /PID $pgPid | Out-Null
        }
        Write-Host "[pg] 已停止"
    } catch {
        Write-Host "[pg] 停止失败: $_"
    }
}

switch ($Action) {
    'init' {
        New-Item -ItemType Directory -Force -Path $Runtime, $DownloadDir | Out-Null
        if (-not (Test-Path $Bin)) {
            $zip = Join-Path $DownloadDir "postgresql-$PgVersion-windows-x64-binaries.zip"
            if (-not (Test-Path $zip)) {
                $url = "https://get.enterprisedb.com/postgresql/postgresql-$PgVersion-windows-x64-binaries.zip"
                Write-Host "[pg] 下载 $url"
                Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
            }
            Write-Host "[pg] 解压到 $PgHome"
            Expand-Archive -Path $zip -DestinationPath $PgHome -Force
        }
        if (-not (Test-Path (Join-Path $PgData 'PG_VERSION'))) {
            Write-Host "[pg] initdb -> $PgData"
            $initdb = Join-Path $Bin 'initdb.exe'
            & $initdb -D $PgData -U $DbUser --auth=trust -E UTF8 --locale=C
            if ($LASTEXITCODE -ne 0) { throw "initdb 失败" }
        }
        # 端口与监听地址（仅回环）
        $conf = Join-Path $PgData 'postgresql.conf'
        $content = Get-Content $conf -Raw
        $content = $content -replace "(?m)^#?\s*port\s*=.*$", "port = $Port"
        $content = $content -replace "(?m)^#?\s*listen_addresses\s*=.*$", "listen_addresses = '127.0.0.1'"
        Set-Content -Path $conf -Value $content -Encoding UTF8
        Write-Host "[pg] 完成。下一步: .\scripts\pg_portable_setup.ps1 start"
    }
    'start' {
        $ready = Join-Path $PgData 'postmaster.pid'
        if (Test-Path $ready) {
            Write-Host "[pg] 看起来已在运行（postmaster.pid 存在），如需强启先 stop"
            return
        }
        Start-PgDirect
        $createdb = Join-Path $Bin 'createdb.exe'
        & $createdb -h 127.0.0.1 -p $Port -U $DbUser testdock 2>$null
        if ($LASTEXITCODE -ne 0) {
            Write-Host "[pg] 数据库 testdock 可能已存在（可忽略）"
        }
        Write-Host "[pg] 已启动: postgresql://$DbUser@127.0.0.1:$Port/testdock"
    }
    'stop' {
        Stop-PgByPid
    }
    'reset' {
        if (Test-Path (Join-Path $PgData 'postmaster.pid')) { Stop-PgByPid }
        if (Test-Path $PgData) { Remove-Item -Recurse -Force $PgData }
        Write-Host "[pg] 数据目录已删除，重新 init 即可"
    }
    'status' {
        $isready = Join-Path $Bin 'pg_isready.exe'
        & $isready -h 127.0.0.1 -p $Port 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "[pg] 运行中: 127.0.0.1:$Port"
        } elseif (Test-Path $PgData) {
            Write-Host "[pg] 已初始化但未运行（执行 start 启动）"
        } else {
            Write-Host "[pg] 未初始化或未运行"
        }
    }
}
