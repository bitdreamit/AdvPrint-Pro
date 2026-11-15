# Release Notes - AdvPrint Pro v3.5.3

**STATUS BAR ALWAYS VISIBLE - the bottom bar stays on screen**

by Bit Dream IT - Innovative Healthcare Solutions - 2026-11-15

---

## The one-line story

v3.5.2 was confirmed working ("3.5.2 fine"); the user then reported the
last layout bug: the bottom status bar - Hub Running / IP:port /
Printers / Queue / History / LAN / DropZone / Uptime / version -
rendered BELOW the bottom edge of the window ("outside bottom, not
showing"). v3.5.3 fixes it with three CSS declarations and changes
nothing else.

## Root cause - a 936px frame inside a 900px window

The console stylesheet never reset the browser's default `8px` body
margin and never set `box-sizing`:

- `.desktop{height:100vh;padding:14px}` with the default content-box
  model laid out **900px of content plus 14px of padding on each side
  = 936px of real page**, and the UA body margin pushed it another
  8px down;
- `body{overflow:hidden}` then silently clipped everything past the
  fold - and the **last** element in the window frame is the status
  bar, so the bar went outside the bottom exactly as reported.

Measured before the fix at a 900px-tall window: the bar occupied
y=894..921 - **21 of its 27 pixels were below the fold**.

## The fix - surgical, three declarations

```css
body{margin:0; ...}                                   /* kill the UA 8px margin */
.desktop{height:100vh;box-sizing:border-box;...}      /* 100vh = REAL total size */
.window{...;box-sizing:border-box}                    /* 1px border adds no height */
```

Result: the frame exactly fills the viewport at any window size and
the status bar sits fully on screen.

## Verified end-to-end (real hub, real Chromium)

The release gate is `scripts/smoke_v353.py` + `tests/test_v353.py`:

| Viewport | Status bar (top..bottom) | Viewport height | Desktop bottom | Doc scroll height | JS errors |
|----------|--------------------------|-----------------|----------------|-------------------|-----------|
| 1280x720 | 678..705 | 720 | 720 | 720 | 0 |
| 1366x768 | 726..753 | 768 | 768 | 768 | 0 |
| 1440x900 | 858..885 | 900 | 900 | 900 | 0 |
| 1600x1000 | 958..985 | 1000 | 1000 | 1000 | 0 |

`desktop bottom == viewport height` and `document scroll height ==
viewport height` prove there is no hidden overflow left anywhere; the
bar bottom is always `viewport - 15px` (frame padding), fully visible.

Also re-verified on the served `/ui` from the live hub:

- `/health` reports `version: 3.5.3`;
- v3.5.2 regressions all still pass: real success rate math
  (success = printed + saved, canceled excluded), `/jobs?date_from=
  &date_to=` whole-database date filter, `/jobs/<id>/file?view=1`
  inline disposition, and **zero** `type="password"` inputs in the ONE
  UI (no browser save-password prompts);
- the served page carries all three fix declarations.

## What did NOT change

Print logic, queue, rules, themes (ProTheme 8 themes + density /
corners / frame), network sharing, IPP/RAW, DropZone, the extension,
history behavior - all exactly the working v3.5.2 build.

## Version coherence

Hub `VERSION`/`VERSION_NAME`, `VERSION.txt`, `extension/manifest.json`
3.5.3, popup + i18n (EN/Bangla) + api.js fallback, NSIS
`VIProductVersion 3.5.3.0` + `DisplayVersion` + setup exe name, deb
`control` 3.5.3, console title and `BOOT.version` UI fallbacks.

## Upgrade

Same as every 3.x release: close the old hub, install over it (the
Windows setup exe keeps config.json, the queue database and rules),
restart; Chrome self-updates the extension from the hub within a
minute. Linux: `sudo dpkg -i advprint-pro_3.5.3_all.deb`.
