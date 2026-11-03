@echo off
REM ============================================================
REM  AdvPrint Pro - Windows uninstall  (v2.8)
REM  v2.8: ALSO stops and removes the optional "AdvPrint" service
REM  (stop + wait + PID kill + sc delete) before touching files,
REM  and removes the firewall rule. Fixes "service not uninstalled".
REM  Does NOT delete your print data or the Chrome extension.
REM  Run as Administrator for the service + firewall steps.
REM ============================================================
title AdvPrint Pro Uninstall
echo.
echo [..] Removing Startup shortcut "AdvPrint Pro" ...
del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\AdvPrint Pro.lnk" >nul 2>&1
if not exist "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\AdvPrint Pro.lnk" (
  echo [OK] Startup shortcut removed - no more auto-run at logon
) else (
  echo [!] Could not remove the Startup shortcut - delete it manually:
  echo     %APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
)
echo [..] Removing legacy logon task "AdvPrint Pro" (v1.2-v1.4) ...
schtasks /Delete /TN "AdvPrint Pro" /F >nul 2>&1

echo [..] Stopping the AdvPrint service + hub (v2.8 bullet-proof stop) ...
set HERE=%~dp0
powershell -NoProfile -ExecutionPolicy Bypass -File "%HERE%hub-stop.ps1" >nul 2>&1
if errorlevel 1 (
  net stop AdvPrint /y >nul 2>&1
  sc delete AdvPrint >nul 2>&1
)
sc query AdvPrint 2>nul | findstr /i "SERVICE_NAME" >nul 2>&1
if not errorlevel 1 (
  echo [!] The service entry is still listed - run once more as Administrator,
  echo     or reboot (Windows marks it for deletion, gone after restart).
) else (
  echo [OK] Service removed / was not installed
)

echo [..] Removing the firewall rule ...
netsh advfirewall firewall delete-rule name="AdvPrint Pro" dir=in >nul 2>&1
echo [OK] Firewall rule removed (if it existed)

echo.
echo [OK] AdvPrint Pro uninstalled.
echo      Print data kept in:  %USERPROFILE%\.advprint
echo      Delete it manually if you want:
echo        rmdir /s /q "%USERPROFILE%\.advprint"
echo      Remove the Chrome extension in chrome://extensions
echo.
pause
