# AdvPrint Pro v3.4.8 — A-to-Z DEVELOPMENT & BUILD GUIDE

AdvPrint Pro (Advanced Printer) by Bit Dream IT - Innovative Healthcare
Solutions. This guide covers ONLY the v3.4.8 delta on top of v3.4.7.
v3.4.7 is the BASE: the first v3.4.8 attempt (table fix + rule-editor
kind remapping + run bookkeeping + /rules/test parity) was REVERTED
because it did not work; this release restarts from the working
v3.4.7 tree and ships the layout fix ONLY. Read
`AdvPrint-Pro-v3.4.7-A-to-Z-DEV-GUIDE.md` first - everything there
still applies.

---

## 0. The one-paragraph delta

v3.4.8 is a **layout-only release**: the ONE UI rules table (14
columns) no longer overflows its card. Headers may wrap
(`white-space:normal;vertical-align:bottom`), every ONE UI `.tbl`
table is wrapped in `<div class="tbl-wrap">` (`overflow-x:auto`,
scrolls INSIDE the card as a last resort), the rules table carries
`class="tbl compact"` with shrunken min-widths, and `renderRules`
clamps the Page-content cell (`.doc` + inline max-width) like the
pattern cell. No print / rule / queue / network logic changed - and
`tests/test_v348.py` LOCKS that the reverted risky changes stay absent
(no `value=` attributes on the editor's URL-type select, no web->html
alias in either matcher, no `last_run` push, single-form
`rule_test_result` call) plus that the installer runtime
(`python311.zip` + 30+ files) is still bundled.

## 1. The exact diff of this release

```
tool/unix/hub/console.html            <- THE fix (CSS + tbl-wrap +
                                         compact widths + cell clamp)
tool/windows/portable/hub/console.html   <- byte-identical copy
installer/stage/hub/*                    <- re-staged by build-all.sh
tool/*/hub/advprint.py                <- VERSION 3.4.8 + VERSION_NAME
                                         + re-embedded console
extension/* (manifest, popup, i18n, options, api.js)   <- version pins
installer/setup.nsi                   <- OutFile / VIProductVersion /
                                         DisplayVersion 3.4.8
VERSION.txt                           <- 3.4.8
tests/test_v348.py                    <- NEW lock file (14 tests)
```

Everything else is untouched v3.4.7 source.

## 2. The console.html fix in detail

1. `.tbl th`: `white-space:nowrap` -> `white-space:normal` +
   `vertical-align:bottom` (headers wrap to a second line).
2. New CSS after `.tbl .id`: `.tbl-wrap{overflow-x:auto}`,
   `.tbl.compact th,.tbl.compact td{padding:6px 6px}`,
   `.tbl.compact .doc{max-width:118px}`.
3. All 13 ONE UI `.tbl` tables wrapped in `<div class="tbl-wrap">`...
   `</table></div>` (the modal `.mtable` is NOT wrapped).
4. Rules table: `<table class="tbl compact" style="font-size:10px">`
   with measured widths - `#` 22, Rule min 58, URL filter min 80,
   Printer min 70, Cpl 26, Paper 46, On 30, Auto 34, Runs 52,
   actions 84.
5. `renderRules`: the Page-content cell (`td[4]`) gets
   `className="doc"` + `style="max-width:100px;font-weight:500"` for
   content rules, else class/style reset and an em dash - so long
   "must contain" lines ellipsis-clamp instead of stretching the row.

## 3. Why the first attempt was reverted (do not re-apply blindly)

The first v3.4.8 bundled three logic changes on top of the layout fix;
the user reported "not work, fully bug" and reverted to v3.4.7:

- the rule editor's URL-type select was re-valued
  (`value=pdf/web/text/zpl/image/""` + ZPL/Image options) with a
  saveRule IIFE that normalized `web->html` and defaulted content
  rules on Any to html - plus `web` aliased to `html` in BOTH matchers
  (extension `matchRule` + hub `rule_matches`);
- the extension pushed `last_run` with the run counters and the hub
  rules cleaner kept `title` + `last_run` on central edits;
- `/rules/test` GET learned `&kind=` + `&title=` parity.

Any of these may return as their own careful release AFTER the user
confirms v3.4.8 works - never silently bundled again. Until then
`tests/test_v348.py` fails the build if they re-appear.

## 4. Build & verify (A to Z)

```bash
python3 scripts/embed_console.py      # console -> BOTH advprint.py
python3 -m pytest tests/ -q           # full suite (663 green)
python3 scripts/ui_check_v348.py      # 1280px fit + 800px inner scroll
bash scripts/build-all.sh             # CRX3 + ext zip + deb + SHA256SUMS
# NSIS at a custom prefix (this sandbox):
( cd installer && env NSISDIR=$P/usr/share/nsis   LD_LIBRARY_PATH=$P/usr/lib/x86_64-linux-gnu $P/usr/bin/makensis -V2 setup.nsi )
cd dist && sha256sum AdvPrint-Pro.crx AdvPrint-Pro-Extension-3.4.8.zip   advprint-pro_3.4.8_all.deb AdvPrint-Pro-Setup-3.4.8.exe   > SHA256SUMS-3.4.8.txt && sha256sum -c SHA256SUMS-3.4.8.txt
```

Sync order matters: `embed_console.py` BEFORE the test suite (the
embedded-copy test reads the patched console), `build-all.sh` before
the final suite run (the CRX-freshness tests read the re-signed
package), the Setup exe AFTER `build-all.sh` (it consumes
`installer/stage/`), and the SHA256SUMS last (covers the exe too).
