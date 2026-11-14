# AdvPrint Pro v3.5.0 — A-to-Z DEVELOPMENT & BUILD GUIDE

AdvPrint Pro (Advanced Printer) by Bit Dream IT - Innovative Healthcare
Solutions. This guide covers ONLY the v3.5.0 delta on top of v3.4.8.1.
v3.4.8.1 is the BASE: the working v3.4.7 tree plus the rules-table
layout fix. Read `AdvPrint-Pro-v3.4.8-A-to-Z-DEV-GUIDE.md` first -
everything there still applies (the table fit is untouched and still
locked by `tests/test_v348.py`).

---

## 0. The one-paragraph delta

v3.5.0 is a **theming + layout release**: the ONE UI gets the **Pro
Theme engine** (7 themes incl. 2 dark, light/dark, density, corners,
window frame - saved in localStorage, applied before first paint,
Theme menu + Settings > Appearance), the **dashboard data view** is
fixed to agree with the rest of the UI (own IPP-printer branch, live
mDNS/RAW/DropZone rows, idle printers count as usable, held jobs not
double-counted, rounded progress widths), a **local QR generator**
renders QR tiles without the hub, and every version surface says
3.5.0. No print / rule / queue / network logic changed. The theme
source was also scrubbed of the FIRST (buggy) v3.4.8 rule-editor
remap - the working v3.4.7 editor stays, re-locked by
`tests/test_v350.py`.

## 1. The exact diff of this release

```
tool/unix/hub/console.html            <- Pro Theme engine (CSS + early
                                         apply + Theme menu + Appearance
                                         card + tooltip helper), dashboard
                                         fixes, local QR, 3.5.0 surfaces,
                                         buggy remap stripped
tool/windows/portable/hub/console.html   <- byte-identical copy
tool/*/hub/advprint.py                <- VERSION 3.5.0 + VERSION_NAME
                                         + re-embedded console (unix +
                                         windows copies stay identical)
installer/stage/hub/advprint.py       <- embedded console refreshed
                                         (build-all.sh re-stages anyway)
extension/manifest.json               <- version 3.5.0
extension/popup.html / options.html   <- version pins
extension/i18n.js                     <- brandLine en + bn
extension/content/api.js              <- _apVerFallback 3.5.0
extension/popup.js                    <- header comment
installer/setup.nsi                   <- OutFile / VIProductVersion /
                                         DisplayVersion / hints 3.5.0
installer/deb/DEBIAN/control          <- Version: 3.5.0 (was stale 3.2.8)
VERSION.txt                           <- 3.5.0
START-HERE.txt / README.md / CHANGELOG.md
docs/RELEASE-NOTES-v3.5.0.md          <- NEW
docs/AdvPrint-Pro-v3.5.0-A-to-Z-DEV-GUIDE.md  <- this file
docs/SHA256SUMS-3.5.0.txt             <- dist checksums
tests/test_v350.py                    <- NEW lock file (21 tests)
tests/test_v348.py + older locks      <- current-version asserts
                                         refreshed to 3.5.0 (repo
                                         convention)
```

Everything else is untouched v3.4.8.1 source.

## 2. The Pro Theme engine in detail

Four additive blocks in `console.html` (the served ONE UI):

1. **Theme CSS** - after the base design system: `:root` carries the
   Cobalt palette; `html[data-theme="classic|emerald|violet|graphite|
   midnight|carbon"]{...}` re-map the design tokens; dark themes add
   status/chip/log token overrides; `html[data-mode="dark"]{
   color-scheme:dark}`. A "THEME ENGINE EXTRAS" block adds the
   density/corners/frame CSS (`html[data-density|data-corners|
   data-frame]`), per-theme component tweaks and an inline-color
   bridge; an "APPEARANCE CARD (Settings)" block styles
   `.theme-tile` + `.pv` preview mockups.
2. **Early apply script** (in `<head>`, parser-blocking = before
   first paint): reads `localStorage["advprintTheme"]`, resolves
   `system` via `prefers-color-scheme`, and sets `data-theme`,
   `data-mode`, `data-density`, `data-corners`, `data-frame` on
   `<html>`. Exposes `window.AdvTheme = {KEY, DEFAULTS, MODES, load,
   save, apply, resolve}`.
3. **Theme menu + Appearance card markup** - the menubar Theme menu
   (`data-theme-set` items incl. "System (auto light / dark)" +
   "Appearance settings...") and the Settings Appearance card
   (`#appearanceCard`, `#themeGrid` with 8 tiles, density / corners /
   frame toggles, `#themeStatus` line, `#apprReset`).
