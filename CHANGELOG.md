# Changelog - AdvPrint Pro (Advanced Printer)
by Bit Dream IT - Innovative Healthcare Solutions

## v2.6.8 - PRINTER-NAME SELF-HEAL + EXTENSION MENU FIX (2026-11-01)

### Fixed: job died with "printer 'XxX' not found" when a stored printer
### name was the same text twice in a row
- Live case (Debug tab, job #2): the submitted printer was
  "Canon LBP6230/6240Canon LBP6230/6240" - the real name concatenated
  with itself (typed/pasted twice into a stored setting). The v2.6.7
  guard correctly refused the bogus name, but the job stayed dead.
- **fix_printer_name() self-heal** in the print path: a doubled name
  (x + x) collapses to x; names differing only by case or whitespace
  match the installed printer exactly. The job prints on the REAL
  printer, the history row is corrected and a printer.corrected audit
  entry records the original value.
- The extension now collapses a doubled name in hubPrint BEFORE sending
  (second safety net).
- Retry of the old dead job now simply works.

### Fixed: extension error spam "Cannot access contents of url
### chrome-extension://... Extension manifest must request permission"
- Right-click "Print this page" on the extension's own options page (or
  any chrome://, edge://, about: or Web Store page) tried to inject into
  a page Chrome forbids and reported an error to the hub Debug tab.
- Context menus now carry documentUrlPatterns (http/https/file only) so
  they never appear on browser-internal pages, and the click handlers +
  Alt+P shortcut show a friendly notification instead of an error.

- Tests: +6 v2.6.8 regressions (doubled-name heal, case/space match,
  heal leaves exact names alone, heal missed -> clear error kept, NSIS
  version bump, extension source carries healPrinterName +
  documentUrlPatterns). Suite: 109 passed.

## v2.6.7 - PRINT RELIABILITY FIX (2026-11-01)

### Fixed
- **"save-as-PDF failed: [Errno 13] Permission denied" (job lost).**
  Right after the hub writes the PDF into its jobs folder, a real-time
  antivirus / search indexer / sync filter can hold the fresh file
  EXCLUSIVELY for a few hundred ms; the save-as-PDF step read the file
  exactly once, hit that window and the job failed with no retry.
  Now: retry-read with backoff (~4 s, `_read_locked`), atomic part-file
  write + `os.replace` (`_write_atomic`), and a readability probe
  (`_wait_readable`) before ANY print backend is spawned so SumatraPDF /
  lp cannot hit the same lock. The error text now names the cause and
  the fix (Retry from history / antivirus exclusion) if a lock persists.
- **"print backend exit 1: " (dead letter) for queued "File (PDF)"
  jobs.** "File (PDF)" - the hub's own save-as-PDF destination - was
  missing from `VIRTUAL_PDF_PRINTERS`, so the worker handed the job to
  SumatraPDF as `-print-to "File (PDF)"` (a Windows printer that does
  not exist) and Sumatra exited 1 silently. "File (PDF)" now routes to
  the save path (status "saved", PDF in Downloads\AdvPrint) in the FIFO
  worker AND in the Queue-Mode-OFF direct path (`_print_now`).
- **Silent backend errors explained.** The backend's stdout is captured
  together with stderr (SumatraPDF reports on stdout); when both are
  empty the error says so ("usually the printer name does not exist or
  the file was locked") instead of ending with a bare colon.
- **Printer-not-found guard.** Before spawning the backend, non-virtual
  targets are checked against the OS printer list; a wrong name now
  fails fast with "printer 'X' not found on this PC (installed: ...)".
- **Debug tab: stuck service surfaced.** The optional Windows service
  sitting in "start pending" (stale SCM state from a pre-upgrade service
  process - the real hub runs from the Startup app) is now listed under
  Problems with the one-line fix (services.msc > AdvPrint > Restart, or
  service-remove; keep only ONE of service / Startup app active).
- Atomic writes for the destination:"file" path as well (antivirus /
  OneDrive lock windows on Downloads\AdvPrint).

### Unchanged
- Full v2.6.4 feature set kept 1:1 (baseline restored in v2.6.5,
  glitch fix from v2.6.6): TUI menu [0-13], tray icon + auto-start,
  all endpoints, six extension tabs, service, installers, Bangla +
  English UI.

## v2.6.6 - SCREEN GLITCH FIX (NO MORE CONSOLE FLASHES) (2026-10-31)

### Fixed
- **The periodic Windows "screen glitch" is gone.** The windowless hub
  (`AdvPrintPro.exe`) queried the optional Windows service state with
  `sc query` WITHOUT the `CREATE_NO_WINDOW` flag, so Windows allocated a
  brand-new console window for `sc.exe` every ~10 seconds (the service
  state cache TTL) for as long as the hub ran - the health refresher
  thread pulls the service state every 3 s through
  `build_health_snapshot()`. Users saw a black window / screen flash
  appear "after some time" and stop only when the tool or hub was
  closed. `creationflags=HIDE` is now set - zero flashes, verified.
- **Tool hardened the same way**: every Windows console child of the
  Control Tool (`tasklist`, `taskkill` x2, PowerShell port-kill x2) now
  also runs with `CREATE_NO_WINDOW`, so no black window can appear even
  when the tool itself runs hidden (VBS / service context).
- Audited ALL remaining `subprocess` call sites in hub + tool: every
  one is either flagged, POSIX-only (`lpstat` / `lp` / `lpoptions` /
  `fuser` / `pkill`), a GUI-subsystem process, or the intentional UAC
  elevation prompt. Nothing else can flash a console window.

### Unchanged
- Full v2.6.4 feature set kept 1:1 (baseline restore from v2.6.5):
  TUI menu [0-13], tray icon + auto-start, all endpoints, six extension
  tabs, service, installers, Bangla + English UI.

## v2.6.5 - BASELINE RESTORE (FULL v2.6.4 FEATURE SET) + SERVICE & SUMATRA FIXES + EXTENSION UI REFRESH (2026-10-31)

### Why this release exists
- An intermediate build had accidentally started from the old **1.5.0**
  tree instead of the real 2.6.4 source, so it shipped with FEWER
  features (missing tray icon, missing TUI menu items, reduced
  dashboard/extension). Users correctly refused that update.
- **v2.6.5 is built directly from the v2.6.4 tree - every feature is
  kept 1:1, nothing was reduced.** Verified against the published
  v2.6.4 source tag: TUI menu [0-13] (start/stop/status, test page,
  service install/remove, auto-run, update check, history, uninstall,
  LIVE TEST, dashboard, Diagnose & fix), tray icon module + auto-start,
  all endpoints (/health /audit /debug /diagnostics /dashboard
  /token/current /config /jobs ...), all six extension tabs (Queue /
  History / Settings / Debug / LAN / About) with the full Hub settings
  (advanced) block, master switch, queue mode, retry-offline, alarms,
  managed policy, LAN sharing, ESC/POS + ZPL, profiles, scheduler -
  all present.

### Fixed
- **Missing `import glob`** (same bug family as the v2.6.4 winreg
  fix): the SumatraPDF folder scans and the ALL-USERS profile scan
  (`C:\Users\*\AppData\Local\SumatraPDF\SumatraPDF.exe`) raised
  NameError that `find_sumatra()` swallowed as "not found". Service-mode
  PDF printing lost its last-resort detection. The scan now really runs.
- **SumatraPDF per-user detection widened**: new candidate
  `%LOCALAPPDATA%\Programs\SumatraPDF\SumatraPDF.exe` (newest
  installers) on top of the existing per-user / per-machine / registry
  / PATH / all-users scans. Still zero hardcoded user names.
- **Windows service can no longer hang in START_PENDING**: the service
  now imports + binds synchronously with SCM checkpoints every 2 s and
  reports RUNNING only after a real bind. Port busy (the normal
  Startup copy already owns 9235) or any error => clean STOPPED with
  the reason in hub.log instead of an eternal "Starting".
- **GitHub URLs corrected** to `github.com/bitdreamit/AdvPrint-Pro`
  (hub update check, extension manifest homepage, Options update
  check + releases link, docs).

### Improved
- **/health now carries `token_hint`** (last 4 characters of the
  active token) so a token mismatch between hub and extension can be
  VERIFIED in seconds - no more silent 401 / auth.failed loops.
- **Extension Options UI refresh**: live hub status pill in the header
  (online / token problem / starting / offline), hover states on the
  tab bar, and saving with an EMPTY token field now keeps the stored
  token instead of quietly writing the legacy default.
- **Tool menu [13] Diagnose & fix unblocks more**: the install folder
  PLUS per-user locations (legacy `%LOCALAPPDATA%\AdvPrintPro`,
  per-user SumatraPDF folders) - a blocked per-user exe can no longer
  hold print jobs in "queued" silently. Step [1/5] also prints the
  detected SumatraPDF path up front.

### Removed
- Stale prebuilt binaries (2.6.4 Setup exe + deb) from the package;
  build fresh ones from `installer/setup.nsi` (NSIS 3) so every
  release ships binaries that match its own version exactly.

## v2.6.4 - WINREG FIX + NEVER-EMPTY-RESPONSE + TOKEN AUTO-REPAIR (2026-10-31)

### Fixed: /health stuck on "starting": true and /debug + /diagnostics
### dying with ERR_EMPTY_RESPONSE (the v2.6.3 field incident)
- **ROOT CAUSE: missing `import winreg`.** v2.6.3 read the Windows
  registry in `_winreg_lookup_sumatra()` without ever importing the
  module. On Windows every call raised `NameError` inside
  `find_sumatra()` - which sits on the /health snapshot path (so /health
  answered the tiny `"starting": true` fallback forever), on /debug and
  /diagnostics (both requests crashed before sending a single byte =
  Chrome's ERR_EMPTY_RESPONSE) and on the PDF PRINT PATH ITSELF (every
  print job would fail). Linux/macOS never execute that code, which is
  why the v2.6.3 smoke tests were green while the user's Windows PC was
  broken. The import is now guarded (`winreg = None` off-Windows) and
  `find_sumatra()` is fully crash-proof on top.
- **Never-empty-response guarantee**: `do_GET` / `do_POST` are wrapped -
  an unexpected handler crash now answers a readable JSON 500 (browsers
  get an HTML error page) and the full traceback lands in hub.log and
  the audit trail. A hub bug can never again look like "connection
  reset" to the user.
- **Stale-token 302 auto-repair**: a browser opening /dashboard, /docs
  or any page with an OLD token from the hub PC is redirected (302) to
  the SAME page with the CURRENT token - old bookmarks and old popup
  links simply work again. Remote IPs and API clients keep the strict
  401 + lockout rules (the redirect is loopback + browser-only).
- **Installer zombie sweep**: the Setup exe now stops a running hub by
  IMAGE NAME (AdvPrintPro.exe / legacy PrintHubPro.exe) in addition to
  the port-9235 kill - a hub on a non-default port can no longer
  survive an upgrade with its old token in memory.
- Tests: +8 v2.6.4 regressions (winreg guard, find_sumatra never
  raises, health snapshot survives Sumatra crashes, crashed endpoint
  answers 500, loopback 302 with Location check, extension auto-heal
  anchor, setup.exe zombie kill). Lockout test now simulates a REMOTE
  IP. Suite: 100 passed.

## v2.6.1 - HUB START + TRAY FIX RELEASE (2026-10-31)

### Fixed: "hub always offline" on Windows (the big one)
- **Tool menu [13] "Diagnose & fix"** - finds and repairs the usual
  causes without console knowledge: install-folder pre-flight,
  **Unblock-File over the whole folder** (Mark-of-the-Web from
  downloaded zips silently blocks the hub exe), zombie port cleanup
  (offers to kill whatever holds 9235), then a **visible console
  start test** - the hub's own output shows any remaining error as
  readable text right in the tool. Ends with the hub.log tail and a
  copy/paste manual start command using the REAL full path.
- Failed starts now print WHY in the tool window itself: port
  state, process state (AdvPrintPro.exe alive or blocked/shot),
  the last 20 lines of hub.log, manual command, AV hint.
- Start polling extended 10 s -> 20 s with progress beats (first
  start can be slow while the antivirus scans the fresh runtime).
- Pre-flight check: a missing advprint.py/runtime now gives a clear
  "install folder is incomplete" message instead of silence.
- The hub logs **[BOOT]** lines for every start (python version +
  path, data dir, log path) and **any crash is written to hub.log**
  (previously a pythonw crash was completely silent).
- CLI hints in logs/messages now carry the full real path
  (`cli_cmd()`), so "python advprint.py serve"-style hints can never
  fail with "can't open file" from the wrong working directory.

### Fixed: tray icon missing
- Root cause: the bundled embedded runtime (pythonw + ._pth) runs
  in isolated mode and never adds the script folder to sys.path, so
  `import tray_windows` failed in the portable layout (hub served,
  icon never appeared). advprint.py now inserts its own folder into
  sys.path at boot (idempotent, works in every layout).
- Successful tray start is confirmed in hub.log ("[TRAY] icon
  active next to the clock").

### Fixed: dashboard (the REAL cause of "buttons do nothing")
- **The whole dashboard JavaScript never parsed** since v2.2: the
  LAN card's printer-status-hold button had a stray quote
  (`toggleHold(+(!HOLD_OFF)+")` -> `SyntaxError: Unexpected token ')'`),
  which killed the ENTIRE `<script>` block - queue, jobs, printers,
  audit table (Time/Event/Job/Site-IP/Printer/Reason) stayed as
  placeholder dashes and the live test tool sat at "idle - click the
  button above" no matter what was clicked. Fixed (and the dashboard
  script is now node-syntax-checked on every build + smoke run).
- Live debug & test tool header shows the real version
  (`(v@@VERSION@@)`, was hardcoded "v2.5").
- Every live-test button now says plainly "Hub is OFFLINE - start
  AdvPrint Pro first ..." instead of an idle/error line, including
  when the hub goes away in the middle of a watch.

### Packaging
- Version 2.6.1 in one place everywhere: hub VERSION, manifest,
  popup, options (chip + About), i18n brandLine (en + bn), page API,
  Setup exe (product/file/display version + uninstall entry), deb,
  docs, tests. Extension About/manifest/popup all show 2.6.1.

## v2.6.0 - REBRAND + ONE-CLICK TOKEN FIX + ENTERPRISE POLISH (2026-10-31)

### Branding (no old name anywhere)
- The whole product is now **AdvPrint Pro (Advanced Printer) by
  Bit Dream IT - Innovative Healthcare Solutions**: hub, dashboard,
  extension (manifest, popup, options, page API `window.advprint`),
  tray icon, desktop tool, service name ("AdvPrint"), deb package
  (`advprint-pro`), installers, docs, i18n (English + Bangla).
- Data folder `~/.printhub` -> `~/.advprint` with **automatic
  migration** on first start (old folder kept as backup).
- Env vars `ADVPRINT_*` (legacy `PRINTHUB_*` still honored).
- Header `X-AdvPrint-Token` (legacy `X-PrintHub-Token` accepted).
- Old `python printhub.py ...` muscle memory keeps working via the
  shipped `printhub.py` shim. GitHub repo URL unchanged (real).

### Token UX (the "dashboard needs the current token" era is over)
- **One-click fix on the dashboard error page itself**: a wrong/stale
  bookmark shows a green "Fix it now - open the dashboard with the
  current token" button + "Copy current token". Powered by the new
  `GET /token/current` endpoint - **loopback only** (the hub PC);
  remote IPs get 403 so the token never leaves the machine.
- Tray menu "Open dashboard" (renamed from "Open status page") always
  opens WITH the current token; double-click does the same.
- Extension Options -> **Detect token** button asks the local hub and
  fills+saves the token automatically (background `tokenDetect`).

### Live test / debug tool
- New **full A-to-Z self-test** (`run_livetest`): Python, data dir,
  token, print engine (SumatraPDF/lp), browser, port, queue DB
  mechanics, printers - `[OK]/[!!]` lines + exit code, shared by:
  `python advprint.py livetest [print]`, desktop tool menu [11],
  dashboard "Full self-test" button, extension Debug tab
  "Run full self-test (A-to-Z)" (new `POST /livetest`).
- The dashboard Live test section keeps test-print-and-watch + release.

### Extension (tab-wise + more settings)
- Options page tabs (Queue/History/Settings/Debug/LAN-PCs/About) kept
  and **enhanced**: new "Hub settings (advanced)" section edits the
  hub's config live (retries, dedupe, holds, instant fallback, auth
  lockout policy, header-only, allowed origins, reprint watermark +
  reason, audit, thermal engine + codepage, save-as-PDF dir,
  keep-files, SumatraPDF path) via `hubConfigGet` (GET /config).
- Debug tab gained the self-test button + output console.

### Installers (complete + automatic, no manual Security-tab work)
- `AdvPrint-Pro-Setup-2.6.0.exe` (NSIS, ~9.6 MB): **complete** payload -
  hub + shim + tool + tray + service files + full 34-file Python 3.11.9
  runtime (incl. python311.zip) + extension files + docs. Components:
  optional headless Windows service + extension files. Per-user, no
  UAC; auto-run = visible Startup app "AdvPrint Pro"; **removes all
  pre-2.6 PrintHub Pro auto-run/task/service/registry leftovers**;
  silent install `/S` for enterprise rollout.
- `advprint-pro_2.6.0_all.deb`: hub + tool + extension + docs +
  systemd --user unit + XDG autostart + CLI (`advprint`,
  `advprint-start`, `advprint-tool`); Conflicts/Replaces
  printhub-pro. Desktop tool menu gained LIVE TEST [11] and
  Open dashboard [12].

### Docs
- New **AdvPrint-Pro-Full-Guide.html / .pdf** (A to Z: setup,
  token one-click fix, every extension tab, every dashboard card,
  LAN/IP + shifting, queue/history/audit, full settings table,
  debug & live test, enterprise GPO/silent/service, API, A-to-Z
  troubleshooting, files & folders).

### Compatibility
- 2.5.3 -> 2.6.0 upgrade: config/history/log preserved (auto-migrated),
  old token still valid, old header accepted, old env names accepted,
  `python printhub.py ...` still works (shim).

## v2.5.3 — the COMPLETE RUNTIME fix (2026-10-30)

### Fixed
- **Setup 2.5.2 could not install on PCs without Python** ("Setup could
  not prepare the bundled Python runtime and found no system Python").
  Its bundled `runtime/` carried only the DLLs + .pyd modules (30
  files) and was missing the four files that make it runnable:
  `python.exe`, `pythonw.exe`, `AdvPrintPro.exe` (pythonw renamed so
  Task Manager shows "AdvPrintPro") and `python311.zip` (the standard
  library). v2.5.3 ships the COMPLETE Python 3.11.9 runtime - 34 files,
  byte-identical to the proven 2.5.0 installer (verified with a
  per-file `cmp` against the payload extracted from the 9.5 MB
  Setup-2.5.0.exe). No system Python, no internet needed.
- **Launchers only knew the portable layout.** `install-windows.bat`,
  `START-PRINT-HUB.vbs` and `service-install.ps1`/`service-remove.ps1`
  looked for the runtime under `installer\runtime\` only; the NSIS
  installer puts it under `runtime\`. All four now resolve BOTH
  layouts (installed: `runtime\` - portable: `installer\runtime\`),
  so every entry point works after setup AND from the portable zip.

### Verified
- Payload of the rebuilt `AdvPrint-Pro-Setup-2.5.3.exe` enumerated with
  7-Zip: full runtime (34 files) + hub (advprint.py, tool.py,
  tray_windows.py, service_main.py, service/) + install helpers
  (INSTALL/REMOVE-WINDOWS-SERVICE, service ps1, install/uninstall bat,
  START-PRINT-HUB.vbs) + the complete 15-file extension + docs +
  START-HERE/VERSION + uninstaller with Add/Remove Programs entry.
- `advprint-pro_2.5.3_all.deb` installs the extension to
  `/opt/advprint/extension` next to the hub, CLI (`advprint`,
  `advprint-start`), the SYSTEM service unit
  (`/usr/lib/systemd/system/advprint.service`, data in
  `/var/lib/advprint`, enabled at boot) and the user unit + XDG
  autostart fallback.
- 78-test pytest suite + 48-item live smoke: /debug 2.5.3,
  /capabilities, dashboard, quality draft+dpi, instant, queue
  shift/pause/resume, release_all, testprint.

## v2.5.2 — installers rebuilt: full payload + run-as-service on both platforms (2026-10-30)

### Fixed
- **The Windows Setup exe shipped a 1.5.0-era payload.** It copied only
  `advprint.py` + a VBS launcher - no `extension/`, no `tool.py` control
  menu, no tray, no service files. Rebuilt from this tree (NSIS 3.11):
  the v2.5.2 extension (all 15 files), `hub/advprint.py` + `tool.py` +
  `tray_windows.py` + `service_main.py` + `service/AdvPrintProService.cs`,
  every `install/*.bat|ps1|vbs` helper, docs (API, extension API,
  privacy), START-HERE, VERSION - plus the bundled Python 3.11 runtime
  (unchanged, pure-stdlib service needs no pywin32).
- **`service-install.ps1` / `service-remove.ps1` never worked.** They
  called the hub with `service install` (space form) but the CLI only
  dispatched `service-install`. The hub now accepts BOTH
  (`advprint.py service <install|remove|status>` alias) and the ps1
  helpers use the dash form.
- **The .deb had no real run-as-service story.** It now ships
  `/usr/lib/systemd/system/advprint.service` (system service, data in
  `/var/lib/advprint`) next to the user unit + XDG autostart; postinst
  enables + starts the system service on real systemd hosts (user-unit
  path stays the no-root fallback), prerm stops/disables both.
  `tool/unix/advprint.service.system` is versioned in the repo and
  `install-unix.sh` gained `sudo bash install-unix.sh --service` for
  portable system installs.
- Version anchors updated to 2.5.2 (hub x2, manifest, api.js, popup,
  tests).

### Verified
- pytest 78/78; live smoke 48/48 against the hub extracted from the
  delivered zip; the hub inside the .deb answers /health 2.5.2;
  `systemd-analyze verify` clean on both units; NSIS build log lists
  the full payload (extension/, install/, hub/service).

## v2.5.1 — extension restore release (2026-10-30)

### Fixed
- **The 2.5.0 merge had gutted the EXTENSION.** The hub came over complete,
  but `extension/` was accidentally replaced by a stripped rewrite
  (background 1,253→714 lines, options 761→280, popup 281→108). Everything
  that existed in v2.3.0 is back, taken verbatim from the v2.3.0 tag and
  only re-versioned:
  - Bangla/English UI fully wired again (`i18n.js` loaded by popup +
    options, `data-i18n` labels, Language selector auto/en/bn in Options).
  - Master switch, Queue Mode (FIFO vs instant bypass), Retry-when-offline
    buffer, per-rule `enabled` + `type` (glob/regex) + `title` matching.
  - `alarms` permission restored (minute-interval retry + keep-alive).
  - `managed.json` enterprise policy schema back to the full v2.3.0 set.
  - v2.3.0 `background.js` error reporter (`reportDebug` → POST
    `/debug/report`) - the hub keeps `/client/report` as its alias, so
    nothing is lost from 2.5.0's side.
- Version anchors updated to 2.5.1 (hub, manifest, api.js, popup, tests).

### Verified
- Hub unchanged from 2.5.0 except VERSION: still a strict superset of
  v2.3.0 (routes, config keys, functions - diff-verified, zero losses).
- pytest 78/78; live smoke 48/48 (fake-lp end-to-end incl. /debug,
  capabilities, config sumatra_path round-trip, release_all, dashboard).

## v2.5.0 — the merge release (2026-10-30)

### Fixed
- **Feature regression in 2.4.0/2.4.1** — those builds were assembled from a
  stale 1.5.0 tree (dev-machine reset) and silently dropped the v2.0–v2.3
  feature set. v2.5.0 is built on the REAL 2.3.0 source (recovered from
  github.com/bitdreamit/AdvPrint-Pro) and re-unites everything: LAN sharing
  (`share_lan` 0.0.0.0 bind + `/peers` + peer forwarding), ESC/POS + ZPL raw
  printing (cut/drawer/barcode/QR, `escpos_codepage`, Bangla auto-routed via
  headless Chrome), scheduled prints (`run_at` + promotion), printer groups,
  profiles, priority queue, dedupe, exponential retry, `/capabilities`,
  `/stats`, `/diagnostics`, in-hub `/docs` guide, Windows service wrapper
  (`service_main.py` + AdvPrintProService.cs) and `tool.py` control menu.
- **SumatraPDF under Windows services** — new all-users profile scan
  (`C:\Users\*\AppData\Local\SumatraPDF`) + HKLM registry views: found even
  when the hub's service account is not the logged-in user (user name stays
  dynamic). `/debug` now reports `sumatra_path` + the full `sumatra_searched`
  list; `sumatra_path` is a first-class config key (dashboard Settings box,
  POST /config, ADVPRINT_SUMATRA env).
- **Folder churn ended at the git level** — the package tree is now 1:1 with
  the repo (`tool/`, `extension/`, `docs/`, `tests/`, `pytest.ini`,
  `.gitignore`); full.zip extracts over the repo working copy cleanly.
  `tests/conftest.py` path fixed (hub lives at `tool/windows/portable/hub`).

### Added
- Virtual-PDF direct save ported onto the 2.3.0 worker (`_save_virtual_pdf`,
  status `saved`, `print.saved` audit) — "Microsoft Print to PDF" works
  without a physical printer and without SumatraPDF.
- `POST /jobs/{id}/release` + `POST /jobs/release_all` (print-now aliases)
  and `POST /client/report` (alias of `/debug/report`).
- Dashboard "Live debug & test tool" panel: Send test print & watch live
  (verdict REAL PRINTER HIT / SAVED / HELD / FAILED+reason), Release ALL
  held jobs, Settings → sumatra_path; token injected via `@@TOKEN@@`.
- `{"instant": true}` accepted as alias of `mode:"instant"`.
- Repo parity files restored into the package: `i18n.js` (Bangla UI strings),
  service bats/ps1, AdvPrint-Tool.bat, RELEASE-NOTES-*.md, HOW-TO-*, sample
  report, store assets.

### Tests
- pytest: 78/78 (repo suite; version anchors updated to 2.5.0, layout-aware
  manifest check). Smoke: 64/64 (fake-lp end-to-end incl. virtual-PDF save,
  release_all, dashboard token injection, sumatra_path round-trip).

## v2.4.1 — packaging & docs release (2026-10-30)

### Fixed
- **Folder churn between releases** ("why does every folder change?") —
  packaging is now a frozen contract: every zip (full.zip, portable zip,
  extension zip) unpacks to the SAME root folder `AdvPrintPro/` with no
  version in the name. Updates = extract over the old folder. The v1.x loose
  layout and the per-version root folders (`AdvPrintPro-2.4.0/…`) are gone
  for good; old folders are safe to delete (data lives in
  `%USERPROFILE%\.advprint`, never inside the program folder).
- Version strings synced in every surface: hub `VERSION`, extension
  `manifest.json` + `window.advprint.version` + popup header, installer
  metadata (NSIS `DisplayVersion` / `FileVersion` / `ProductVersion`), deb
  `control`, smoke-test version anchor.

### Added
- `docs/EXTENSION-TEST.md` — step-by-step extension tool test (hub → token →
  debug mode → popup test page → live dashboard verdict → physical proof),
  status-meaning table, troubleshooting table (symptom → where → fix), pass
  checklist. Answers "did the REAL printer get hit?" with evidence.
- `docs/FOLDER-MAP.md` — why layouts differed before, the frozen layout with
  a one-line purpose for every folder/file, where user data lives, and the
  2-minute migration from old per-version folders.
- START-HERE.txt rewritten around the folder promise + the live test.

## v2.4.0 — debug & reliability release (2026-10-30)

### Fixed
- **SumatraPDF "not found" although installed** — detection is rebuilt and
  fully dynamic: per-user install folder `%LOCALAPPDATA%\SumatraPDF` (resolves
  to the CURRENT Windows user — the user name is never hardcoded), both
  Program Files folders, Windows registry (App Paths + Uninstall for HKCU and
  HKLM, 32/64-bit views), `PATH`, and a folder scan fallback. A manual
  override (`sumatra_path` in Settings / `config.json` / `ADVPRINT_SUMATRA`
  env var) always wins. `/debug` and `doctor` print the exact list of paths
  searched, so a miss is instantly explainable.
- **Stale detection / restart required** — SumatraPDF and printer status are
  re-checked fresh on EVERY job. Installing SumatraPDF takes effect on the
  next print; no hub restart. Failed jobs auto-retry 2× (60 s apart) with
  `retry N/2 in 60s: <reason>` shown in history, then `failed` with the
  reason.

### Added
- **Live debug & test tool**: `GET /dashboard?token=...` — send a real test
  print to any printer and watch every status change live with a final
  verdict (REAL PRINTER HIT / saved as PDF / held / failed+fix hint);
  Release held jobs, pause/resume, settings toggles, problems list.
- **`GET /debug`** — full diagnostics JSON (same shape as the dashboard):
  version, uptime, worker alive, paused, hold_offline, instant_auto_queue,
  masked token, printers with ready/offline status, default printer,
  sumatra_found + sumatra_path + sumatra_searched[], browser found,
  db stats (by_status, queue_size, jobs_today, success_rate, printed_7d,
  failed_7d), recent_jobs, problems[] with fixes, client_reports[].
- **`GET /audit`** — persistent audit trail in SQLite (survives restarts):
  print.submitted (actor/site/ip/doc_hash), print.held, print.requeued,
  print.saved, auth.failed (attempt counter), config.changed,
  queue.paused/resumed.
- **Instant / direct print mode** — `POST /print` with `instant:true` or
  `mode:"instant"` (extension toggle: "Instant / direct print mode") jumps
  the queue (priority dispatch). If no printer is ready, the job
  auto-falls back to the normal queue (`instant_auto_queue`, default on) —
  the job is never lost.
- **Held jobs** — with `hold_offline` (default on) a job for an offline
  printer is parked as `held` with a reason; a watcher auto-releases it
  when the printer is ready again; `POST /jobs/{id}/release` ("Print now")
  and `POST /jobs/release_all` force it.
- **Virtual PDF printers** — targeting "Microsoft Print to PDF" now saves
  the PDF directly to the Downloads/AdvPrint folder (status `saved`, path in
  dashboard/`/debug`) instead of popping a Save-As dialog. Printing works
  even with no physical printer installed.
- **Debug on/off switch** — dashboard Settings card + extension options.
  When on, the extension reports browser-side JS errors via
  `POST /client/report`; `/debug` lists them next to desktop-side errors.
  Toggling is audit-logged (`config.changed: debug`).
- **`GET/POST /config`** — live settings (debug, hold_offline,
  instant_auto_queue, token_header_only, sumatra_path, file_dir, printer,
  token) persisted to `<data dir>/config.json`.
- **`GET /jobs/{id}`** — single-job fetch (used by the live watcher).

### Notes
- Auth rules unchanged: GET accepts `?token=` or header; POST is
  header-only (`token_header_only`). Loopback is exempt from lockout;
  remote IPs: 10 wrong-token attempts / 5 min → 5 min lock.
- Extension bumped to 2.4.0 (instant + debug toggles, error reporting,
  live-dashboard shortcuts). Reload the unpacked extension after update.
