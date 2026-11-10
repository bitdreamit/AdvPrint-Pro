# Release Notes - AdvPrint Pro v3.2.1

**"THE APPROVED UI - NOW THE REAL PRODUCT"**

Base: v3.2.0 - every feature ships unchanged. This release replaces the
v3.2.0 console face with the **customer-approved rev-4 All-in-One design**
(`AdvPrint-Pro-AllInOne-UI-Design-v3.1.3-4.html`) and closes the release's
feedback points. by **Bit Dream IT - Innovative Healthcare Solutions**.

---

## 1. The approved rev-4 design IS the product UI

- **THE UI IS NOW EMBEDDED IN advprint.py ITSELF** (`CONSOLE_HTML`):
  the Windows Setup EXE of the first v3.2.1 build did not pack
  `console.html` into the install folder, so on those installs
  `http://127.0.0.1:9235/` fell back to the OLD classic dashboard and
  the tray pointed at a missing file ("console.html was not found next
  to advprint.py"). The hub now carries the ENTIRE All-in-One UI inside
  `advprint.py` - no external file can ever go missing again, and `/`,
  `/ui`, `/dashboard` ALWAYS answer with the approved rev-4 UI.
- `console.html` is now **byte-for-byte the approved rev-4 markup + CSS**:
  38px blue-gradient title bar with logo, **9 working menus** (File, View,
  Queue, History, Printers, Network, Hub, Tools, Help), glossy toolbar,
  address bar with live hub URL + token badge, **218px sidebar tree** with
  live counters, 24px status bar, animated striped progress bars,
  Cascadia/Consolas mono, design tokens `--navy #1e3a8a / --blue #1d4ed8`.
- **17 tabs**: Dashboard, Queue, History, Printers, LAN Sharing,
  Connections, Hub, DropZone, Rules, Power Switches, Browser Behavior,
  Extension, Debug & Tools, Audit, Logs, Settings, About.
- The demo script of the design was swapped for the production wiring -
  every value on every tab is now **live hub data** (poll every 3 s):
  jobs, printers, rules, audit, logs, peers, DropZone, tokens, QR codes.

## 2. One endpoint - all UIs in one URL

- **`http://127.0.0.1:9235` = everything.** `/`, `/ui` and `/dashboard`
  serve the SAME page (verified byte-identical). No options.html, no
  separate dashboard URL.
- **SELF PC UI vs CENTER PC UI** (unchanged semantics, new face): the
  owner on 127.0.0.1 gets the full console; a LAN PC gets the same
  console with the amber CENTER banner (queue, history, rules and IPP
  work there; the 14 system tools stay on the center PC).
- The extension **Options page now opens `http://127.0.0.1:9235`
  directly** - one click from Chrome and you are in the ONE UI. A token
  fallback is shown only when the hub is offline.

## 3. Rule editor (rev-4 modal) - live

- The rev-4 rule editor is fully wired: Match by URL / page content /
  type, printer picker (built from the LIVE printer list), what to
  print (auto / whole page / selection / raw ZPL-ESC-POS / linked PDF),
  copies, paper, color, duplex, schedule, priority, On + Auto switches.
- The hub's `rules_mirror` now keeps all rev-4 fields
  (`auto`, `sched`, `priority`, `content`, `color`, `duplex`) so the
  extension adopts exactly what you edited. Every rule row has
  **Edit + Delete** (two-step confirm) and live **runs counters**.

## 4. Extension tab - silent CRX install for EVERY Chromium browser

- Policy table for **Chrome, Edge, Brave, Vivaldi, Chromium, Opera** -
  one row per browser with the exact `ExtensionInstallForcelist` path.
- New hub tool `POST /tool {"action":"policy-install","browser":...,
  "hive":"HKCU|HKLM"}` writes the forcelist value (reuses the v3.2.0
  policy helpers; HKCU needs no admin, HKLM asks for elevation).
- The Chrome "not listed in the Web Store" banner is explained in the
  UI itself, exactly as in the approved design.
- Website API whitelist defaults to `*` (ALL websites may print) -
  editable in Connections, mirrored to paired browsers.

## 5. The 14 tools - all present, nothing extra

Debug & Tools now injects the **complete desktop-tool menu** as a grid:
start / stop / status / test page / service install / service remove /
autostart ON-OFF / check for updates / recent jobs / uninstall /
LIVE TEST / open dashboard / diagnose / restart - each one a POST /tool
call (loopback + token). Menus carry the same actions.

## 6. Real QR codes

The LAN tab tiles + the enlarge modal render REAL QR codes served by
the hub (`/qr`), now including **kind=hub** (the console URL itself,
token embedded) next to send / invite / IPP.

## 7. Bug fixes carried into v3.2.1

- Options page duplicate "Default printer" entries - gone with the old
  options UI (the ONE UI builds the picker from live data).
- Test suite re-pointed at the new UI: **301 tests pass**
  (`tests/test_one_ui_v321.py` locks the rev-4 contract).

## 8. Packages

- `AdvPrint-Pro.crx` v3.2.1 (same stable ID
  `likldbkamojokkfdlcjibiljpgbbnohc`), served by the hub at
  `/extension/AdvPrint-Pro.crx` with `updates.xml` auto-update.
- `AdvPrint-Pro-Setup-3.2.1.exe` (NSIS, embeddable Python), 
  `advprint-pro_3.2.1_all.deb`, source + docs in the FULL zip.
- How to build every artifact yourself: `docs/BUILD-FROM-SOURCE.md`.
