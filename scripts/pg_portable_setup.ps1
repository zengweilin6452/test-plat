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
$PgHome = Join-Path $Runtime "pg$($PgVersion.Split('-')[0])"
$PgData = Join-Path $Runtime 'pgdata'
$Bin = Join-Path $PgHome 'pgsql\bin'
$LogFile = Join-Path $Runtime 'pg.log'
$DownloadDir = Join-Path $Runtime 'downloads'

function Get-PgBin([string]$name) {
    $p = Join-Path $Bin "$name.exe"
    if (-not (Test-Path $p)) { throw "找不到 $p，先执行 init" }
    return $p
}

function Invoke-PgCtl([string[]]$Extra) {
    $pgctl = Get-PgBin 'pg_ctl'
    & $pgctl -D $PgData @Extra
    return $LASTEXITCODE
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
        $null = Invoke-PgCtl @('-l', $LogFile, '-w', 'start')
        Start-Sleep -Seconds 2
        $createdb = Join-Path $Bin 'createdb.exe'
        & $createdb -h 127.0.0.1 -p $Port -U $DbUser testdock 2>$null
        if ($LASTEXITCODE -ne 0) {
            Write-Host "[pg] 数据库 testdock 可能已存在（可忽略）"
        }
        Write-Host "[pg] 已启动: postgresql://$DbUser@127.0.0.1:$Port/testdock"
    }
    'stop' {
        $null = Invoke-PgCtl @('-m', 'fast', '-w', 'stop')
        Write-Host "[pg] 已停止"
    }
    'reset' {
        if (Test-Path (Join-Path $PgData 'postmaster.pid')) { $null = Invoke-PgCtl @('-m', 'immediate', 'stop') }
        if (Test-Path $PgData) { Remove-Item -Recurse -Force $PgData }
        Write-Host "[pg] 数据目录已删除，重新 init 即可"
    }
    'status' {
        if (Test-Path (Join-Path $PgData 'postmaster.pid')) {
            $null = Invoke-PgCtl @('status')
        } else {
            Write-Host "[pg] 未初始化或未运行"
        }
    }
}
