# v3.1.3 - THE ONE UI SKIN (2026-11-09)

**AdvPrint Pro by Bit Dream IT - Innovative Healthcare Solutions**

Base: **v3.1.2** - every previous feature ships unchanged. Zero behavior
change, zero API change. This release makes the installed product LOOK
exactly like the approved UI designs (v3.1.2 shipped the same
functionality behind a plain utility skin).

## 1. Hub console (/ui) = approved Design 1, pixel for pixel

- Real **window chrome**: blue gradient title bar (AP logo, live hub
  version + PC name via the new `/health` "host" key), menu bar,
  address bar with live hub dot + token badge, 218px **category tree**
  with count badges, segmented status bar.
- Glossy **SVG toolbar**: New Job / Pause-Resume / Clear / Printers /
  IPP Queue / Refresh / Extension / Settings / Audit / Dashboard -
  every button live (pause/resume the queue, clear, refresh, tab
  navigation, classic dashboard).
- IDM components everywhere: 4 KPI stat cards, striped progress bars,
  chip status badges, dark `#0d1731` log terminal, job filter chips,
  live settings switches in a 2-column form grid.
- Same live API wiring as before (health / stats / queue / printers /
  jobs / audit / config / debug), same token auth, same actions.

## 2. Extension options = approved Design 2, all 10 tabs

- The same IDM window chrome around the existing 10 tabs: sidebar
  category tree (Overview / Automation / Settings / System) with live
  red badges (queue + debug), an IDM **toolbar whose buttons DO the
  real actions** (Save Settings / Test Page / Connect Hub / New Rule /
  Reprint / Pause Queue / Self-Test / Hub Config / Console / About),
  the live hub status pill in the address bar and a status bar that
  mirrors the active tab + hub state.
- **Console is the landing tab** and embeds the live `/ui` console
  (with the offline fallback card when the hub is down).
- Every input id, save button and settings flow untouched.

## 3. Fixed in this release

- **Console tab could never be opened in v3.1.2**: `"console"` was
  missing from the TABS list in options.js - showTab("console")
  silently fell back to "general" (the iframe even loaded while the
  General panel was shown). Fixed; Console is now also the default tab.
- /health gained a `host` key (PC name) - shown in the console title
  bar, matching the mockup ("AI-Lab-PC").
- The options title-bar close button now closes the tab.

## Files in this release

| File | What it is |
|---|---|
| `AdvPrint-Pro-Setup-3.1.3.exe` | Windows installer (NSIS, bundled Python 3.11 runtime, ~10 MB) |
| `advprint-pro_3.1.3_all.deb` | Linux DEB (systemd user service + XDG autostart) |
| `AdvPrint-Pro.crx` | signed CRX3 extension (repo key, fixed id) |
| `AdvPrint-Pro-3.1.3-source.zip` | full source (build everything yourself) |
| `SHA256SUMS-3.1.3.txt` | checksums of all artifacts |
