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

## What's new in v3.4.8 (RULES TABLE FITS + RULE EDITOR SAVES REAL KINDS + RUN BOOKKEEPING SYNCED)

The final-polish release on top of v3.4.7. Locked by
`tests/test_v348.py`; full details in `CHANGELOG.md`; developer delta
in `docs/AdvPrint-Pro-v3.4.8-A-to-Z-DEV-GUIDE.md`.

1. **The rules table never pushes Edit/Del outside again.** The
   reported bug: with Paper or another extra selected the columns
   Rule / URL / address filter / Match by / Page content / URL type /
   Printer / What to print / Cpl / Paper / On / Auto / Runs pushed
   the Edit button outside the card (the 14 nowrap headers forced a
   1145px table inside a 990px card). Fixed at the root: headers
   wrap, the table is compact, long pattern / content cells clamp
   with an ellipsis (measured: table 990 = card 990, overflow 0) and
   EVERY ONE UI table sits in a horizontal-scroll `.tbl-wrap` as a
   last resort - no column and no button can ever render outside the
   card again.
2. **The rule editor saves real URL types.** The old editor saved a
   SHIFTED kind: "Web page" saved kind `web` - a kind no page ever
   reports - so such rules could never fire. The select carries real
   values now (PDF link / Web page / Plain text / ZPL label page /
   Image page / Any), legacy `web` rules read as `html` in both
   matchers, and a content rule left on Any defaults to html.
3. **Run bookkeeping synced.** The Runs column shows "last HH:MM"
   again - `last_run` rides along with the extension's rules push and
   the hub cleaner keeps it (plus the title filter) on central edits.
4. **`/rules/test` GET form honors `kind` + `title`** - content rules
   are testable from the browser bar now, same as the POST form.

The v3.4.7 configurable hub port, DropZone watch toggle, strict LAN
share and URL rules engine are unchanged (below).

---

## What's new in v3.4.7 (CONFIGURABLE HUB PORT + DROPZONE WATCH FIX + STRICT LAN SHARE + URL RULES THAT REALLY MATCH)

The user said "current work fine" and asked for the next version with
five items. Fixed and locked by `tests/test_v347.py`. Full details in
`CHANGELOG.md`; developer delta in
`docs/AdvPrint-Pro-v3.4.7-A-to-Z-DEV-GUIDE.md`; the URL rules guide is
`docs/PRINT-RULES-RECIPES.md`.

1. **The hub port is configurable.** Default 9235 stays, but when
   another program on the PC already owns it: ONE UI Settings > HUB
   PORT (saves for real now), `python advprint.py port 9300`,
   `"port"` in config.json, or `ADVPRINT_PORT` env (wins over
   config.json). Validated 1024-65535 (631/5353/9100 refused);
   applied on restart; a busy port at boot logs every way to move.
2. **The DropZone watch button really toggles.** It used to be a
   static "Disable" that always sent `drop_enabled:false` - the watch
   could never be turned on from the ONE UI. Now Enable/Disable
   follows the live state.
3. **Strict LAN share.** Switch it ON and the hub lists EVERY IP that
   hits it (even refused ones) with hit counts; one click on Allow
   puts the IP on the Allowed-IPs list (first Allow replaces `*` and
   locks the hub down to real entries). `GET /lan/hits`,
   `POST /lan/allow`, `/lan/hits/clear`.
4. **URL print rules that really match.** The rule editor can pick the
   pattern type (glob / regex / contains - the hub keeps the field it
   used to strip), a recipe dropdown preloads the htncr.org lab set
   (single-test-id report, sample->ZPL, receipt client/all/lab/admin
   ->A5), and "Which rule fires?" REALLY tests a URL against the
   extension's engine (`POST /rules/test`) before anybody trusts it.
5. **No version prefixes in the UI notes.** "v2.8 ·", "v3.2.6 ·" and
   friends are gone from every panel and dashboard note.

The v3.4.6 one-port design (below) is unchanged.

---

## What's new in v3.4.6 (ONE PORT FOR EVERYTHING + POPUP REMEMBERS THE LAST PRINTER)

The user asked the right question about v3.3.5: *"why not the hub
default port only - one port to handle different PCs to connect
through IPP or other?"* Fixed and locked by `tests/test_v346.py`.
Full details in `CHANGELOG.md`; developer delta in
`docs/AdvPrint-Pro-v3.4.6-A-to-Z-DEV-GUIDE.md`.

1. **ONE TCP port again - the hub port 9235 serves EVERY printer for
   every PC.** The v3.3.5 dedicated per-printer ports (9236, 9237,
   ... + the TCP 9235-9259 firewall range) are removed. Exactly like a
   CUPS server, the queues are distinguished by their FULL URI
   (`/ipp/print` = the default queue, `/ipp/print/<printer>` = that
   one printer) plus the per-queue identity (unique printer-name,
   stable unique printer-uuid, the client's own URI echoed, one mDNS
   service per queue with its own `rp` and uuid on the SAME SRV
   port). Fewer sockets, ONE firewall rule (TCP 9235 + 9100 + 631 +
   UDP 5353), no port exhaustion - and every printer still adds side
   by side. The v3.3.4-era add failure was the shared queue IDENTITY,
   not the shared port.
