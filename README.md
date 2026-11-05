# AdvPrint Pro — Print from Any Web Page to Any Printer

**Silent. Local. Open source. No subscription.**

AdvPrint Pro prints from any web page to **any printer** — thermal, receipt, label, or standard — with **no print dialog and no confirmation**. It is a free, 100%-local, MIT-licensed alternative to paid products like Ultraprint Hub: a small **desktop hub** (single Python file, zero pip dependencies) plus a **Chrome extension** that talk to each other on `localhost` only.

```
Web page ──► Chrome extension ──► AdvPrint Pro hub (localhost:9235) ──► ANY printer
             (right-click /       • queue: pause · resume · cancel      thermal · receipt
              popup / API /       • history: last 100 jobs (SQLite)     label · A4 · POS
              auto rules)         • screenshot & HTML → PDF              80mm roll
```

---

## What's new in v3.0.1 (tray menu click fix + window.print() hook into Power switches)

Two fixes on top of v3.0.0 - nothing removed:

- **Tray menu click fix - 'the text and the click are not the same' is solved.** The self-drawn tray menu's click handler used a selectable-row number as a raw item index, and the menu has separators - so every item AFTER the first separator executed the WRONG command: **Pause queue did nothing, Start at Windows logon paused the queue, Restart hub toggled autostart, Allow LAN in firewall RESTARTED the hub, and Exit opened the firewall prompt**. The highlight and the hit band always agreed - only the final text->action lookup was shifted. Now every item triggers its own action, and a regression test simulates the full click->command path over the real menu layout.
- **Intercept window.print() moved into Options > Power switches.** The switch now sits next to the master switch and Queue mode (it used to be buried mid-page in Behavior). Same `hookPrint` setting as the popup's "window.print() hook" toggle - the two always agree; no migration needed.

## What's new in v3.0.0 (renumbered release - the full v2.9.1 feature set under a clean new number)

The v2.9.1 packages were already distributed; shipping different content under the same 2.9.1 number would collide with installed copies (same version, different bytes). **v3.0.0 ships the identical v2.9.1 feature set under the new number** - network printer mode, print-destination routing, the responsive dashboard tables, the 27-finding security hardening and the full documentation, unchanged. Every surface (hub `VERSION`/`VERSION_NAME`, dashboard badge, extension manifest/popup/Options/About, Setup exe, deb, docs) says 3.0.0. Installs straight over 2.8.2 / 2.9.0 / 2.9.1 - settings and history are kept. 212 tests pass.

## What's new in v2.9.1 (network printer mode + phone auth fix + smooth tray + responsive dashboard)

Base: v2.8.2 ("it work fine"). Nothing removed. Three things:

- **Network printer mode — add this PC like a real IP printer.** The hub now speaks the two protocols a network printer speaks:
  - **IPP printer URL** `http://<this-PC-IP>:9235/ipp/print` — Windows 10/11 "Select a shared printer by name" installs it with the built-in Microsoft IPP Class Driver; phones with manual-IPP print services work too. Same port as the hub, so no extra firewall rule. No token (printer protocol, size-bounded, audited, switchable off with `"ipp_printer": false`). Opening the URL in a browser shows a how-to page.
  - **JetDirect RAW listener on TCP 9100** (`"raw_printer_port"`, 0 = off) — Windows "Add a printer using TCP/IP address" with device type *Generic Network Card* and your real printer's driver: Windows renders ANY file (Word, Excel, photos, web) and streams the print-ready bytes here; the hub prints them. ESC/POS and ZPL apps can use the same socket. Follows `share_lan`, rebinds on DHCP changes, never binds 0.0.0.0.
  - **Smart payload routing** for both: `%PDF` → the normal PDF pipeline (History, audit, reprint); JPEG → single-page PDF (pure-stdlib DCTDecode); PostScript / PCL / ESC/POS / ZPL → RAW passthrough. Every job is audited with the source IP.
  - The dashboard LAN card shows both rows (URL + copy + QR for IPP, port + status + "How to add" for RAW) and `GET /qr?kind=ipp` renders the printer URL as a QR. The one-click firewall fix now adds BOTH ports in a single UAC prompt (9235 + 9100).
