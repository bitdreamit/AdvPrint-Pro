@echo off
rem ============================================================
rem  AdvPrint Pro - one-click build on Windows (v3.5.5+)
rem  by Bit Dream IT - Innovative Healthcare Solutions
rem
rem  Double-click this file, or run from a terminal:
rem     build.cmd                build everything
rem     build.cmd --skip-exe     everything except the Setup EXE
rem
rem  Needs: Python 3.9+  (https://www.python.org - tick "Add to PATH")
rem         NSIS 3.x for the Setup EXE (https://nsis.sourceforge.io)
rem ============================================================
setlocal

set "PY="
where python >nul 2>nul && set "PY=python"
if not defined PY where py >nul 2>nul && set "PY=py -3"
if not defined PY (
  echo [X] Python 3 was not found.
  echo     Install it from https://www.python.org/downloads/
  echo     IMPORTANT: tick "Add python.exe to PATH" on the first installer page.
  goto :fail
)

%PY% -c "import cryptography" >nul 2>nul
if errorlevel 1 (
  echo [i] Installing the single build dependency: cryptography ...
  %PY% -m pip install --upgrade pip cryptography
  if errorlevel 1 goto :fail
)

%PY% "%~dp0scripts\build-all.py" %*
if errorlevel 1 goto :fail

echo.
echo [OK] Build finished. Artifacts are in the dist\ folder.
set "NOARGS=1"
if not "%~1"=="" set "NOARGS=0"
if "%NOARGS%"=="1" pause
exit /b 0

:fail
echo.
echo [X] Build FAILED - read the message above.
set "NOARGS=1"
if not "%~1"=="" set "NOARGS=0"
if "%NOARGS%"=="1" pause
exit /b 1
