# IPP Printer Mode - the professional guide (v3.2.2)

AdvPrint Pro (Advanced Printer) by Bit Dream IT - Innovative Healthcare Solutions

Since v2.9 the hub is also a **network printer**: any device on the LAN can
add the PC as an IPP printer exactly like a hardware printer. v3.0.8 makes
that mode professional - it fixes the "Windows couldn't connect to the
printer" failure, speaks the operations macOS/iOS/Android really use, and
announces itself over mDNS/Bonjour so phones see it **without typing any
URL**.

```
Phone / Mac / Windows / Linux
   │  (IPP over HTTP, port 9235)
   ▼
AdvPrint Pro hub  ──►  the REAL printer connected to this PC
   (queue, history,     thermal / receipt / label / A4 - everything
    pause, cancel,      the hub can already print)
    audit trail)
```

## The printer address

| What | Value |
| --- | --- |
| IPP URL (hub port) | `ipp://<this-PC-LAN-IP>:9235/ipp/print` and `http://<LAN-IP>:9235/ipp/print` - both work |
| IPP URL (STANDARD port, v3.2.2) | `http://<LAN-IP>:631/ipp/print` - the SAME endpoint mirrored on the standard printer port |
| RAW JetDirect port | `<LAN-IP>:9100` |
| Discovery | automatic via mDNS whenever IPP printer mode is ON (v3.2.2 - LAN sharing no longer required; IPP printer mode starts the LAN listener itself) |
| Auth | none (like a physical network printer) - the endpoint only accepts print data, is size-capped, audited per IP and can be turned off with `"ipp_printer": false`; the 631 mirror is `"ipp_standard_port": 0` |

Open `http://<pc-ip>:9235/ipp/print` in a **browser** and you get the
per-OS cheat sheet (it lists both ports); IPP clients POST binary IPP
to the same URL on either port.

Open `http://<pc-ip>:9235/ipp/print` in a **browser** and you get the
per-OS cheat sheet; IPP clients POST binary IPP to the same URL.

## What v3.0.8 fixed (the Windows "couldn't connect" bug)

Adding the hub in Windows via **Add a printer → IPP Device →
`http://192.168.1.7:9235/ipp/print`** failed with *"Windows couldn't
connect to the printer"*. Root cause - the v2.9 engine answered with:

1. **Wrong wire types** (RFC 8010 violations): `printer-state` sent as
   ASCII `"3"` inside a URI/charset tag instead of a 4-byte enum, booleans
   inside an enum tag, integers inside a boolean tag, `copies-supported`
   (a range) inside a boolean tag, `printer-name` inside a text tag.
2. **Missing required attributes** (RFC 8011 §4.2.5.2): no
   `printer-uri-supported`, `uri-authentication-supported`,
   `operations-supported`, `document-format-default`, `charset-configured`,
   `printer-up-time`, `printer-current-time`, `pdl-override-supported`.
3. **Missing operations**: no Create-Job + Send-Document (how macOS CUPS,
   iOS PrintKit and Android Mopria submit), no Get-Jobs /
   Get-Job-Attributes / Cancel-Job, no chunked request bodies.

