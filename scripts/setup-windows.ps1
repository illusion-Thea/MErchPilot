<#
MerchPilot Windows 本地开发环境初始化。

用法：
  powershell -ExecutionPolicy Bypass -File .\scripts\setup-windows.ps1
#>

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root "backend"
$venv = Join-Path $backend ".venv-windows"

if (-not (Test-Path (Join-Path $venv "Scripts\python.exe"))) {
    python -m venv $venv
}

$python = Join-Path $venv "Scripts\python.exe"
& $python -m pip install --upgrade pip
& $python -m pip install -e "$backend[dev]"

$frontend = Join-Path $root "frontend"
Push-Location $frontend
try {
    $env:CI = "true"
    pnpm install --frozen-lockfile
} finally {
    Pop-Location
}

Write-Host "MerchPilot Windows environment is ready."
Write-Host "Backend: $python"
Write-Host "Run tests: backend\\.venv-windows\\Scripts\\python.exe -m pytest -q -m 'not integration'"
Write-Host "Run frontend checks: cd frontend; node_modules\\.bin\\tsc.cmd --noEmit"
