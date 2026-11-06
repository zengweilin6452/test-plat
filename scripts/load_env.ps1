# Read configuration as data; never execute .env contents as PowerShell.
$ConfigPython = if ($env:TESTDOCK_PYTHON) { $env:TESTDOCK_PYTHON } else { 'python' }
$ConfigJson = & $ConfigPython (Join-Path $PSScriptRoot 'deployment_env.py')
if ($LASTEXITCODE -ne 0) { throw '无法读取根目录 .env 配置。' }
$ConfigValues = $ConfigJson | ConvertFrom-Json
foreach ($Property in $ConfigValues.PSObject.Properties) {
    if ($null -eq [Environment]::GetEnvironmentVariable($Property.Name, 'Process')) {
        [Environment]::SetEnvironmentVariable($Property.Name, [string]$Property.Value, 'Process')
    }
}
