# RELEASE NOTES - AdvPrint Pro v2.9.0
**AdvPrint Pro (Advanced Printer) - by Bit Dream IT - Innovative Healthcare Solutions**
MIT license - 100% local - no cloud, no tracking - 2026-11-04

Base: v2.8.2 ("it work fine"). Nothing removed - every v2.8.x feature
(LAN sharing live rebind, firewall one-click, send-portal QR, one-click
invite, DropZone, two hub profiles) is unchanged.

---

## 1. NEW: Network printer mode - add this PC like a real IP printer

This is the "Windows add device → IP + port" feature. The hub now
speaks the two protocols a network printer speaks, so ANY Windows PC or
phone print app can add this PC as a printer and print into it - the
hub manages the jobs and prints them on the hub PC's real printer.

### Way A - IPP printer URL (easiest, no extra port)

```
http://<this-PC-IP>:9235/ipp/print
```

- **Windows 10/11:** Settings → Bluetooth & devices → Printers &
  scanners → Add device → **Add manually** → *"Select a shared printer
  by name"* → paste the URL. Windows installs it with the built-in
  **Microsoft IPP Class Driver** - no driver download.
- **Phones:** print services that accept a manual IPP address (e.g.
  Samsung Print Service) can add the same URL.
- IPP rides the SAME port as the hub, so **no extra firewall rule**.
- Opening the URL in a normal browser shows a short how-to page.
- No token on IPP - it is a printer protocol (like a physical network
  printer). It only accepts print data, is size-bounded, audited with
  the source IP, and can be switched off with `"ipp_printer": false`
  in config.json.

### Way B - classic TCP/IP printer port (JetDirect RAW, port 9100)

- The hub listens on **TCP 9100** (config `raw_printer_port`, 0 = off)
  bound to the PC's LAN IP whenever LAN sharing is ON.
- **Windows:** Add printer → "The printer that I want isn't listed" →
  **Add a printer using TCP/IP address** → IP = this PC, port 9100,
  device type **Generic Network Card** (RAW) → pick the driver of the
  REAL printer. Windows renders any file (Word, Excel, photos, web
  pages) with that driver and streams the print-ready bytes to the hub,
  which passes them to the real printer.
- ESC/POS / ZPL apps (label/receipt) can open the same raw socket.
- Follows LAN sharing: stops when sharing is off, rebinds itself when
  the router gives the PC a new IP, never binds 0.0.0.0.

### What the hub does with the bytes (both ways)

| Payload | Routed to |
|---|---|
| `%PDF` | the normal PDF pipeline (SumatraPDF/Edge, History, audit, reprint) |
| JPEG photo | wrapped into a single-page PDF, then printed |
| `%!PS` (PostScript) | RAW passthrough to the selected Windows queue |
| PCL / ESC / POS | RAW passthrough |
| `^XA...^XZ` (ZPL) | RAW passthrough (label printers) |

The dashboard LAN card shows both rows (URL + copy + QR for IPP, port +
status + "How to add" for RAW). `GET /qr?kind=ipp` renders the printer
URL as a QR code. The one-click **Allow in firewall** now opens ONE UAC
prompt and adds both rules (hub port + 9100).

## 2. NEW: Print destination - ANY printer (default / selected / IP printer)

The hub does not just RECEIVE jobs like an IP printer - it also
decides where they print. The new **Print destination** dashboard card
(config `dest_mode` / `ip_printer_host` / `ip_printer_port` /
`ip_printer_proto`) offers ANY printer:

- **default** - the OS default printer (the classic behaviour).
- **selected** - ANY installed printer, picked from the live list.
- **ip** - an upstream IP printer: a real network printer at IP:port,
  spoken with **JetDirect RAW** (stream the bytes) or **IPP
  Print-Job** (`/ipp/print`, `application/pdf`, `copies` supported).

