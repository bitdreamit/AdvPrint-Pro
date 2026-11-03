# AdvPrint Pro v2.8 - remove the Windows service (one UAC prompt)
# v2.8: stops the service FIRST (bullet-proof: status wait + PID kill),
# deletes the registration, then verifies it is really gone.
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot          # install\ -> package root
$py   = Join-Path $root "runtime\AdvPrintPro.exe"
if (-not (Test-Path $py)) { $py = Join-Path $root "installer\runtime\AdvPrintPro.exe" }
if (-not (Test-Path $py)) { $py = Join-Path $root "runtime\pythonw.exe" }
if (-not (Test-Path $py)) { $py = Join-Path $root "installer\runtime\pythonw.exe" }
if (-not (Test-Path $py)) { $py = Join-Path $root "AdvPrintPro.exe" }
$hub = Join-Path $root "hub\advprint.py"

Write-Host "AdvPrint Pro - removing the Windows service..."
# 1) stop + deregister without any prompt (this script is already admin
#    when the UAC prompt of the caller was confirmed; otherwise start
#    the helper elevated below)
$svc = Get-Service -Name AdvPrint -ErrorAction SilentlyContinue
if ($svc -and -not (Test-Path $hub)) {
  # hub files missing - do it inline (no python needed)
  Stop-Service -Name AdvPrint -Force -ErrorAction SilentlyContinue
  Start-Sleep 1
  sc.exe delete AdvPrint | Out-Null
}
# 2) normal path: the hub's own service-remove (writes service_result.txt)
if (Test-Path $hub) {
  Write-Host "  running the hub's service-remove (confirm the UAC prompt)..."
  Start-Process -FilePath $py -ArgumentList ('"' + $hub + '"', "service-remove") -Verb RunAs -Wait
  $res = Join-Path $env:USERPROFILE ".advprint\service_result.txt"
  if (Test-Path $res) { Get-Content $res }
}
# 3) verify - a half-removed service must never survive
Start-Sleep 1
$svc = Get-Service -Name AdvPrint -ErrorAction SilentlyContinue
if ($svc) {
  Write-Host "  service still registered - forcing removal..."
  Stop-Service -Name AdvPrint -Force -ErrorAction SilentlyContinue
  Start-Sleep 1
  $p = (Get-CimInstance Win32_Service -Filter "Name='AdvPrint'").ProcessId
  if ($p) { Stop-Process -Id $p -Force -ErrorAction SilentlyContinue }
  sc.exe delete AdvPrint | Out-Null
  Start-Sleep 1
  if (Get-Service -Name AdvPrint -ErrorAction SilentlyContinue) {
    Write-Host "  WARNING: Windows still lists the service (marked for deletion)."
    Write-Host "  It disappears at the next reboot - this is a Windows SCM behavior,"
    Write-Host "  not an AdvPrint problem."
  } else {
    Write-Host "  [OK] service removed."
  }
} else {
  Write-Host "  [OK] service removed (or was never installed)."
}
Write-Host "Tip: turn the Startup app back on from the tray menu or Options > Windows service."
Pause
