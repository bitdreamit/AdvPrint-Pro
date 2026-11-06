; ============================================================
;  AdvPrint Pro (Advanced Printer) - Windows one-time installer
;  by Bit Dream IT - Innovative Healthcare Solutions
;  v3.0.6 - built with NSIS 3.11 on Linux
; ------------------------------------------------------------
;  - PER-MACHINE install to %ProgramFiles%\AdvPrintPro with
;    REAL administrator rights: the exe requests admin via its
;    manifest, so Windows shows the UAC prompt by itself
;    ("auto permission to install" - nothing is half-installed).
;    Silent install:  AdvPrint-Pro-Setup-3.0.6.exe /S
;    (elevation still applies - Windows shows UAC once.)
;  - v2.8 UPGRADE / UNINSTALL FIX (the v2.7.x pain "service not
;    uninstalled, some files abort install"): BEFORE any file is
;    touched, hub-stop.ps1  1) stops the optional "AdvPrint"
;    service (with wait + PID kill),  2) DELETES the service
;    registration (Setup re-installs it fresh when ticked),
;    3) kills every process running from the install folder,
;    4) frees TCP 9235. Old program folders are wiped, so no
;    stale file can ever abort the new install again.
;  - firewall rule for LAN sharing is added automatically
;    (removed on uninstall)
;  - COMPLETE payload: hub + desktop tool + tray + service +
;    extension + docs + bundled Python 3.11.9 runtime
;  - runtime ships AdvPrintPro.exe (= pythonw.exe renamed):
;    Task Manager shows "AdvPrintPro", never "python"
;  - auto-run = NORMAL STARTUP APP (visible in Task Manager >
;    Startup apps; old PrintHub Pro auto-run/task is removed)
;  - cleans up ALL older installs on upgrade (per-user
;    %LOCALAPPDATA%\AdvPrintPro copy AND the old "PrintHub Pro")
;  - real uninstaller with Add/Remove Programs entry
; ============================================================

Unicode true
Name "AdvPrint Pro (Advanced Printer)"
OutFile "/home/z/my-project/build/AdvPrint-306-installer/AdvPrint-Pro-Setup-3.0.6.exe"
InstallDir "$PROGRAMFILES64\AdvPrintPro"
InstallDirRegKey HKLM "Software\AdvPrintPro" "InstallDir"
; full admin rights - the Windows UAC prompt appears by itself when
; the setup starts (requestedExecutionLevel requireAdministrator).
; This is the "auto permission": Windows elevates the exe, no manual
; right-click needed, on ANY PC.
RequestExecutionLevel admin
SetCompressor /SOLID lzma
SetDatablockOptimize on
ShowInstDetails show
ShowUnInstDetails show
ManifestDPIAware true

VIProductVersion "3.0.6.0"
VIAddVersionKey ProductName "AdvPrint Pro (Advanced Printer)"
VIAddVersionKey FileVersion "3.0.6"
VIAddVersionKey ProductVersion "3.0.6"
VIAddVersionKey CompanyName "Bit Dream IT - Innovative Healthcare Solutions"
VIAddVersionKey LegalCopyright "MIT License"
VIAddVersionKey FileDescription "AdvPrint Pro - silent printing for any web page, PDF or application (setup)"

!include "MUI2.nsh"
!include "FileFunc.nsh"
!include "LogicLib.nsh"
!include "Sections.nsh"      ; ${SF_SELECTED} for the service pre-tick

!define MUI_ICON   "/home/z/my-project/build/AdvPrint-306-installer/installer.ico"
!define MUI_UNICON "/home/z/my-project/build/AdvPrint-306-installer/installer.ico"
!define MUI_ABORTWARNING
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "/home/z/my-project/build/AdvPrint-306-installer/LICENSE"
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_RUN
!define MUI_FINISHPAGE_RUN_FUNCTION "LaunchHub"
!define MUI_FINISHPAGE_SHOWREADME "$INSTDIR\docs\AdvPrint-Pro-Full-Guide.html"
!define MUI_FINISHPAGE_SHOWREADME_TEXT "Open the full setup guide (A to Z)"
!define MUI_FINISHPAGE_SHOWREADME_NOTCHECKED
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

; ---------------- section descriptions ----------------
Function LaunchHub
  ReadRegStr $R0 HKLM "Software\AdvPrintPro" "PythonW"
  ${If} $R0 != ""
    Exec '"$R0" "$INSTDIR\hub\advprint.py" serve'
    DetailPrint "Hub starting on http://127.0.0.1:9235 (tray icon: AdvPrint Pro)"
  ${EndIf}
