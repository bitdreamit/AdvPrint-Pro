@echo off
setlocal enabledelayedexpansion

:: Check for Administrator privileges
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Please right-click this file and select "Run as administrator".
    pause
    exit /b 1
)

set "EXT_ID=likldbkamojokkfdlcjibiljpgbbnohc"
set "SOURCE_URL=http://127.0.0.1:9235/*"

set "BROWSERS[0]=HKLM\SOFTWARE\Policies\Google\Chrome"
set "BROWSERS[1]=HKLM\SOFTWARE\Policies\Microsoft\Edge"
set "BROWSERS[2]=HKLM\SOFTWARE\Policies\BraveSoftware\Brave"
set "BROWSERS[3]=HKLM\SOFTWARE\Policies\Vivaldi"
set "BROWSERS[4]=HKLM\SOFTWARE\Policies\Chromium"

for /L %%i in (0,1,4) do (
    set "BASE_KEY=!BROWSERS[%%i]!"
    echo ==================================================
    echo Configuring !BASE_KEY!
    echo ==================================================

    :: 1. Clean up any broken/blocked force_install keys
    reg delete "!BASE_KEY!" /v ExtensionSettings /f >nul 2>&1
    reg delete "!BASE_KEY!\ExtensionInstallForcelist" /f >nul 2>&1

    :: 2. Add Extension ID to ExtensionInstallAllowlist (avoiding duplicates)
    call :AddPolicyValue "!BASE_KEY!\ExtensionInstallAllowlist" "%EXT_ID%"

    :: 3. Add Local Hub URL to ExtensionInstallSources (avoiding duplicates)
    call :AddPolicyValue "!BASE_KEY!\ExtensionInstallSources" "%SOURCE_URL%"
)

echo.
echo ==================================================
echo [SUCCESS] All browser policies updated!
echo Next steps:
echo  1. Restart your browsers (or open chrome://policy / brave://policy and click "Reload policies").
echo  2. Open http://127.0.0 in your browser to install.
echo ==================================================
pause
exit /b 0

:AddPolicyValue
set "TARGET_KEY=%~1"
set "TARGET_VAL=%~2"

:: Check if the exact value already exists under this key
reg query "%TARGET_KEY%" 2>nul | findstr /I /C:"%TARGET_VAL%" >nul
if %errorlevel% equ 0 (
    echo   [SKIP] Already present in %TARGET_KEY%
    goto :eof
)

:: Find the next available numbered slot (1, 2, 3...)
set "SLOT=1"
:FindSlot
reg query "%TARGET_KEY%" /v "%SLOT%" >nul 2>&1
if %errorlevel% equ 0 (
    set /a SLOT+=1
    goto FindSlot
)

echo   [ADD] Slot %SLOT% -^> %TARGET_VAL%
reg add "%TARGET_KEY%" /v "%SLOT%" /t REG_SZ /d "%TARGET_VAL%" /f >nul
goto :eof
