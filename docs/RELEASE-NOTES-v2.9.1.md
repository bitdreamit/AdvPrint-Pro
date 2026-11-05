# RELEASE NOTES - AdvPrint Pro v2.9.1
**AdvPrint Pro (Advanced Printer) - by Bit Dream IT - Innovative Healthcare Solutions**
MIT license - 100% local - no cloud, no tracking - 2026-11-05

Base: v2.9.0 (network printer mode). Nothing removed - every 2.9.0 and
2.8.x feature is unchanged. v2.9.1 = the responsive dashboard fix, the
full documentation refresh, clean version numbering AND the complete
security-hardening pass (27 verified findings from the independent
code audit - every HIGH/MEDIUM/LOW item fixed, see section 4).

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

## 4. Security & reliability hardening (the audit pass - 27 findings fixed)

An independent code audit of the v2.9.1 tree was verified finding by
finding (7 findings reproduced live against a running hub, 27 of 28
confirmed real) and EVERY confirmed finding is fixed in this release.
The hub and the extension were hardened as follows.

**Print integrity (silent wrong/missing prints)**
- **Job file collisions (HIGH).** Job payloads are now written with a
  random suffix and an exclusive create - a double-click producing two
  identical jobs in the same second can no longer overwrite the first
  job's file, and the duplicate-blocker runs BEFORE the file is saved
  (the old order could delete the original job's payload) and is
  serialized by a process-wide lock.
- **Headless-render temp files (HIGH).** Every page/HTML render gets
  its own temp directory (no more PID-named files shared between
  concurrent requests), correct `file:` URLs (paths with spaces or `#`
  work), a 2-render concurrency limit, and the whole browser process
  tree is killed on timeout.
- **Cancel vs printer-group fallback (MED).** Cancel now stops the
  group fallback loop immediately and a print that finishes after
  Cancel keeps the "canceled" verdict (no silent overwrite). Instant
  (Queue Mode OFF) jobs resolve printer groups like the FIFO worker.
- **Duplicate printing on retry (MED).** RAW/ESC-POS jobs and
  "printer did not respond" timeouts no longer auto-retry - a raw
  stream may already be half-printed, and a timeout usually means the
  paper IS in the tray. They land in the dead-letter list for a
  one-click manual reprint instead.
- **Peer forwarding only on real failure (MED).** Jobs are forwarded
  to a peer PC only when the printer reports offline / paper-out /
  error - never on the "unknown" state (group names, unlisted
  printers). Dead peers get a 60 s skip cache.
- **RAW 9100 listener (MED).** Oversized payloads are rejected whole
  (no more silent truncated prints), connections are capped at 8, and
  printer-language passthrough (PCL/PostScript/ZPL/ESC-POS) is now
  ENQUEUED - it gets a history row, pause/cancel/reprint and the
  Print-destination routing.
- **Atomic settings apply (MED).** `POST /config` validates everything
  first and applies once - a rejected key can no longer leave
  memory/disk half-updated. `peer_hubs` entries survive as real
  objects (they were stringified into garbage before) and printer
  groups are validated.

**Network hardening**
- **Host-header allowlist (HIGH).** DNS-rebinding pages that point
  their own domain at 127.0.0.1 get **421** - the hub answers only to
  127.0.0.1 / localhost, its LAN IP and hostname, `.local` names and
  private IP literals.
- **IPP + CORS (HIGH).** The raw IPP endpoint refuses browser `Origin`
  requests (native IPP clients never send one) and the
  `Access-Control-Allow-Private-Network` preflight answer is now
  emitted only for origins that are actually allowed.
- **SSRF guards (HIGH).** `page_url` now runs the same private-address
  guard as `pdf_url` (file:// and internal hosts -> 400), and
  `pdf_url` re-checks EVERY redirect hop - a public URL that redirects
  to 127.0.0.1/file:// is blocked.
- **Slow-client protection (MED).** Requests carry a 30 s socket
  timeout and unauthenticated bodies larger than 1 MB are refused
  (401) before a single byte is read - the phone Send portal keeps
  working via its QR link token.
- **Token never in logs (MED).** The startup line prints a masked
  dashboard URL, new installs no longer log the plain token, and
  `/diagnostics` log tails are regex-redacted (the old "token
  REDACTED" promise was not true).

**Extension hardening**
- **Website API allowlist (HIGH).** `window.advprint` /
  `printPdfLink` are no longer callable by every website. Options >
  **Website API** holds the allowlist (`*://www.htncr.org/*` style
  patterns); an EMPTY list means the page API is OFF everywhere.
  Upgraded installs are migrated once: the sites of their existing
  auto-print rules (incl. the htncr.org lab integration) keep access.
- **Page print quality (MED).** "Print this page" now strips
  `<script>`/`<noscript>` from the clone and injects `<base href>` -
  stylesheets and images resolve again and page scripts no longer
  re-run inside the headless renderer.
- **Faster + lighter PDF path (PERF).** PDFs are uploaded as raw
  `application/pdf` bodies (no more +33% base64 detour), the
  auto-print path reads `document.contentType` from the tab instead
  of downloading the URL twice, the page-API `/jobs` limit is clamped
  client-side, and the stale 2.6.2 version fallback is gone.

**Performance**
- The FIFO worker now sleeps on a wake event (sub-millisecond job
  pickup instead of a 0.35 s poll) and the job database uses SQLite
  **WAL** mode with `synchronous=NORMAL` - lower latency, less CPU,
  faster history writes on Windows disks.
- History/audit API limits are clamped server-side.

**Filename & header fixes (LOW)**
- Bengali/Unicode file names keep their combining marks
  (`রিপোর্ট-Lab` no longer mangles), download names cannot inject
  into `Content-Disposition`, Sumatra always gets a valid
  `paper=` flag (and falls back to the OS default printer instead of
  opening its GUI), and the auth lockout state is thread-safe.

**Regression coverage**: 23 new tests (`tests/test_audit_fixes.py`)
map one-to-one to the audit findings - 212 tests pass in total.

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