FunctionEnd

; ------------------------------------------------------------
; Find pythonw.exe -> $R0 (empty when not found)
; 0) bundled runtime $INSTDIR\runtime\AdvPrintPro.exe (always used)
; 1) PEP 514 registry fallback, 2) py launcher fallback
; ------------------------------------------------------------
!macro TryHive ROOT VIEW
  StrCpy $R4 0
LoopEnum_${ROOT}_${VIEW}:
  ClearErrors
  EnumRegKey $R1 ${ROOT} "Software\Python\PythonCore" $R4
  ${If} ${Errors}
    Goto Done_${ROOT}_${VIEW}
  ${EndIf}
  IntOp $R4 $R4 + 1
  StrCpy $R5 "$R1" 2
  ${If} $R5 != "3."
    Goto LoopEnum_${ROOT}_${VIEW}
  ${EndIf}
  ClearErrors
  ReadRegStr $R2 ${ROOT} "Software\Python\PythonCore\$R1\InstallPath" "ExecutablePath"
  ${IfNot} ${Errors}
    ${GetParent} $R2 $R3
    StrCpy $R3 "$R3\pythonw.exe"
    Goto Found
  ${EndIf}
  ClearErrors
  ReadRegStr $R3 ${ROOT} "Software\Python\PythonCore\$R1\InstallPath" ""
  ${IfNot} ${Errors}
    StrCpy $R3 "$R3pythonw.exe"
    Goto Found
  ${EndIf}
  Goto LoopEnum_${ROOT}_${VIEW}
Done_${ROOT}_${VIEW}:
!macroend

Function FindPythonW
  StrCpy $R0 ""
  ; 0) bundled Python runtime - the normal path, zero dependencies
  ${If} ${FileExists} "$INSTDIR\runtime\AdvPrintPro.exe"
    StrCpy $R0 "$INSTDIR\runtime\AdvPrintPro.exe"
    Goto Found
  ${EndIf}
  ${If} ${FileExists} "$INSTDIR\runtime\pythonw.exe"
    StrCpy $R0 "$INSTDIR\runtime\pythonw.exe"
    Goto Found
  ${EndIf}
  ; 1) PEP 514 registry, both views (emergency fallback only)
  SetRegView 64
  !insertmacro TryHive HKLM 64
  !insertmacro TryHive HKCU 64
  SetRegView 32
  !insertmacro TryHive HKLM 32
  !insertmacro TryHive HKCU 32
  SetRegView lastused
  ; 2) py launcher (last resort)
  nsExec::ExecToStack 'py -3 -c "import sys;print(sys.executable)"'
  Pop $R2
  Pop $R3
  ${If} $R2 == "0"
    ${GetParent} $R3 $R2
    StrCpy $R2 "$R2\pythonw.exe"
    ${If} ${FileExists} $R2
      StrCpy $R0 $R2
    ${Else}
      StrCpy $R0 $R3
    ${EndIf}
  ${EndIf}
Found:
FunctionEnd

; ------------------------------------------------------------
; remove ALL older installs (upgrade safety):
;   - pre-2.6 "PrintHub Pro" leftovers
;   - pre-2.6.4 PER-USER copy in %LOCALAPPDATA%\AdvPrintPro
; ------------------------------------------------------------
Function RemoveLegacyInstalls
  DetailPrint "Removing older AdvPrint Pro / legacy auto-runs..."
  Delete "$SMSTARTUP\PrintHub Pro.lnk"
  nsExec::Exec 'schtasks /Delete /TN "$\"PrintHub Pro$\"" /F'
  nsExec::Exec 'sc delete AdvPrintHub'
  nsExec::Exec 'sc delete "PrintHub"'
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\PrintHubPro"
  DeleteRegKey HKCU "Software\PrintHubPro"
  RMDir "$SMPROGRAMS\PrintHub Pro"
  ; pre-2.6.4 per-user install (this setup is per-machine now)
  ReadRegStr $R7 HKCU "Software\AdvPrintPro" "InstallDir"
  ${If} $R7 != ""
    ${AndIf} $R7 != "$INSTDIR"
    DetailPrint "Removing the old per-user copy: $R7"
    RMDir /r "$R7"
  ${EndIf}
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AdvPrintPro"
  DeleteRegKey HKCU "Software\AdvPrintPro"
