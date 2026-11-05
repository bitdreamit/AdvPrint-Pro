# RELEASE NOTES - AdvPrint Pro v3.0.2
**AdvPrint Pro (Advanced Printer) - by Bit Dream IT - Innovative Healthcare Solutions**
MIT license - 100% local - no cloud, no tracking - 2026-11-05

Base: v3.0.1. Nothing removed except a duplicated switch - every
3.0.x / 2.9.x / 2.8.x feature is unchanged.

---

## 1. The popup's window.print() hook switch is gone - ONE switch, ONE place

v3.0.1 moved the "Intercept window.print()" switch into **Options >
Power switches** (next to the master switch and Queue mode). v3.0.2
completes that move: **the popup's duplicate switch is removed**.

- The popup Power section now shows the master switch + Queue mode (+
  the LAN sharing switches) - leaner, no duplicated state.
- The switch lives ONLY in Options > Power switches > *Intercept
  window.print()*.
- Same `hookPrint` setting as always - value, behaviour, saved data
  and the page-API allowlist are untouched. Nothing to migrate.
- The popup's i18n keys for the removed row are cleaned out
  (popHook* in English and Bangla).

## 2. New: docs/MULTI-PRINTER.md - one PC, many printers, at the same time

The lab question, answered end to end with the real routing facts:
receipt/PDF printing on A4 or A5 on one printer **while a Zebra (or
any other) printer prints ZPL labels simultaneously**.

The rules that make multi-printer work:

- **The per-job printer name always wins** (`resolve_dest()`):
  extension auto-print rule printer, Options default-printer dropdown,
  page API `printPage({printer:...})`, `POST /print` `"printer"`
  field, or a named `profiles` entry.
- **The payload type decides the pipeline** (content sniffing):
  `%PDF` -> the PDF engine (paper a4/a5, tray, duplex, pages, copies,
  quality, n-up); JPEG -> wrapped PDF; **ZPL `^XA` / ESC-POS /
  PostScript / PCL -> RAW passthrough**, byte-for-byte to the named
  printer - labels render on the Zebra, reports on the laser, queued
  side by side, every job in History with its printer name.
- **Printer groups fail over**: `printer_groups {"Lab": [A, B]}` -
  the first member that is not offline/paper-out/error prints the job.
- **No printer name on the job** (phones/PCs printing via IPP or RAW
  9100): the Print destination card decides; an unreachable upstream
  IP printer holds the job (Print now overrides).
- Includes the step-by-step lab setup (LIS portal -> HP LaserJet
  A4/A5 + label page -> Zebra ZD421), group failover, profiles, and
  curl snippets (`lang:"zpl"` + label text, or `raw_base64`).

The Full Guide gained **section 6.6 "Multiple printers on one PC"**
with the same story; `MULTI-PRINTER.md` ships in the source zip, the
FULL zip and next to the downloads.

## 3. Version

3.0.2 everywhere: hub `VERSION` / `VERSION_NAME` + dashboard badge +
tray tooltip, extension manifest / popup / Options / About (single
source = the manifest), `AdvPrint-Pro-Setup-3.0.2.exe` (NSIS
`VIProductVersion 3.0.2.0`), `advprint-pro_3.0.2_all.deb`, VERSION.txt,
README, CHANGELOG, Full Guide, START-HERE.

**Regression coverage**: 3 new tests (popup carries no trace of the
removed switch + the one Options switch stays in Power switches;
MULTI-PRINTER.md ships with the real routing facts) - 217 tests pass.

---

## Files in this release

| File | What |
| --- | --- |
| `AdvPrint-Pro-Setup-3.0.2.exe` | Windows installer (bundles Python 3.11.9, UAC once, silent `/S`) |
| `advprint-pro_3.0.2_all.deb` | Debian/Ubuntu/Mint package |
| `AdvPrint-Pro-3.0.2-source.zip` | Complete source (hub, extension, installer, tests, docs) |
| `AdvPrint-Pro-v3.0.2-FULL.zip` | Portable tree + docs + prebuilt installers |
| `AdvPrint-Pro-Extension-v3.0.2.zip` | Browser extension only |
| `SHA256SUMS-3.0.2.txt` | Checksums for everything above |

## Upgrade

Run the new setup over the old one (2.8.2 / 2.9.x / 3.0.x - settings
and history are kept), or replace the portable folder. The deb
upgrades with `sudo dpkg -i advprint-pro_3.0.2_all.deb`. The extension
updates by Remove + Load unpacked. After updating, the popup drops the
removed switch automatically (no action needed).
