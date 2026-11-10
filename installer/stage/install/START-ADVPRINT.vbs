' AdvPrint Pro - hidden launcher, no console window  (v2.5.0)
' MANUAL / FALLBACK launcher only: normal installs start the hub
' as the Startup app "AdvPrint Pro" (Task Manager > Startup apps)
' or from the tray icon. Double-click this file only when both
' are unavailable.
' Hub log: %UserProfile%\.advprint\hub.log

Option Explicit
Dim sh, fso, base, hub, logdir, ts
Dim py, candidates, v, wout, wline

Set sh  = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
base = fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName))
hub  = base & "\hub\advprint.py"

' ---- 1) resolve the launcher -------------------------------------------
py = ""

' 1pre) BUNDLED runtime (full package) - v2.4.0 prefers
'       AdvPrintPro.exe (= pythonw.exe renamed: Task Manager shows
'       "AdvPrintPro" instead of "python")
If fso.FileExists(base & "\installer\runtime\AdvPrintPro.exe") Then
  py = base & "\installer\runtime\AdvPrintPro.exe"
ElseIf fso.FileExists(base & "\installer\runtime\pythonw.exe") Then
  py = base & "\installer\runtime\pythonw.exe"
ElseIf fso.FileExists(base & "\runtime\AdvPrintPro.exe") Then
  ' NSIS-installed layout: runtime\ sits directly under $INSTDIR
  py = base & "\runtime\AdvPrintPro.exe"
ElseIf fso.FileExists(base & "\runtime\pythonw.exe") Then
  py = base & "\runtime\pythonw.exe"
End If

' 1a) whatever is on PATH (where.exe, first hit wins)
On Error Resume Next
If fso.FileExists(sh.ExpandEnvironmentStrings("%SystemRoot%\System32\where.exe")) Then
  Set wout = sh.Exec("%ComSpec% /c where pythonw.exe 2>nul")
  Do While Not wout.StdOut.AtEndOfStream
    wline = Trim(wout.StdOut.ReadLine())
    If py = "" And wline <> "" And fso.FileExists(wline) Then py = wline
  Loop
End If
On Error GoTo 0

' 1b) per-user installs - the case most installers miss
'     %LocalAppData%\Programs\Python\Python31x\pythonw.exe
' 1c) all-users installs - C:\Program Files\Python31x\pythonw.exe
If py = "" Then
  candidates = Array( _
    sh.ExpandEnvironmentStrings("%LocalAppData%\Programs\Python"), _
    "C:\Program Files\" )
  Dim roots, root, vers
  vers = Array("314","313","312","311","310")
  For Each root In candidates
    For Each v In vers
      If fso.FileExists(root & "\Python" & v & "\pythonw.exe") Then
        py = root & "\Python" & v & "\pythonw.exe"
        Exit For
      End If
    Next
    If py <> "" Then Exit For
  Next
End If

' 1d) py launcher (all-users default) then bare PATH fallback
If py = "" And fso.FileExists("C:\Windows\pyw.exe") Then py = "C:\Windows\pyw.exe"
If py = "" Then py = "pythonw.exe"

' ---- 2) boot log - makes "why is nothing printing" answerable ---------
logdir = sh.ExpandEnvironmentStrings("%LocalAppData%\AdvPrintPro")
On Error Resume Next
If Not fso.FolderExists(logdir) Then fso.CreateFolder(logdir)
Set ts = fso.OpenTextFile(logdir & "\boot.log", 8, True)
ts.WriteLine Now & "  start  python=""" & py & """  hub=""" & hub & """"
ts.Close
On Error GoTo 0

' ---- 3) launch hidden --------------------------------------------------
sh.CurrentDirectory = base & "\hub"
sh.Run """" & py & """ """ & hub & """ serve", 0, False