- **Print destination — ANY printer (default / selected / IP printer).** The hub not only RECEIVES like an IP printer; it routes every job to the destination picked in the new **Print destination** dashboard card: the OS **default printer**, **any installed printer**, or an upstream **IP printer** (a real network printer at IP:port — JetDirect RAW or IPP Print-Job; `POST /ip-printer/test` checks reachability). Phones and PCs that added this hub as THEIR IP printer print through exactly that destination. A per-job `printer` name always wins. `/health` reports `dest_mode` / `dest_display` / `ip_printer` / `ip_printer_mode`.
- **Phone "Auth fail" on the Send portal FIXED.** With `token_header_only: true` the portal page opened on the phone but the upload POST could never authenticate (a phone cannot send the `X-AdvPrint-Token` header) — so every phone got "invalid or missing token" after picking a PDF while PCs kept working. `/send` POST now accepts the token from the query/body (the same shared QR-link transport the GET page always used); the token is still required, every other endpoint stays header-strict, and the portal also sends the token as a hidden form field. A wrong token answers with a clear "re-scan the fresh QR" message.
- **One version everywhere (extension).** Popup badge, Options header chip and the About panel all read `chrome.runtime.getManifest().version` — the manifest is the single source; the hardcoded HTML copies (stuck at 2.8.0) can never drift again.
- **Smooth tray menu.** Every tray action (dashboard, test page, pause, autostart, restart, firewall) runs on its own thread — a slow action can no longer freeze the icon or lag the next right-click. The menu font is cached per DPI scale.

Nothing removed: every v2.8.2 feature (live LAN rebind, firewall one-click, Test LAN) is unchanged.

## What's new in v2.8.2 (LAN sharing applies live + firewall one-click)

Fixes the field report **"LAN sharing is ON but `http://<lan-ip>:9235` does not answer - only 127.0.0.1 works"**:

- **Live LAN rebind — no restart, zero downtime.** The loopback listener (`127.0.0.1:9235`) always stays up; toggling LAN sharing now starts/stops a SECOND listener bound to the PC's **specific LAN IP** inside the same HTTP request. A failed LAN bind is only logged — it can never take local printing down. DHCP IP changes are followed automatically within seconds.
- **Windows firewall: state + one-click fix.** The dashboard LAN card shows ALLOWED / BLOCKED / unknown (`firewall_ok` in `/health`) and an **Allow in firewall** button (one UAC prompt, rule for the current port); the tray menu gains **Allow LAN in firewall**. `POST /firewall/allow` is loopback-only by design.
- **Test LAN.** `GET /lan/selftest` — the hub connects to its own LAN URL and reports PASS/FAIL with the reason: PASS + another PC still failing = firewall; FAIL = listener problem (hub.log explains).

Nothing removed: every v2.8.1 feature (send-portal QR, one-click invite) is unchanged.

## What's new in v2.8.1 (QR code + one-click LAN invite)

Two additions to the dashboard's LAN sharing card — both 100% local:

