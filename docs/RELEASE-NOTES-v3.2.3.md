# Release Notes - AdvPrint Pro v3.2.3
**CLEAN UI, ONE BUTTON + EVERY SWITCH VERIFIED + ALLOWED IPS**
by Bit Dream IT - Innovative Healthcare Solutions · 2026-11-10 · MIT license · 100% local

Base: v3.2.2 — every feature unchanged. v3.2.3 delivers exactly what was
asked after the v3.2.2 rollout: the same UI with the duplicated buttons
reduced, the extension page reduced to branding only, and a new
Allowed-IPs feature for the center PC/hub. The live switch test also
caught (and this release fixes) a REAL bug: the Hub-tab switches never
saved.

> GitHub note: release tag `v3.2.1.1` on the repo is actually a
> previous v3.2.2-era build. **v3.2.3 is the first release with the
> clean UI, the verified switches and Allowed IPs — publish it as the
> latest release.**

---

## 1. "Any togol not work" — FIXED FOR REAL (Hub-tab switches never saved)

The v3.2.2 pre-flight only clicked a **Power** switch in a browser —
Power/Browser switches worked, so the release shipped. A full
switch-by-switch verification for v3.2.3 caught the real defect:

**Root cause (two bugs stacked):**

1. The Hub panel posts `escpos_codepage` + `thermal_text_engine` with
   every switch save — but those two keys were missing from the hub's
   accepted-config-types list. POST /config answered
   `400 unknown config key` and the WHOLE save was rejected: none of
   the Hub switches (hold offline, instant auto-queue, strict header,
   watermark, reason required, audit, keep files) ever persisted.
2. The Hub panel only refreshed from the live config when you OPENED
   the tab — never on the 3 s poll — so its inputs kept the static
   demo values (`C:\Users\Admin\Documents\Reports`, a fake SumatraPDF
   path), which a first save would have written into config.json.

**Fixed in v3.2.3:**

- `escpos_codepage` (validated `^[a-z0-9_-]{1,24}$`) and
  `thermal_text_engine` (validated `auto|builtin|browser`) are accepted
  server-side.
- The Hub panel refreshes from the live config on EVERY poll.
- File paths are saved only when actually changed — demo placeholders
  can never reach config.json again.
- **Verified end-to-end in a real browser:** Power switch 0, Browser
  switch 0, Hub switch 0 and the Settings LAN switch are clicked, the
  POST /config body is captured, /config is re-read server-side, and
  the page is fully reloaded — every switch keeps its new state after
  reload (`scripts/switch_verify_v323.py`).

## 2. "same button different area reduce" — ONE UI, ONE BUTTON

Everything on screen now appears exactly once:

| Surface | Before (v3.2.2) | v3.2.3 |
|---|---|---|
| Toolbar | 14 buttons — 10 of them tab-navigation duplicates of the sidebar | **4 real actions**: New Job · Pause Queue (flips to Resume) · Release ALL · Test Page + live chips **LAN — ON** and **IPP — READY** |
| Address bar | 5 pill buttons (QR codes, Send Portal, Connections, DropZone, THE ONE UI) | only the URL + token lock — QRs live in the Network menu and LAN tab |
| Dashboard | Quick-actions card with 6 sidebar duplicates, Test Page twice, Open Printers | removed — dashboard keeps Refresh only |
| Sidebar | 17 tabs | unchanged — **the only tab switcher** |
| Menus | unchanged | unchanged (hidden until clicked, keyboard shortcuts kept) |

## 3. NEW FEATURE: Allowed IPs — who may reach this hub

**LAN Sharing → Allowed IPs** (a new card between Sharing status and
Scan & connect):

- Factory default `["*"]` — **every device on this LAN** may connect,
  exactly like every previous version.
- The moment you add real entries, **ONLY those may connect**:
  - exact IP — `10.26.94.100`
  - CIDR subnet — `10.26.94.0/24`
  - simple wildcard — `10.26.*`
- Enforcement is total and immediate (no restart):
  - ONE UI console + send portal + hub API → branded **403 access
    denied** page (JSON for API clients),
  - IPP printing on **9235** and the **631** standard-port mirror → 403,
  - **RAW 9100** → connection closed instantly,
  - every denial is audited (`acl.denied`, max 1 row / 10 s / IP).
- The hub PC itself (`127.0.0.1`) is **ALWAYS** allowed — the owner can
  never lock themselves out; an emptied list falls back to `["*"]`.
- The card shows the mode chip (ALL LAN (*) vs RESTRICTED — N IPs), the
  live list with one-click remove (×), **Add IP** + **Allow ALL (*)**
  buttons and an Enter-to-add input.
- `/health` now reports `allowed_ips` + `acl_restricted`.
- Config key: `allowed_ips` (list, default `["*"]`) — editable via
  POST /config and visible in config.json.

## 4. Extension page = branding only

- The extension options page is now a **brand card only**: gradient
  bar, logo block, status line, and the footer
  **"100% local · no cloud. AdvPrint by Bit Dream IT - Innovative
  Healthcare Solutions."**
- No Console/Dashboard/Debug/API buttons — every option lives in THE
  ONE UI. The card auto-opens the console when the hub answers (and on
  click); a token field appears only if the hub refuses the saved
  token.
- The toolbar-icon click keeps opening the console directly (the popup
  stays gone since v3.2.2).

---

## Everything from v3.2.2, unchanged

- Both IPP URL styles — `ipp://ip:9235/ipp/print` and
  `http://ip:9235/ipp/print` — plus the **631 standard-port mirror** for
  Android's Default Print Service / Mopria.
- mDNS/AirPrint-grade discovery (`_ipp._tcp`, `_universal._sub._ipp._tcp`)
  so the printer appears by itself on Windows 10/11, macOS, iPhone/iPad
  and Android.
- Working Power/Browser switches mirrored to paired browsers, real
  actions on all menu items, no extension popup.

## Files in this release

| File | What |
|---|---|
| `AdvPrint-Pro-Setup-3.2.3.exe` | Windows installer (NSIS, portable Python runtime inside) |
| `advprint-pro_3.2.3_all.deb` | Linux DEB |
| `AdvPrint-Pro.crx` | Chrome extension (CRX3) |
| `AdvPrint-Pro-Extension-3.2.3.zip` | Extension source zip (unpacked install) |
| `AdvPrint-Pro-v3.2.3-FULL.zip` | Everything: hub, extension, docs, tools |
| `SHA256SUMS-3.2.3.txt` | Checksums for all of the above |
