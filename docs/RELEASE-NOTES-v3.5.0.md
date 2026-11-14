# AdvPrint Pro v3.5.0 - Release Notes

**Pro Themes for the ONE UI + the dashboard data view finally shows the
real state.**
by Bit Dream IT - Innovative Healthcare Solutions

## What this release is

The ProTheme design was applied to the **current** console source (no
design rollback) and shipped as a full release: the theme engine is now
part of the REAL hub console that `advprint.py` serves at `/ui`, the
dashboard data view that "previously [was] not showing correctly" is
fixed, and every version surface says 3.5.0. Built on the working
**v3.4.8.1** tree - print, rule-matching, queue and network logic are
untouched. Locked by `tests/test_v350.py`; `tests/test_v348.py` still
locks the rules-table fit.

## 1. The Pro Theme engine

The ONE UI console gets a real theme system:

- **7 color themes** - Cobalt (new default), Classic IDM (the original
  v3.2.1 Windows-IDM blue, kept alive as a theme), Emerald, Violet,
  Graphite, Midnight and Carbon. The last two are complete dark themes
  (surfaces, lines, chips, log pane, scrollbars - everything re-colored).
- **Light / dark** via the theme mode; a "System" entry follows the OS
  preference automatically.
- **Density** (comfortable / compact), **corners** (rounded / sharp) and
  **window frame** (framed / borderless) as separate options.
- Two entry points: the **Theme menu** in the menu bar (top left, next
  to File) and **Settings > Appearance** - an 8-tile preview grid (7
  themes + System), density / corners / frame toggles, a live status
  line and a one-click **Reset appearance**.
- The choice is saved in the browser (`localStorage` key
  `"advprintTheme"`) and applied by an early-apply script in `<head>`
  BEFORE first paint - the console never flashes the wrong theme.
- The old decorative `THEME` select row ("Windows IDM (Blue)" that did
  nothing) is gone, together with its JS reference.
- Icon-only sidebar / toolbar items show their label as a tooltip on
  hover / focus / tap.

## 2. Dashboard data view - fixed ("previously not showing correctly")

The dashboard glance rows disagreed with the rest of the UI:

| Row / stat | Before | v3.5.0 |
| --- | --- | --- |
| IPP printer | mDNS discovery text (wrong branch) | `READY /ipp/print` (or OFF) |
| mDNS / RAW port / DropZone | static placeholders | live (`LISTENING 10.26.94.206:9100`, `ON watching the DropZone folder`) |
| Printers Ready | `2/4 · 2 offline` (idle counted as down) | `3/4 · 1 offline` (idle = usable, matches the Printers tab + status bar) |
| In Queue | `4 (+2)` (held jobs counted twice) | `4` with `2 held` in the corner label |
| Progress bars | `width:66.66666666666667%` | rounded (`67%`) |

The static fallback markup (visible before JS runs) uses the same
consistent values, and the sample jobs carry the page totals the static
table always claimed (18 / 4 / 1).

## 3. Local QR generator

The QR tiles (hub / invite / IPP) render from a local SVG generator
instead of probing the hub first, and the QR modal BASE uses
`location.origin` (not the string `"null"` on file://), so QRs appear
even while the hub is restarting.

## 4. The rule editor keeps the working v3.4.7 logic

The theme source still carried the FIRST (buggy) v3.4.8 rule-editor
remap: `value=` attributes + ZPL/Image editor options, a `web -> html`
alias and a value-based save. That build was reverted as "not work,
fully bug" and v3.4.8.1 re-locked the v3.4.7 behavior - v3.5.0 strips
the remap again and `tests/test_v350.py` re-locks it (label-based
select, positional save, no ZPL/Image editor options).

## 5. Version 3.5.0 everywhere

VERSION.txt, both `advprint.py` copies (VERSION + VERSION_NAME), the
embedded ONE UI console (unix + windows + installer stage), the
extension (manifest, popup, options, i18n en+bn, api.js fallback,
popup.js header), setup.nsi, the deb control, START-HERE.txt, README.md
and CHANGELOG.md. `dist/` was rebuilt with the repo's `build-all.sh`:
signed CRX3 v3.5.0 (all embedded copies synced + verified), extension
zip, Setup EXE, deb and `SHA256SUMS-3.5.0.txt`.

## Everything else = working v3.4.8.1

Configurable hub port (9235 default, movable when busy), DropZone watch
Enable/Disable toggle, strict LAN share with the IP hit list + one-click
Allow, URL rules that really match (glob / regex / contains + the
"Which rule fires?" test box), one TCP port 9235 for every queue, the
popup that remembers the last printer, manual LAN/IPP re-scan, auto-CRX
on install, idempotent set-default.

## Upgrade

Install straight over v3.4.6 / v3.4.7 / v3.4.8 (Setup exe / deb) -
settings, history and printer queues are kept. Browsers with the
auto-installed extension update themselves within a minute. Verify:
`http://127.0.0.1:9235/health` reports `"version": "3.5.0"`, the console
Theme menu switches all 7 themes instantly, and the dashboard IPP row
shows `READY /ipp/print`.
