@echo off
REM  AdvPrint Pro v1.7.2 - install as a Windows service ("AdvPrint Pro Service"
REM  in services.msc, starts at boot, auto-restarts). One UAC prompt.
REM  Installed layout: <root>\install\*.bat, <root>\runtime\AdvPrintPro.exe,
REM  <root>\hub\advprint.py
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0service-install.ps1"
