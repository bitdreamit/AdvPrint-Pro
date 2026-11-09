# v3.0.9 — BUG FIX + PER-PRINTER IPP QUEUES (2026-11-09)

AdvPrint Pro (Advanced Printer) by **Bit Dream IT - Innovative Healthcare Solutions**
Base: v3.0.8 — everything from v3.0.8 ships unchanged.

## 1) FIXED — printer names duplicated in the extension Default-printer dropdown

The Default printer dropdown showed every name twice:

    AdvPrint Pro @ AI-LabAdvPrint Pro @ AI-Lab
    OneNote (Desktop)OneNote (Desktop)
    Microsoft Print to PDFMicrosoft Print to PDF
    HP Laser 103 107 108HP Laser 103 107 108

**Root cause:** `extension/options.js` built the option label as
`p.name + (ternary..., p.name)` — one closing paren was missing, so the
`, p.name` inside the parens parsed as the **comma operator**: the
decorated label was computed and silently discarded and the expression
evaluated to `p.name + p.name`.

**Fix:** the paren is closed. Names render once again, and the
`[status]` / `(OS default)` decorations that were silently dropped now
show again. Regression tests: `tests/test_printer_label.py` (replays the
old broken expression AND the live expression pulled from `options.js`).

## 2) NEW — per-printer IPP queues: the hub as central IPP middleware

Every LOCAL printer now also gets its own queue on the hub:

    ipp://<lan-ip>:9235/ipp/print/<printer>

- **One center PC serves the whole LAN.** Child PCs, phones and tablets
  add ONE printer of the center PC directly — no AdvPrint tool on the
  client; the Chrome extension or plain IPP is enough.
- **Queue names just work:** raw Windows name (`HP%20Laser%20103%20107%20108`),
  slug (`hp-laser-103-107-108`), case-insensitive, punctuation-insensitive.
- **mDNS/Bonjour announces ONE service PER printer** (plus the classic
  central queue) — Windows 10/11, macOS, iPhone AirPrint and Android
  Mopria list every printer of the center PC by itself.
- `GET /printers` answers `ipp_queue` + `ipp_path` per printer and
  `ipp_central_url` for the classic shared queue.
- `GET /ipp/print/<printer>` serves a per-queue landing page (exact
  ipp:// URL, live printer state, Windows / CUPS add steps).
- Unknown queues: clean `404` + `ipp.queue.reject` audit row.
- Jobs from a per-printer queue are audited and enqueued with their
  real printer — pause / queue mode / history / reprint all work.

Tests: `tests/test_ipp_perprinter.py` (10 tests: slug matching, encoded
names, end-to-end Print-Job routing, virtual-PDF behavior kept, mDNS
service list, landing page, /printers metadata).

## Build / publish kit

`scripts/build-all.sh` builds EVERYTHING from this tree (no prebuilt
binaries needed — the CRX signing key ships in `extension-signing/`):

    CRX        dist/AdvPrint-Pro.crx               (tool/crx3.py + repo key)
    Extension  dist/AdvPrint-Pro-Extension-3.0.9.zip
    Setup EXE  dist/AdvPrint-Pro-Setup-3.0.9.exe   (NSIS 3.x, repo-relative setup.nsi)
    DEB        dist/advprint-pro_3.0.9_all.deb     (dpkg-deb)
    SHA256SUMS dist/SHA256SUMS-3.0.9.txt
