# Changelog - AdvPrint Pro (Advanced Printer)
by Bit Dream IT - Innovative Healthcare Solutions

## v3.0.2 - POPUP HOOK SWITCH REMOVED + MULTI-PRINTER LAB GUIDE (2026-11-05)

Two changes on top of v3.0.1 - no settings migration, no removed
functionality.

- **Popup window.print() hook switch removed.** Options > Power
  switches > Intercept window.print() is now the ONE switch in ONE
  place (the popup duplicate is gone; the hookPrint setting and the
  Options switch are unchanged). The popup Power section keeps the
  master switch + Queue mode; i18n popHook* keys removed.
- **Multi-printer handling documented end to end**
  (docs/MULTI-PRINTER.md, new; Full Guide section 6.6): one PC,
  A4/A5 PDF reports on the laser AND ZPL labels on the Zebra at the
  same time. Grounded in the real routing code: per-job printer
  name wins (rule / dropdown / page API / API field / profile);
  payload sniffing picks the pipeline (PDF engine, image wrap, ZPL
  + ESC/POS + PostScript + PCL raw passthrough); printer_groups
  fail over to the first healthy member; dest_mode covers unnamed
  jobs; hold/probe behaviour when the target is unreachable.
- Version strings bumped to 3.0.2 everywhere (hub, dashboard
  badge, extension manifest/popup/Options/About, Setup exe
  VIProductVersion 3.0.2.0, deb control, docs). New tests: the
  popup must NOT contain the hook switch; MULTI-PRINTER.md must
  ship. 215 tests pass.

## v3.0.1 - TRAY MENU CLICK FIX + HOOK SWITCH INTO POWER (2026-11-05)

Two fixes on top of v3.0.0 - nothing removed, no settings migration.

- **Tray menu click->action fix (the 'text and click not the same'
  bug, root cause found).** The self-drawn menu's WM_LBUTTONUP did
  `self.items[idx]` with the selectable-row ORDINAL from `_hit()`,
  but `self.items` also holds ("sep",) entries - so every item after
  the first separator was shifted by one: 'Pause queue' did nothing
  (it hit the separator), 'Start at Windows logon' paused the queue,
  'Restart hub' toggled autostart, 'Allow LAN in firewall'
  RESTARTED the hub, 'Exit' opened the firewall UAC prompt. Fixed
  with `_pos_of()` (ordinal -> real items position); regression
  test simulates click bands over the real menu layout and checks
  the command of every row.
- **Intercept window.print() moved into Options > Power switches**
  (was mid-page in Behavior). Same `hookPrint` key as the popup
  toggle - both switches stay in sync automatically.
- Version strings bumped to 3.0.1 everywhere (hub, dashboard badge,
  extension manifest/popup/Options/About, Setup exe
  VIProductVersion 3.0.1.0, deb control, docs). 213 tests pass.

## v3.0.0 - RENUMBERED RELEASE (2026-11-05)

The v2.9.1 packages were already distributed; shipping different
content under the same 2.9.1 number would collide with installed
copies (same version, different bytes). This release therefore ships
the IDENTICAL v2.9.1 feature set - network printer mode, print
destination routing, responsive dashboard tables, the 27-finding
security hardening and the full documentation - under the clean new
number 3.0.0. No feature was added or removed; every surface (hub
VERSION/VERSION_NAME, dashboard badge, extension manifest/popup/
Options/About, Setup exe VIProductVersion, deb control, docs) says
3.0.0. Installs straight over 2.8.2 / 2.9.0 / 2.9.1; settings and
history are kept. 212 tests pass.

## v2.9.1 - RESPONSIVE TABLES + SECURITY HARDENING (audit pass) + FULL DOCS (2026-11-05)

The responsive-table fix plus a complete security/reliability hardening
pass - all 27 confirmed findings of an independent code audit are fixed
(HIGH job-collision / temp-file / rebinding / CORS-IPP / SSRF issues,
MEDIUM print-integrity and network issues, the LOW batch and the
performance items) - plus a full documentation refresh and clean
version numbering (one version everywhere: hub, extension, setup, deb,
docs). 23 regression tests added; 212 tests pass.