2. **The popup shows the RIGHT printer now - and remembers it.** The
   selector always fell back to the FIRST printer after every
   popup open/reload because it read `default_printer` - a field the
   hub never sends (the hub answers `default`). Fixed, the popup now
   REMEMBERS the last printer you picked (`advLastPrinter`) and
   auto-selects it on the next open, falls back to the hub's current
   default, and marks the OS default with `[default]` in the list.
3. **v3.3.5 features all stay**: the "Show other PCs (LAN / IPP)"
   list stays MANUAL (Re-scan button only), the tool still installs
   and auto-updates its own extension (auto CRX on install + the
   silent per-start HKCU pass), the v3.3.4 multi-printer uuid fix and
   the idempotent set-default are untouched.

## What was new in v3.3.5 (DEDICATED QUEUE PORTS + MANUAL RE-SCAN + AUTO-CRX-ON-INSTALL)

Two new features locked by `tests/test_v335.py` (the dedicated
queue-port experiment was replaced by the v3.4.6 one-port design
above). Full details in `CHANGELOG.md`; developer delta in
`docs/AdvPrint-Pro-v3.3.5-A-to-Z-DEV-GUIDE.md`.

1. ~~**One dedicated TCP port per printer (9236, 9237, ...)**~~ -
   superseded by v3.4.6: ONE port serves every queue again.
2. **"Show other PCs (LAN / IPP)" no longer auto-loads.** The Printers
   panel list renders from the LAST MANUAL SCAN and refreshes ONLY via
   the panel Re-scan button or the switch itself - the 3 s poll never
   probes the other PC on its own any more.
3. **The tool installs its own extension (AUTO CRX).** The Setup writes
   the full browser policy (Forcelist + Allowlist + Sources, HKLM +
   HKCU, Chrome/Edge/Brave/Chromium/Vivaldi/Opera), and the hub
   silently re-applies the per-user pass on every start - no UAC, no
   .bat - so the built-in CRX installs and auto-updates itself from
   the hub.

## What was new in v3.3.4 (MULTI-PRINTER IPP ADD + POPUP PRINTER/RELOAD/NETWORK RELEASE)

Three real-world reports, all fixed and locked by `tests/test_v334.py`.
Full details in `CHANGELOG.md`; developer delta in
`docs/AdvPrint-Pro-v3.3.4-A-to-Z-DEV-GUIDE.md`.

1. **Every printer of the hub can be added now - not just one.** On the
   LAN, Windows refused the SECOND per-printer queue
   (`http://<hub-ip>:9235/ipp/print/<printer>`) because mDNS advertised
   ONE shared `UUID` TXT record for every queue - so each per-printer
   service looked like a re-announcement of the first. Every advertised
   queue now carries its OWN stable uuid (announce + direct TXT
   answers), so all printers appear and add side by side in Windows /
   phones.
2. **The popup sets the printer, reloads and shows the network state
   (new ONE design).** A PRINTER dropdown (hub printers + status;
   picking one makes it the OS default - ONE command per real change,
   nothing on popup open/reload, and the hub endpoint is idempotent:
   "already default" answers with zero commands). A RELOAD arrow
   re-reads everything. A NETWORK icon in the header shows at a glance:
   gray = offline, green = hub on this PC, teal pulse = Sharing ON
   listening on the LAN (tooltip names the address). The LAN switch is
   labelled **Sharing** and carries the network/connection icon.
3. **Browser auto-integration is INTERNAL now (AUTOCRX) - no extra
   .bat needed.** The hub runs the policy pass itself with an elevated
   PowerShell (one UAC prompt): Forcelist + Allowlist + Sources for
   Chrome/Edge/Brave/Vivaldi/Chromium/Opera in HKLM + HKCU, with
   duplicate-skip and a real per-browser report. One click in the
   console (Extension tab > **Auto-integrate (admin)**), or CLI
   `python advprint.py activate-extension [host:port]`. The fixed
   `allow_extention_advprint_pro.bat` (writes all three policies, real
   HKLM/HKCU menu) stays in prebuilt/ as an offline fallback only.

---

## What's new in v3.3.0 (THE ANY-PC INVITE + DUAL-STACK LISTENER RELEASE)

Three more real-world LAN reports, all fixed and locked by
`tests/test_v330.py`. Everything from v3.2.9 - the multi-PC IPP release
- stays unchanged.

1. **The invite page connects the RIGHT PC.** Opening
   `http://<hub-ip>:9235/connect?t=<token>` built the peer URL from the
   serving PC's own `lan_ip()` guess and a user who opened the invite on
   the hub PC itself silently added the hub to ITSELF. The page now uses
   the address the VISITOR typed (Host header), refuses self-invites on
   the page AND on `POST /peer-connect`, probes the visiting PC's own
   hub before you click (no more raw browser error when the other PC has
   no hub yet), explains a token that belongs to a DIFFERENT PC's hub,
   and offers every hub address (IPv4 + IPv6) as "use this" chips.
