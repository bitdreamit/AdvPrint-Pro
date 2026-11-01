# Release Notes - AdvPrint Pro v2.6.7
by Bit Dream IT - Innovative Healthcare Solutions
"AdvPrint Pro (Advanced Printer) - Version 2.6.7 - by Bit Dream IT - Innovative Healthcare Solutions - MIT license - 100% local - no cloud, no tracking"

## Print reliability fix - the two "nothing prints" bugs

### What you reported (Debug tab, v2.6.6)
- job #6 - **failed** - "save-as-PDF failed: [Errno 13] Permission denied:
  C:\\Users\\...\\.advprint\\jobs\\...pdf"
- job #4 - **dead** - "print backend exit 1: " (no reason printed)

### Root cause A - the Errno 13
The hub writes every job's PDF into its private jobs folder. Immediately
after such a file is closed, a real-time antivirus / search indexer /
sync filter opens it EXCLUSIVELY for scanning for a few hundred
milliseconds. The save-as-PDF step read the file exactly ONCE - when it
hit that window Windows answered the read with [Errno 13] Permission
denied, the job failed and nothing was saved. No retry existed.

### Fix A
- The file is now read with retries and backoff (~4 s total) - the
  scanner's lock window always clears.
- Saved PDFs are written through a .part file + atomic rename, so a
  partial file can never be observed and a locked destination is
  retried too.
- EVERY print backend spawn (SumatraPDF / lp) is preceded by a
  readability probe, so the same lock cannot make the PRINT fail.
- If a lock genuinely never clears (e.g. quarantine), the error now
  says "PDF still locked by antivirus / another program after retries -
  Retry from the history; if it repeats add C:\\Users\\...\\.advprint
  to your antivirus exclusions".

### Root cause B - "print backend exit 1: "
A queued job can carry the printer name "File (PDF)" (the hub's own
save-as-PDF destination). "File (PDF)" was missing from the hub's
virtual-printer list, so the worker treated it as a REAL Windows
printer and ran SumatraPDF with -print-to "File (PDF)". No such
printer exists, SumatraPDF exited with code 1 and printed nothing -
the history showed "print backend exit 1: " with an empty message.

### Fix B
- "File (PDF)" is now in the virtual-printer list: the worker routes
  such jobs to the save path - the PDF lands in Downloads\AdvPrint
  with status "saved" (no paper, no dialog), exactly like the
  Microsoft Print to PDF virtual printer.
- The Queue-Mode-OFF direct path got the same routing.
- Before any backend starts, a non-virtual printer name is validated
  against the OS printer list - you get "printer 'X' not found on this
  PC (installed: ...)" instead of a silent exit 1.
- The backend's stdout is captured in error messages (SumatraPDF
  reports on stdout; stderr is usually empty).

### Also
- The Debug tab's Problems list now reports a Windows service stuck in
  "start pending" (stale state from an older service process - the hub
  actually runs from the Startup app) together with the one-line fix.

### Files
- `AdvPrint-Pro-Setup-2.6.7.exe` (~9.5 MB) - Windows per-machine setup
  (UAC prompt once), bundled Python 3.11.9 runtime, silent `/S` support.
- `advprint-pro_2.6.7_all.deb` - Linux deb (systemd user service +
  XDG autostart + CLI).
- `AdvPrint-Pro-v2.6.7-FULL.zip` - everything in one portable zip
  (hub + tool + extension + docs + prebuilt installers).

### Upgrade
1. Run `AdvPrint-Pro-Setup-2.6.7.exe` (installs over the old version),
   or extract the FULL zip over the portable folder.
2. Open the hub's History and press **Retry** on the failed job(s).
3. If the service shows "start pending" in Debug: services.msc >
   AdvPrint > Restart once (or reboot). Keep only ONE of service /
   Startup app active.
