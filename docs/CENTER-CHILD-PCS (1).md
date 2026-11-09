# CENTER PC + CHILD PCs — one printing PC for the whole LAN (v3.1.2)

**AdvPrint Pro** by Bit Dream IT - Innovative Healthcare Solutions

One PC (the **Center PC**) runs the AdvPrint Pro tool (the hub). Every
other PC, phone or tablet in the LAN is a **child** and needs NOTHING
installed — the Chrome extension and/or plain IPP queues are enough.
Many child PCs connect to one center PC at the same time.

```
Center PC  ── AdvPrint Pro tool (hub, :9235) ── all real printers
   ▲   ▲                      │  ▲
   │   │ extension            │  │ IPP + mDNS (v3.0.9+)
   │   └──────────────────────┘  │
   │                             │
child PC 1      child PC 2     phones / tablets
(extension only) (extension    (AirPrint / Mopria /
 + IPP queues)    only)          any IPP client)
```

## What the Center PC does (once)

1. Install the AdvPrint Pro tool (Setup EXE or DEB).
2. Turn **LAN sharing ON** (tray → Allow LAN in firewall; Console →
   Settings → LAN sharing).
3. Keep **Per-printer IPP queues** + **mDNS** ON (Console → Settings).
4. Read the token: Console → Extension tab, or
   `python advprint.py token`.

## Child PC — way A: the extension only (2 minutes)

1. Install the AdvPrint Pro **extension** (load the CRX, or the
   force-install policy from the hub, or the extension zip).
2. Options → **Connections → Center PC / child PC mode**:
   - Mode: `Auto` (recommended) or `Center PC only` for a pure child.
   - **Center PC hub URL**: `http://CENTER-IP:9235`
   - **Center PC token**: the center's token. Save settings.
3. Done. Every print (popup, right-click, rules, window.print() hook,
   page API) goes to the center PC's hub. The status line shows
   `[auto] local tool NOT running -> printing on CENTER PC: ...`.

## Child PC — way B: per-printer IPP queues (no extension at all)

Add the center PC's printers DIRECTLY as network printers:

- **Windows 10/11**: Settings → Printers → Add device — the queues
  appear by themselves (mDNS). Or *Add manually → Select a shared
  printer by name* → paste
  `ipp://CENTER-IP:9235/ipp/print/<printer>`.
- **Linux/CUPS**: `lpadmin -p advprint-hp -E -v ipp://CENTER-IP:9235/ipp/print/HP-Laser-103-107-108 -m everywhere`
- **macOS / iPhone / Android**: discovered automatically
  (Bonjour / AirPrint / Mopria) while LAN sharing is ON.

Every local printer of the center PC gets its own queue (v3.0.9);
queue names accept the raw Windows name (URL-encoded) or the slug
form. Unknown names get a clean 404. The console **IPP Printer** tab
lists every queue URL with a Copy button.

## Both ways combined

A child PC can run the extension AND the IPP queues: the extension for
silent browser printing with rules; the IPP queues so ANY application
on the child PC (Word, AutoCAD, the OS print dialog) prints on the
center PC too.

## Version notes

- Child PC extension behavior needs **v3.1.2+** (Center Mode).
- IPP queues + mDNS need **v3.0.9+** on the center PC (any IPP client
  works regardless of client version).
- The center PC must be ON and the hub running (tray icon) — it is a
  print SERVER for the LAN.
- Firewall: inbound TCP 9235 (print) + UDP 5353 (mDNS). The Setup EXE
  adds both; `Allow LAN in firewall` (tray) re-adds TCP.
