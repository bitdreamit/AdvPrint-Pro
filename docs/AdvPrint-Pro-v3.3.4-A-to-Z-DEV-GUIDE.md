# AdvPrint Pro v3.3.4 — A-to-Z DEVELOPMENT & BUILD GUIDE

> **v3.3.4 = "MULTI-PRINTER IPP ADD + POPUP PRINTER/RELOAD/NETWORK
> RELEASE" on top of v3.3.3.** Three real-world reports, all fixed and
> locked by `tests/test_v334.py`. Everything from v3.3.3 (Share Send
> popup-fix, peers online), v3.3.0 (dual-stack listeners) and earlier
> stays unchanged. The deep architecture reference lives in
> `docs/AdvPrint-Pro-v3.2.7-A-to-Z-DEV-GUIDE.md`; this guide documents
> the v3.3.4 delta.

> **BUG 1 — "only default or only one add possible" (multi-printer
> IPP add).** Windows could add the hub ONCE; adding a second,
> per-printer queue `http://ip:9235/ipp/print/<printer>` errored ("add
> again another it show error"). Root cause: the mDNS announcer stamped
> the SAME `UUID` TXT record on EVERY `_ipp._tcp` service, so Windows
> treated each per-printer queue as a re-announcement of the first one.
> Fix: every service carries its OWN stable uuid now — hub uuid for the
> central queue, per-queue uuid (`token|hostname|slug`) for each
> printer — on BOTH the proactive announce AND direct unicast TXT
> answers. The IPP endpoints (`/ipp/print/<printer>`,
> Get-Printer-Attributes / Validate-Job / Print-Job) already had
> per-queue uuids since v3.2.9; only discovery was broken.
>
> **BUG 2 — "popup reload / set printer: cmd continues to run
> multiple".** Two layers: (a) the popup's new printer selector sends
> set-default ONLY on a real user change (programmatic selection fires
> no change event; `_printerApplied` + `_settingPrinter` guards; failed
> set reverts); `refresh()` has an in-flight guard so the popup boot
> storm cannot stack duplicate hub calls. (b) `POST /printers/set-default`
> is IDEMPOTENT: if the requested printer IS already the OS default
> (10 s cached read), it answers `unchanged: true` and spawns ZERO
> commands — even a looping client cannot multiply the cmd.
>
> **FEATURE — popup as a control surface (user-approved ONE design).**
> The popup ships the new 340px ONE design (navy gradient header,
> overlapping status pill, printer selector with an inline reload
> arrow, three Power switch tiles, wide Options card, queue bar).
> PRINTER selector (hub printers + status; picking one makes it the OS
> default via the new `hubSetDefault` background message — ONE command
> per real change, nothing on popup open/reload), RELOAD arrow
> (spins, one at a time, never sends set-default), NETWORK icon in the
> header (gray = offline, green = this PC, teal-pulse = Sharing ON
> listening on the LAN; tooltip shows the LAN address from `/health
> lan_bind_addrs`; click = reload).
>
> **FEATURE — "Receive" is now "Sharing" with the connection icon.**
> The Share Receive switch is labelled **Sharing** (en + bn) and its
> icon is the network/connection icon (network nodes) — the old
> download-tray arrow is gone from that switch (Save PDF keeps its
> download icon, which is what it does). The header network icon shows
> the LAN receive state at a glance.
>
> **FEATURE — AUTOCRX: browser auto-integration is INTERNAL now.**
> No extra .bat needed: the hub runs the policy pass itself — it
> generates `advprint-activate-extension.ps1` (Forcelist + Allowlist +
> Sources for Chrome/Edge/Brave/Vivaldi/Chromium/Opera, HKLM + HKCU,
> duplicate-skip, never deletes) and executes it ONCE elevated via
> `Start-Process powershell -Verb RunAs` (a single UAC prompt), then
> reads back a JSON result. Entry points: ONE UI console Extension tab
> → **Auto-integrate (admin)**; `POST /extension/policy/activate`
> (optional `{"host": "ip:port"}` for LAN activations);
> `POST /tool` action `autocrx`; CLI `python advprint.py
> activate-extension [host:port]`. The .bat stays in prebuilt/ as an
> OFFLINE manual fallback only (and still has the fixed
> HKLM/HKCU menu).
>
> **FIXED — `prebuilt/allow_extention_advprint_pro.bat`.** The old
> script DELETED `ExtensionInstallForcelist` on every run and never
> re-wrote it, so the CRX force-install was wiped while the script
> claimed success. The rewrite writes ALL THREE policies (Forcelist +
> Allowlist + Sources) for Chrome/Edge/Brave/Vivaldi/Chromium/Opera
> with duplicate-skip, has a real menu [1]=HKLM (auto-elevates, UAC)
> [2]=HKCU (no admin) [3]=BOTH [R]=Remove [0]=Exit, accepts scripted
> args (`HKLM|HKCU|BOTH|REMOVE`), and asks once for the hub address
> (Enter = 127.0.0.1:9235, or a LAN IP for other PCs).

---

## 1. The files that must stay in sync

| File | Role |
| --- | --- |
| `tool/unix/hub/advprint.py` | the hub source of truth (VERSION 3.3.4) |
| `tool/windows/portable/hub/advprint.py` | byte-identical copy (installer + tests import THIS one) |
| `extension/*` ↔ `tool/unix/hub/extension/` | the mirror ships the signed CRX only (`AdvPrint-Pro.crx`); `scripts/build-all.sh` re-syncs it |
| `prebuilt/allow_extention_advprint_pro.bat` | v3.3.4 rewrite — policy helper with Apply HKLM/HKCU |

After editing hub code:
`cp tool/unix/hub/advprint.py tool/windows/portable/hub/advprint.py`
(md5 must match). After editing the console UI:
`python3 scripts/embed_console.py` (re-embeds `CONSOLE_HTML` into BOTH
hub copies — v3.3.4 changed the console: the AUTOCRX button).

## 2. v3.3.4 code map (delta only)

### mDNS per-service UUID — `tool/unix/hub/advprint.py`

```
_mdns_services()      -> (instance, rp, ty, note, slug) 5-tuples;
                         slug None for the central queue,
                         _ipp_queue_slug(name) per printer
_mdns_txt_records(rp, ty, note, slug=None)
                      -> TXT with UUID = _ipp_printer_uuid(slug)
                         (was: always _ipp_printer_uuid() — the shared
                          hub uuid, the cause of BUG 1)
_mdns_rrset()         -> passes the slug through
_ipp_mdns_answer()    -> instances map (rp, ty, note, slug); the
                         DIRECT unicast TXT answer also stamps the
                         per-queue uuid now
_ipp_printer_uuid(slug)  -> stable per-queue urn:uuid (v3.2.9, reused)
```

### Idempotent set-default — POST /printers/set-default

```
cur = default_printer_cached(max_age=10.0)
if cur and cur.lower() == requested.lower():
    return 200 {"ok": true, "unchanged": true, "default": cur,
                "detail": "'…' is already the OS default printer …"}
# else os_set_default_printer(name) as before (PowerShell / lpoptions)
```

### Popup v3.3.4 (ONE design) — `extension/popup.html` + `popup.js` + `background.js`

```
popup.html   navy-gradient header with <span id=netIcon> (SVG globe,
             .net/.on/.lan pulse), overlapping status pill, "Select
             printer" row: <select id=selPrinter> in .psel (printer
             glyph) + <button id=bRefreshPrinters> (reload arrow);
             3-tile Power switches (Enable / Queue / Sharing —
             swShareRxRow labelled SHARING with the network-nodes
             CONNECTION icon); wide Options card; legacy div keeps
             swShareTx/bShot/bTest alive for popup.js
popup.js     loadPrinters()        fills #selPrinter (NO command sent;
                                  programmatic select fires no change;
                                  the applied default lives in the
                                  select's title tooltip)
             selPrinter.onchange   change-ONLY set-default:
                                  same-as-_printerApplied -> return;
                                  _settingPrinter -> return (one at a
                                  time); failure reverts + msg()
             refresh()             in-flight guard (_refreshBusy) +
                                   _refreshBody() split
             renderNetIcon()       gray / green(.on) / teal(.lan pulse)
             renderShareRxState(on, reachable, listenAddr)
             reloadAll()           bRefreshPrinters + netIcon click
background.js  case "hubSetDefault" -> POST /printers/set-default
```

### AUTOCRX — internal auto-integration — `tool/unix/hub/advprint.py`

```
EXT_ACTIVATE_BROWSERS       EXT_POLICY_BROWSERS + Opera
_ext_activate_updates_url(host)
                            loopback default or host[:port] override
_ext_activate_ps_script(url, result_path)
                            the .bat apply pass as PowerShell:
                            per hive (HKLM, HKCU) x browser x key
                            (Forcelist/Allowlist/Sources) with
                            duplicate-skip (StartsWith match),
                            never deletes, writes result JSON
ext_policy_activate(host)   writes the .ps1 into data_dir, runs it
                            ONCE via Start-Process -Verb RunAs
                            (single UAC prompt), reads back the
                            JSON result -> {ok, elevated, result,
                            message, error}
POST /extension/policy/activate    body {"host": "ip:port"} optional
POST /tool action "autocrx"        (+ aliases activate-extension,
                                    policy-activate; loopback only)
CLI  python advprint.py activate-extension [host:port] | autocrx
console.html  Extension tab > "Auto-integrate (admin)" button
              -> ACTIONS.autocrx -> /extension/policy/activate
```

### Policy helper — `prebuilt/allow_extention_advprint_pro.bat` (offline fallback)

```
menu           1=HKLM (self-elevates via Start-Process -Verb RunAs)
               2=HKCU  3=BOTH  R=Remove  0=Exit
arg mode       HKLM|HKCU|BOTH|REMOVE (used by the elevation relaunch)
:OneBrowser    Forcelist = EXT_ID;http://hub:port/updates.xml
               Allowlist = EXT_ID
               Sources   = http://hub:port/*
               each with findstr duplicate-skip + free-slot scan
:NextSlot      first free numeric value name (cap 64)
hub address    asked once in menu mode; Enter = 127.0.0.1:9235
```

## 3. Config keys (unchanged in v3.3.4)

`share_lan`, `ipp_printer`, `ipp_mdns`, `ipp_standard_port`,
`drop_enabled`, `rules_mirror`, `ext_prefs`, `autostart`,
`allowed_ips` — see `docs/AdvPrint-Pro-v3.2.7-A-to-Z-DEV-GUIDE.md`.
The popup uses the existing `share_lan` (Share Receive), the
extension-side `lanSend` (Share Send) and the new `hubSetDefault`
message (printer), which maps to POST `/printers/set-default`.

## 4. Tests (tests/test_v334.py)

```
BUG 1  _mdns_services() returns 5-tuples; TXT uuid of every
       per-printer service differs from the hub uuid AND from each
       other; the direct TXT query answer carries the queue uuid too;
       2 printers -> 3 services, 3 distinct UUIDs
BUG 2  /printers/set-default answers unchanged:true with ZERO
       os_set_default_printer calls when the printer is already
       default (monkeypatched counter), and calls the setter exactly
       ONCE for a real change
POPUP  popup.js contains the change-only guard (no send when
       name === _printerApplied), background.js routes hubSetDefault,
       popup.html carries selPrinter/bRefreshPrinters/netIcon, the
       switch reads "Sharing" with the connection icon, no Receive
       label, legacy controls present
AUTOCRX the generated PS script writes all three keys in HKLM+HKCU
       for six browsers, never deletes, duplicate-skips, reports
       JSON; host override maths; off-Windows honest refusal; the
       route/tool-action/CLI/console wiring exists
BAT    the bat no longer deletes ExtensionInstallForcelist in the
       apply path and writes all three policy keys
```

Run: `cd tests && python3 -m pytest test_v334.py -x -q`
Real-browser: `python3 scripts/popup_check_v334.py` (Playwright —
change-only set-default, Sharing label, net icon classes,
screenshot `scripts/popup-v334.png`).

## 5. Build + release checklist

1. Bump: `VERSION.txt`, both `advprint.py` `VERSION = "3.3.4"`,
   `extension/manifest.json`, i18n brandLine, popup.html badge.
2. `bash scripts/build-all.sh` → dist/: CRX3 + extension zip + Setup
   EXE (NSIS) + deb + SHA256SUMS. The build hard-fails if the embedded
   CRX copies are stale or the CRX version != hub version.
3. `cd tests && python3 -m pytest -x -q` (v3.3.4 + regression).
4. Package the FULL source zip (source tree + dist/ artifacts):
   `AdvPrint-Pro-v3.3.4-FULL.zip`.
5. GitHub release v3.3.4: attach CRX, extension zip, Setup EXE, deb,
   SHA256SUMS, FULL zip; changelog from CHANGELOG.md.

## 6. Upgrade notes for users

- Upgrade = install the new Setup EXE over the old one (or replace the
  portable folder). Config/queue survive.
- Multi-printer: on each device REMOVE the previously half-added
  printer once, then add the specific queues you want — either by URL
  (`http://<hub-ip>:9235/ipp/print/<printer-name>`) or from the
  Bonjour list, where every printer now appears as its OWN entry with
  its own uuid. Windows remembers queues by uuid, so the old shared
  uuid entry should be removed first.
- Popup: new Printer dropdown = "make this the default printer"
  (one command per real change; flipping between the same printers
  costs nothing). Reload re-reads everything; the globe icon shows
  LAN sharing at a glance and is clickable.
- Extension policy: run the new `allow_extention_advprint_pro.bat`:
  option 2 (HKCU) needs no admin; option 1 (HKLM) asks via UAC. It no
  longer wipes the force-install policy.
