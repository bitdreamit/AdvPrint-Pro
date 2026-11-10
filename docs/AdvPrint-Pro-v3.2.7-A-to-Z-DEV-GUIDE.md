# AdvPrint Pro v3.2.7 — A-to-Z DEVELOPMENT & BUILD GUIDE

> **v3.2.7 = "THE DEVELOPER API RELEASE" on top of v3.2.6.** The print
> API — `window.advprint` in every web page + `POST /print` over HTTP —
> is documented A-to-Z with every option and every real case, and the
> extension API now has FULL parity with the HTTP API. Every change is
> locked by `tests/test_v327.py` and the full suite; v3.2.6's 30 locks
> (and everything before) keep passing.
>
> **NEW 1 - `docs/DEVELOPER-API.md` (~600 lines).** The complete guide:
> window.advprint method-by-method with the camelCase->hub mapping and
> the Promise/timeout/fallback mechanics; direct HTTP with three token
> placements and four body styles (JSON / raw PDF bytes / raw label
> bytes kind=raw / multipart + CSP form fallback); the payload-source
> priority order; the full option table (priority 1 urgent first,
> pages ranges + odd/even, n-up, quality presets AND DPI, scale,
> margins, duplex, paper, tray, profiles, destination file,
> queue:false instant, run_at, dedupe, reason, watermark); response
> fields; the 400/401/403/421/500 error map.
>
> **NEW 2 - the cases, worked end-to-end.** SAME PC MANY PRINTERS
> (receipt + invoice at the same moment via queue:false = one thread
> per job; one-call-per-printer loops never dedupe-blocked because the
> dedupe key includes the printer; groups as fallback lists).
> MANY PCs ONE HUB (LAN POSTs to http://<lan-ip>:9235/print,
> Allowed-IPs decide, UI stays local-only; what serializes vs what
> runs parallel). PDF + ZPL AT THE SAME TIME (raw jobs skip the
> printer probe; verbatim ^XA...^XZ latin-1 labels in curl/JS/Python;
> the ESC/POS marker builder #big |center| |right| |cut| |drawer|
> |barcode:| |qr:|). Plus run_at schedules, priority:1 urgent jobs,
> duplex/n-up, archive-as-PDF, watermarked reprints, kiosk routing,
> and the URL & token map (ipp:// vs http://, per-printer slugs, 631
> mirror, RAW 9100, /send, local-only /ui).
>
> **NEW 3 - the guide ships in THREE places.** `docs/DEVELOPER-API.md`
> + the hub /docs page section 9 (9a methods, 9b HTTP, 9c multi-
> printer cases, 9d raw printing, 9e URL/token map, TOC entry) + the
> in-UI Docs modal section 9 (same content, live hub URL baked in).
> docs/EXTENSION-API.md + docs/API.md carry the full option table and
> link to the guide.
>
> **NEW 4 - window.advprint.print() FULL API PARITY.** The extension
> `background.js` print case now also passes `run_at`, `queue`,
> `dedupe`, `tray` and `watermark_text` to the hub - the browser API
> and the HTTP API accept exactly the same option set.
>
> **v3.2.6 recap (all unchanged):** History/Queue clear really cleans;
> printer Details no longer doubles /ipp/print; LAN panel top switch
> + token-carrying Copy URL + independent IPP toggle; IPP auto-ON with
> LAN sharing; QR encodes http:// (copy keeps ipp://); docs inside the
> UI; the UI LOCAL-ONLY security model; CLI menu gone; tray =
> Dashboard / Restart / Exit.

> **Build flow (same as v3.2.6, one command each):**
> 1. edit `tool/unix/hub/console.html` (the ONE UI source),
> 2. re-embed it: `python3 /home/z/my-project/scripts/embed_console_v327.py`
>    (writes the `CONSOLE_HTML` constant into BOTH advprint.py copies -
>    the UI is served from INSIDE the interpreter, a stale embed means
>    a stale UI),
> 3. build everything: `bash scripts/build-all.sh` (CRX3 + extension
>    zip + NSIS Setup EXE + DEB + SHA256SUMS into dist/),
> 4. verify: `python3 -m pytest tests/` (full suite incl. the new
>    v3.2.7 locks).

## 2.7 What changed in v3.2.7 (the exact code map)

| Change | File | Detail |
|---|---|---|
| Developer API guide | `docs/DEVELOPER-API.md` | NEW ~600 lines: window.advprint methods, POST /print body styles + token placements, payload-source order, full option reference, response fields, errors, multi-printer + concurrency cases, ZPL/ESC-POS, URL & token map, case studies a-i, cheat sheet |
| /docs section 9 | `advprint.py` DOCS_HTML | "9. Developer API" (9a-9e) + TOC entry `#devapi` |
| In-UI docs section 9 | `console.html` `docsHtml()` | `id="d-api"` section with live BASE/port + v3.2.7 release notes |
| Extension parity | `extension/background.js` | print case passes run_at / queue / dedupe / tray / watermark_text |
| API doc parity | `extension/content/api.js` + `docs/EXTENSION-API.md` + `docs/API.md` | header comment + full option table + links to DEVELOPER-API.md |
| Version | everywhere | VERSION.txt, VERSION/VERSION_NAME, manifest, popup/options/i18n, api.js fallback, console boot default -> 3.2.7 |
| Tests | `tests/test_v327.py` | version matrix, parity fields in background.js, docs sections present, hub copies synced |