How it fits the IP-printer feature: a phone or PC that added THIS hub
as their network printer prints through exactly this destination - one
setting routes everything. A per-job `printer` name (API, extension,
groups) always wins.

The queue honours the destination everywhere:

- the hold check probes the IP printer's reachability ("IP printer
  x.x.x.x:9100 is unreachable - job held") instead of a local printer;
- the virtual-PDF-printer save path never hijacks an IP-routed job;
- the instant (queue-off) path routes the same way;
- audits and the History tab name the real destination.

`POST /ip-printer/test` checks reachability + latency (also the
**Test** button in the card). `/health` reports `dest_mode`,
`dest_display`, `ip_printer` and the derived **`ip_printer_mode`**
flag. The LAN card shows **IP Printer mode: ACTIVE** in one row
("every PC or phone adds this PC as their network printer -> jobs
print to ...").

## 3. FIXED: phone "Auth fail" on the Send portal QR

Reported: scanning the Send-portal QR with ANY phone opened the portal,
but after picking a PDF it answered *"invalid or missing token"*
("Auth fail") - while PC-to-PC kept working.

Root cause: with `token_header_only: true` (a security option), POST
`/send` accepted the token ONLY from the `X-AdvPrint-Token` header -
which a phone browser cannot send. The extension (header) worked, every
phone (query token from the QR link) failed.

Fix in v2.9.0: `/send` POST now accepts the token from the query/body -
the same shared QR-link transport the portal GET always used. The token
is still REQUIRED and still compared with `hmac.compare_digest`; every
other endpoint stays header-strict. The portal also appends the token
as a hidden form field (survives QR apps that mangle URLs), and a wrong
token now answers with a clear phone-friendly message ("re-scan the
fresh QR code from the dashboard").

## 4. NEW: one version everywhere in the extension

The popup badge, the Options header chip and the About panel all show
the version read live from `chrome.runtime.getManifest().version`. The
manifest is the single source of truth - the old hardcoded HTML copies
(stuck at 2.8.0 in some places) can never drift again. Hub version and
extension version ship in lockstep (2.9.0).

## 5. NEW: smooth tray menu

Every tray action now runs on its own thread - Open dashboard, Print
test page, Pause queue, Start at logon, Restart hub, Allow LAN in
firewall. Before, a slow action (browser launch, printer-status WMI,
the UAC prompt) froze the tray icon and made the next right-click feel
laggy. The menu font is also cached per DPI scale instead of being
rebuilt on every right-click.

## 6. Update / install / uninstall

- Install over the old version - settings, history and the data folder
  (`~/.advprint`) are kept. The service is stopped + replaced during
  upgrade (v2.8.0 lifecycle rules apply).
- Silent install: `AdvPrint-Pro-Setup-2.9.0.exe /S`
  (elevation via the exe manifest, hub starts automatically, firewall
  rules for TCP 9235 + 9100 are added automatically).

## 7. Verification for this release

- `pytest`: **189 passed, 1 skipped** (35 new v2.9.0 tests: 14
  network-printer + 21 destination-routing).
- Live self-check (`live_selfcheck_290.py`, real hub process, fake
  CUPS): **73/73 OK** - includes the phone flow in BOTH token modes,
  IPP attribute + print (pdf/jpeg/zpl), the RAW 9100 socket print,
  share_lan on/off rebind, firewall/selftest routes, the CLI and the
  9 new destination checks (/ip-printer/test reachable + refused,
  dest_mode=ip round-trip, health dest_display, ip_printer_mode,
  END-TO-END /print -> queue -> worker -> JetDirect sink, restore).
- Files: `AdvPrint-Pro-Setup-2.9.0.exe`, `advprint-pro_2.9.0_all.deb`,
  `AdvPrint-Pro-2.9.0-source.zip`, `AdvPrint-Pro-2.9.0-FULL.zip`
  (everything in one bundle), Full Guide (HTML + PDF), SHA256SUMS.