Windows' strict parser (the **Microsoft IPP Class Driver**) refuses the
first mistyped attribute - every other client just got lucky. v3.0.8
rebuilds the wire layer byte-exact (verified against CUPS' `cups/ipp.h`)
and answers the full required attribute set **plus both URI schemes**
(`http://...` for Windows, `ipp://...` for macOS/iOS/CUPS).

## Add the printer - per OS

### Windows 10 / 11

**Way A (discovery - v3.0.8):** Settings → Bluetooth & devices →
Printers & scanners → **Add device** → "AdvPrint Pro @ <pc-name>"
appears in the list → Add it. (Needs LAN sharing ON; the driver shows as
*Microsoft IPP Class Driver*; discovery needs inbound **UDP 5353** - the
Setup exe adds the rule, portable installs can add it once:

```bat
netsh advfirewall firewall add rule name="AdvPrint Pro mDNS" dir=in action=allow protocol=UDP localport=5353
```

**Way B (manual URL):** Add device → **Add manually** → *Add a printer
using an IP address or hostname* → Device type **IPP Device** →
address `http://<pc-ip>:9235/ipp/print` → Next. (Alternatively paste the
same URL under *Select a shared printer by name* - both work in 3.0.8.)

### macOS

System Settings → Printers & Scanners → **Add Printer, Scanner, or
Fax** → the hub appears in the Bonjour list. Or the **IP** tab → Protocol
**IPP** → Address `<pc-ip>:9235` → Queue `ipp/print` → Use **Generic /
IPP Everywhere** or let macOS pick *AirPrint*.

### iPhone / iPad (AirPrint)

Open anything printable (Safari page, Photos, Files PDF) → Share →
**Print** → **Select Printer** → "AdvPrint Pro @ <pc-name>" appears by
itself while the phone is on the same Wi-Fi and LAN sharing is ON.
Prints land in the hub queue and print on the PC's real printer.

### Android

Print from any app (Chrome menu → Print, Gmail, Photos) → choose
**Default Print Service** (or Mopria / OEM service) → "AdvPrint Pro"
appears in the list (mDNS discovery - v3.2.2 runs it as soon as IPP
printer mode is on).

**Manual add - the v3.2.2 fix:** Android's Default Print Service
IGNORES custom ports when you add a printer by IP: it always builds
`http://<ip>:631/ipp/print`. Since v3.2.2 the hub MIRRORS the IPP
endpoint on port 631, so manual add by IP just works. If your network
blocks 631, set `"ipp_standard_port"` to a free port - but note that
stock Android will still try 631 first, so keep 631 reachable when
possible.

### Linux desktops

`lpadmin -p AdvPrint -E -v ipp://<pc-ip>:9235/ipp/print -m everywhere`
(GUI: Print Settings → Add → Network Printer → Enter URL - AppSocket/IPP).

## Operations the hub now speaks

| IPP operation | Used by |
| --- | --- |
| Get-Printer-Attributes | every OS when adding the printer |
| Print-Job | Windows IPP Class Driver, Android Mopria |
| Create-Job + Send-Document | macOS CUPS, iOS PrintKit, Linux CUPS |
| Validate-Job | CUPS before submitting |
| Get-Jobs / Get-Job-Attributes | OS print queue dialogs |
| Cancel-Job | "cancel" in any print dialog |
| Print-URI | kiosk / automation flows (SSRF-guarded) |

Document formats accepted: `application/pdf` (preferred by every OS -
printed natively), `image/urf` (iOS AirPrint raster), `image/jpeg`,
`text/plain`, `application/octet-stream` (raw ESC-POS/ZPL/PCL
passthrough), `image/pwg-raster` accepted on request.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| Windows: "couldn't connect" (3.0.7 or older) | **Update to 3.0.8** - this exact bug is fixed |
| Printer not discovered on phones | IPP printer mode ON (v3.2.2: it alone starts discovery); phone on same Wi-Fi (guest Wi-Fi isolation blocks mDNS); Windows firewall allows UDP 5353 |
| Android manual add fails | it tries port 631 - keep the mirror on (`"ipp_standard_port": 631`) and allow inbound TCP 631 (the Setup exe adds the rule) |
| Discovery works, print fails | AP/router "client isolation" or VPN on the phone; test the manual URL way |
| Windows adds it but jobs hang | the PC must be awake and the hub running (tray icon); check the hub History tab for the job |
| "ipp_mdns" noise on a big network | set `"ipp_mdns": false` in config.json - manual URL printing keeps working |
| Turn the network-printer mode off entirely | `"ipp_printer": false` (and `"raw_printer_port": 0`) |
