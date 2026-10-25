# P1 验收：便携 PG -> 迁移 -> 种子 -> 只读 API -> 回归测试
# 用法: pwsh -File scripts/verify_p1.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$env:PYTHONUTF8 = "1"
$python = if ($env:TESTDOCK_PYTHON) { $env:TESTDOCK_PYTHON } else { "python" }
$pg = Join-Path $root ".runtime/pg17/pgsql"
$dbUrl = "postgresql+psycopg://testdock@127.0.0.1:55432/testdock"
$env:TESTDOCK_DATABASE_URL = $dbUrl
$env:TESTDOCK_TEST_DATABASE_URL = $dbUrl

function Step($name) { Write-Host ""; Write-Host "=== $name ===" -ForegroundColor Cyan }

Step "1/5 启动便携 PostgreSQL"
& (Join-Path $PSScriptRoot "pg_portable_setup.sh") start

Step "2/5 alembic upgrade head"
Push-Location (Join-Path $root "server")
try {
    & $python -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw "alembic upgrade 失败" }
} finally { Pop-Location }

Step "3/5 写入演示种子数据"
& $python (Join-Path $root "scripts/seed_demo.py")
if ($LASTEXITCODE -ne 0) { throw "seed_demo 失败" }

Step "4/5 校验库内对象数"
& (Join-Path $pg "bin/psql.exe") -h 127.0.0.1 -p 55432 -U testdock -d testdock -tAc @"
SELECT 'tables=' || count(*) FROM information_schema.tables
 WHERE table_schema='public' AND table_type='BASE TABLE';
"@

Step "5/5 只读 API 回归测试"
Push-Location $root
try {
    & $python -m pytest server/tests -q
    if ($LASTEXITCODE -ne 0) { throw "pytest 失败" }
} finally { Pop-Location }

Write-Host ""
Write-Host "P1 验收通过。" -ForegroundColor Green