### 2.7.1 v3.2.7 verification (what the tests lock)

- `tests/test_v327.py`: VERSION = 3.2.7 in the hub + VERSION.txt parses
  to 3.2.7 + manifest 3.2.7; background.js maps run_at/queue/dedupe/
  tray/watermark_text; DOCS_HTML has section 9 with 9a-9e and the TOC
  entry; CONSOLE_HTML has the d-api docs section + v3.2.7 release
  notes; DEVELOPER-API.md exists with the required anchors (window
  .advprint, POST /print, ZPL ^XA, ESC/POS markers, multi-printer,
  many PCs, queue:false, run_at, dedupe); the unix + windows portable
  hub copies are byte-identical.

## 2.6 What changed in v3.2.6 (the exact code map)

> **BUG 1 - "History and Queue clear but not clean".** The old
> `POST /queue/clear` only flipped queued jobs to canceled and the
> hub IGNORED the `{finished:true}` body the console sent for
> "Clear ALL history" - no row was ever removed. NOW: plain
> `/queue/clear` cancels every live job (queued/held/scheduled/
> printing) AND deletes every terminal row (`db_clear_queue()`), so
> both views come back genuinely empty; `{finished:true}` is an
> alias of `POST /history/clear`; the console button calls
> `/history/clear` directly. Waiting jobs are never touched by the
> history clear.
>
> **BUG 2 - printer Details doubled the path.** `/printers` returned
> `ipp_path = "ipp/print/<slug>"` and the console prepended
> `/ipp/print/` again -> `/ipp/print/ipp/print/<printer>?token=...`.
> NOW the hub returns the BARE slug and the console joins it once.
>
> **BUG 3 + 4 - LAN panel top switch + Copy URL token.** The header
> Disable/Enable was never wired (only rows were); Copy URL built a
> token-less URL. NOW `#lanTopToggle` toggles share_lan with a live
> label, `#ippTopToggle` is the NEW independent IPP Enable/Disable,
> and every "Copy URL" copies `http://<ip>:9235/ui?token=<token>`.
>
> **BUG 5 - the QR must encode http://.** `/qr?kind=ipp` hard-pins
> the `http://<ip>:9235/ipp/print` payload (phones Google-search
> ipp:// URLs); the modal displays and COPIES the `ipp://` printer
> URL, and the note spells out both URLs. Test-locked.
>
> **BUG 6 - install doc backdated + Docs in the UI.** The self-host
> extension page shows `(v%s) % VERSION` instead of "(v3.0.7)"; the
> /docs install section uses @@VERSION@@; the console gained an
> in-UI Docs modal (`openDocs()` / `docsHtml()` - 8 sections +
> release notes, opened by Help > Quick start guide, About > Docs /
> Release notes). The old /docs page stays behind "Full guide page".
>
> **SECURITY - "only own ip or loopback ip can show ui".** NEW
> `_mgmt_locked()` gate (runs in do_GET + do_POST after the
> allowed-ips gate): non-local callers get a branded 403 for every
> UI/settings/management route; the PRINT SURFACE stays open per
> allowed_ips - `/print`, `/send`, `/ipp/*` (+ 631 mirror, RAW 9100),
> `/jobs` (+cancel/print-now/bulk-reprint), `/printers`, `/health`,
> `/extension/*`, `/connect`, `/testprint`, error reports. The hub
> PC (loopback AND its own LAN IP - `own_ip_set()`) always passes.
> `/jobs/release_all` stays local via `MGMT_POST_DENY`. Refusals are
> audited (`ui.locked`) and logged.
>
> **NEW - LAN share ON auto-enables IPP.** `/config` with
> `share_lan:true` sets `ipp_printer:true` (unless the request set
> ipp_printer explicitly); the 631 + mDNS listeners re-ensure
> immediately; the LAN panel gets the extra IPP toggle + row button.
>
> **REMOVE 1 - the interactive CLI menu is gone.** `tool.py` has no
> numbered menu; running it opens THE ONE UI (`open_console()`).
> Every one-shot subcommand stays (start/stop/restart/status/
> testprint/history/autorun/livetest/diagnose/dashboard/service-*/
> update-check/uninstall). Start Menu: "AdvPrint Console.lnk".
>
> **REMOVE 2 - the tray menu is 3 items:** Open dashboard /
> Restart hub / Exit ("tray can reduce only need Exit, Dashboard,
> Restart").

> **Build flow (same as v3.2.5, one command each):**
> 1. edit `tool/unix/hub/console.html` (the ONE UI source),
> 2. re-embed it: `python3 /home/z/my-project/scripts/embed_console_v326.py`
>    (writes the `CONSOLE_HTML` constant into BOTH advprint.py copies -
>    the UI is served from INSIDE the interpreter, a stale embed means
>    a stale UI),
> 3. build everything: `bash scripts/build-all.sh` (CRX3 + extension
>    zip + NSIS Setup EXE + DEB + SHA256SUMS into dist/),
> 4. verify: `python3 -m pytest tests/` (397 tests incl. the 30 new
>    v3.2.6 locks) + `python3 /home/z/my-project/scripts/render_v326.py`
>    (live hub + Playwright, verifies all seven fixes end-to-end and
>    screenshots them).

| Change | File | Detail |
|---|---|---|
| Clear really cleans | `advprint.py` | `db_clear_queue()` (cancel live + DELETE terminal); `/queue/clear` honors `{finished:true}` -> `db_clear_history()`; response `{canceled, removed}` / `{deleted}` |
| Clear wiring | `console.html` | `ACTIONS["queue-clear-finished"]` -> `POST /history/clear`; confirm text states the clean behavior |
| Bare slug | `advprint.py` | `/printers` `item["ipp_path"] = _ipp_queue_slug(n)` |
| Details URL | `console.html` | `data-open` = slug or ""; handler opens `BASE + "/ipp/print" + (slug?"/"+slug:"") + "?token="` |
| Header switches | `console.html` | `#lanTopToggle` + `#ippTopToggle` wired in `renderLanRows()`; "Network printer (IPP)" row gets its own Enable/Disable mapped to ipp_printer |
| Copy URL token | `console.html` | `ACTIONS["copy-hub-url"]` copies `lanBase() + "/ui?token=" + encodeURIComponent(TOKEN)` |
| QR payload | `advprint.py` | `/qr` kind=ipp branch pins `http://<ip>:<port>/ipp/print` |
| QR modal | `console.html` | `QR_KINDS.ipp.note` + openQR note show both URLs; copy keeps ipp:// |
| In-UI docs | `console.html` | `#docsmodal` + `docsHtml()` (8 sections + release notes) + `openDocs(anchor)`; Help/About buttons rewired; "Full guide page" keeps /docs |
| Doc version | `advprint.py` | `/extension` page prints `(v%s) % VERSION`; DOCS_HTML uses `@@VERSION@@` |
| UI security gate | `advprint.py` | `own_ip_set()` (5 s cache), `MGMT_OPEN_GET/POST_EXACT/PREFIX`, `MGMT_POST_DENY`, `Handler._is_own_host()`, `_mgmt_locked()`, `_ui_locked_answer()` (branded 403, audited), wired in do_GET/do_POST |
| IPP linkage | `advprint.py` | `/config` POST: share_lan true -> ipp_printer true unless explicitly set; instant `ipp631_listen_ensure()` + `ipp_mdns_ensure()` |
| CLI menu removed | `tool.py` | `MENU`/`menu()` deleted; `open_console()` opens `http://127.0.0.1:<port>/ui?token=...`; usage() updated; menu[N] strings -> subcommand form |
| Shortcut | `installer/setup.nsi` | `AdvPrint Tool.lnk` -> `AdvPrint Console.lnk`; version 3.2.6 |
| Portable bat | `tool/windows/portable/AdvPrint-Tool.bat` | opens the console (the menu lives in the UI) |
| Tray slim | `tray_windows.py` | `_menu_items()` = Open dashboard / Restart hub / sep / Exit |
| Version | everywhere | VERSION.txt, VERSION/VERSION_NAME, manifest, popup/options/i18n, setup.nsi -> 3.2.6 (now 3.2.7) |
| Tests | `tests/test_v326.py` | 30 locks incl. a 37-row security-gate matrix |

### 2.6.1 v3.2.6 verification (what the tests + live run lock)

- `tests/test_v326.py`: /queue/clear leaves ZERO rows and honors
  finished:true; /history/clear keeps waiting jobs; ipp_path is a
  bare slug with no "/"; the Details handler joins the prefix once;
  the header toggles exist + the row toggle maps to ipp_printer;
  copy-hub-url carries the token; /qr?kind=ipp answers an SVG whose
  payload URL rule is pinned; the docs modal + sections exist and
  Help/About open it; no backdated v3.0.7 strings; the gate matrix
  passes for local (loopback + own LAN IP) and refuses every
  management route for a remote IP while the whole print surface
  answers; the gate is wired into do_GET and do_POST; LAN-share ON
  auto-enables IPP and an explicit false beats it; tool.py has no
  menu and opens the console; NSIS has no Tool shortcut; the tray is
  3 items; version 3.2.6 everywhere + embedded console freshness.
- `scripts/render_v326.py` (live hub + Playwright): all of the above
  in a real browser - header toggles flip with labels, copied URL
  contains /ui?token=, Details opens the undoubled URL, QR modal
  shows http payload + copies ipp://, docs modal opens with
  "1 - Quick start", Release notes jumps inside the modal, zero page
  errors. Screenshots: docs/v326-*.png.

---

## 2.5 What changed in v3.2.5 (the exact code map)

| Change | File | Detail |
|---|---|---|
| Set Default endpoint | `tool/unix/hub/advprint.py` | `os_set_default_printer(name)` (LegacyDefaultPrinterMode=1 + WScript.Network.SetDefaultPrinter + verify; `lpoptions -d` on Unix); `POST /printers/set-default` returns `{ok, default, detail}` or `{ok:false, error}`; CFG["printer"] synced; audit row written |
| Set Default UI | `console.html` (ONE UI) + legacy dashboard | `data-setdef` handler calls `/printers/set-default`, toast shows `r5.detail` |
| History selection | `console.html` | `histSel` state; render applies it (`checked = !!histSel[j.id]`); counter `#histSelInfo`; per-row Cancel for queued/held/printing; select-all `data-hall` |
| Queue checkboxes | `console.html` | checkbox column + `data-qall` select-all; `queueSel` state; `#queueCancelSel` / `#queueSelInfo`; Cancel selected + Clear selected; selection persists |
| Selection engine | `console.html` | `selIds/syncSelBar/bindSelections/clearSelection/cancelSelected`, bound in `boot()`; `btnLike` bindings for all four bulk buttons |
| Policy honesty | `console.html` | `api()` throws `d.error || d.message || HTTP <status>` |
| Policy fallback | `advprint.py` | `_ext_reg_add`: reg.exe first, PowerShell `New-ItemProperty` fallback; `/tool policy-install` + `ext_policy_install` carry `error` + truthful per-browser report |
| Autostart honest | `console.html` | poll reads `h.autostart` (real Startup-file state); switch POSTs `/autostart {enabled}` instead of refusing; Minimize-to-tray keeps its hint |
| Autostart snapshot | `advprint.py` | `POST /autostart` rebuilds the health snapshot so the poll cannot flip the switch back |
| Version | everywhere | VERSION.txt, VERSION/VERSION_NAME, manifest, popup/options/i18n, setup.nsi → 3.2.5 |
| Tests | `tests/test_v325.py` | 19 locks, one per contract (see below) |

### 2.5.1 v3.2.5 verification (what the tests + live run lock)

- `tests/test_v325.py`: the endpoint exists with verify-then-sync
  semantics; the OS call fails honestly on a sandbox without CUPS;
  history/queue selection survives the poll (no `checked = false`
  anywhere); per-row Cancel + bulk buttons + select-all present;
  selection engine bound at boot and Clear selected NEVER deletes jobs;
  the per-printer IPP URL works LIVE (landing page for slug + raw name,
  404 for unknown); api() surfaces `d.message`; PowerShell fallback
  present; policy responses carry `error`; autostart reads `/health`,
  the switch POSTs `/autostart`, and the round-trip writes/removed the
  real Startup file with `/health` mirroring it.
- `scripts/render_v325.py` (live hub + Playwright): set-default flips a
  stubbed CUPS default and the hub config follows; bogus printer fails
  with the real reason; policy-install on Linux answers
  `{ok:false, error:...}`; autostart ON/OFF round-trip + the UI switch
  follows; seeded jobs render with checkboxes, selection survives a
  real 3 s poll tick, select-all ticks every visible row, Cancel
  selected cancels a queued job (state -> canceled), Clear selected
  unticks; printer cards show the exact `ipp://127.0.0.1:<port>/
  ipp/print/<slug>` URLs; popup ver chip v3.2.5 + branding footer.

> **v3.2.4 = "THE TOOLBAR POPUP IS BACK" on top of v3.2.3.** One change,
> exactly as requested: `manifest.json` carries `default_popup` again,
> the toolbar icon opens the 340px quick popup (master switches, Print
> this page / Save as PDF / Print screenshot / Test page / **Options**,
> queue state + recent jobs with Print now, offline / token / held
> banners with one-click Fix token) and the footer is BRANDING ONLY
> ("100% local · no cloud. By Bit Dream IT - Innovative Healthcare
> Solutions."). The four dead footer-link listeners are removed from
> popup.js; the disabled-state errors point at the popup again; every
> popup i18n key exists in both languages; `setup.nsi` packs
> popup.html + popup.js again. THE ONE UI console stays the single
> place for every advanced option, and the options page stays
> branding-only. Everything else from v3.2.3 (switch-save fix, ONE UI
> ONE BUTTON, Allowed IPs) is unchanged.

> **v3.2.3 = "CLEAN UI, ONE BUTTON + EVERY SWITCH VERIFIED + ALLOWED

> **v3.2.3 = "CLEAN UI, ONE BUTTON + EVERY SWITCH VERIFIED + ALLOWED
> IPS" on top of v3.2.2.** (1) The Hub-tab switch bug is fixed for
> real — `escpos_codepage`/`thermal_text_engine` were missing from the
> accepted config types, so every Hub-panel save died with 400 and no
> Hub switch ever persisted; they are now accepted + validated, the
> Hub panel refreshes on every poll and demo placeholder paths can no
> longer reach config.json. Every switch is verified end-to-end in a
> real browser (click → POST /config → server state → reload).
> (2) ONE UI, ONE BUTTON — the toolbar carries only the four real
> actions (New Job, Pause Queue, Release ALL, Test Page) + LAN/IPP
> status chips; the ten nav buttons that duplicated the sidebar, the
> five address-bar pills, the dashboard Quick-actions card and the
> dashboard Test Page / Open Printers duplicates are GONE; the sidebar
> is the only tab switcher. (3) NEW Allowed IPs — LAN Sharing >
> Allowed IPs: default ["*"] = whole LAN; once real IPs are added ONLY
> those may connect (console, portal, API, IPP 9235 + 631, RAW 9100 —
> all 403 / closed; 127.0.0.1 always allowed; denials audited as
> acl.denied). (4) The extension options page is branding-only with
> the footer "100% local · no cloud. AdvPrint by Bit Dream IT -
> Innovative Healthcare Solutions."

> **Build flow (unchanged since v3.2.1, one command each):**
> 1. edit `tool/unix/hub/console.html` (the ONE UI source),
> 2. re-embed it: `python3 scripts/embed_console_v322.py` (writes the
>    `CONSOLE_HTML` constant into BOTH advprint.py copies and syncs the
>    windows console.html),
> 3. build everything: `bash scripts/build-all.sh` (CRX3 + extension
>    zip + NSIS Setup EXE + DEB + SHA256SUMS into dist/),
> 4. verify: `python3 -m pytest tests/` + `python3
>    /home/z/my-project/scripts/switch_verify_v323.py` (live browser
>    switch verification) + Playwright screenshots of all 17 tabs.
## 2.4 What changed in v3.2.4 (the exact code map)

| Change | File | Detail |
|---|---|---|
| Popup restored | `extension/manifest.json` | `action.default_popup: "popup.html"`, `default_title: "AdvPrint Pro"`, version 3.2.4 |
| Popup files | `extension/popup.html` + `extension/popup.js` | back from the v3.2.1 feature set; ver chip v3.2.4; footer branding-only (no Console/Dashboard/Debug/API links) |
| Dead listeners removed | `extension/popup.js` | the four `lnkDash/lnkConsole/lnkDebug/lnkApi` blocks deleted (elements no longer exist); token help + Share-Send-without-URL open the options page via `chrome.runtime.openOptionsPage()` |
| Wording | `extension/background.js` | disabled-state errors: "enable it in the popup (toolbar icon)"; `chrome.action.onClicked` console-open kept as fallback; icon-click comment block updated |
| i18n | `extension/i18n.js` | header updated (popup is back); all 36 popup keys verified for en + bn |
| NSIS | `installer/setup.nsi` | File popup.html/popup.js lines re-added to the extension section; OutFile/VIProductVersion/FileVersion/ProductVersion/DisplayVersion/silent-hint → 3.2.4 |
| Version | everywhere | VERSION.txt, `VERSION`/`VERSION_NAME` (twin copies identical), manifest 3.2.4 |
| Tests | `tests/test_v324.py` | popup contract locks (see below) |

### 2.4.1 v3.2.4 verification (what the tests lock)

- `tests/test_v324.py`: manifest has default_popup + version 3.2.4;
  popup.html/popup.js/i18n.js exist; footer branding-only (no footer
  link elements); popup.js has no dead footer listeners or dead
  options.html anchors; every popup i18n key exists (en + bn); every
  sendMessage type used by popup.js exists in background.js; setup.nsi
  packs popup.html + popup.js; version coherence manifest == hub ==
  VERSION.txt.

## 2.3 What changed in v3.2.3 (the exact code map)

| Area | File | Change |
|---|---|---|
| Hub switch 400 bug | `advprint.py` | `CONFIG_TYPES` += `escpos_codepage: str`, `thermal_text_engine: str` (validated in POST /config: codepage `^[a-z0-9_-]{1,24}$`, engine `auto|builtin|browser`); these were MISSING, so every Hub-panel switch save was rejected 400 |
| Hub panel live refresh | `console.html` | `poll()` now calls `refreshHubPanel()` every 3 s (was only on tab open) — inputs can no longer carry demo values into a save |
| Demo-path guard | `console.html` | `saveHub()` includes `file_dir`/`sumatra_path` only when the value differs from the live config |
| Toolbar dedupe | `console.html` | toolbar = New Job + Pause Queue + Release ALL + Test Page (ids `tbNew/tbPause/tbRelease/tbTest`, no `data-tab`) + status chips `chipLan`/`chipIpp`; Pause label flips with `pausedState` in `renderFrame()`; the 10 nav `tbtn`s removed |
| Address bar dedupe | `console.html` | the five pill buttons removed (QRs: Network menu + LAN tab) |
| Dashboard dedupe | `console.html` | Quick-actions card removed; p-head keeps Refresh; printer-card Test Page / Open Printers removed |
| ALLOWED IPS matcher | `advprint.py` | `ip_allowed_by_list(ip, rules)` — `*`, exact IP, CIDR (`ipaddress`), wildcard (`fnmatch`); `::ffff:` + zone-suffix normalisation; bad CIDR falls back to text compare (typos can only tighten) |
| ALLOWED IPS gate | `advprint.py` | `Handler._ip_gate()` runs in `do_GET`/`do_POST` before auth; branded 403 HTML (footer branding) + JSON 403; audits `acl.denied` (1 per 10 s/IP); `IPP631Handler` gates GET+POST (+ own `_is_loopback`); RAW 9100 accept-loop closes denied IPs |
| ALLOWED IPS config | `advprint.py` | CFG `allowed_ips` default `["*"]`; in CONFIG_KEYS + CONFIG_TYPES(list); POST /config cleans the list (empty / `*` → `["*"]`); /health reports `allowed_ips` + `acl_restricted` |
| ALLOWED IPS UI | `console.html` | LAN tab card: mode chip `aclMode`, input `aclInput`, buttons `aclAdd`/`aclAllowAll`, list `aclList`; `renderAcl()` (called from `renderLanRows()`), `saveAcl()`, `aclWire()` (Enter-to-add) |
| Options = branding | `extension/options.html`+`options.js` | brand card + footer "100% local · no cloud. AdvPrint by Bit Dream IT - Innovative Healthcare Solutions."; auto-opens the console (click to retry); token row only when the hub refuses |
| Version | everywhere | VERSION.txt, `VERSION`/`VERSION_NAME`, manifest 3.2.3, NSIS `VIProductVersion 3.2.3.0` + OutFile …3.2.3.exe, DEB control (auto from VERSION.txt) |

---

## 2.2 What changed in v3.2.2 (the exact code map)

| Area | File | Change |
|---|---|---|
| Standard-port IPP mirror | `advprint.py` | `IPP631Handler` + `ipp631_listen_start/stop/ensure()`; config `ipp_standard_port` (default 631); serves only /ipp/print(+/<printer>), landing page + redirects; health refresher hooks it every 3 s |
| IPP landing page shared | `advprint.py` | new `ipp_landing_html()` — one source for both ports, shows ipp:// AND http:// URLs + the 631 note when the mirror is up |
| Discovery decoupling | `advprint.py` | `_ipp_mdns_loop` want = `ipp_printer AND ipp_mdns` (share_lan removed); `lan_listen_ensure` want = `share_lan OR ipp_printer` |
| mDNS TXT | `advprint.py` | adds `usb_MFG=Bit Dream IT`, `usb_MDL=AdvPrint Pro Hub` (Mopria display name) |
| Health fields | `advprint.py` | `/health` now returns `ipp_urls {ipp,http,std}`, `ipp_mdns_up`, `ipp_std {up,port,err}` |
| Switches that work | `console.html` | `bindSwitches()` = ONE delegated document-level click handler on `.switch` inside `.tgl/.f-row/#rulemodal`; `swSave()` debounces 400 ms → `saveExtPrefs()/saveHub()/saveSettingsPanel()`; `swDirty()` guards the 3 s poll; saves clear dirty keys |
| Menu linkups | `console.html` | 13 `data-toast="…(demo)"` items replaced with `data-act=`, `data-tool=`, `data-goto=`; menu clicks close the dropdown |
| Dedupe | `console.html` | removed both "Save & push to browsers" buttons, dashboard quick-action duplicates, DropZone double "Open folder" |
| IPP guide card | `console.html` | LAN tab: per-platform table (Windows 10/11, macOS, iPhone/iPad, Android) with live-filled ids `ippUrlIpp`, `ippUrlHttp`, `ippGuideWin/MacHost/Android/Android631/RawIp`; live chips rows `row-mdns`, `row-ipp631` |
| No popup | `extension/` | v3.2.2 removed the popup (see the v3.2.2 table row) — **v3.2.4 brings it back** with a branding-only footer |
| Firewall | `installer/setup.nsi` | + TCP 631 rule "AdvPrint Pro IPP 631" |
| Version | everywhere | VERSION.txt, `VERSION`/`VERSION_NAME`, manifest 3.2.2, NSIS `VIProductVersion 3.2.2.0` + OutFile …3.2.2.exe, DEB control (auto from VERSION.txt) |

## 2.3 v3.2.2 verification (what the tests lock)

- `tests/test_v322.py` (16 tests): the mirror answers a REAL IPP
  Print-Job (RFC 8010 wire form) with `successful-ok` and queues the
  job; landing page + redirect behavior; `ipp_standard_port` config
  round-trip; `/health` carries the new fields; discovery no longer
  depends on share_lan; LAN listener follows ipp_printer; AirPrint TXT
  keys; the delegated switch handler + instant-save wiring; tray-managed
  switches refuse; NO popup files + manifest has no default_popup +
  onClicked opens /ui; ZERO demo-stub menu items; all 13 real menu
  actions present; no duplicate "Save & push" buttons; LAN tab
  platform guide + live fill.
- Full suite: **318 passed, 1 skipped** (was 302 on v3.2.1).

---

# (v3.2.0 architecture reference below - still exactly how it works)

**AdvPrint Pro** by Bit Dream IT — Innovative Healthcare Solutions
The complete development process: architecture, every artifact, every
build command, from `git clone` to a deployed LAN. No prebuilt binaries
required — everything rebuilds from this tree alone.

---

## 0. What this product is (30-second map)

```
AdvPrint Pro
├── hub (Python, pure stdlib, port 9235)
│     tool/unix/hub/advprint.py          the whole hub (one file, twin copies)
│     tool/*/hub/console.html            THE ONE UI (dev copy; the hub
│                                        serves the EMBEDDED CONSOLE_HTML)
│     tool/*/hub/tool.py                 desktop tool menu [1]…[14] (14 tools)
│     tool/*/hub/tray_windows.py         Windows tray icon
│     tool/*/hub/gui_app.py              native window wrapper (loads /ui)
│     tool/*/hub/service_main.py         Windows service entry
├── extension (Chrome / Edge / Brave / Chromium / Vivaldi, MV3)
│     extension/manifest.json · background.js · options.html/js · popup
├── installer/
│     setup.nsi                          Windows Setup EXE (NSIS)
│     deb/                               Linux DEB (systemd user service)
├── tool/crx3.py                          CRX3 packer/signer (repo key)
├── extension-signing/advprint-printer.pem fixed extension id key
├── scripts/build-all.sh                  builds EVERYTHING into dist/
└── tests/                                pytest suite (301 tests)
```

Two rule that never changed:

1. **Print traffic** = extension → hub (`X-AdvPrint-Token` header) → OS
   printer (or per-printer IPP queue, or DropZone, or rules).
2. **Management traffic** = same token, same hub: `/health /stats
   /queue /printers /jobs /audit /config /debug /tool …`.

---

## 1. Development environment

| Tool | Used for | Install |
|---|---|---|
| python3 ≥ 3.9 | hub, tests, CRX3 packer, QR generator | preinstalled (Win: python.org) |
| pytest | 290-test suite | `pip install pytest` |
| zip | extension zip | `apt-get install zip` |
| dpkg-deb | DEB package | preinstalled on Debian/Ubuntu |
| NSIS 3.x (`makensis`) | Setup EXE | `apt-get install nsis` |
| Node.js ≥ 18 (optional) | JS syntax check, ONE-UI regression | nodejs.org |
| Playwright (optional) | UI screenshot / interaction checks | `pip install playwright` |

First run:

```bash
git clone https://github.com/bitdreamit/AdvPrint-Pro.git
cd AdvPrint-Pro
python3 -m pytest tests/ -q          # 290 passed, 1 skipped
python3 tool/unix/hub/advprint.py serve    # hub on http://127.0.0.1:9235
```

Run the hub against a scratch data dir while developing:

```bash
ADVPRINT_DATA=/tmp/ap-data python3 tool/unix/hub/advprint.py serve
# token: cat /tmp/ap-data/config.json | python3 -c "import json,sys;print(json.load(sys.stdin)['token'])"
```

---

## 2. THE ONE UI — how it works (v3.2.0 architecture)

### 2.1 One page, three URLs

`console.html` is a single self-contained file (CSS + HTML + JS, no
dependencies). The hub serves it on **every** browser route:

| route | served by | view |
|---|---|---|
| `GET /` | `do_GET` root branch (Accept: text/html only) | self / center |
| `GET /ui` | `do_GET` `/ui` branch | self / center |
| `GET /dashboard` | `do_GET` `/dashboard` branch | self / center |

`console_page_bytes(view)` (advprint.py) reads the file and replaces the
placeholder `<script id="bootjson" type="application/json">
__ADVPRINT_BOOT_JSON__</script>` with real JSON:

```json
{"view":"self|center","host":"AI-Lab-PC","lan_ip":"10.26.94.206",
 "port":9235,"version":"3.2.0"}
```

- `view:"self"` — the request came from loopback (the hub PC's owner).
- `view:"center"` — the request came from the LAN: the page renders the
  amber **CENTER PC UI** banner and hides the 14 system tools.
- `?view=self|center` query overrides both (previews/screenshots).
- API clients (`Accept:` not text/html) still get JSON at `/`.

The classic dashboard function `dashboard_html()` remains in the code
(tests embed it), it is simply no longer the browser answer.

### 2.2 Page anatomy (console.html)

| Block | Content |
|---|---|
| title bar | AP logo, live `tSub` = version · PC name · view |
| menu bar | 9 menus (File/View/Queue/History/Printers/Network/Hub/Tools/Help), 40+ live items |
| toolbar | New Job · Test Page · Pause Queue · History · Release ALL · LAN · DropZone · Connections · Hub · Rules · Tools(14) · Power · Debug · Settings · About |
| address bar | live hub dot + `hubUrl` + token lock + QR pill |
| center banner | amber, only in center view |
| sidebar | 218px tree, 17 panels, live count badges |
| content | 17 `<section class="panel" id="p-…">` |
| status bar | hub state · version · view · queue · printers · URL |
| modals | QR enlarge, keyboard shortcuts, rule editor, confirm |
| cards | token card + offline card (shown when needed) |

### 2.3 JS wiring (all vanilla, no framework)

```js
api(path, opts)            fetch + X-AdvPrint-Token header, 401 → token card
poll()                     /health /stats /queue /printers /jobs /audit
                           /config every 3 s → renders all panels
ACTIONS{...}               every data-act button (queue ops, exports, QR,
                           copy, rotate, restart, firewall, LAN test…)
runTool(action)            POST /tool → dark output box (status / livetest
                           steps / recent jobs / diagnose / update check)
renderRules()              central rule manager table + editor modal
SWITCH_MAP / dirtyKeys     power switches save instantly (POST /config),
                           settings switches wait for Save
openQR(kind)               real SVG from hub /qr?kind=send|invite|ipp
```

Console ↔ extension sync (background.js):

```
options/rules edited  ──push──▶  POST /config {rules_mirror, ext_api_sites}
alarm (5 min)        ◀──pull──   GET /config → adopt rules_mirror ONLY if
                                  local rules unchanged since last sync
rule fired           ──runs──▶   ruleStats.runs merged into every push
```

### 2.4 The 14 tools (parity with tool.py)

`POST /tool {"action": …}` — loopback + token only. One handler, 14
actions + `fw-allow`: start, stop, status, testprint, service-install,
service-remove, autorun-toggle, check-update, recent-jobs, uninstall,
livetest, open-dashboard, diagnose, restart. Each action maps to the
same module functions the desktop tool calls (`service_state`,
`cmd_service`, `autostart_set`, `run_livetest`, `db_list`,
`firewall_rule_ok`, …) so behaviour is identical.

---

## 3. Rebuilding every artifact

### 3.1 One command

```bash
python3 -m pytest tests/ -q      # always test first
bash scripts/build-all.sh        # → dist/ (CRX, ext zip, EXE, DEB, SHA256)
```

`build-all.sh` reads the version from `VERSION.txt`, packs + signs the
CRX3, stages `tool/windows/portable/{hub,install}` + runtime + docs,
builds the NSIS EXE and the DEB, writes SHA256SUMS.

### 3.2 CRX3 + extension zip only

```bash
python3 tool/crx3.py pack extension \
        extension-signing/advprint-printer.pem dist/AdvPrint-Pro.crx
python3 tool/crx3.py info dist/AdvPrint-Pro.crx    # verify id + 3.2.0
( cd extension && zip -r ../dist/AdvPrint-Pro-Extension-3.2.0.zip . )
```

The repo key pins the extension id `likldbkamojokkfdlcjibiljpgbbnohc`
(keep the key, keep the id — force-installed browsers auto-update from
your hub's `updates.xml`).

### 3.3 Windows Setup EXE (NSIS)

```bash
( cd installer && makensis -V2 setup.nsi )   # → dist/AdvPrint-Pro-Setup-3.2.0.exe
```

What the EXE does: bundles Python runtime (`installer/stage/runtime/`),
installs hub + console.html, registers the `AdvPrint` service, writes
the `ExtensionInstallForcelist` policy for Chrome (Chrome/Edge/Brave
variants), adds the firewall rule, starts the tray.

### 3.4 Linux DEB

```bash
dpkg-deb --build --root-owner-group installer/deb dist/advprint-pro_3.2.0_all.deb
sudo dpkg -i dist/advprint-pro_3.2.0_all.deb
```

### 3.5 Silent / multi-browser deploy (per PC)

Value line for every Chromium browser (copy from the ONE UI Extension
panel): `<ext-id>;http://<hub-ip>:9235/extension/updates.xml`

| Browser | `HKLM\SOFTWARE\` path |
|---|---|
| Chrome | `Google\Chrome\ExtensionInstallForcelist` |
| Edge | `Microsoft\Edge\ExtensionInstallForcelist` |
| Brave | `BraveSoftware\Brave-Browser\ExtensionInstallForcelist` |
| Chromium | `Chromium\ExtensionInstallForcelist` |
| Vivaldi | `Vivaldi\ExtensionInstallForcelist` |

Registry commands (admin cmd):

```bat
reg add "HKLM\SOFTWARE\Google\Chrome\ExtensionInstallForcelist" /f /v 1 /t REG_SZ /d "likldbkamojokkfdlcjibiljpgbbnohc;http://10.26.94.206:9235/extension/updates.xml"
reg add "HKLM\SOFTWARE\Microsoft\Edge\ExtensionInstallForcelist" /f /v 1 /t REG_SZ /d "likldbkamojokkfdlcjibiljpgbbnohc;http://10.26.94.206:9235/extension/updates.xml"
```

Policy install is silent and never shows the “not listed in the Chrome
Web Store” warning. Drag-in installs (chrome://extensions, developer
mode) always show that warning — the policy is the fix.

---

## 4. Release checklist (the exact v3.2.0 process)

1. `VERSION.txt` → `3.2.0` (single source; NSIS + deb + CRX read it).
2. `advprint.py`: `VERSION`, `VERSION_NAME` (twin copies stay identical
   — `cp tool/unix/hub/advprint.py tool/windows/portable/hub/`).
3. `extension/manifest.json` version; options/popup ver chips.
4. `installer/setup.nsi` OutFile/VIProductVersion/DisplayVersion.
5. Tests: pin updates (`tests/test_hub_v2.py` version anchors) + new
   feature tests (`tests/test_one_ui_v320.py` for v3.2.0).
6. `python3 -m pytest tests/ -q` → all green.
7. `bash scripts/build-all.sh` → dist artifacts + SHA256SUMS.
8. `docs/RELEASE-NOTES-v3.2.0.md` + `CHANGELOG.md` entry.
9. Git: `git add -A && git commit -m "v3.2.0 THE ONE ALL-IN-ONE UI
   EVERYWHERE" && git tag v3.2.0 && git push --tags`.
10. GitHub Release → upload CRX, ext zip, EXE, DEB, SHA256SUMS.

---

## 5. Where things live (code map, v3.2.0)

| Change | File | Place |
|---|---|---|
| one-UI on / · /ui · /dashboard | `tool/*/hub/advprint.py` | `_do_get_impl`: root branch (Accept: text/html), `/ui`, `/dashboard`; helper `console_page_bytes()` |
| self/center detection | same | each route: `self._is_loopback()` + `?view=` override |
| 14 tools API | same | `do_POST` → `route == "/tool"` |
| rule mirror validation | same | `POST /config` list branch, `key == "rules_mirror"` |
| config keys | same | `CFG` defaults + `CONFIG_KEYS` + `CONFIG_TYPES` |
| ONE UI page | `tool/*/hub/console.html` | whole file (CSS → HTML → JS) |
| whitelist default `*` | `extension/background.js` | `DEFAULTS.apiSites`, onInstalled migration |
| rules sync / runs | same | `HUB_SYNC_ALARM` block + `bumpRuleStats` |
| policy per browser | `tool/*/hub/console.html` | Extension panel table |
| desktop 14 tools | `tool/*/hub/tool.py` | unchanged (menu parity) |

## 6. Local verification workflow (how every release is UI-checked)

```bash
python3 tool/unix/hub/advprint.py serve &                 # real hub
# browser:
#   http://127.0.0.1:9235/ui          → SELF PC UI
#   http://127.0.0.1:9235/ui?view=center → CENTER PC UI banner + note
#   http://127.0.0.1:9235/dashboard   → same ONE UI
#   http://127.0.0.1:9235/            → same ONE UI (browser)
# then: pytest suite + build-all + smoke print via POST /print
```

Playwright screenshot recipe (used for the release previews):
navigate each panel id (`#p-dashboard`, `#p-queue`, …, `#p-tools`),
click a menu, open the QR modal, press Ctrl+2 — assert no horizontal
overflow and no JS pageerror.

---

*by Bit Dream IT — Innovative Healthcare Solutions · full source, A-to-Z
rebuildable, 290 tests green.*
