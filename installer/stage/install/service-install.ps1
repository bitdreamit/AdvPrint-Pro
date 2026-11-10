# AdvPrint Pro v1.7.2 - install the Windows service (one UAC prompt)
# Runs from install\INSTALL-WINDOWS-SERVICE.bat or directly:
#   powershell -NoProfile -ExecutionPolicy Bypass -File service-install.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot          # install\ -> package root
$py   = Join-Path $root "runtime\AdvPrintPro.exe"
if (-not (Test-Path $py)) { $py = Join-Path $root "installer\runtime\AdvPrintPro.exe" }
if (-not (Test-Path $py)) { $py = Join-Path $root "runtime\pythonw.exe" }
if (-not (Test-Path $py)) { $py = Join-Path $root "installer\runtime\pythonw.exe" }
if (-not (Test-Path $py)) { $py = Join-Path $root "AdvPrintPro.exe" }
$hub = Join-Path $root "hub\advprint.py"
if (-not (Test-Path $hub)) { Write-Host "hub\advprint.py not found next to this script"; Pause; exit 1 }
Write-Host "AdvPrint Pro - installing the Windows service (confirm the UAC prompt)..."
Start-Process -FilePath $py -ArgumentList ('"' + $hub + '"', "service-install") -Verb RunAs -Wait
$res = Join-Path $env:USERPROFILE ".advprint\service_result.txt"
if (Test-Path $res) { Get-Content $res }
Write-Host ""
Write-Host "Check: services.msc -> 'AdvPrint Pro Service' (or: python advprint.py service status)"
Pause