- **Send-portal QR code.** The LAN card now shows the *Send portal (phones)* row: **Copy send URL** copies `http://<this-PC-ip>:9235/send?token=...`, and **QR code** shows the same URL as a scannable QR that is generated **inside the hub** (pure-stdlib encoder, verified bit-exact against an independent implementation — no internet, no CDN, no tracking). Any phone or tablet on the same Wi-Fi scans it, opens the Send portal, picks a PDF — it prints on this PC's default printer seconds later. API: `GET /qr?token=...&kind=send|invite` returns the QR as SVG.
- **One-click invite — connect another PC in 10 seconds.** The *Connect another PC* row's **Copy invite link** copies `http://<this-PC-ip>:9235/connect?t=<token>&n=<PC-name>`. Opened in a browser on the OTHER PC (chat / e-mail / QR — any way), it shows a confirmation page with an **Add "PC-name" as a LAN print peer** button. Clicking it saves this hub into the other PC's `peer_hubs` automatically (via its own hub's `POST /peer-connect`), live-checks it and reports the peer's version. No retyping the IP, no config.json editing. Guarded: loopback-only, private-LAN URLs only, explicit user click, Origin must match the added hub — a random website cannot silently inject a peer, and every accept is audited (`peer.connected`).

Nothing removed: every v2.8.0 feature is unchanged.

## What's new in v2.8.0 (two hub profiles + DropZone + bullet-proof uninstall)

The ten most-requested features, all in one release:

- **Two hub profiles — Self PC + LAN PC.** Options → **Connection 1 (Self PC)** keeps this computer's `hubUrl` + `token`; **Connection 2 (LAN PC)** keeps the OTHER PC's hub URL + its token. **Share Send Mode** in the popup is now the routing switch: **ON → every print job goes to the LAN PC**, **OFF → jobs print on this PC**. The popup status line names the active target, and Recent jobs / Pause follow it.
- **Share Receive Mode** (this PC accepts jobs from other PCs) stays the hub-side `share_lan` switch — receiving is configured on the PC that owns the printer.
- **window.print() on/off in the popup** — one click turns the silent-print interception on or off (same switch as Options → Behavior).
- **Dashboard + Audit log, Self and LAN separately** — four buttons in Options: *Open dashboard / audit log — Self PC* and *— LAN PC*; the popup footer opens the active target.
- **Close tab after auto-print is now default OFF** — tabs stay open unless you explicitly opt in (Options → Behavior).
- **DropZone + Send portal — printing WITHOUT the extension.** The hub watches a folder: in Word/Excel/ANY app choose *Microsoft Print to PDF* and save into the DropZone — the page prints seconds later (dashboard → DropZone card; `POST /dropzone/open` opens the folder). Phones/tablets/other PCs print through the built-in **Send portal** (`/send`, token-protected, same as every endpoint).
- **Restart hub** — in the tray menu, AdvPrint Tool [14] and the dashboard button: the hub relaunches itself cleanly (new process waits for the port; queued jobs, settings and history are kept).
- **Bullet-proof upgrade & uninstall.** The setup now runs `hub-stop.ps1` BEFORE touching files: stops the optional *AdvPrint* service (wait + PID kill), **deletes the service registration** (reinstalled fresh when ticked — upgrades keep it automatically), kills every process under the install folder and frees TCP 9235. Old program folders are wiped, so no stale file can abort an install any more; the uninstaller retries the folder sweep and reports leftovers honestly.
- **Silent install** `AdvPrint-Pro-Setup-3.0.1.exe /S` — elevation is requested by the exe manifest itself ("auto permission" on any PC), the hub auto-starts after a silent install, and the firewall rule for LAN sharing (TCP 9235) is added automatically (removed on uninstall).
- **New A + printer logo** — the letter A drawn as a printer: the crossbar is the output slot and a printed page slides out of it. Same mark in the extension, popup, dashboard, tray icon, installer and docs.

Nothing removed: every v2.7.0 feature (history manager, share toggles, live test tool) is unchanged.

## What's new in v2.7.0 (history manager + share modes + layout fix)

- **Job history manager** (dashboard + Options > History): filter by any status (incl. one-click "Not printed"), search by title / printer / #id, tick rows with check/uncheck-all, **Reprint selected**, **Reprint all non-printed**, **Clear ALL history** — finished jobs only, waiting jobs are never touched. New API: `POST /jobs/bulk-reprint`, `POST /history/clear`.
- **Share Receive / Send Mode toggles in the popup**: Receive = hub `share_lan` (accept jobs from other PCs); Send = this browser may shift jobs to peer PCs (OFF locks every send-to-PC button here).
- **Dashboard layout fixed**: the Live debug & test tool + SumatraPDF settings are now proper panels inside the page (they used to hang below it, unstyled).
- **Dashboard data fix**: Recent jobs / Audit tables were silently empty on real installs (the token was glued into the query string as `?limit=12?token=...`) — fixed.
- Version badge everywhere, About panel shows the real manifest version, 117/117 tests. Nothing removed.

## What's new in v2.6.7 (print reliability — the two "nothing prints" bugs)

Two real failures reported through the Debug tab are fixed:

1. **`save-as-PDF failed: [Errno 13] Permission denied`** — a real-time
   antivirus / search indexer / sync filter briefly holds the fresh PDF
   exclusively right after the hub writes it; the single read attempt hit
   that window and the job died. The hub now **retry-reads with backoff
   (~4 s)**, writes atomically (`.part` + rename) and **probe-reads every
   file before a backend (SumatraPDF / lp) starts**. If a lock truly never
   clears, the error now says exactly that and names the fix.
2. **`print backend exit 1:` on a queued *File (PDF)* job** — `File (PDF)`
   was missing from the virtual-printer list, so the job went to
   SumatraPDF as a Windows printer name that does not exist. It now routes
   to the save path (status *saved*, PDF in `Downloads\AdvPrint`), also
   with Queue Mode OFF.

Plus: backend **stdout is captured** in errors (SumatraPDF reports on
stdout), a **printer-not-found guard** ("printer 'X' not found on this PC
(installed: …)"), and the Debug tab now lists a Windows service stuck in
*start pending* with the fix. Nothing else changed — full v2.6.4 feature
set kept 1:1.

## What's new in v2.6.6 (screen-glitch fix — no more console flashes)

- **The periodic Windows "screen glitch" is fixed.** The windowless hub queried the optional Windows service with `sc query` without the `CREATE_NO_WINDOW` flag, so Windows allocated a fresh console window for `sc.exe` every ~10 seconds for as long as the hub ran — a black window flashing "after some time", stopping only when the tool or hub was closed. All background child processes now run windowless (`creationflags=HIDE`).
- **The Control Tool is hardened the same way** (`tasklist` / `taskkill` / PowerShell port-kill), so nothing can flash a console even when the tool runs hidden.
- **Everything else is unchanged** — full v2.6.4 feature set kept 1:1 (baseline restored in v2.6.5).

## What's new in v2.6.5 (baseline restore — full v2.6.4 feature set, all polished)

- **The feature baseline is v2.6.4 — kept 1:1.** An intermediate build had accidentally started from the old 1.5.0 tree and shipped with fewer features (no tray icon, missing TUI menu items). v2.6.5 is built **from the published v2.6.4 source**: TUI menu [0–13], tray icon with auto-start, every endpoint, all six extension tabs, service, installers — **nothing reduced**.
- **Missing `import glob` fixed** (same family as the v2.6.4 winreg fix): the SumatraPDF **all-users profile scan** (`C:\Users\*\AppData\Local\SumatraPDF\...`) and portable folder scans were dead on Windows — service-mode PDF printing lost its last-resort detection. Now they really run; plus a new `%LOCALAPPDATA%\Programs\SumatraPDF` candidate.
- **Windows service cannot hang at "Starting"** anymore: synchronous bind with SCM checkpoints, RUNNING only after a real bind, port-busy → clean STOPPED with the reason in hub.log.
- **Token self-check**: `/health` now carries `token_hint` (last 4 chars) — verify hub ↔ extension token match in seconds (the 401 / auth.failed family). One-click *Fix token* (popup) and *Detect token* (Options) unchanged.
- **Extension Options UI refresh**: live hub status pill in the header (online / token problem / starting / offline), tab-bar hover states, and saving with an empty token field keeps your stored token.
- **Tool [13] Diagnose & fix unblocks more**: install folder + per-user locations (legacy `%LOCALAPPDATA%\AdvPrintPro`, per-user SumatraPDF) — blocked per-user exes can no longer hold jobs in "queued" silently. Step [1/5] prints the detected SumatraPDF path.
- **GitHub links corrected** to `github.com/bitdreamit/AdvPrint-Pro` everywhere (hub update check, extension manifest + Options, docs).

---

## What's new in v2.5.0 (the merge release — git-repo parity)

- **Package = your git repo, 1:1.** The zip now unpacks to the exact tree of `github.com/bitdreamit/AdvPrint-Pro`: `tool/` (windows portable hub + service + runtime, unix hub), `extension/` (incl. `i18n.js` Bangla strings restored), `docs/`, `tests/` + `pytest.ini` + `.gitignore` at the root. Extract `full.zip` over your repo working copy and `git status` shows only real changes — no renames, no deletions. (`doc/` in the repo is an old duplicate of `docs/` — `git rm -r doc` once.)
- **Honest fix: v2.4.0/2.4.1 were rebuilt from an older 1.5.0 tree after a dev-machine reset and accidentally dropped v2.0–v2.3 features.** v2.5.0 merges the REAL 2.3.0 source (recovered from this git repo) with the 2.4.x fixes, so **everything is back**: LAN sharing (`share_lan`, `/peers`, peer forwarding), the full **ESC/POS + ZPL raw printing** suite with Bangla auto-routing via headless Chrome, **scheduled prints** (`run_at`), printer groups + profiles, priority queue, dedupe, exponential retry.
- **SumatraPDF detection made service-proof** — per-user `%LOCALAPPDATA%\SumatraPDF` (dynamic user name), both Program Files, **registry (HKCU+HKLM, 32/64 views)**, `PATH`, portable folder scan, and a new **all-users profile scan** (`C:\Users\*`) so it is found even when the hub runs as a Windows **service** under a different account. Fresh re-scan on every job + `sumatra_path` manual override (dashboard Settings → Save).
- **Virtual PDF printers save directly** to `Downloads\AdvPrint` (status `saved`, no Save-As dialog) — printing to *Microsoft Print to PDF* works with **no physical printer** and no SumatraPDF.
- **Dashboard live test tool** (kept from 2.4.x, now inside the 2.3.0 dashboard): *"Send test print & watch live"* with the verdict **REAL PRINTER HIT / SAVED / HELD / FAILED+reason**, *Release ALL held jobs*, and a Settings box for `sumatra_path`.
- `/client/report` alias for `POST /debug/report` (extension browser-error reporting), `POST /jobs/{id}/release` + `POST /jobs/release_all` (dashboard/extension friendly names for print-now).
- **Tests**: 78 pytest (your repo suite, layout-fixed) + 64-check smoke — all green on the merged hub.

## What's new in v2.4.1 (packaging & docs release)

- **Frozen folder format** — the folder layout changed too often between releases (v1.x zips were loose, v2.0–v2.4.0 put the version in the root folder name, so every update "moved everything"). From v2.4.1 every zip unpacks to **`AdvPrintPro/`** — no version in the name. Extract over the old folder, reload the extension, done — **the layout never changes again**. Full explanation + per-folder reference: `docs/FOLDER-MAP.md`.
- **`docs/EXTENSION-TEST.md`** — the missing test guide: a 5-minute, step-by-step extension tool test that ends with the proof the **real printer was hit** (live dashboard verdict + where the physical proof shows up: paper, Windows print queue, or the PDF in `Downloads\AdvPrint`), plus a symptom → where-to-look → fix table.
- Version strings synced everywhere (hub, extension, installers, installers' metadata) — `popup` and `options` all report **2.4.1**.

## What's new in v2.4.0 (debug & reliability release)

- **LIVE debug & test tool** — open `http://127.0.0.1:9235/dashboard?token=<your token>` in any browser: send a real test print and **watch every step live** (queued → printing → printed / saved / held / failed) with a final verdict: *REAL PRINTER HIT* or the exact reason why not. Includes Release-held-jobs ("Print now"), settings toggles and one-click `/debug` + `/audit` views.
- **`GET /debug`** — one JSON page that answers *"why is it not printing?"*: hub version/uptime, worker alive, queue + held counts, every printer with ready/offline status, SumatraPDF found + **the exact list of paths searched**, recent jobs with errors, 7-day success rate, and a prioritized `problems[]` list with fixes. Token required (`?token=`).
- **`GET /audit`** — persistent audit trail (SQLite): `print.submitted` (with SHA-256 doc hash), `print.held`, `print.requeued`, `print.saved`, `auth.failed` (wrong token, per-attempt), `config.changed`, `queue.paused/resumed`.
- **SumatraPDF detection rebuilt** — the user name is **never hardcoded**: per-user install (`%LOCALAPPDATA%\SumatraPDF\SumatraPDF.exe` — resolves to the CURRENT user, e.g. `C:\Users\<name>\...`), both Program Files, Windows **registry** (App Paths + Uninstall, per-user and per-machine), `PATH`, folder scan, plus a manual **`sumatra_path` override** in Settings. Detection re-runs **fresh on every job** — installing SumatraPDF takes effect on the next print, **no hub restart needed**. Failed jobs auto-retry 2× (60 s apart).
- **Instant / direct print mode** — `POST /print` with `"instant": true` (or extension toggle / `mode:"instant"`) jumps the queue and prints immediately. If no printer is ready, the job **auto-falls back to the normal queue** (`instant_auto_queue`) — nothing is ever lost.
- **Hold-while-offline done right** — jobs for an offline printer are parked as `held` (with reason), auto-released by a watcher every 5 s when the printer comes back, and can be force-printed any time ("Print now" / `POST /jobs/{id}/release` / `POST /jobs/release_all`).
- **Virtual PDF printers solved** — printing to *Microsoft Print to PDF* would pop a Save-As dialog; the hub now **saves the PDF directly** to your Downloads/AdvPrint folder (status `saved`, path shown in dashboard & `/debug`). Works even with **no physical printer installed**.
- **Debug on/off switch** — in the dashboard Settings AND extension options. When on, the **extension reports browser-side JS errors** to the hub (`POST /client/report`) and `/debug` shows them next to the desktop-side errors — you can see whether the problem is in the web side or the desktop side. Every toggle is audit-logged (`config.changed: debug`).
- **`POST /config` / `GET /config`** — live-editable settings persisted to `<data>/config.json`: `debug`, `hold_offline`, `instant_auto_queue`, `sumatra_path`, `file_dir`, `printer`, `token_header_only`.

---

## Feature highlights

| | AdvPrint Pro |
|---|---|
| **Any printer** | Thermal, receipt, label, or standard. If the OS sees it, the hub can print to it. |
| **Save as PDF (File)** | Any job can go to a **File** destination instead of paper — the hub writes the PDF into `~/Downloads/AdvPrint` (configurable). No dialog, no paper. |
| **No print dialog** | Jobs are sent straight to the OS print system (SumatraPDF on Windows, CUPS `lp` on Linux/macOS). |
| **Auto-routing rules** | Match URLs to printers automatically — orders page → receipt printer, shipping page → label printer. |
| **Auto-print on open** | Open a report URL (e.g. your Laravel `/medical_reports/pdf-test/...` route) and it prints instantly — the tab closes right after, so there is **zero browser view**. |
| **Print interception** | `window.print()` calls **and Ctrl+P / Cmd+P** from any web app (Odoo, SAP, POS) are rerouted silently. Injection is CSP-safe: it works even on strict-CSP sites with no console errors. |
| **Works everywhere** | Any web application: ERP, POS, e-commerce, logistics, healthcare. |
| **Developer API** | Global one-liner `printPdfLink(url, title)` on every page (silent + automatic browser fallback) + `window.advprint` API + plain HTTP `POST /print` (raw binary PDF = no base64) for any language. |
| **Screenshot printing** | Capture and print the visible page with one click. |
| **Print queue** | Pause, resume, cancel — live, and the queue survives hub restarts. |
| **Job history** | Last 100 jobs with status, printer, timing — reprint any job in one click. |
| **Enterprise ready** | Managed-storage schema (`managed.json`) for GPO/MDM deployment of settings and locked rules. |
| **Private by design** | No data collection, no external servers, no accounts. Hub binds to `127.0.0.1` and is token-protected. |

**Extra features beyond the paid original:** auto-print PDF URLs with login cookies (Laravel signed routes work), silent printing of raw text to 80 mm thermal rolls, **save-as-PDF File destination for every job type**, reprint-from-history via HTTP and CLI, `doctor` self-diagnosis, optional LAN mode for shared office printers.

---

## Quick start (3 steps)

### 1. Install the hub (one-time, zero questions)

**Easiest — native installers (v2.4.1):**

| | file | what it does |
|---|---|---|
| **Windows** | `AdvPrint-Pro-Setup-2.4.1.exe` | **STANDALONE installer — Python is included inside** (bundled 3.11 runtime + `AdvPrintPro.exe`): copies everything to `%LOCALAPPDATA%\AdvPrintPro`, registers **auto-run as a visible Startup app** (Task Manager → Startup apps → "AdvPrint Pro"), starts the hub, adds Start Menu shortcuts + a real **Add/Remove Programs uninstaller**. The hub shows a **"AdvPrint Pro" tray icon** (right-click = status page, test page, pause, auto-run on/off, exit). No admin, no Python install, no dialogs, never shows as "python". Note: unsigned EXE → SmartScreen may ask once: *More info → Run anyway*. |
| **Linux (Debian/Ubuntu/Mint)** | `advprint-pro_2.4.1_all.deb` | `sudo apt install ./advprint-pro_2.4.1_all.deb` — installs to `/opt/advprint`, ships a **systemd user service** (auto-run at login, restarts on crash) + XDG autostart fallback. CLI: `advprint doctor`. |
| **macOS / other Linux** | `tool/unix/install-unix.sh` | same auto-run via LaunchAgent / systemd --user / XDG, no sudo needed. |

**Or the portable way (both platforms):**

**Windows** — double-click one file:
```
tool\windows\portable\install\install-windows.bat        ← starts the hub NOW + auto-run at every logon,
                                     uses the BUNDLED Python runtime (installer\runtime)
                                     if present - no system Python needed, no prompts
```

**Linux / macOS** — one command:
```
bash tool/unix/install-unix.sh       ← starts the hub NOW + auto-run at every login,
                                     no sudo needed (systemd --user / LaunchAgent)
```

Both installers register **auto-run automatically** — after a reboot the hub is
always there, no shortcut needed. To undo it:

| | stop auto-run + hub | keep / remove print data |
|---|---|---|
| **Windows** | `tool\windows\portable\install\UNINSTALL-WINDOWS.bat` | data in `%USERPROFILE%\.advprint` |
| **Linux / macOS** | `bash tool/unix/uninstall-unix.sh` | data in `~/.advprint` |

Windows notes (v2.4.1): the hub runs as `AdvPrintPro.exe` (a renamed
`pythonw.exe`), so Task Manager shows **"AdvPrintPro"** — not "python".
Auto-run is a normal **Startup app** shortcut: open **Task Manager →
Startup apps** and you will find "AdvPrint Pro" there with its icon —
right-click → Enable/Disable any time (same switch as the tray icon
menu, or `UNINSTALL-WINDOWS.bat`). The installer also removes
Mark-of-the-Web from the downloaded files automatically, and the
installer/upgrader deletes the invisible scheduled task that v1.2–v1.4
used to create. If the hub ever fails to start after a reboot, open
`%USERPROFILE%\.advprint\hub.log` — the hub logs every
startup and print there.

The hub starts on `http://127.0.0.1:9235`. Fresh installs generate a private
random token (read it with `python "C:\\...\\hub\\advprint.py" token` — use the full path, or the desktop tool); upgrades of pre-2.0
installs keep working with the old default `PrintHub-2024` until you rotate it.
Wrong-token bookmarks are fixed in one click on the dashboard error page itself.

### 2. Load the extension

1. Open `chrome://extensions` in Chrome / Edge / Brave
2. Enable **Developer mode** (top-right)
3. Click **Load unpacked** → select the `extension/` folder

### 3. Connect & print

1. Click the AdvPrint icon → the popup shows **Connected**
2. Right-click any page → **AdvPrint Pro → Print this page**
3. Or open a URL matching a routing rule (the default rule auto-prints `*://www.htncr.org/lab/medical_reports/*`) — it prints with no dialog

---

## The HTTP API (any language, any tool)

```bash
# list printers
curl -H "X-AdvPrint-Token: $TOKEN" http://127.0.0.1:9235/printers

# print a PDF from a URL (silent)
curl -X POST http://127.0.0.1:9235/print \
  -H "X-AdvPrint-Token: $TOKEN" -H "Content-Type: application/json" \
  -d '{"pdf_url":"https://example.com/invoice.pdf","title":"Invoice 42"}'

# print a thermal receipt
curl -X POST http://127.0.0.1:9235/print \
  -H "X-AdvPrint-Token: $TOKEN" -H "Content-Type: application/json" \
  -d '{"text":"|center|MY SHOP\nItem 1      10.00\nTOTAL        10.00","paper":"thermal"}'

# pause / resume / clear the queue
curl -X POST -H "X-AdvPrint-Token: $TOKEN" http://127.0.0.1:9235/queue/pause
```

Full reference: [`docs/API.md`](docs/API.md) · Browser API: [`docs/EXTENSION-API.md`](docs/EXTENSION-API.md)

---

## Configuration

| Environment variable | Default | Meaning |
|---|---|---|
| `ADVPRINT_TOKEN` | (random per install) | API token (header `X-AdvPrint-Token`; legacy `PRINTHUB_TOKEN` still honored) |
| `ADVPRINT_PORT` | `9235` | HTTP port |
| `ADVPRINT_HOST` | `127.0.0.1` | Bind address — set `0.0.0.0` for office LAN sharing |
| `ADVPRINT_PRINTER` | *(OS default)* | Force a specific printer |
| `ADVPRINT_FILE_DIR` | `~/Downloads/AdvPrint` | Where `destination:"file"` PDFs are saved |
| `ADVPRINT_DATA` | `~/.advprint` | Data folder (SQLite history + job files) |

**CLI:** `python hub/advprint.py serve | testprint [a4|thermal] | printers | history [n] | reprint <id> | queue | doctor | help`

**LAN mode:** set `ADVPRINT_HOST=0.0.0.0` and point the extension (Options → Hub URL) at your PC's LAN IP, e.g. `http://192.168.1.20:9235`. Token is always required.

---

## Privacy & security

- **No data collection.** There is no telemetry, no account, no analytics.
- **Localhost only.** The hub binds to `127.0.0.1` unless you explicitly enable LAN mode.
- **Token-protected.** Every endpoint (except `/health`) requires the token, compared in constant time.
- **Open source, MIT.** Audit every line — the whole hub is one readable Python file.

## Requirements

- Python 3.8+ (no pip packages)
- **Windows:** [SumatraPDF](https://www.sumatrapdfreader.org/) (free, installer offers it via winget)
- **Linux/macOS:** CUPS (`cups-client`)
- Optional: Chrome/Chromium/Edge — used only for *page* printing (HTML → PDF); PDF/image/text printing works without it

## License

MIT © Bit Dream IT — free for personal and commercial use.