FunctionEnd

; ================= sections =================
Section "AdvPrint Pro hub (required)" SEC_MAIN
  SectionIn RO
  SetShellVarContext all
  Call RemoveLegacyInstalls

  ; ---- v2.8 BULLET-PROOF STOP (fixes "some file abort install") ----
  ; hub-stop.ps1 stops the service (wait + PID kill), DELETES the
  ; service registration, kills every process under $INSTDIR and
  ; frees TCP 9235 - so no locked file can abort the upgrade.
  DetailPrint "Stopping the service and every hub process (v2.8 bullet-proof stop)..."
  SetOutPath "$PLUGINSDIR"
  File "/oname=hub-stop.ps1" "/home/z/my-project/build/AdvPrint-306-installer/stage/install/hub-stop.ps1"
  nsExec::Exec 'powershell -NoProfile -ExecutionPolicy Bypass -File "$PLUGINSDIR\hub-stop.ps1" "$INSTDIR"'
  Pop $R8
  Sleep 700

  ; ---- wipe OLD program folders so stale files can never survive ----
  DetailPrint "Removing old program files (clean upgrade)..."
  RMDir /r "$INSTDIR\hub"
  RMDir /r "$INSTDIR\install"
  RMDir /r "$INSTDIR\extension"
  RMDir /r "$INSTDIR\docs"
  RMDir /r "$INSTDIR\runtime"

  DetailPrint "Copying program files..."
  SetOutPath "$INSTDIR\hub"
  File "/home/z/my-project/build/AdvPrint-306-installer/stage/hub/advprint.py"
  File "/home/z/my-project/build/AdvPrint-306-installer/stage/hub/tool.py"
  File "/home/z/my-project/build/AdvPrint-306-installer/stage/hub/tray_windows.py"
  File "/home/z/my-project/build/AdvPrint-306-installer/stage/hub/service_main.py"
  File "/oname=advprint.ico" "/home/z/my-project/build/AdvPrint-306-installer/stage/hub/advprint.ico"
  SetOutPath "$INSTDIR\hub\service"
  File "/home/z/my-project/build/AdvPrint-306-installer/stage/hub/service/AdvPrintProService.cs"
  SetOutPath "$INSTDIR\install"
  File "/home/z/my-project/build/AdvPrint-306-installer/stage/install/install-windows.bat"
  File "/home/z/my-project/build/AdvPrint-306-installer/stage/install/UNINSTALL-WINDOWS.bat"
  File "/home/z/my-project/build/AdvPrint-306-installer/stage/install/START-ADVPRINT.vbs"
  File "/home/z/my-project/build/AdvPrint-306-installer/stage/install/INSTALL-WINDOWS-SERVICE.bat"
  File "/home/z/my-project/build/AdvPrint-306-installer/stage/install/REMOVE-WINDOWS-SERVICE.bat"
  File "/home/z/my-project/build/AdvPrint-306-installer/stage/install/service-install.ps1"
  File "/home/z/my-project/build/AdvPrint-306-installer/stage/install/service-remove.ps1"
  File "/home/z/my-project/build/AdvPrint-306-installer/stage/install/hub-stop.ps1"
  SetOutPath "$INSTDIR\docs"
  File "/home/z/my-project/build/AdvPrint-306-installer/stage/docs/AdvPrint-Pro-Full-Guide.html"
  SetOutPath "$INSTDIR"
  File "/oname=README.md" "/home/z/my-project/build/AdvPrint-306-installer/stage/README.md"
  File "/oname=LICENSE" "/home/z/my-project/build/AdvPrint-306-installer/LICENSE"
  File "/oname=advprint.ico" "/home/z/my-project/build/AdvPrint-306-installer/installer.ico"
  DetailPrint "SumatraPDF: not bundled - the installer auto-installs it via winget when missing (needs internet once)."

  DetailPrint "Installing the bundled Python 3.11.9 runtime (standalone - no system Python needed)..."
  SetOutPath "$INSTDIR\runtime"
  File /r "/home/z/my-project/build/AdvPrint-306-installer/runtime\*.*"

  DetailPrint "Resolving the bundled launcher..."
  Call FindPythonW
  WriteRegStr HKLM "Software\AdvPrintPro" "InstallDir" "$INSTDIR"
  WriteRegStr HKLM "Software\AdvPrintPro" "PythonW" "$R0"

  ; ---- SumatraPDF info ----
  ${If} ${FileExists} "$INSTDIR\tools\SumatraPDF.exe"
    DetailPrint "SumatraPDF installed (bundled - silent PDF printing ready)."
  ${ElseIf} ${FileExists} "$PROGRAMFILES\SumatraPDF\SumatraPDF.exe"
    DetailPrint "SumatraPDF found on this PC (silent PDF printing ready)."
  ${ElseIf} ${FileExists} "$LOCALAPPDATA\SumatraPDF\SumatraPDF.exe"
    DetailPrint "SumatraPDF found on this PC (silent PDF printing ready)."
  ${Else}
    DetailPrint "SumatraPDF not found - auto-installing it via winget (silent, needs internet)..."
    nsExec::ExecToLog 'winget install --id=SumatraPDF.SumatraPDF -e --silent --accept-package-agreements --accept-source-agreements'
    Pop $R8
    ${If} ${FileExists} "$PROGRAMFILES\SumatraPDF\SumatraPDF.exe"
      DetailPrint "SumatraPDF installed via winget - silent PDF printing ready."
    ${ElseIf} ${FileExists} "$LOCALAPPDATA\SumatraPDF\SumatraPDF.exe"
      DetailPrint "SumatraPDF installed via winget - silent PDF printing ready."
    ${Else}
      DetailPrint "SumatraPDF could not be auto-installed (offline?). PDF printing needs it: run $INSTDIR\install\install-windows.bat later or download it from sumatrapdfreader.org (guide: chapter Print engines)."
    ${EndIf}
  ${EndIf}

  ; ---- v2.8/v2.9: firewall rules so LAN sharing + the network
  ; printer port work out of the box (hub 9235 + RAW 9100) ----
  DetailPrint "Adding the firewall rules for LAN sharing + printer port (TCP 9235 + 9100)..."
  nsExec::Exec 'netsh advfirewall firewall delete-rule name="AdvPrint Pro" dir=in'
  nsExec::Exec 'netsh advfirewall firewall delete-rule name="AdvPrint Pro RAW 9100" dir=in'
  nsExec::Exec 'netsh advfirewall firewall add rule name="AdvPrint Pro" dir=in action=allow protocol=TCP localport=9235'
  nsExec::Exec 'netsh advfirewall firewall add rule name="AdvPrint Pro RAW 9100" dir=in action=allow protocol=TCP localport=9100'

  ; ---- auto-run as a normal STARTUP APP (visible + controllable) ----
  DetailPrint "Registering auto-run as a Startup app..."
  ${If} $R0 != ""
    CreateShortcut "$SMSTARTUP\AdvPrint Pro.lnk" "$R0" \
      '"$INSTDIR\hub\advprint.py" serve' "$INSTDIR\advprint.ico" 0
    ${If} ${FileExists} "$SMSTARTUP\AdvPrint Pro.lnk"
      DetailPrint "Auto-run registered: Startup app 'AdvPrint Pro' (Task Manager > Startup apps)."
    ${Else}
      DetailPrint "Auto-run shortcut could not be created - start via Start Menu."
    ${EndIf}
  ${Else}
    DetailPrint "No usable pythonw.exe (bundled runtime missing + no system Python)."
    ${IfNot} ${Silent}
      MessageBox MB_ICONEXCLAMATION|MB_OK \
        "Setup could not prepare the bundled Python runtime and found no system Python.$\n$\nPlease re-download AdvPrint-Pro-Setup-3.0.6.exe (the file may be damaged in transit) and run it again."
    ${EndIf}
  ${EndIf}

  ; ---- shortcuts + uninstaller (Start Menu: all users) ----
  DetailPrint "Creating shortcuts..."
  CreateDirectory "$SMPROGRAMS\AdvPrint Pro"
  ${If} $R0 != ""
    CreateShortcut "$SMPROGRAMS\AdvPrint Pro\Start AdvPrint Pro.lnk" "$R0" \
      '"$INSTDIR\hub\advprint.py" serve' "$INSTDIR\advprint.ico" 0
    CreateShortcut "$SMPROGRAMS\AdvPrint Pro\AdvPrint Tool.lnk" \
      "$INSTDIR\runtime\python.exe" '"$INSTDIR\hub\tool.py"' "$INSTDIR\advprint.ico" 0
  ${EndIf}
  CreateShortcut "$SMPROGRAMS\AdvPrint Pro\Setup guide (A to Z).lnk" \
    "$INSTDIR\docs\AdvPrint-Pro-Full-Guide.html"
  CreateShortcut "$SMPROGRAMS\AdvPrint Pro\Uninstall AdvPrint Pro.lnk" "$INSTDIR\uninstall.exe"
  WriteUninstaller "$INSTDIR\uninstall.exe"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\AdvPrintPro" \
    "DisplayName" "AdvPrint Pro (Advanced Printer) by Bit Dream IT"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\AdvPrintPro" \
    "DisplayVersion" "3.0.6"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\AdvPrintPro" \
    "Publisher" "Bit Dream IT - Innovative Healthcare Solutions"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\AdvPrintPro" \
    "DisplayIcon" "$INSTDIR\advprint.ico"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\AdvPrintPro" \
    "UninstallString" "$INSTDIR\uninstall.exe"
  WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\AdvPrintPro" \
    "NoModify" 1
  WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\AdvPrintPro" \
    "NoRepair" 1

  ; v2.8: silent installs (/S) skip the Finish page - start the hub
  ; here so the install is complete and running without any click.
  ${If} ${Silent}
    DetailPrint "Silent install - starting the hub..."
    Call LaunchHub
  ${EndIf}