4. **Engine script** (own `<script>` before the tooltip helper):
   renders the tiles with live mini-preview mockups, wires the menu
   items, tiles, toggles and reset, persists via `AdvTheme.save()`,
   updates `aria-checked` + the status line, and keyboard-activates
   (Enter/Space).

The icon-tooltip helper (separate small script) shows the label of
icon-only sidebar/toolbar items as a `#uiTip` bubble on hover / focus
/ tap (media-query aware, `prefers-reduced-motion` safe).

## 3. The dashboard data-view fixes in detail

1. The glance-row loop had `else if (key.indexOf("ipp") >= 0 ||
   key.indexOf("mdns") >= 0)` BEFORE the specific rows, so "IPP
   printer" matched the `ipp` branch and printed mDNS text. The
   branches are now: `key.indexOf("ipp printer") === 0` (chip READY +
   the `/ipp/print` endpoint from `cfgCache.ipp_printer`), then
   `mdns`, then `raw` (`LISTENING <hubIp>:<raw_port from health>`),
   then `dropzone` (`ON watching the DropZone folder` / OFF).
2. Printer counting changed from `p.status === "ready"` to
   `p.status === "ready" || p.status === "idle"` in BOTH
   `renderStats` (dashboard) and `renderFrame` (status bar) - an idle
   printer is usable; only `offline` is down. The dashboard, the
   Printers tab and the status bar finally agree.
3. The In Queue stat is `q.pending` only; the held count moves into
   the small label (`q.held + " held"`), so held jobs appear once.
4. `prog()` returns `Math.round(...)` widths.
5. Static fallback markup mirrors the same values; sample jobs carry
   `pages_total` 18 / 4 / 1 so the static table and the data agree.

## 4. The local QR generator

`window.apQRsvg(text)` (additive script in `<head>` + engine script)
renders the QR tiles locally as SVG; the QR modal computes BASE from
`location.origin` so `file://` previews no longer produce the string
`"null"`. When the hub IS running, tiles still prefer the live
endpoint - the generator is the fallback, not a behavior change.

## 5. Version surfaces bumped

See the diff table in section 1. Both `advprint.py` copies stay
byte-identical (`tests/test_hub_copies` asserts); the embedded
`CONSOLE_HTML` equals the on-disk `console.html` exactly in unix,
windows AND installer stage. `scripts/embed_console.py` is the canonical
re-embed tool - run it after ANY console.html edit, then
`bash scripts/build-all.sh`.

## 6. Build + verify (all from the repo root)

```
python3 scripts/embed_console.py          # after console.html edits
python3 -m pytest tests/ -q               # 682 passed (2 pre-existing
                                          # tarball failures excluded)
bash scripts/build-all.sh                 # CRX3 + zip + deb + SHA256SUMS
(cd installer && ../.build-bin/makensis -V2 setup.nsi)   # Setup EXE
```

CRX guard: build-all re-signs the CRX from `extension/` with the repo
key, syncs EVERY embedded copy (unix / windows / prebuilt / stage) and
hard-fails if any copy differs or the CRX version != hub version.

## 7. Test lock map

- `tests/test_v350.py` (NEW, 21 tests): theme engine (7 theme CSS
  blocks, early-apply in head, localStorage key, Theme menu +
  Appearance card, density/corners/frame, tooltip helper, legacy THEME
  row gone), dashboard fixes (IPP branch, idle counting x2, no double
  count, rounded widths), the buggy remap stays absent, no template
  preview layer in the served console, byte-identical copies + fresh
  embedded consoles, version 3.5.0 coherence, local QR present.
- `tests/test_v348.py`: rules-table fit + reverted-logic locks
  (assertions refreshed to the multi-line ProTheme markup and 3.5.0).
- Older release locks (`test_hub_v2`, `test_v32x/33x/34x`):
  current-version asserts refreshed to 3.5.0 per repo convention.

## 8. Known notes

- The GitHub source tarball of v3.4.8.1 shipped without
  `prebuilt/allow_extention_advprint_pro.bat`, so the two `test_v334`
  bat assertions fail on a fresh tarball checkout (pre-existing, not
  related to v3.5.0).
- The deb control in-repo was stale at 3.2.8; `build-all.sh` always
  rewrote it at package time - the checked-in file now says 3.5.0 too.
