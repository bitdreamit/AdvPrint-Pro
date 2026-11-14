@echo off
:: ============================================================
:: AdvPrint Pro - browser extension policy helper  (v3.3.4)
:: by Bit Dream IT - Innovative Healthcare Solutions
::
:: WHAT IT FIXES (v3.3.4):
::   - the old script DELETED ExtensionInstallForcelist on every run
::     and never wrote it back - so the CRX force-install was wiped and
::     "Apply HKLM / Apply HKCU" seemed to do nothing. This version
::     WRITES all three policies (Forcelist + Allowlist + Sources) for
::     every Chromium browser, with duplicate-skip, and only removes
::     them when you explicitly choose R)emove.
::   - a working APPLY HKLM / APPLY HKCU menu (the old script only
::     ever wrote HKLM): HKCU needs NO admin, HKLM self-elevates via
::     UAC when needed.
::
:: Usage (can also be called from scripts):
::   allow_extention_advprint_pro.bat            -> menu
::   allow_extention_advprint_pro.bat HKLM       -> machine-wide (elevates)
::   allow_extention_advprint_pro.bat HKCU       -> current user
::   allow_extention_advprint_pro.bat BOTH       -> HKLM + HKCU
::   allow_extention_advprint_pro.bat REMOVE     -> remove policies
:: ============================================================
setlocal EnableDelayedExpansion
title AdvPrint Pro - browser extension policy helper (v3.3.4)

set "EXT_ID=likldbkamojokkfdlcjibiljpgbbnohc"
set "HUB_HOST=127.0.0.1"
set "HUB_PORT=9235"

:: ---------- optional: hub address override (LAN deployments) ----------
:: Press Enter to keep 127.0.0.1:9235 (the hub PC itself). For OTHER
:: PCs on the LAN enter the hub's IP, e.g. 192.168.0.10:9235
if /i "%~1"=="" (
    echo.
    echo Hub address for the policy [Enter = 127.0.0.1:9235, or IP:PORT]:
    set /p "HUBIN=  > "
    if not "!HUBIN!"=="" for /f "tokens=1,2 delims=:" %%a in ("!HUBIN!") do (
        set "HUB_HOST=%%a"
        if not "%%b"=="" set "HUB_PORT=%%b"
    )
)
set "SOURCE_URL=http://!HUB_HOST!:!HUB_PORT!/*"
set "UPDATES_URL=http://!HUB_HOST!:!HUB_PORT!/updates.xml"

:: ---------- admin check ----------
set "IS_ADMIN=0"
net session >nul 2>&1 && set "IS_ADMIN=1"

:: ---------- argument mode (used by the self-elevation relaunch) ------
if /i not "%~1"=="" goto :argmode

:menu
cls
echo ============================================================
echo   AdvPrint Pro - browser extension policy helper  v3.3.4
echo   by Bit Dream IT - Innovative Healthcare Solutions
echo ============================================================
echo   Extension : %EXT_ID%
echo   Hub       : %UPDATES_URL%
echo   Admin     : %IS_ADMIN%  (1 = running as administrator)
echo ------------------------------------------------------------
echo   [1] Apply HKLM  - machine-wide, EVERY user of this PC
echo       (needs admin; a UAC prompt appears if needed)
echo   [2] Apply HKCU  - only the CURRENT user (no admin needed)
echo   [3] Apply BOTH  - HKLM + HKCU
echo   [R] Remove      - remove the AdvPrint policies again
echo   [0] Exit
echo ------------------------------------------------------------
echo   Writes, per browser (Chrome, Edge, Brave, Vivaldi,
echo   Chromium, Opera): ExtensionInstallForcelist (the CRX
echo   auto-install value), ExtensionInstallAllowlist and
echo   ExtensionInstallSources. Existing values are kept.
echo.
choice /C 123R0 /N /M "Select [1=HKLM 2=HKCU 3=BOTH R=Remove 0=Exit]: "
if errorlevel 6 goto :done
if errorlevel 5 goto :askremove
if errorlevel 4 goto :doremove
if errorlevel 3 set "APPLY=BOTH" & goto :prep
if errorlevel 2 set "APPLY=HKCU" & goto :prep
set "APPLY=HKLM" & goto :prep

:askremove
set "APPLY=REMOVE"

:doremove
call :RemoveAll HKLM
call :RemoveAll HKCU
echo.
echo [DONE] AdvPrint policies removed (where they existed and were
echo        writable). Restart the browsers afterwards.
echo.
pause
goto :done

:prep
:: HKLM needs admin - self-elevate once (keeps the chosen mode)
if /i "!APPLY!"=="HKCU" goto :run
if "!IS_ADMIN!"=="1" goto :run
echo.
echo [UAC] "Apply HKLM" needs administrator rights - elevating...
powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -ArgumentList '!APPLY!' -Verb RunAs" >nul 2>&1
if !errorlevel! neq 0 (
    echo [ERROR] Could not elevate. Right-click this file and choose
    echo         "Run as administrator", then pick option 1 again.
)
goto :done

:argmode
set "APPLY=%~1"

:run
if /i "!APPLY!"=="REMOVE" goto :doremove
if /i "!APPLY!"=="BOTH" (
    call :ApplyAll HKLM
    call :ApplyAll HKCU
) else (
    call :ApplyAll !APPLY!
)
echo.
echo ============================================================
echo   [SUCCESS] Policy pass finished for: !APPLY!
echo   Next steps:
echo     1. Restart the browsers once (or open chrome://policy and
echo        click "Reload policies").
echo     2. The AdvPrint Pro extension installs by itself from
echo        !UPDATES_URL!
echo     3. Check chrome://extensions - AdvPrint Pro must appear.
echo ============================================================
echo.
pause
goto :done

