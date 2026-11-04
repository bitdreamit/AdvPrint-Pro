# RELEASE NOTES - AdvPrint Pro v2.9.1
**AdvPrint Pro (Advanced Printer) - by Bit Dream IT - Innovative Healthcare Solutions**
MIT license - 100% local - no cloud, no tracking - 2026-11-04

Base: v2.9.0 (network printer mode). Nothing removed - every 2.9.0 and
2.8.x feature is unchanged. v2.9.1 is one focused dashboard fix, a full
documentation refresh and clean version numbering.

---

## 1. Responsive dashboard tables - all options visible on load

The reported annoyance: wide table rows in the dashboard disappeared
into a horizontal scroll INSIDE the card, so on load you saw only part
of the columns and had to scroll (or not even know there was something
to scroll) to reach the buttons and options.

**What changed**

- Every dashboard card table now **wraps instead of scrolling**:
  LAN sharing & other PCs, Debug, Printers, Queue, Job history, Audit
  trail and the **Print destination** card.
- Cells allow wrapping again (`white-space:normal`); long job titles,
  printer names and file paths break cleanly
  (`overflow-wrap:anywhere`), so a table can never push itself out of
  the card.
- Status chips (printed / held / failed ...) stay on one line - they
  keep their pill shape.
- Action buttons (Cancel / Print now / Shift / Retry / Reprint) flow
  onto the next line instead of being cut off.
- **Print destination card**: the IP / Port / Proto fields now render
  as a wrapping flex row - they stack cleanly on narrow windows (the
  toggle switches `display:flex`, not `display:inline`).
- Phones/tablets (viewport <= 640 px): cards go 2-up, table font and
  paddings shrink, inputs never exceed their row.
- The panel-level `overflow-x:auto` was removed - there is no inner
  scrollbar any more; the page itself scrolls normally like any web
  page.

**Zero migration**: pure CSS/JS inside the hub's embedded dashboard.
Update the hub, open the dashboard, press **Ctrl+F5** once.

## 2. Full documentation refresh

- **Full Guide (HTML + PDF, 14 chapters)** updated to v2.9.1 and now
  documents the complete v2.9.x feature set end to end:
  - network printer mode - add this PC like a real IP printer
    (IPP `http://<lan-ip>:9235/ipp/print` for Windows "Select a shared
    printer by name" + phone print services; JetDirect RAW on TCP 9100
    for the classic "Add a printer using TCP/IP address" flow);
  - the **Print destination** card: OS default / any installed printer
    / upstream IP printer (RAW or IPP), Test button, held-queue
    behaviour while the IP printer is unreachable;
  - `POST /ipp/print`, `POST /ip-printer/test`, the new `/health`
    fields (`dest_mode`, `dest_display`, `selected_printer`,
    `ip_printer`, `ip_printer_mode`);
  - settings reference rows for `dest_mode`, `ip_printer_host`,
    `ip_printer_port`, `ip_printer_proto`, `ipp_printer`,
    `raw_printer_port`;
  - three new troubleshooting rows (phone "Auth fail" fix, IP-printer
    held jobs, dashboard tables cut off -> fixed in 2.9.1).
- **RELEASE-NOTES-v2.9.1.md** (this file) ships in the source zip and
  next to the downloads.

## 3. Clean version numbering (the "two 2.9.0" confusion - solved)

The v2.9.0 label was used twice (the original network-printer build
and the follow-up work), which was confusing next to the installed
2.8.2. To end that: the follow-up ships as **2.9.1** everywhere -

| Surface | Now shows |
| --- | --- |
| Hub `/health` + dashboard badge + tray + portals | v2.9.1 |
| Extension manifest / popup / Options / About | 2.9.1 (read from the manifest - single source) |
| Windows Setup exe (file name + NSIS `VIProductVersion` / `DisplayVersion`) | AdvPrint-Pro-Setup-2.9.1.exe / 2.9.1 |
| Linux package | advprint-pro_2.9.1_all.deb |
| Docs (README, CHANGELOG, VERSION.txt, START-HERE, guides) | 2.9.1 |

The CHANGELOG keeps the v2.9.0 entry for the network-printer features;
v2.9.1 = those features + the responsive-table fix + docs.

---

## Files in this release

| File | What |
| --- | --- |
| `AdvPrint-Pro-Setup-2.9.1.exe` | Windows installer (bundles Python 3.11.9, UAC once, silent `/S`) |
| `advprint-pro_2.9.1_all.deb` | Debian/Ubuntu/Mint package |
| `AdvPrint-Pro-2.9.1-source.zip` | Complete source (hub, extension, installer, tests, docs) |
| `AdvPrint-Pro-Full-Guide.html` / `.pdf` | The full A-to-Z documentation |
| `SHA256SUMS-2.9.1.txt` | Checksums for everything above |

## Upgrade

Run the new setup over the old one (2.8.2 or 2.9.0 - settings and
history are kept), or replace the portable folder. On the dashboard
press Ctrl+F5 once so the browser drops the old stylesheet. The
extension updates by Remove + Load unpacked.
