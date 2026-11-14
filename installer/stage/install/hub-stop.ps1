# ============================================================
#  AdvPrint Pro v2.8 - bullet-proof hub stop
#  Used by the Setup (upgrade), the Uninstaller and the
#  install/uninstall helper scripts. Fixes the v2.7.x pain:
#  "service not uninstalled / some files abort install" - the
#  service and every hub process are stopped AND removed BEFORE
#  any file is overwritten or deleted.
#  Run:  powershell -NoProfile -ExecutionPolicy Bypass -File hub-stop.ps1 "C:\Program Files\AdvPrintPro"
# ============================================================
$ErrorActionPreference = 'SilentlyContinue'

Write-Host "  [1/4] stopping the AdvPrint service (if installed)..."
$svc = Get-Service -Name AdvPrint -ErrorAction SilentlyContinue
if ($svc) {
  Stop-Service -Name AdvPrint -Force
  $i = 0
  while ($svc.Status -ne 'Stopped' -and $i -lt 20) {
    Start-Sleep -Milliseconds 500
    $svc.Refresh()
    $i++
  }
  if ($svc.Status -ne 'Stopped') {
    # stuck in STOP_PENDING: kill the service process by PID
    $p = (Get-CimInstance Win32_Service -Filter "Name='AdvPrint'").ProcessId
    if ($p -and $p -ne 0) { Stop-Process -Id $p -Force }
    Start-Sleep -Milliseconds 800
  }
  # remove the registration so no half-dead service survives an
  # upgrade - Setup re-installs it fresh when the box is ticked
  sc.exe delete AdvPrint | Out-Null
  Write-Host "        service stopped and deregistered"
} else {
  Write-Host "        no service installed"
}

Write-Host "  [2/4] stopping hub processes from the install folder..."
$dir = "$args"
if ($dir) {
  $dir = $dir.TrimEnd('\')
  Get-Process | Where-Object { $_.Path -like ($dir + '\*') } |
    Stop-Process -Force
}

Write-Host "  [3/4] stopping anything listening on TCP 9235..."
Get-NetTCPConnection -LocalPort 9235 -State Listen -ErrorAction SilentlyContinue |
  Select-Object -ExpandProperty OwningProcess -Unique |
  ForEach-Object { Stop-Process -Id $_ -Force }

Write-Host "  [4/4] stopping renamed hub images..."
Stop-Process -Name AdvPrintPro -Force
Stop-Process -Name PrintHubPro -Force
Start-Sleep -Milliseconds 700

Write-Host "  hub stopped - files are free now."
exit 0