SectionEnd

Section "Run as Windows service (optional, headless)" SEC_SERVICE
  DetailPrint "Installing the AdvPrint Windows service (services.msc)..."
  ; hub-stop.ps1 already removed any old registration - this is a
  ; FRESH install of the service pointing at the new runtime
  nsExec::ExecToLog '"$INSTDIR\runtime\python.exe" "$INSTDIR\hub\advprint.py" service-install'
  Pop $R9
SectionEnd

Section "Install browser extension files" SEC_EXT
  DetailPrint "Installing extension files to $INSTDIR\extension..."
  SetOutPath "$INSTDIR\extension"
  File "/home/z/my-project/build/AdvPrint-306-installer/stage/extension/manifest.json"
  File "/home/z/my-project/build/AdvPrint-306-installer/stage/extension/background.js"
  File "/home/z/my-project/build/AdvPrint-306-installer/stage/extension/i18n.js"
  File "/home/z/my-project/build/AdvPrint-306-installer/stage/extension/managed.json"
  File "/home/z/my-project/build/AdvPrint-306-installer/stage/extension/options.html"
  File "/home/z/my-project/build/AdvPrint-306-installer/stage/extension/options.js"
  File "/home/z/my-project/build/AdvPrint-306-installer/stage/extension/popup.html"
  File "/home/z/my-project/build/AdvPrint-306-installer/stage/extension/popup.js"
  SetOutPath "$INSTDIR\extension\content"
  File "/home/z/my-project/build/AdvPrint-306-installer/stage/extension/content/api.js"
  File "/home/z/my-project/build/AdvPrint-306-installer/stage/extension/content/hook.js"
  File "/home/z/my-project/build/AdvPrint-306-installer/stage/extension/content/relay.js"
  SetOutPath "$INSTDIR\extension\icons"
  File "/home/z/my-project/build/AdvPrint-306-installer/stage/extension/icons/icon16.png"
  File "/home/z/my-project/build/AdvPrint-306-installer/stage/extension/icons/icon32.png"
  File "/home/z/my-project/build/AdvPrint-306-installer/stage/extension/icons/icon48.png"
  File "/home/z/my-project/build/AdvPrint-306-installer/stage/extension/icons/icon128.png"
  DetailPrint "Extension ready: chrome://extensions > Developer mode > Load unpacked > $INSTDIR\extension"
