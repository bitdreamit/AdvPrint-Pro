@echo off

rem AdvPrint Pro - opens THE ONE UI console in the browser

rem (v3.2.6: the old numbered CLI menu is gone - the console IS the

rem  menu now. One-shot repair commands still work:

rem  python hub\tool.py start|stop|status|diagnose|uninstall ...)

if exist "%~dp0installer\runtime\python.exe" (

  "%~dp0installer\runtime\python.exe" "%~dp0hub\tool.py"

) else (

  python "%~dp0hub\tool.py"

)

pause