2. **Every listener answers on IPv4 AND IPv6, on every interface.** The
   9235 LAN hub, the 631 IPP mirror and the RAW 9100 port each bound ONE
   IPv4 address (`lan_ip()`) - deaf on all the PC's other adapters, and
   silent on IPv6. Now one IPv4 socket per interface IP plus one `[::]`
   socket (IPV6_V6ONLY) on every port; the LAN panel shows the real
   bound sockets; the interface-set changes trigger a clean rebind; mDNS
   announces AAAA. The `allowed_ips` ACL gates every socket exactly as
   before.
3. **Per-printer IPP queues work for ANY printer that exists.** The old
   slug folded every non-ASCII printer name (Bangla, Arabic, CJK) to the
   single slug `printer`, so those queues collided. Slugs are
   Unicode-aware now (percent-encoded in URLs), matching tolerates every
   slug style (dash / underscore / %20), a new printer's queue goes live
   in seconds (negative matches force a printer-list refresh) and the
   unknown-queue 404 lists the queues that ARE live.

## What's new in v3.2.8 (THE ipp:// + HTTP-PAGE FIX RELEASE)

Two real-world bugs reported against v3.2.7, both fixed and locked by
new tests (`tests/test_v328.py`). Everything from v3.2.7 — the complete
Developer API guide and every earlier fix — stays unchanged.

1. **The IPP landing page no longer prints the protocol twice.**
   Opening `http://192.168.1.101:9235/ipp/print` in a browser showed
   `ipp://http://192.168.1.101:9235/ipp/print` — `ipp://` was prepended
   to a URL that already carried `http://`, so Windows, macOS, iOS and
   CUPS refused the pasted address. The new `_ipp_scheme_url()` helper
   strips the web scheme first; the page now shows the one clean form
   `ipp://192.168.1.101:9235/ipp/print` next to the browser-friendly
   `http://…` URL.
2. **`window.advprint.printPdf()` (and every other page-API method)
   now works on http:// sites too.** A `https://host/*` pattern in the
   Website API list pinned the scheme, so the SAME site over `http://`
   was refused. The host is what you allow, not the transport:
   `https://reports.example.com/*` now also covers
   `http://reports.example.com/*` (and the other way round). The refusal
   message now names the real editor and suggests a ready-made pattern
   for the blocked host, the console hint documents the rule, and
   `docs/DEVELOPER-API.md` gained a full "Website API permission"
   section with the http troubleshooting case.
3. **The hub can no longer serve a stale extension.** Chrome
   auto-updates the extension from the hub's own package
   (`/extension/updates.xml`) — and only when that package is NEWER.
   The first 3.2.8 build left the embedded hub copies at 3.2.6, so
   browsers silently never updated and kept the old http-page refusal.
   The build now syncs + verifies every embedded CRX (hard-fail on
   drift), and the hub flags a stale package in `/health`,
   `/extension/info`, the `/extension` page and the Console Extension
   panel. After updating the hub, re-run Setup (or copy
   `prebuilt/AdvPrint-Pro.crx` over `hub/extension/AdvPrint-Pro.crx`)
   and let Chrome update to 3.2.8.

Details: `docs/RELEASE-NOTES-v3.2.8.md` and
`docs/AdvPrint-Pro-v3.2.8-A-to-Z-DEV-GUIDE.md`.

## What's new in v3.2.7 (THE DEVELOPER API RELEASE)

The print API — `window.advprint` in every web page and `POST /print`
over plain HTTP — is now documented A-to-Z, with every option and every
real case, in THREE places: the new **`docs/DEVELOPER-API.md`** (~600
lines), the hub `/docs` page (**section 9**) and the **in-UI Docs
modal** (section 9).

1. **The full guide** — every method (`status`, `printers`, `history`,
   `printPage`, `printPdf`, `print`, `printPdfLink`), every option
   (priority 1-urgent-first, page ranges + odd/even, n-up, quality
   presets AND explicit DPI, scale, margins, duplex, paper, tray,
   profiles, destination file, `queue:false` instant mode, `run_at`
   scheduling, dedupe override, watermark), the four HTTP body styles
   (JSON / raw PDF bytes / raw label bytes / multipart), the payload
   sources in priority order, the response fields and the error map.
2. **The real cases, worked end-to-end** — SAME PC MANY PRINTERS
   (receipt on the thermal roll + invoice on the laser at the same
   moment), MANY PCs ONE HUB (the whole LAN prints; the UI stays
   local-only), **PDF + ZPL `^XA` labels at the same time** (verbatim
   latin-1 ZPL and the ESC/POS marker builder), scheduled prints,
   urgent jobs, watermarked reprints, kiosk routing — with curl / JS /
   Python / PHP examples and the complete URL & token map
   (`ipp://` vs `http://`, per-printer queues, 631 mirror, RAW 9100).
3. **`window.advprint.print()` now has FULL API PARITY** — it also
   passes `run_at`, `queue`, `dedupe`, `tray` and `watermark_text`;
   the browser API and the HTTP API accept exactly the same options.

Details: `docs/RELEASE-NOTES-v3.2.7.md` and
`docs/AdvPrint-Pro-v3.2.7-A-to-Z-DEV-GUIDE.md`.

