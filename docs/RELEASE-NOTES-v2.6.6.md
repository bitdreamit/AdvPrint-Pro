# Release Notes - AdvPrint Pro v2.6.6
by Bit Dream IT - Innovative Healthcare Solutions
"AdvPrint Pro (Advanced Printer) - Version 2.6.6 - by Bit Dream IT - Innovative Healthcare Solutions - MIT license - 100% local - no cloud, no tracking"

## Screen-glitch fix (no more console flashes)

### The problem you reported
On Windows, a "glitch" flashed on the screen **after some time** whenever
AdvPrint Pro was running - and it stopped only when the Tool or the hub
was closed/exit.

### The root cause
The hub runs windowless (`AdvPrintPro.exe`, a renamed pythonw). To show
the service state in /health and the dashboard, it runs `sc query` - but
that child process was started WITHOUT the Windows `CREATE_NO_WINDOW`
flag. So Windows allocated a brand-new console window for `sc.exe`
**every ~10 seconds** (the service-state cache TTL), because the health
refresher thread refreshes the snapshot every 3 s. Each allocation is
the black flash users saw. Closing the tool/hub stopped the refresher -
that is why the glitch stopped.

### The fix
- `service_state()` in the hub now runs `sc query` with
  `creationflags=HIDE` (CREATE_NO_WINDOW) - the periodic flash is gone.
- The Control Tool's own Windows console children (`tasklist`,
  `taskkill` x2, PowerShell port-kill x2) got the same flag, so nothing
  can flash even when the tool runs hidden (VBS / service context).
- Every remaining `subprocess` call site was audited: flagged, or
  POSIX-only (`lpstat` / `lp` / `lpoptions` / `fuser` / `pkill`), or a
  GUI-subsystem process, or the intentional UAC elevation. Nothing else
  can create a console window.

### Not changed
- Full v2.6.4 feature set kept 1:1 (baseline restored in v2.6.5):
  TUI menu [0-13], tray icon + auto-start, all endpoints
  (/health /audit /debug /diagnostics /dashboard /token/current ...),
  all six extension tabs, Windows service, installers, Bangla +
  English UI.

### Files
- `AdvPrint-Pro-Setup-2.6.6.exe` (~9.5 MB) - Windows per-machine setup
  (UAC prompt once), bundled Python 3.11.9 runtime, silent `/S` support.
- `advprint-pro_2.6.6_all.deb` - Linux deb (systemd user service +
  XDG autostart + CLI).
- `AdvPrint-Pro-v2.6.6-FULL.zip` - everything in one portable zip
  (hub + tool + extension + docs + prebuilt installers).

### Upgrade
1. Run `AdvPrint-Pro-Setup-2.6.6.exe` (installs over the old version),
   or extract the FULL zip over the portable folder.
2. Chrome -> chrome://extensions -> AdvPrint Pro -> Reload.
3. Done - the glitch disappears with the first start of the new hub.
