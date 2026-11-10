# Release Notes - AdvPrint Pro v3.2.2
**EVERY IPP PATTERN + WORKING SWITCHES + NO POPUP**
by Bit Dream IT - Innovative Healthcare Solutions · 2026-11-10 · MIT license · 100% local

Base: v3.2.1 — every feature unchanged. v3.2.2 fixes exactly what was
reported on v3.2.1: the IPP printer URL "missing", Android failing to
connect in every documented way, UI switches dead on click, duplicate
buttons, and the unnecessary popup.

---

## 1. "both all ipp pattern need access able" — FIXED

Every IPP URL style now answers on this hub:

| Pattern | Where | Status |
|---|---|---|
| `ipp://10.26.94.206:9235/ipp/print` | hub port | worked in 3.2.1 engine, landing page now shows BOTH URLs |
| `http://10.26.94.206:9235/ipp/print` | hub port | same engine (Windows "IPP Device", macOS IP tab) |
| `http://10.26.94.206/ipp/print` (port **631**) | **NEW standard-port mirror** | the same IPP engine bound to the standard printer port |
| `ipp://10.26.94.206:9235/ipp/print/<printer>` | per-printer queue | unchanged (one mDNS service per printer too) |

Why the 631 mirror exists: **Android's Default Print Service / Mopria
ignores custom ports on manual add.** You type the IP, Android builds
`http://<ip>:631/ipp/print` — port 9235 alone can never answer that.
v3.2.2 mirrors the endpoint on 631 (config `"ipp_standard_port": 631`,
`0` = off). Windows needs no admin for port 631; on macOS/Linux a
refused bind only disables the mirror and is logged (`[IPP631]` in
hub.log). The installer adds the TCP 631 firewall rule. The mirror
serves ONLY the IPP endpoint — every other path redirects to the hub
port, so nothing new is exposed.

## 2. "in android it not success to connect any of given" — FIXED

Root causes, both fixed:
1. **No auto-discovery path Android could use**: the mDNS/Bonjour
   responder only ran while **LAN sharing** was ON. v3.2.2 decouples
   discovery from LAN sharing — **IPP printer mode owns it**. The
   announce is unchanged and AirPrint-grade (`_ipp._tcp` +
   `_universal._sub._ipp._tcp`, TXT `rp=ipp/print`, `pdl`, `URF`,
   `UUID`, `usb_MFG`/`usb_MDL`, one extra service per local printer).
2. **Manual add tried port 631** → the new mirror answers it (above).
   Auto-discovery (Mopria) also works again because the hub now
   advertises itself as soon as IPP printer mode is on.

Bonus correctness fix: **IPP printer mode now starts the LAN listener
by itself** (a loopback-only hub cannot accept phone jobs). Turning
off both *IP Printer mode* and *LAN sharing* stops it again — checked
live every 3 s, no restart needed.

Result: the printer appears **by itself** in Windows 10/11
Settings → Printers → Add device, the macOS Bonjour list, the iOS
AirPrint picker and Android Default Print Service / Mopria.

## 3. "Any togol not work" — FIXED

v3.2.1 rendered every switch but clicking one only set a hidden dirty
flag — it did not move and nothing was saved. v3.2.2 ships one
delegated handler for the whole console:

- **Power Switches** and **Browser Behavior** → saved into
  `ext_prefs` instantly; every paired Chrome/Edge adopts the change
  within a minute (the extension pulls the mirror).
- **Hub panel** switches → `/config` (same patch as *Apply*).
- **Settings panel** → `/config`; *Start with Windows* and *Minimize
  to tray* remain service/tray-managed and refuse with a hint.
- **DropZone** delete-after-print → `drop_delete`, straight to the hub.
- **Rule editor** On/Auto toggles flip and are saved with the form.
- Fast flips are debounced (400 ms = one write); every save clears its
  dirty flags so the 3 s poll refreshes again.

## 4. "popup also no need" — REMOVED

- `popup.html` / `popup.js` deleted; the manifest no longer opens a
  popup.
- **Clicking the toolbar icon opens the console**
  `http://127.0.0.1:9235/ui` (paired token appended automatically).
  The popup was a second, weaker copy of the same console — one UI now.
- Extension error messages point to the Console / Power Switches.

## 5. UI cleanups

- The two duplicate **"Save & push to browsers"** buttons are gone —
  the switches save instantly (toasts confirm).
- Dashboard quick-actions strip = navigation shortcuts only (REAL test
  print / Release ALL held / Full self-test stay in their home tabs).
- DropZone has ONE *Open folder* button.
- **All 13 demo-stub menu items now fire their real actions** (export
  CSV, clear finished, copy hub URL, firewall, LAN test, restart,
  rotate token, service install, update check, real test print,
  quick-start guide, GitHub) and any menu choice closes the dropdown.
- **LAN tab**: live-filled `ipp://` + `http://` URLs with copy buttons
  and QR, live status chips for *AirPrint/mDNS discovery* and
  *Standard IPP port 631* (from `/health` → `ipp_mdns_up`, `ipp_std`),
  plus the full per-platform add-printer guide (Windows 10/11, macOS,
  iPhone/iPad, Android — including the 631 note).

## Upgrade

Replace the files (installer / deb / CRX all in one), same token, same
config, same data. New config key: `"ipp_standard_port": 631`.

## Validation

- 318 pytest tests green (16 new v3.2.2 tests: the mirror answers a
  real IPP Print-Job with `successful-ok`, the landing page, the
  redirect, config round-trip, health fields, discovery decoupling,
  switch wiring, no popup, no demo stubs, menu actions).
- Live probes: `/ipp/print` GET + POST on the hub port AND the mirror;
  boot JSON injected; 17 panels rendered.