## What's new in v3.2.6 (SEVEN BUGS + THE UI SECURITY MODEL)

Everything below is locked by tests (397 passed) **and** verified live
in a browser (`scripts/render_v326.py`).

1. **History / Queue clear really cleans.** Clear queue cancels every
   waiting job AND removes all finished records — the list is empty
   afterwards. "Clear ALL history" calls the real `/history/clear`
   endpoint (it used to post a body the hub ignored). Waiting jobs are
   never touched by the history clear.
2. **Printer → Details no longer doubles the path** — the
   `/ipp/print/ipp/print/<printer>` URL is dead; the hub returns the
   bare queue slug and the console joins it once.
3. **LAN panel top Disable/Enable works** (it was never wired) and
   **every Copy URL carries the token**
   (`http://<ip>:9235/ui?token=...`).
4. **QR codes encode `http://`** (phone browsers cannot open `ipp://`
   — they Google-search it) while the display and the Copy button
   keep the `ipp://` printer URL printers expect.
5. **The install doc is not backdated** (the self-host extension page
   shows the current version, not v3.0.7) and the console has an
   **in-UI Docs button** — the guide opens inside THE ONE UI, no
   extra old-UI tab.
6. **SECURITY — the console UI is local-only.** Only the hub PC itself
   (loopback or its own IP) can open the console or change settings.
   LAN PCs and phones keep FULL print access per the Allowed-IPs list
   (Send portal, IPP printer URL, print API, ports 9235/631/9100) —
   they get a friendly locked page instead of the UI.
7. **LAN sharing ON now switches the IPP printer ON automatically**
   (an explicit IPP: ON/OFF toggle stays independent in the LAN panel
   header), **the interactive CLI tool menu is gone** (running
   `tool.py` opens the console; every repair subcommand stays) and
   **the tray menu is exactly Dashboard / Restart / Exit**.

Details: `docs/RELEASE-NOTES-v3.2.6.md` and
`docs/AdvPrint-Pro-v3.2.6-A-to-Z-DEV-GUIDE.md`.

## What's new in v3.2.5 (SIX USER-REPORTED BUGS, ALL FIXED)

Everything below is locked by tests **and** verified live in a browser.

1. **Set Default printers FOR REAL.** The old button only saved the hub
   config key; Windows kept its own default and the factory-on
   *"Let Windows manage my default printer"* feature flipped it back.
   The new `POST /printers/set-default` performs the OS-level change
   (Windows: disables the auto-manage feature per-user —
   `LegacyDefaultPrinterMode=1` — then sets the default and VERIFIES by
   reading it back; Unix: `lpoptions -d`), keeps the hub destination in
   sync and the toast reports the verified result.
2. **Job History selection survives the 3 s auto-refresh** — ticked
   rows stay ticked; a live "n selected" counter plus **Reprint
   selected / Cancel selected / Clear selected** and a per-row
   **Cancel** (queued/held/printing) join the per-row **Reprint**; the
   header checkbox is a real select-all.
3. **Live Queue gets the same treatment** — checkbox column, select-all,
   per-row actions by status, **Cancel selected** + **Clear selected**,
   selection persists.
4. **The per-printer IPP URL is confirmed working** —
   `ipp://<ip>:9235/ipp/print/<printer>` resolves raw names, URL-encoded
   names and slugs (case/punctuation-insensitive) on both the GET
   landing page and the IPP print queue; unknown queues answer 404.
5. **Force-install policy reports its REAL failure** — the console no
   longer hides `{ok:false}` behind "HTTP 200"; the hub gets a
   PowerShell fallback when reg.exe is blocked; the release notes
   document exactly how to apply and verify the policy
   (`chrome://policy`, `ExtensionInstallForcelist`, manual .reg, GPO,
   managed-PC caveat).
6. **Start with Windows is honest** — the Settings switch reads the REAL
   Startup-folder state from `/health` and actually toggles it via
   `POST /autostart` (writes/removes the same shortcut the tray icon and
   Task Manager → Startup apps show). Tray, UI and Task Manager can no
   longer disagree.

All v3.2.4 features are unchanged (the toolbar popup, ONE UI ONE
BUTTON, Allowed IPs, branding-only options page). See
`docs/RELEASE-NOTES-v3.2.5.md` and
`docs/AdvPrint-Pro-v3.2.5-A-to-Z-DEV-GUIDE.md`.

## What's new in v3.2.4 (THE TOOLBAR POPUP IS BACK)

One change, exactly as requested: the quick toolbar **popup is back**.

1. **The popup is back.** Clicking the toolbar icon opens the 340px
   quick popup again — master switches (AdvPrint enabled, Queue mode,
   Share Receive / Share Send), the five action buttons (**Print this
   page · Save as PDF · Print screenshot · Test page · Options**), live
   queue state with Pause/Resume and the eight most recent jobs with a
   one-click **Print now** for stuck ones, plus the offline /
   default-token / held-jobs banners with the one-click **Fix token**.
   The footer is **branding only**: *100% local · no cloud. By Bit Dream
   IT - Innovative Healthcare Solutions.* The disabled-state error
   messages point at the popup again, and every popup string exists in
   both UI languages (English + Bangla).