SectionEnd

LangString DescMain    ${LANG_ENGLISH} "The AdvPrint Pro hub, bundled Python 3.11 runtime, bundled SumatraPDF, tray icon, auto-run at logon, desktop tool and full documentation. Required."
LangString DescService ${LANG_ENGLISH} "Run the hub headless as a real Windows service (services.msc). For servers / shared PCs. The normal auto-run already covers desktop use. On upgrade an existing service is stopped, removed and reinstalled fresh automatically."
LangString DescExt     ${LANG_ENGLISH} "Browser extension files installed to $INSTDIR\extension - load once via chrome://extensions > Load unpacked."

!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
  !insertmacro MUI_DESCRIPTION_TEXT ${SEC_MAIN}    "$(DescMain)"
  !insertmacro MUI_DESCRIPTION_TEXT ${SEC_SERVICE} "$(DescService)"
  !insertmacro MUI_DESCRIPTION_TEXT ${SEC_EXT}     "$(DescExt)"
!insertmacro MUI_FUNCTION_DESCRIPTION_END

; ---------------- .onInit: keep the service across upgrades ---------
; (defined AFTER the sections so ${SEC_SERVICE} exists at compile time)
Function .onInit
  ; v2.8: when the optional AdvPrint service is ALREADY installed,
  ; pre-tick the service section so the upgrade reinstalls it fresh
  ; after hub-stop.ps1 removed the old registration. Silent installs
  ; (/S) behave exactly the same.
  nsExec::ExecToStack 'sc query AdvPrint'
  Pop $R0                       ; exit code: 0 = exists, 1060 = not installed
  Pop $R1                       ; (output, unused)
  ${If} $R0 == "0"
    SectionSetFlags ${SEC_SERVICE} ${SF_SELECTED}
    DetailPrint "Existing AdvPrint service detected - it will be reinstalled fresh."
  ${EndIf}
