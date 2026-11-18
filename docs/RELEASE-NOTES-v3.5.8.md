# Release Notes — AdvPrint Pro v3.5.8
**REAL WINDOW BUTTONS + BRAND + TAB MEMORY** — 2026-11-18
by Bit Dream IT — Innovative Healthcare Solutions

## What the owner asked for

> "fake minimize maximize close correct also update actually work
> able" · the "AdvPrint Pro — Printing Hub · ALL-IN-ONE Console … —
> Pro Themes" title replaced by **AdvPrint Pro by Bit Dream IT —
> Innovative Healthcare Solutions** · tab URL path support (click
> History, refresh, stay on History — `?path=history` in the URL, and
> if there is no path the last tab is saved internally) · "Dashboard
> with uuid show no need, just Dashboard need" · "cmd powershell
> hiddenly work need no flick any".

## 1. The window buttons really work now

The three title-bar buttons were design-only decoration (a toast and
two style toggles). In v3.5.8 they behave like real window buttons:

| Button | Behaviour |
| --- | --- |
| `—` Minimize | Collapses the console to its title bar (every other frame layer is hidden). A second click restores the console. Works everywhere — no browser permission needed. |
| `□` Maximize | Toggles **real fullscreen** via the Fullscreen API. **Double-click on the title bar** does the same. If the browser refuses fullscreen (embedded frame, missing permission) the console maximizes **edge-to-edge in-page** instead (frame gaps and rounded corners removed). |
| `✕` Close | Really calls `window.close()`. When the browser blocks it (the tab was not opened by script) an honest toast explains it — the tab's own `✕` closes it. The hub keeps printing either way; the tray icon manages the hub. |

A `fullscreenchange` listener keeps the maximize state in sync when
the user leaves fullscreen with `Esc`, so the frame never gets stuck.

## 2. The new brand title

The browser tab title and the console title bar now read:

**AdvPrint Pro by Bit Dream IT — Innovative Healthcare Solutions**

Removed from the console: the composite `<title>` "…ALL-IN-ONE Console
vX — Pro Themes", the "All-in-One Console vX · `<machine-id>` · THE
ONE UI" title bar suffix and the "ALL-IN-ONE" address-bar text. The
version is still visible where it belongs: the status bar pane
("Printing Hub v3.5.8 · Bit Dream IT") and the Hub tab stat card.

## 3. Tab memory + URL path

- Every `showTab()` call validates the tab name against the real
  panels, then writes `?path=<tab>` into the URL with
  `history.replaceState` — the `?token=` query is preserved.
- The same tab is stored in `localStorage` (`ap_console_tab`).
- On boot: `?path=` in the URL wins → else the legacy `#tab=` hash →
  else the saved last tab → else the Dashboard. An invalid name never
  blanks the console; it simply keeps the Dashboard.
- Result: click **History** → the URL becomes `…/ui?token=…&path=history`
  → refresh stays on History; a plain re-open of `/ui` (no `?path`)
  still restores the last tab from the saved state.

## 4. No uuid on the Dashboard

The Dashboard subtitle and the old title bar embedded the machine id
(on many PCs a uuid-looking hostname). v3.5.8 removes it: the
subtitle is now simply "live · every feature in ONE window" and the
title bar carries only the brand.

## 5. CMD/PowerShell stays 100% silent — the v3.5.7 SILENT WINDOWS guarantee

Every helper process the hub launches on Windows (reg.exe policy
queries/writes/removes, the elevated PowerShell passes, CUPS lp, the
renderer, schtasks/netsh/sc/taskkill/tasklist) still launches with
`creationflags=CREATE_NO_WINDOW` — **zero flicker**. The AST
build-gate sweep in `tests/test_v357.py` still hard-fails the build
if any console-binary call loses its hide flag. The only visible
dialog is the Windows UAC prompt when elevation is genuinely needed
(it must be approved by a human).

## Everything else

All v3.5.7 / v3.5.6 features are untouched: LAN admin console
(`ui_admin_mode` + `admin_ips`), `ipp://` printer URLs, signed CRX3
chain (extension ID `likldbkamojokkfdlcjibiljpgbbnohc`), windowless
hub + tray icon, NSIS Setup EXE, DEB, full build kit, byte-identical
unix/windows hub twins.

## Verify

```
python3 scripts/build-all.py
python tool/crx3.py verify dist/AdvPrint-Pro.crx 3.5.8
pytest tests/test_v358.py -q
python3 scripts/smoke_v358.py
```