2. **One product, two depths.** The popup is the quick depth; THE ONE UI
   console stays the single place for every advanced option. The
   **Options** button (popup and options page) opens the brand card,
   which opens the console itself.

All v3.2.3 fixes are unchanged (Hub-switch save bug, ONE UI ONE BUTTON,
Allowed IPs, branding-only options page).

## What was new in v3.2.3 (EVERY IPP PATTERN + WORKING SWITCHES + CLEAN UI)

The three reported v3.2.1 defects are fixed:

1. **The IPP printer answers in EVERY pattern.** `ipp://ip:9235/ipp/print`
   and `http://ip:9235/ipp/print` on the hub port, plus a **new
   standard-port mirror on 631** (`http://ip:631/ipp/print`) — Android's
   Default Print Service / Mopria ignores custom ports on manual add and
   always tries port 631 first (that is why Android could not connect).
   The installer opens TCP 631 in the firewall; `"ipp_standard_port": 0`
   turns the mirror off.
2. **The printer appears by itself everywhere.** AirPrint/mDNS discovery
   no longer requires LAN sharing — IPP printer mode alone starts it
   (and starts the LAN listener), so Windows 10/11 "Add device", macOS
   Bonjour, iOS AirPrint and Android Mopria discover the hub on their own.
3. **Every switch in THE ONE UI works** — click = flip + instant save
   (Power/Browser switches push to paired browsers; Hub/Settings save to
   config.json). The **extension popup is gone** — the toolbar icon opens
   the console directly. 13 demo-stub menu items now fire their real
   actions; duplicate buttons removed; the LAN tab shows live IPP URLs
   and the per-platform add-printer guide.

See `docs/RELEASE-NOTES-v3.2.4.md` and
`docs/AdvPrint-Pro-v3.2.4-A-to-Z-DEV-GUIDE.md`.

## What was new in v3.2.1 (THE APPROVED UI IS NOW THE PRODUCT)

The customer-approved rev-4 All-in-One design is now the shipped UI -
byte-for-byte markup/CSS with live hub data wired in (17 tabs, 9 menus,
rule editor, multi-browser silent CRX install, real QR codes).

**v3.2.1 fix - the UI is EMBEDDED in `advprint.py`** (`CONSOLE_HTML`):
the hub never depends on an external `console.html` file, so the
approved UI is served at `/`, `/ui` and `/dashboard` on every install,
even if files are damaged. extension Options opens
http://127.0.0.1:9235 directly.

## What was new in v3.2.0 (THE ONE ALL-IN-ONE UI EVERYWHERE)

v3.2.0 makes ONE approved IDM window manage EVERYTHING, on EVERY URL,
for EVERY PC:

- **One UI, no separate URLs** — `/`, `/ui` and `/dashboard` all serve
  the same approved All-in-One console. 17 live panels incl. LAN,
  DropZone, Connections, Rules, Power, Extension, Audit, Logs.
- **SELF PC UI vs CENTER PC UI** — the owner (127.0.0.1) gets full
  control; a LAN PC opening the share URL sees the CENTER PC UI (amber
  banner, live print features, system tools stay on the center PC).
- **Tools (14)** — the desktop tool's whole menu ([1] start … [14]
  restart) is now a console panel backed by the new POST /tool API.
  Nothing extra shown, nothing missing.
- **Central rule manager** — the Rules panel edits URL/address filter,
  match by (URL / page content), what to print, printer, copies, paper,
  on/auto and the runs counter; installed extensions sync two-way with
  the hub (local edits always win).
- **Website whitelist defaults to `*`** — ALL websites may print out of
  the box (extension apiSites = ["*"], mirrored live to the console).
- **Silent install per browser** — Chrome / Edge / Brave / Chromium /
  Vivaldi ExtensionInstallForcelist values in the Extension panel with
  one-click copy (no Chrome Web Store warning on policy installs).

See `docs/RELEASE-NOTES-v3.2.0.md` and
`docs/AdvPrint-Pro-v3.2.0-A-to-Z-DEV-GUIDE.md` (full development +
build process).


## What's new in v3.1.2 (premium graphical window + center mode)

- **THE ONE UI** — the hub serves `console.html` at **/ui**: a Windows-IDM style console (Dashboard / Printers / Jobs / Audit / IPP Printer / Extension / Settings / Logs, live 3 s polling, real actions). The SAME page runs in the native window (gui_app v2), in Chrome, and embedded in the extension options Console tab.
- **gui_app v2** — the native window wraps /ui through a backend ladder: pywebview → Qt WebEngine → GTK WebKit → Chrome/Edge `--app` window → default browser. PySide6 (241 MB) is gone — the Setup EXE is ~10 MB again. New START-CONSOLE.vbs launcher + **Console (THE ONE UI)** tray item.
- **CENTER MODE** — one center PC, many child PCs: a child PC installs ONLY the extension (no tool) and prints through the Center PC's hub (Connections → Center PC / child PC mode: auto / local / center + URL + token, 60 s probe cache). Popup **Console** button + options **Console** tab with offline fallback.
- **Build everything from source** — `scripts/build-all.sh` builds the CRX, extension zip, Setup EXE and DEB from this tree alone. See `docs/BUILD-FROM-SOURCE.md` + `docs/CENTER-CHILD-PCS.md`.