FunctionEnd


; ================= uninstaller =================
Section "Uninstall"
  DetailPrint "Stopping the service and every hub process (v2.8 bullet-proof stop)..."
  SetShellVarContext all
  ${If} ${FileExists} "$INSTDIR\install\hub-stop.ps1"
    nsExec::Exec 'powershell -NoProfile -ExecutionPolicy Bypass -File "$INSTDIR\install\hub-stop.ps1" "$INSTDIR"'
  ${Else}
    ; helper missing (very old install) - do the minimum inline
    nsExec::Exec 'net stop AdvPrint /y'
    nsExec::Exec 'sc delete AdvPrint'
    nsExec::Exec 'taskkill /F /IM AdvPrintPro.exe'
    nsExec::Exec 'powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 9235 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess | ForEach-Object { Stop-Process -Id $$_ -Force -ErrorAction SilentlyContinue }"'
  ${EndIf}
  Sleep 700

  DetailPrint "Removing auto-run, shortcuts and the firewall rule..."
  Delete "$SMSTARTUP\AdvPrint Pro.lnk"
  Delete "$SMSTARTUP\PrintHub Pro.lnk"
  nsExec::Exec 'schtasks /Delete /TN "$\"PrintHub Pro$\"" /F'
  Delete "$SMPROGRAMS\AdvPrint Pro\*.lnk"
  RMDir "$SMPROGRAMS\AdvPrint Pro"
  nsExec::Exec 'netsh advfirewall firewall delete-rule name="AdvPrint Pro" dir=in'
  nsExec::Exec 'netsh advfirewall firewall delete-rule name="AdvPrint Pro RAW 9100" dir=in'
  DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\AdvPrintPro"
  DeleteRegKey HKLM "Software\AdvPrintPro"
  ; also clean a pre-2.6.4 per-user install if one is still around
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AdvPrintPro"
  DeleteRegKey HKCU "Software\AdvPrintPro"

  ; v2.8: retry the folder removal - a just-killed process can hold a
  ; handle for another moment; after 3 sweeps leftover junk (AV locks)
  ; is reported instead of silently keeping the Revo Uninstaller pain.
  StrCpy $R0 0
uninst_sweep:
  IntOp $R0 $R0 + 1
  RMDir /r "$INSTDIR"
  ${If} ${FileExists} "$INSTDIR"
    ${AndIf} $R0 < 3
    Sleep 900
    Goto uninst_sweep
  ${EndIf}
  ${If} ${FileExists} "$INSTDIR"
    DetailPrint "Some files could not be removed (antivirus / in use). Leftover folder: $INSTDIR"
    ${IfNot} ${Silent}
      MessageBox MB_ICONEXCLAMATION|MB_OK \
        "AdvPrint Pro is uninstalled, but Windows kept a few files in:$\n$INSTDIR$\n$\nThis happens when antivirus software briefly holds them. Delete the folder manually in a minute - or just ignore it; it is inert."
    ${EndIf}
  ${Else}
    DetailPrint "Program folder fully removed."
    ${IfNot} ${Silent}
      MessageBox MB_ICONINFORMATION|MB_OK \
        "AdvPrint Pro uninstalled.$\n$\nYour print history and settings in %USERPROFILE%\.advprint were kept.$\nDelete that folder manually if you do not want them."
    ${EndIf}
  ${EndIf}
SectionEnd