- **Job payload collisions (audit H1, fix).** Job files get a random
  suffix + exclusive create; the duplicate check runs BEFORE the file
  is saved and is lock-serialized - a same-second double submission
  can no longer overwrite the original job's payload or print twice.
- **Headless render isolation (audit H2/P4, fix).** Every page render
  gets its own temp dir + correct file: URLs; renders are capped at 2
  concurrent and a timeout kills the whole browser process tree.
- **Host-header allowlist (audit H5, fix).** Foreign Host headers
  (DNS rebinding) get 421; the hub only answers to its own names.
- **IPP browser-Origin block + scoped ACAPN (audit H6, fix).** The raw
  IPP endpoint refuses web-page requests; the Private-Network CORS
  answer is only sent to allowed origins.
- **SSRF guards everywhere (audit H4/H7, fix).** page_url runs the
  pdf_url guard (file:// + internal hosts -> 400); pdf_url re-checks
  every redirect hop.
- **Slowloris + big-body defence (audit M1, fix).** 30 s socket
  timeout; >1 MB unauthenticated bodies are refused before reading.
- **Token out of the logs (audit M2/L8, fix).** Startup URL masked,
  no plain token on first start, /diagnostics log tail redacted.
- **Print-integrity fixes (audit M3/M4/M5/M7, fix).** Cancel stops the
  group fallback (and is no longer overwritten by a finished print);
  instant jobs resolve printer groups; peer forwarding only on real
  offline/error; RAW 9100 rejects oversized payloads, caps
  connections at 8 and ENQUEUES printer-language passthrough (history
  row + cancel/reprint + destination routing); RAW jobs and printer
  timeouts no longer auto-retry into duplicate prints.
- **Atomic /config apply (audit M6, fix).** Validate-then-apply in one
  shot; peer_hubs entries stay real objects; printer_groups validated.
- **Extension Website API allowlist (audit H3, fix).** Options >
  Website API - empty list = page API OFF; upgraded installs are
  migrated from their auto-print rules (htncr.org keeps working).
- **Page-print quality (audit M8, fix).** Scripts stripped + <base
  href> injected for "Print this page" - styles/images resolve again.
- **Performance (audit P1/P2/P3, fix).** Worker wake-event + SQLite
  WAL/synchronous=NORMAL; PDFs upload raw (no base64 detour); the
  auto-print path reads document.contentType instead of double-
  downloading; /jobs + /audit limits clamped.
- **LOW batch (audit L1-L7, fix).** Bengali filenames keep combining
  marks; Sumatra paper= fallback + print-to-default; Content-
  Disposition sanitized (RFC 5987 for Unicode); auth-state lock; the
  stale 2.6.2 extension version fallback updated.
- **Responsive dashboard tables (fix).** Every dashboard card table
  (LAN sharing, Debug, Printers, Queue, Job history, Audit trail and
  the new **Print destination** card) used `overflow-x:auto` with
  `white-space:nowrap` cells, so on a narrow window the right-hand
  columns/buttons disappeared into a horizontal scroll INSIDE the card
  and were invisible on load. Cells now **wrap**: long job titles and
  paths break (`overflow-wrap:anywhere`), status chips stay on one
  line, action buttons flow onto the next line - **every column,
  button and option is visible the moment the page loads**, no inner
  scrolling. On phones the cards go 2-up, controls shrink, and the
  Print destination IP / Port / Proto fields stack cleanly (flex wrap;
  the span now toggles display:flex instead of display:inline).
  Pure CSS/JS - no settings change, no data migration; hard-refresh
  the dashboard (Ctrl+F5) after updating.
- **Full documentation refresh.** The Full Guide (HTML + PDF, 14
  chapters) covers the whole v2.9.x feature set end to end: the
  network printer mode (IPP `/ipp/print` + JetDirect RAW 9100), the
  **Print destination** card (default / selected / IP printer + Test),
  the phone "Auth fail" fix, `POST /ip-printer/test`, the new
  `/health` destination fields, the settings reference rows for
  `dest_mode` / `ip_printer_host` / `ip_printer_port` /
  `ip_printer_proto` / `ipp_printer` / `raw_printer_port`, and three
  new troubleshooting rows (phone auth fail, IP-printer held jobs,
  dashboard cut-off). Release notes v2.9.1 ship separately.
- **Version hygiene.** This tree was briefly labelled 2.9.0 twice
  (the original network-printer build and the follow-up work); to end
  the confusion the follow-up ships as **2.9.1**. Hub VERSION,
  dashboard/portal badges, extension manifest + popup + Options +
  About (single manifest source), Setup exe (NSIS
  VIProductVersion/DisplayVersion/filenames), deb package, VERSION.txt,
  START-HERE.txt, README, CHANGELOG and docs all say 2.9.1 now. The
  v2.9.0 entry below still documents the network-printer features;
  2.9.1 = those features + the responsive-table fix + docs.

## v2.9.0 - NETWORK PRINTER MODE + PHONE AUTH FIX + SMOOTH TRAY (2026-11-04)

Three things in one release: the hub becomes a real IP-printable network
printer ("Windows add device" style), the phone "Auth fail" on the Send
portal is fixed, and the tray menu stops lagging.

- **Network printer mode (new).** Other devices can now add this PC like
  a physical IP printer - two ways, both new:
  - **IPP at `/ipp/print`** (`http://<lan-ip>:9235/ipp/print`, same port
    as the hub - no extra firewall rule). Windows 10/11: Add printer >
    "Select a shared printer by name" > paste the URL - it installs with
    the built-in Microsoft IPP Class Driver. Phones: any print service
    that accepts a manual IPP address. Opening the URL in a browser
    shows a short how-to page (no token needed for IPP - it is its own
    protocol, like a physical network printer).
  - **JetDirect RAW listener on TCP 9100** (config `raw_printer_port`,
    0 = off). Windows: Add printer > "Add a printer using TCP/IP
    address" > this PC's IP + port 9100 + device type "Generic Network
    Card" > pick your real printer's driver. Windows renders ANY file
    (Word, Excel, photos, web) with that driver and streams the
    print-ready bytes here. The listener binds the LAN IP (never
    0.0.0.0), follows `share_lan`, rebinds on DHCP changes, and stops
    with LAN sharing.
  - **Smart payload routing** (shared by IPP + RAW): `%PDF` -> the
    normal PDF pipeline (SumatraPDF/Edge, History, audit, reprint);
    JPEG -> wrapped into a single-page PDF (pure-stdlib DCTDecode);
    `%!PS`/PCL/ESC/POS/ZPL -> winspool RAW passthrough (or `lp -o raw`
    on CUPS). Every job is audited with the source IP and size-bounded
    (`MAX_PDF`). Both switches live in config.json / `/config`
    (`ipp_printer`, `raw_printer_port`) and apply without a restart.
- **Print DESTINATION - ANY printer (new).** The hub does not just
  RECEIVE like an IP printer - it also routes every job to the
  destination you pick (dashboard card "Print destination"; config
  `dest_mode` / `ip_printer_host` / `ip_printer_port` /
  `ip_printer_proto`): the OS **default printer**, **any installed
  printer**, or an upstream **IP printer** (a real network printer at
  IP:port - JetDirect RAW or an IPP Print-Job with `application/pdf`
  and `copies`). A per-job `printer` name always wins. The whole
  pipeline honours it: the hold check probes the IP printer's
  reachability instead of a local printer ("IP printer x.x.x.x:9100 is
  unreachable - job held"), the virtual-PDF-printer save path never
  hijacks an IP-routed job, the instant (queue-off) path routes the
  same way, and audits name the real destination. New
  `POST /ip-printer/test` (reachability + latency, testable before
  saving). `/health` reports `dest_mode`, `dest_display`,
  `selected_printer`, `ip_printer` and the derived
  **`ip_printer_mode`** flag - LAN sharing + IPP/RAW listener means
  every PC or phone can add this PC as THEIR network printer and
  every job prints to the chosen destination.
- **Phone "Auth fail" FIXED.** With `token_header_only: true` the Send
  portal page opened on the phone but the browser UPLOAD could never
  authenticate (a phone cannot send the `X-AdvPrint-Token` header), so
  every phone got "invalid or missing token" right after picking a PDF
  while PCs (extension, header) kept working. `/send` POST now accepts
  the token from the query/body - the same shared QR link transport the
  GET page always used; the token is still required and still compared
  with `hmac.compare_digest`, and every other endpoint stays
  header-strict. The portal also appends the token as a form field, and
  the 401 text is now phone-friendly ("re-scan the fresh QR").
- **One version everywhere (extension).** popup badge, Options header
  chip and the About panel all read `chrome.runtime.getManifest().
  version` - the manifest is the single source; the hardcoded HTML
  fallbacks (stuck at 2.8.0) can never drift again.
- **Smooth tray.** Every tray action (Open dashboard, Print test page,
  Pause, Autostart, Restart, Allow LAN in firewall) now runs on its own
  thread - before, a slow action (browser launch, printer-status WMI,
  UAC) froze the icon and the next right-click lagged. The menu font is
  cached per DPI scale instead of being rebuilt on every right-click.
- **Firewall covers the printer port too.** The one-click "Allow in
  firewall" (dashboard + tray) now adds BOTH rules in a single UAC
  prompt: the hub port (9235) and the RAW printer port (9100).
- Dashboard LAN card: new **IP Printer mode** row (ACTIVE/OFF + the
  destination jobs print to + one-click Turn on + QR), **Network
  printer (IPP)** row (URL + copy + QR), **RAW printer port** row
  with a "How to add" hint, and a step-by-step add-printer hint under
  the card. `/qr?kind=ipp` renders the printer URL as a QR. New
  **Print destination** card picks default / any installed printer /
  IP printer (with IP/port/protocol + Test button).
- Tests: 35 new tests - 14 for the network printer (phone auth in both
  token modes, IPP attribute response, IPP Print-Job pdf/jpeg/zpl,
  validate/garbage/unknown-op, payload sniffing, size guard, ipp off,
  QR kinds, health fields, version single-source, tray threading,
  firewall RAW port) + 21 destination-routing tests (resolve_dest
  modes/legacy/override, IPP client framing incl. copies + error
  propagation, /config validation, /health destination fields,
  /ip-printer/test reachable + refused, ip_printer_mode flag,
  worker -> JetDirect sink END-TO-END, hold while the IP printer is
  down, raw routing to the sink, selected/default regression).
  Live self-check: 73/73 (9 new destination checks incl. the full
  /print -> queue -> worker -> JetDirect sink print). Version bumped
  across hub, setup.nsi (VI 2.9.0.0), extension manifest, docs.

## v2.8.2 - LAN SHARING APPLIES LIVE + WINDOWS FIREWALL ONE-CLICK (2026-11-04)

Fixes the field report "LAN sharing ON but http://<lan-ip>:9235 does not answer - only 127.0.0.1 works".

- **Live LAN rebind - the share switch now works instantly.** The hub keeps its loopback listener (127.0.0.1) up at all times and runs LAN sharing on a SECOND listener bound to the PC's specific LAN IP. Toggling LAN sharing (dashboard, extension Options or `POST /config`) starts/stops that listener inside the same HTTP request - no hub restart, zero downtime, and a failed LAN bind can never take local printing down. New internals: `lan_listen_start/stop/ensure` (`lan_active` in `/health` now reflects the real bind).
- **DHCP-proof.** A 3 s watcher follows LAN IP changes automatically: if the router hands the PC a new address, the LAN listener rebinds itself and logs `[LAN] LAN IP changed ... - rebinding`.
- **Windows firewall: detected and one-click fixed.** `/health` reports `firewall_ok` (netsh rule query, cached 30 s). The dashboard LAN card shows ALLOWED / BLOCKED / unknown plus an **Allow in firewall** button (single UAC prompt, rule for the current port); the tray menu gains **Allow LAN in firewall**. `POST /firewall/allow` is loopback-only by design.
- **Test LAN.** New `GET /lan/selftest`: the hub connects to its own LAN URL and reports PASS/FAIL with the exact reason - PASS + another PC still failing = firewall; FAIL = listener problem (hub.log explains).
- **Dashboard copy rewritten** - no more "RESTART the hub to apply"; the LAN card now shows the firewall row, the Test LAN button and honest error text when a bind fails.
- Docs page (`/docs`), START-HERE, README, API.md and the Full Guide updated for the new behaviour. Version bumped to 2.8.2 across hub, tray, setup.nsi (VI 2.8.2.0), extension manifest.

## v2.8.1 - SEND-PORTAL QR CODE + ONE-CLICK LAN INVITE (2026-11-03)

Two additions to the dashboard's LAN sharing card, both requested as
"share ip port with token, so any phone can send and another PC
auto-connects". Nothing removed.

### New: Send-portal QR code (phones print without any install)
- Dashboard > LAN card gets a **Send portal (phones)** row when LAN
  sharing is ON: **Copy send URL** copies
  `http://<this-PC-ip>:9235/send?token=...`, **QR code** shows the same
  URL as a scannable QR (toggles a row with the QR, the URL and a copy
  button). A phone on the same Wi-Fi scans it, opens the Send portal,
  picks a PDF - it prints on the hub's default printer.
- The QR is generated **inside the hub** by a vendored pure-stdlib
  encoder (byte mode, ECC M, versions 1-40, auto mask, ported from the
  MIT-licensed Nayuki reference design) and verified **bit-exact**
  against an independent implementation for every mask 0-7 - no
  internet, no CDN, no tracking, no new dependencies.
- New endpoint: `GET /qr?token=...&kind=send|invite` -> SVG image
  (`image/svg+xml`, no-store). `kind=send` encodes the phone upload
  URL, `kind=invite` the PC invite link below.
- `/health` now also reports `"hostname"` so the dashboard can build
  the invite link client-side without a second round-trip.

### New: one-click LAN invite (connect another PC in 10 seconds)
- Dashboard > LAN card gets a **Connect another PC** row: **Copy invite
  link** copies `http://<this-PC-ip>:9235/connect?t=<token>&n=<PC-name>`
  (a QR of it is available too). Opened in a browser on the OTHER PC it
  shows a confirmation page (new `GET /connect`, no hub auth - it
  validates its own `t=` token, wrong/stale t -> readable error page)
  with an **Add "<PC-name>" as a LAN print peer** button.
- The button form-POSTs to the OTHER PC's OWN hub
  (`http://127.0.0.1:9235/peer-connect`), which saves this hub into its
  `peer_hubs` (dedupe by URL), live-checks `/health`, shows the peer's
  version + a warning when LAN sharing is off there, and links straight
  to its dashboard. config.json editing and IP retyping are gone.
- **Security model** of `POST /peer-connect` (it must work without the
  receiving hub's token): loopback only; browser `Origin` must equal the
  peer URL being added (a random website cannot forge it - drive-by
  CSRF cannot inject a peer); peer URL must be a private-LAN http(s)
  address (localhost / 10.x / 172.16-31.x / 192.168.x / 169.254.x);
  GET never changes anything; every accept is audited
  (`peer.connected`) and denials are audited too
  (`peer.connect.denied`).
- Audit events: `peer.invite` (invite page opened),
  `peer.connected` (peer saved), `peer.connect.denied` (CSRF blocked).
- Dashboard LAN card polish: `Copy URL` now anchors to the first row
  explicitly (the new rows also use .mono cells); the no-peers tip
  points at the invite link; the QR row survives the 15 s LAN refresh
  (state kept in JS, re-rendered, not collapsed).

### Docs / packaging
- Hub docs page (/docs): new "QR code" + "One-click invite" sections
  with the security notes. API.md lists /qr, /connect, /peer-connect.
- Version bumped to 2.8.1 across hub, tool, setup.nsi (VI 2.8.1.0),
  deb control (baked at build), extension manifest, tests, README,
  START-HERE.

## v2.8.0 - TWO HUB PROFILES + DROPZONE + BULLET-PROOF UNINSTALL (2026-11-03)

Ten requested features on the working v2.7.0 baseline. Nothing removed.

### New: two hub profiles - Self PC + LAN PC (share-send routing)
- The extension keeps TWO full profiles: **Self PC** (hubUrl + token,
  Options > Connection 1) and **LAN PC** (hubUrlLan + hubTokenLan,
  Options > Connection 2 - share-send target).
- The popup **Share Send Mode** toggle is now the print ROUTE:
  ON -> every print job goes to the LAN PC hub; OFF -> jobs print on
  this PC's own hub. The popup status line names the active target;
  Recent jobs + Pause/Resume follow it; the popup test page prints on
  the active target; retry-parked jobs flush to the active target.
- Turning Share Send ON without a LAN PC opens Options at the LAN PC
  section (options.html#lan-settings) instead of failing silently.
- **Connect** on the LAN PC profile verifies reachability AND the
  token; **Clear** forgets the profile. hubFetch gained explicit
  targets ("self" | "lan"); LAN 401s never trigger the loopback
  token auto-heal (that would overwrite the LAN token with this
  PC's token).

### New: DropZone + Send portal - print WITHOUT the extension
- **DropZone** (dashboard card + GET /dropzone): the hub watches a
  folder (default <data>\DropZone; drop_dir / drop_delete settings,
  live on/off - the watcher re-reads the config every poll). Any PDF
  saved into the folder is printed and moved to done\ (or deleted) -
  print from Word/Excel/ANY app via "Microsoft Print to PDF".
  POST /dropzone/open opens the folder on the hub PC (loopback only).
- **Send portal** (GET /send + POST /send): upload a PDF from any
  phone / tablet / PC on the LAN; same token auth as every endpoint;
  multipart (curl -F), raw application/pdf body or pdf_base64 JSON;
  PDF-magic check, 25 MB cap, audited, source "send".

### New: Restart hub (tray + tool + dashboard + API)
- Tray menu **Restart hub**, AdvPrint Tool **[14] Restart AdvPrint**
  (+ CLI `tool.py restart`), dashboard **Restart hub** button and
  POST /restart: the hub relaunches ITSELF as a new process. The new
  process (ADVPRINT_RESTART=1) skips the single-instance pre-check
  and waits up to 12 s for the old listener to release the port.
  Queued jobs, settings and history are kept; hub.restart is audited.

### Fixed: bullet-proof upgrade + uninstall ("some file abort install")
- Setup now runs **hub-stop.ps1** BEFORE copying any file: stops the
  optional AdvPrint service (polite stop -> wait -> PID kill),
  DELETES the service registration (sc delete), kills every process
  under the install folder + anything on TCP 9235 + renamed hub
  images. Old hub/install/extension/docs/runtime folders are wiped
  so no stale file can abort or shadow the new install.
- .onInit pre-ticks the service section when a service exists, so
  upgrades reinstall the service fresh automatically.
- Uninstaller: same stop script, firewall rule removed, 3x folder
  sweep retry, honest leftover report (silent-mode safe).
- service-remove.ps1 verifies + force-removes; portable
  UNINSTALL-WINDOWS.bat stops/removes the service + firewall rule.
- Setup adds the LAN firewall rule (TCP 9235) automatically.

### New: silent install on any PC
- `AdvPrint-Pro-Setup-2.8.0.exe /S`: elevation is requested by the
  exe manifest itself (UAC once), the hub auto-starts after a silent
  install, no interactive popup can block it (silent-safe uninstall
  included).

### New: popup window.print() on/off + close-tab default OFF
- Popup **window.print() hook** switch (same setting as Options >
  Behavior) - one click turns silent interception on/off; the hook
  refused-call message points to the popup switch.
- **closeAfterPrint now defaults to false** - auto-printed URLs keep
  their tabs open unless the user opts in.

### New: dashboard / audit log for Self PC and LAN PC separately
- Options > Settings: Open dashboard - Self PC / Open audit log -
  Self PC / Open dashboard - LAN PC / Open audit log - LAN PC (each
  with the right token). Popup footer Dashboard link opens the
  ACTIVE target. background gained openHubPage {target}.

### New: A + printer logo
- The letter A drawn as a printer: the crossbar is the output slot
  and a printed page slides out of it. New crisp assets: extension
  icons 16/32/48/128, tray + installer ICO (16..256), dashboard +
  popup inline SVG, 440x280 promo tile, docs/logo-512.png.

### Tests
(- 13 new hub tests (dropzone watcher/pickup/move, /send variants,
  /restart auth, /dropzone/open loopback guard, config round-trip of
  the new keys, send portal HTML). Suite: 130/130.

## v2.7.0 - HISTORY MANAGER + SHARE MODES + LAYOUT FIX (2026-11-01)

### New: the Job history is a real manager now (dashboard + extension)
- **Filter** by any status (printed / queued / printing / held /
  scheduled / failed / dead / canceled / saved / forwarded) plus a
  one-click **"Not printed"** view; **search** by title, printer or
  #id; load 50/100/300/1000 rows; 50-per-page paging with
  newer/older; every row gets a **checkbox** with check/uncheck-ALL
  (master checkbox with the indeterminate state) and a live
  "N selected" counter.
- **Reprint selected** - POST /jobs/bulk-reprint {"ids":[...]}.
- **Reprint all non-printed** - POST /jobs/bulk-reprint
  {"scope":"not_printed"} re-queues every failed/dead/canceled job
  (jobs whose original file is gone are skipped and counted).
- **Clear ALL history** - POST /history/clear deletes every FINISHED
  job (printed / failed / dead / canceled / forwarded / saved).
  Active jobs (queued / printing / held / scheduled) are never
  touched, so clearing can not cancel a waiting print. Audited as
  history.cleared.
- The dashboard's old "Recent jobs" table became the **Job history**
  manager; the extension Options > History tab got the same filter /
  search / tick / bulk-reprint / clear-hub-history toolbar (the old
  "Clear extension copy" button stays).

### New: Share Receive Mode + Share Send Mode in the POPUP
- **Share Receive Mode** = hub share_lan (this PC accepts jobs from
  other PCs). One toggle in the popup; saved via POST /config; the
  usual "restart the hub to apply" note appears.
- **Share Send Mode** = extension-side switch (config key lanSend).
  OFF = the background refuses every queue/shift send-to-peer request
  ("nothing leaves this machine"); ON = shift buttons work again.
  Both switches show live state (Receive from /health, Send from the
  saved config) and turn gray/disabled while the hub is offline.
- New en + Bangla strings for every new control; nothing removed.

### Fixed: dashboard layout (the "broken design" below the page)
- The "Live debug & test tool" section and the SumatraPDF
  "Hub settings" box used to sit AFTER </main> - full-width,
  unstyled, below the page. They are now proper panels INSIDE the
  main column (Live test right under the Debug card).
- Dashboard header shows a v2.7.0 version badge; inputs/selects/
  checkboxes are styled; .forwarded status chips got their color.

### Professional polish
- Extension About panel shows the REAL manifest version (it used to
  stay on the hardcoded 2.6.4); popup version badge follows the
  manifest too.
- LAN tab cross-references the new popup switches; About panel got a
  v2.7.0 highlights line; setup.nsi / VERSION.txt / START-HERE /
  README / API docs all speak 2.7.0.

### Tests
- +6 v2.7.0 tests: bulk-reprint by ids, bulk-reprint
  scope=not_printed, history/clear (finished only - active rows
  survive), reprint single still works via the shared core, bad
  bulk payload -> 400, audit entries written. Full suite 117/117.

## v2.6.9 - DOUBLE-PRINT FIX (2026-11-01)

### Fixed: every page printed TWICE with Queue Mode OFF ("after print it
### extra again auto print")
- Live case (Debug tab, v2.6.8): each print produced TWO SumatraPDF
  runs, two "[OK] job #N printed" lines with different timings and two
  sheets of paper. Root cause: with Queue Mode OFF the job row was
  born 'queued' and only flipped to 'printing' AFTER the slow
  printer-status probe (hundreds of ms on Windows). The FIFO worker
  polls every 0.35 s and claimed the job inside that window - so BOTH
  the direct thread and the worker sent the same job to the printer.
- The execution path is now decided BEFORE the DB row exists and the
  row is BORN in its final state ('printing' for direct jobs). The
  worker, which only claims 'queued' rows, can never see a direct job:
  one job = one sheet. Proven by a race regression test that fails on
  v2.6.8 and passes on v2.6.9 (printer-status probe slowed to 0.6 s).
- Also fixed: a direct-mode job that fails now KEEPS its PDF file for
  the automatic retry (the direct thread used to delete the file even
  when the job was requeued, so the retry died on a missing file).

- Tests: +2 v2.6.9 regressions (race: exactly-one-execution; retry
  keeps file). Full suite 111/111.

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