## What's new in v3.0.9 (bug fix + per-printer IPP queues - the hub as central IPP middleware)

- **Fixed the extension Default-printer dropdown showing every printer name TWICE** ("HP Laser 103 107 108HP Laser 103 107 108"): one missing paren in `options.js` let the option label evaluate to `name + name` through the comma operator. Names render once again, with `[status]` / `(OS default)` decorations.
- **Per-printer IPP queues**: every local printer also gets `ipp://<lan-ip>:9235/ipp/print/<printer>` + its own mDNS/Bonjour service. One center PC now serves the whole LAN — child PCs, phones and tablets print to ONE exact printer of the center PC with **no tool installed on the client** (the Chrome extension or plain IPP is enough). Queue names accept the raw Windows name (URL-encoded) or a slug; `GET /printers` answers `ipp_queue` per printer; `GET /ipp/print/<printer>` serves a per-queue landing page. See `docs/IPP-GUIDE.md`.
- **Build everything from source**: `installer/setup.nsi` is now repo-relative and `scripts/build-all.sh` stages + builds the Setup EXE, the DEB, the signed CRX and the extension zip from this tree alone (the CRX signing key ships in `extension-signing/`) — no prebuilt binaries needed.

## What's new in v3.0.8 (professional IPP printer - Windows, macOS, iPhone, Android)

The bug report that drove this release: *"http://192.168.1.7:9235/ipp/print - this IPP printer mode does not work. Windows says 'Windows couldn't connect to the printer'."* Root cause found and fixed: the v2.9 IPP engine answered with **wrong wire tags and value types** (`printer-state` as a text "3", booleans inside an enum tag, integers inside a boolean tag, a range inside a boolean tag) and **omitted every attribute an RFC 8011 printer must answer with** (`printer-uri-supported`, `uri-authentication-supported`, `operations-supported`, `document-format-default`, `printer-up-time`, ...). Loose clients still printed, but the strict **Microsoft IPP Class Driver** refused the answer - hence the connect error. v3.0.8 rebuilds the whole printer:

- **Byte-exact RFC 8010/8011** - every attribute carries the correct value tag and encoding (verified against CUPS' `cups/ipp.h`); a strict wire linter in `tests/test_ipp.py` guards it (16 conformance tests).
- **All the operations real OSes use**: Print-Job, Print-URI, Validate-Job, **Create-Job + Send-Document** (how macOS CUPS, iOS PrintKit and Android Mopria actually submit jobs), Cancel-Job, Get-Job-Attributes, Get-Jobs, Get-Printer-Attributes - plus **chunked request bodies** for phone IPP stacks.
- **AirPrint-grade discovery**: while LAN sharing is on, a stdlib **mDNS/Bonjour announcer** (`_ipp._tcp` + `_universal`) makes the hub appear **by itself** in Windows 10/11 "Add device", macOS "Add Printer", the iPhone/iPad AirPrint picker and Android's Default/Mopria print service. No URL typing. Disable with `config.json` `"ipp_mdns": false`. The Setup exe adds the UDP 5353 firewall rule discovery needs.
- **Per-OS cheat sheet**: the printer info page (`http://<pc-ip>:9235/ipp/print`) now shows exact add-printer steps for Windows, macOS, iPhone/iPad and Android. Full guide: **docs/IPP-GUIDE.md**.

## What's new in v3.0.7 (silent extension auto-install - one download)

Download ONE file and the browser extension installs itself. AdvPrint Pro now packs the extension as a **signed .crx** with a **stable release key** - the extension ID (`likldbkamojokkfdlcjibiljpgbbnohc`) never changes - and the installers write Chrome's enterprise **ExtensionInstallForcelist** policy so the browser installs the extension silently **and keeps it updated on every release**:

- **The hub IS the update server** - it serves `/extension/updates.xml` (Chromium gupdate manifest) and `/extension/AdvPrint-Pro.crx` (the signed package, `Content-Type: application/x-chrome-extension`). Open endpoints (Chrome's updater sends no token) guarded by the usual Host-header rule.
- **Windows Setup**: ships the .crx inside the hub folder and writes the machine-wide policy (HKLM) for Chrome, Edge, Brave, Chromium and Vivaldi - append-safe (never touches another company's entries) and removed cleanly on uninstall. The dashboard card can re-write/repair the per-user (HKCU) policy after a port change.
- **Linux deb**: writes `/etc/{opt/chrome,chromium,opt/edge,brave}/policies/managed/advprint-pro.json` - on Linux silent install has **no domain requirement**; it just works.
- **Schools / workplaces**: point the policy at ANY web server hosting the two files from `AdvPrint-Enterprise-Deploy-Kit` (internal IIS, GitHub Pages, any free host) - GPO / Intune / one .reg import. See **docs/SELF-HOST-DEPLOY.md**.
- **Honest limit**: on a non-domain Windows PC, Chrome/Edge ignore silent off-store install (Google/Microsoft policy, not ours) - home users keep the classic Load-unpacked path; the extension folder still ships. Linux is unrestricted.

## What's new in v3.0.7 (silent extension auto-install - one download)

Download ONE file and the browser extension installs itself. AdvPrint Pro now packs the extension as a **signed .crx** with a **stable release key** - the extension ID (`likldbkamojokkfdlcjibiljpgbbnohc`) never changes - and the installers write Chrome's enterprise **ExtensionInstallForcelist** policy so the browser installs the extension silently **and keeps it updated on every release**:

- **The hub IS the update server** - it serves `/extension/updates.xml` (Chromium gupdate manifest) and `/extension/AdvPrint-Pro.crx` (the signed package, `Content-Type: application/x-chrome-extension`). Open endpoints (Chrome's updater sends no token) guarded by the usual Host-header rule.
- **Windows Setup**: ships the .crx inside the hub folder and writes the machine-wide policy (HKLM) for Chrome, Edge, Brave, Chromium and Vivaldi - append-safe (never touches another company's entries) and removed cleanly on uninstall. The dashboard card can re-write/repair the per-user (HKCU) policy after a port change.
- **Linux deb**: writes `/etc/{opt/chrome,chromium,opt/edge,brave}/policies/managed/advprint-pro.json` - on Linux silent install has **no domain requirement**; it just works.
- **Schools / workplaces**: point the policy at ANY web server hosting the two files from `AdvPrint-Enterprise-Deploy-Kit` (internal IIS, GitHub Pages, any free host) - GPO / Intune / one .reg import. See **docs/SELF-HOST-DEPLOY.md**.
- **Honest limit**: on a non-domain Windows PC, Chrome/Edge ignore silent off-store install (Google/Microsoft policy, not ours) - home users keep the classic Load-unpacked path; the extension folder still ships. Linux is unrestricted.

## What's new in v3.0.6 (rules match by content - ZPL, text, PDF, image)

Until 3.0.5 a rule fired only when the URL matched - the only way to route a ZPL page to the Zebra was a URL pattern plus Action: ZPL label. v3.0.6 lets a rule match **by content** - the page itself decides:

- **Match by: Content** - "Page content: **ZPL label (^XA...^XZ)**" fires for ANY page whose text carries a ZPL label and streams it byte-for-byte to the rule's printer (the Zebra); "**Receipt / plain text**" prints text/plain pages as an ESC-POS receipt on the thermal printer; "**PDF document**", "**Image**" (a picture tab prints the photo - new **Action: Image** pipeline with cookie download + visible-tab capture fallback) and "**Web page**" complete the list.
- **How detection works**: the already-open tab is probed once (document.contentType + a text sample: selection, then <pre>/<textarea>, then body). .pdf URLs / application/pdf -> PDF, image URLs / image/* -> image, text carrying ^XA...^XZ -> ZPL, text/plain -> receipt text, everything else -> web page. No extra download, no page JavaScript. A URL typed into a content rule narrows it ("ZPL pages on THIS site only").
- **Rules power switch in Options only** - the popup no longer carries the auto-print rules switch; it lives on the Rule Manager bar and as the same switch in General > Power switches (one setting: rulesPaused; paused = no hidden auto-print, manual prints keep working).
- **Options split into 9 human tabs** - Queue, History, Rules, General, Printing, Connections, Hub, Debug, About. Every option kept, renamed in plain English with a full description; the old endless Settings page is gone (old #settings/#api/#lan-settings links keep working).
- **Two simulators** - the URL simulator now fetches the URL once (with your login cookies) and reports the detected content as well; the new text simulator answers "which content rule fires for THIS label/receipt text". Both print nothing.
- The lab recipe (PDF reports to the A4/A5 laser + ZPL labels to the Zebra + ESC-POS receipts to the thermal printer) is unchanged - see docs/MULTI-PRINTER.md.

## What's new in v3.0.5 (Rule Manager - the hidden lab, now controlled)

The multi-printer lab rules printed hiddenly (silent auto-print, no dialog). v3.0.5 gives them a dedicated **Rules** tab in the extension Options - the Rule Manager - so everything hidden is now managed and controlled:

- **One dedicated place**: the whole rule table (pattern, printer, Action Auto/PDF/Page/**ZPL label**/**ESC-POS receipt**, copies, paper, Copy button, printer chips) lives in Options > Rules, together with its controls.
- **Pause all rules - one switch**: stops every hidden auto-print at once; the popup has the same switch (Power section). Manual prints keep working while paused.
- **URL simulator (prints nothing)**: paste a URL, press *Which rule fires?* - the manager shows the winning rule, its printer, action, copies/paper, and warns when the rule is OFF or all rules are PAUSED.
- **Per-rule run counters**: every rule shows its runs and the last job time ("12 runs - last 14:02"), keyed by stable rule ids.
- **Rule activity log**: the last 100 hidden hits (time, pattern, action auto/manual, printer, result incl. FAILED + why) with Clear log / Reset counters buttons.
- The **Settings** tab keeps a pointer card ("Open the Rule Manager"). Nothing about the rules themselves changed - the lab recipe (PDF reports to the A4/A5 laser + ZPL labels to the Zebra + ESC-POS receipts to the thermal printer) works exactly as before, just managed. See docs/MULTI-PRINTER.md.

## What's new in v3.0.4 (multi-printer rules made easy)

One PC, several printers, managed entirely in Options > Auto-print & routing rules - now with the full printer list in sight:

- **"Printers on this PC" chip strip** under the rules table: every installed printer (+ groups) as a chip with live status and the OS default marked. One click on **+ rule** starts a new rule with that printer already selected - a rule per printer is two clicks away.
- **Copy button on every rule row**: duplicate the rule, change the URL pattern (and printer if needed) - the fastest way to build the lab rule set.
- **New "Contains" pattern type**: the URL just has to CONTAIN the text (e.g. `medical_reports/pdf`) - no wildcards, no regex to learn. Glob and Regex unchanged.
- The lab recipe: HP chip + rule -> `*://www.htncr.org/lab/medical_reports/pdf/*`, Auto, Paper A5 - Zebra chip + rule -> `.../labels/*`, Action "ZPL label (text on page)", Copies 2. Every job carries its rule printer (the hub gives the per-job name priority over the destination card), so both printers run at the same time. See docs/MULTI-PRINTER.md.

## What's new in v3.0.3 (rules print labels - ZPL / ESC-POS + per-rule copies & paper)

The multi-printer lab is now managed ENTIRELY in Options > Auto-print & routing rules - no page JavaScript, no curl, no destination-card flipping:

- **Rule Action "ZPL label (text on page)" and "ESC-POS receipt (text on page)".** When the rule's URL opens (Auto) or you press Print page, the extension grabs the page TEXT - the user's selection first, then a `<pre>`/`<textarea>` block (what ZPL viewers and label web tools show), then the visible body text - and sends it to the hub with an explicit language. The hub streams ZPL **byte-for-byte** to the rule's printer (the Zebra) or builds an ESC/POS receipt (auto cut) for the thermal printer. A safety guard refuses text without `^` commands so a mis-matched page can never waste labels.
- **Per-rule Copies and Paper.** New rule columns: Copies (1-999, e.g. 2 labels per visit) and Paper (A4/A5/A3/Letter/Legal/Tabloid - Paper A5 for lab receipts while reports stay A4). Rule values override the global Default print options, and the **Reprint a PDF link** box honours the matching rule as well.
- **One hub, many printers, zero JS:** rule 1 `*://www.htncr.org/lab/medical_reports/pdf/*` -> laser, Action Auto/PDF, Paper A5; rule 2 `*://www.htncr.org/lab/labels/*` -> Zebra ZD421, Action ZPL label; rule 3 receipt text -> thermal, Action ESC-POS. The per-job printer name always wins over the Print destination card, so both printers run at the same time. New lab card under the rules table; recipes in docs/MULTI-PRINTER.md.

## What's new in v3.0.2 (popup hook switch removed + the multi-printer lab guide)

Two changes on top of v3.0.1 - nothing removed except a duplicated switch:

- **The popup's window.print() hook switch is gone.** The switch now lives ONLY in Options > Power switches > *Intercept window.print()* - right next to the master switch and Queue mode (v3.0.1 moved it there; v3.0.2 removes the popup duplicate so there is exactly ONE switch in ONE place). Same `hookPrint` setting, same behaviour, no migration.
- **New: `docs/MULTI-PRINTER.md` - how ONE PC handles multiple printers at the same time.** The lab case, answered end to end: receipt/PDF printing on A4 or A5 on one printer while a Zebra (or any other) printer prints ZPL labels simultaneously. The rules that make it work: the **per-job printer name always wins** (extension auto-print rule, Options default-printer dropdown, page API `printer` option, or `POST /print` `"printer"` field); the **payload type decides the pipeline** (`%PDF` -> PDF engine with paper a4/a5/tray/duplex/copies/profiles; JPEG -> wrapped PDF; **ZPL `^XA` / ESC-POS / PostScript / PCL -> raw passthrough**, byte-for-byte to the named printer); **printer groups** fail over to the first healthy member; the Print destination card covers jobs that carry no printer name. Includes a step-by-step lab setup (LIS portal -> HP LaserJet A4/A5 + label page -> Zebra ZD421) and curl snippets (`lang:"zpl"` labels included). The Full Guide gained section 6.6 with the same story.

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
- **Restart hub** — in the tray menu, the console Hub tab and the dashboard button: the hub relaunches itself cleanly (new process waits for the port; queued jobs, settings and history are kept).
- **Bullet-proof upgrade & uninstall.** The setup now runs `hub-stop.ps1` BEFORE touching files: stops the optional *AdvPrint* service (wait + PID kill), **deletes the service registration** (reinstalled fresh when ticked — upgrades keep it automatically), kills every process under the install folder and frees TCP 9235. Old program folders are wiped, so no stale file can abort an install any more; the uninstaller retries the folder sweep and reports leftovers honestly.
- **Silent install** `AdvPrint-Pro-Setup-3.2.5.exe /S` — elevation is requested by the exe manifest itself ("auto permission" on any PC), the hub auto-starts after a silent install, and the firewall rule for LAN sharing (TCP 9235) is added automatically (removed on uninstall).
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
