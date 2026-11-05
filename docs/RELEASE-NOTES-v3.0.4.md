# RELEASE NOTES - AdvPrint Pro v3.0.4
**AdvPrint Pro (Advanced Printer) - by Bit Dream IT - Innovative Healthcare Solutions**
MIT license - 100% local - no cloud, no tracking - 2026-11-06

Base: v3.0.3. Extension-only release - the hub is untouched.
Nothing removed, no settings migration.

---

## What is new (short)

**Goal: one PC, several printers - managed easily in the rules table.**

### 1. "Printers on this PC" - the full list is now IN the rules section

Under the rules table there is a new strip: **one chip per installed
printer** (printer groups too), with its live status (`ready`,
`offline`, `paper-out`...) and the OS default marked.

- Each chip has a **+ rule** button: one click adds a new rule row with
  **that printer already selected**.
- The rule's Printer dropdown shows the same full list - so different
  rules simply pick different printers.
- Hub not connected? The strip shows a "connect to the hub" hint.

### 2. Copy button on every rule

The fastest way to one rule per printer: press **Copy** - the row is
duplicated with everything in it (pattern, type, title, printer,
action, copies, paper, On, Auto). Change the URL pattern, done.

### 3. New pattern type: "Contains"

The easiest match there is: the URL just has to **contain** the text,
no wildcards, no regex:

| You type (Type: Contains) | It matches |
| --- | --- |
| `medical_reports/pdf` | any URL with that text inside |

Glob (`*://www.htncr.org/lab/*`) and Regex stay unchanged. First
matching rule still wins.

## The lab recipe (same PC, two printers, at the same time)

| Do this | Rule you get |
| --- | --- |
| HP chip **+ rule** -> pattern `*://www.htncr.org/lab/medical_reports/pdf/*`, tick **Auto**, Paper **A5** | every report PDF opens -> prints on the HP, A5 |
| Zebra chip **+ rule** -> pattern `*://www.htncr.org/lab/labels/*`, Action **ZPL label (text on page)**, Copies **2**, tick **Auto** | every label page opens -> 2 labels print on the Zebra, no dialog |

Every job carries its rule's printer name, and the hub always gives
the per-job printer name priority - so the Print destination card is
never flipped and both printers work side by side.

Also in this build (from 3.0.3): rule Action **"ZPL label (text on
page)"** / **"ESC-POS receipt (text on page)"** prints labels/receipts
straight from the page text - no page JavaScript - plus per-rule
**Copies** and **Paper** (A4/A5/Letter/...).

## Version

3.0.4 everywhere: hub `VERSION` / `VERSION_NAME` + dashboard badge +
tray tooltip, extension manifest / popup / Options / About, Setup exe
VIProductVersion 3.0.4.0, deb control, docs, Full Guide (PDF
re-rendered). Old version trees and files are untouched.

## Upgrade

Install over 2.8.2 / 2.9.x / 3.0.x - settings and history are kept.
Extension: Remove + Load unpacked. Your existing rules keep working
exactly as before.

**Tests**: full suite green, including the new v3.0.4 checks (Contains
matching, Copy button, chip strip with "+ rule", dropdown hints).

---

## Files in this release

| File | What |
| --- | --- |
| `AdvPrint-Pro-Setup-3.0.4.exe` | Windows installer (bundles Python 3.11.9, UAC once, silent `/S`) |
| `advprint-pro_3.0.4_all.deb` | Debian/Ubuntu/Mint package |
| `AdvPrint-Pro-3.0.4-source.zip` | Complete source (hub, extension, installer, tests, docs) |
| `AdvPrint-Pro-v3.0.4-FULL.zip` | Portable tree + docs + prebuilt installers |
| `AdvPrint-Pro-Extension-v3.0.4.zip` | Browser extension only |
| `SHA256SUMS-3.0.4.txt` | Checksums for everything above |
