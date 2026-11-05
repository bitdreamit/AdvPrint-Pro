# RELEASE NOTES - AdvPrint Pro v3.0.3
**AdvPrint Pro (Advanced Printer) - by Bit Dream IT - Innovative Healthcare Solutions**
MIT license - 100% local - no cloud, no tracking - 2026-11-05

Base: v3.0.2. Extension-only feature release - the hub API was already
ready (`text` + `lang:"zpl"/"escpos"`, `copies`, `paper_size`, per-job
printer). Nothing removed; old rules keep working unchanged (the new
fields default to blank).

---

## 1. Routing rules now print LABELS and RECEIPTS - no page JavaScript

The feedback that drove this release: *"your example needed AJAX/JS
changes - ZPL and raw should be handled in this extension, easily
managed."* Done. **Options > Auto-print & routing rules** - the
**Action** column gained two modes:

| Action | What happens when the rule fires |
| --- | --- |
| `Auto (PDF or page)` | as before - PDF URLs print as PDFs, pages render (v2.0) |
| `PDF only` / `Page render` | as before - force one pipeline (v2.0) |
| **`ZPL label (text on page)`** (new) | the page's TEXT is sent to the hub with `lang:"zpl"` and streams **byte-for-byte** to the rule's printer - the Zebra renders its own labels |
| **`ESC-POS receipt (text on page)`** (new) | the page's TEXT goes to the hub with `lang:"escpos"`; the hub builds the ESC/POS bytes (auto cut) for the thermal receipt printer |

**Where the text comes from** (first that has content wins):

1. the user's text **selection** on the page,
2. a `<pre>` or `<textarea>` block - what ZPL viewers and label web
   tools show,
3. the visible body text.

**Safety guard**: a ZPL rule refuses text without a single `^`
command - a mis-matched page shows a clear error ("this page does not
look like ZPL") instead of wasting labels.

**It works from every path**: auto-print when the URL opens (Auto
ticked + closeAfterPrint = zero-click labels), the popup / dashboard
**Print page** button (the rule turns it into a label print), and the
**Reprint a PDF link** box (matching rule's printer/copies/paper ride
along).

## 2. Per-rule Copies and Paper columns

Two new columns in the rules table:

- **Copies** (1-999): label runs ("2 labels per specimen"), receipt
  duplicates. Blank = hub default (and the global Default print
  options still apply when the rule is blank).
- **Paper** (`(auto)` / A4 / A5 / A3 / Letter / Legal / Tabloid): sent
  as `paper_size` for PDF/page jobs - **Paper A5 for lab receipts
  while reports stay A4** on the same printer or two printers.
  Ignored for ZPL/ESC-POS jobs (labels carry their own media).

Rule values are applied BEFORE the global print defaults, so **the
rule wins**; blank rule fields never override your global defaults.

## 3. The multi-printer lab - now entirely in the rules table

One PC, one hub, several printers at the same time - configured in
Options > Rules, nothing else:

| Rule | URL pattern | Printer | Action | Copies | Paper | Auto |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `*://www.htncr.org/lab/medical_reports/pdf/*` (title `invoice?`) | HP LaserJet (A4/A5) | Auto (PDF or page) | 1 | A5 | on |
| 2 | `*://www.htncr.org/lab/labels/*` | Zebra ZD421 | ZPL label (text on page) | 2 | - | on |
| 3 | `*://www.htncr.org/lab/receipts/*` | XPrinter 80mm | ESC-POS receipt (text on page) | 1 | - | on |

Why this just works (unchanged hub mechanics, documented since 3.0.2):

- **The per-job printer name always wins** (`resolve_dest()`): each
  rule names its printer, so the destination card is never flipped and
  all printers run at the same time.
- **The payload decides the pipeline**: `%PDF` -> the PDF engine
  (paper, tray, duplex, copies...), `^XA` ZPL / ESC-POS -> RAW
  passthrough, byte-for-byte.
- The worker queue serialises jobs per hub, so simultaneous report +
  label jobs never interleave bytes.
- A new **lab card** under the rules table summarises this in the
  extension itself; `docs/MULTI-PRINTER.md` section 3 now shows the
  rules as the primary label flow (page API / network-printer flows
  remain for desktop label software).

## 4. Version

3.0.3 everywhere: hub `VERSION` / `VERSION_NAME` + dashboard badge +
tray tooltip, extension manifest / popup / Options / About (single
source = the manifest), `AdvPrint-Pro-Setup-3.0.3.exe` (NSIS
VIProductVersion 3.0.3.0), `advprint-pro_3.0.3_all.deb` (control
Version), VERSION.txt, START-HERE, README, CHANGELOG, Full Guide
(HTML re-rendered to PDF). The v3.0.2 / v3.0.1 / v3.0.0 / v2.9.1
trees and deliverables are untouched.

## 5. Zero migration

- Existing rules keep working exactly as before - `copies`/`paper`
  default to blank, unknown actions fall back to `auto`.
- No new settings, no new permissions (`scripting` was already used).
- Install over any 2.8.2 / 2.9.x / 3.0.x; extension = Remove + Load
  unpacked.

**Regression coverage**: new v3.0.3 tests - rule actions ship
(ZPL/ESC-POS options in the rules UI), the background label pipeline
(text extraction order, `lang` payload, `^` guard), per-rule
copies/paper in collect() + rulePrintExtras threading, the lab card,
and MULTI-PRINTER.md rules section. Full suite green.

---

## Files in this release

| File | What |
| --- | --- |
| `AdvPrint-Pro-Setup-3.0.3.exe` | Windows installer (bundles Python 3.11.9, UAC once, silent `/S`) |
| `advprint-pro_3.0.3_all.deb` | Debian/Ubuntu/Mint package |
| `AdvPrint-Pro-3.0.3-source.zip` | Complete source (hub, extension, installer, tests, docs) |
| `AdvPrint-Pro-v3.0.3-FULL.zip` | Portable tree + docs + prebuilt installers |
| `AdvPrint-Pro-Extension-v3.0.3.zip` | Browser extension only |
| `SHA256SUMS-3.0.3.txt` | Checksums for everything above |

## Upgrade

Run the new setup over the old one (2.8.2 / 2.9.x / 3.0.x - settings
and history are kept), or replace the portable folder. The deb
upgrades with `sudo dpkg -i advprint-pro_3.0.3_all.deb`. The extension
updates by Remove + Load unpacked. Then open Options > Auto-print &
routing rules and give the label rule its Action + Copies - that is
the whole setup.