:done
endlocal
exit /b 0

:: ============================================================
:: ApplyAll <hive>  - writes the three policies for every browser
:: ============================================================
:ApplyAll
set "HIVE=%~1"
echo.
echo ========== Applying %HIVE% policies ==========
if /i "%HIVE%"=="HKLM" if not "!IS_ADMIN!"=="1" (
    echo [SKIP] HKLM needs admin - relaunch elevated or use HKCU.
    goto :eof
)
call :OneBrowser "%HIVE%" "Google\Chrome"                          "Chrome"
call :OneBrowser "%HIVE%" "Microsoft\Edge"                         "Edge"
call :OneBrowser "%HIVE%" "BraveSoftware\Brave"                    "Brave"
call :OneBrowser "%HIVE%" "Vivaldi"                                "Vivaldi"
call :OneBrowser "%HIVE%" "Chromium"                               "Chromium"
call :OneBrowser "%HIVE%" "Opera Software\Opera"                   "Opera"
goto :eof

:: ============================================================
:: OneBrowser <hive> <key fragment> <display name>
::   1. ExtensionInstallForcelist : "<slot>"="EXT_ID;UPDATES_URL"
::   2. ExtensionInstallAllowlist : "<slot>"="EXT_ID"
::   3. ExtensionInstallSources   : "<slot>"="SOURCE_URL"
:: Duplicate-skip: an entry with the same prefix is kept as-is.
:: ============================================================
:OneBrowser
set "HIVE=%~1"
set "FRAG=%~2"
set "BNAME=%~3"
set "BASE=%HIVE%\SOFTWARE\Policies\%FRAG%"
set "KEY_F=%BASE%\ExtensionInstallForcelist"
set "KEY_A=%BASE%\ExtensionInstallAllowlist"
set "KEY_S=%BASE%\ExtensionInstallSources"

:: --- 1. Forcelist (the CRX auto-install entry) ---
reg query "%KEY_F%" 2>nul | findstr /I /C:"%EXT_ID%;" >nul
if not errorlevel 1 (
    echo   [SKIP] %BNAME%: Forcelist already contains %EXT_ID%
) else (
    call :NextSlot "%KEY_F%"
    reg add "%KEY_F%" /v "!SLOT!" /t REG_SZ /d "%EXT_ID%;%UPDATES_URL%" /f >nul 2>&1
    if errorlevel 1 (
        echo   [FAIL] %BNAME%: could not write %KEY_F% - !HIVE! blocked ^(HKLM needs admin^)
    ) else (
        echo   [OK]   %BNAME%: Forcelist entry !SLOT! = %EXT_ID%;%UPDATES_URL%
    )
)

:: --- 2. Allowlist ---
reg query "%KEY_A%" 2>nul | findstr /I /C:"%EXT_ID%" >nul
if not errorlevel 1 (
    echo   [SKIP] %BNAME%: Allowlist already contains %EXT_ID%
) else (
    call :NextSlot "%KEY_A%"
    reg add "%KEY_A%" /v "!SLOT!" /t REG_SZ /d "%EXT_ID%" /f >nul 2>&1
    if errorlevel 1 (
        echo   [FAIL] %BNAME%: could not write %KEY_A%
    ) else (
        echo   [OK]   %BNAME%: Allowlist entry !SLOT! = %EXT_ID%
    )
)

:: --- 3. Install sources (where the hub URL is trusted) ---
reg query "%KEY_S%" 2>nul | findstr /I /C:"!SOURCE_URL!" >nul
if not errorlevel 1 (
    echo   [SKIP] %BNAME%: Sources already contains !SOURCE_URL!
) else (
    call :NextSlot "%KEY_S%"
    reg add "%KEY_S%" /v "!SLOT!" /t REG_SZ /d "!SOURCE_URL!" /f >nul 2>&1
    if errorlevel 1 (
        echo   [FAIL] %BNAME%: could not write %KEY_S%
    ) else (
        echo   [OK]   %BNAME%: Sources entry !SLOT! = !SOURCE_URL!
    )
)
goto :eof

:: ============================================================
:: NextSlot <key> - first free numeric value name (1,2,3, ...)
:: ============================================================
:NextSlot
set "SLOT=1"
:slotloop
reg query "%~1" /v "%SLOT%" >nul 2>&1
if errorlevel 1 goto :eof
set /a SLOT+=1
if %SLOT% GTR 64 goto :eof
goto slotloop

:: ============================================================
:: RemoveAll <hive> - delete the AdvPrint entries again
:: ============================================================
:RemoveAll
set "HIVE=%~1"
echo.
echo ========== Removing %HIVE% policies ==========
if /i "%HIVE%"=="HKLM" if not "!IS_ADMIN!"=="1" (
    echo [SKIP] HKLM needs admin - relaunch elevated.
    goto :eof
)
for %%F in ("Google\Chrome" "Microsoft\Edge" "BraveSoftware\Brave" "Vivaldi" "Chromium" "Opera Software\Opera") do (
    set "BASE=%HIVE%\SOFTWARE\Policies\%%~F"
    call :WipeKeys "!BASE!"
)
goto :eof

:WipeKeys
reg delete "%~1\ExtensionInstallForcelist" /f >nul 2>&1
reg delete "%~1\ExtensionInstallAllowlist" /f >nul 2>&1
reg delete "%~1\ExtensionInstallSources"   /f >nul 2>&1
echo   [OK]   removed policies under %~1
goto :eof
