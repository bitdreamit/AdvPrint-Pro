# RELEASE NOTES - AdvPrint Pro v3.0.1
**AdvPrint Pro (Advanced Printer) - by Bit Dream IT - Innovative Healthcare Solutions**
MIT license - 100% local - no cloud, no tracking - 2026-11-05

Base: v3.0.0. Nothing removed - every 3.0.0 / 2.9.x / 2.8.x feature is
unchanged. v3.0.1 = the tray menu click fix + the window.print() hook
switch moved into Power switches + the version bump.

---

## 1. Tray menu click fix - "the text and the click are not the same"

The reported bug: clicking the TEXT of one tray menu item works, but
other items trigger something else - the text you see and the action
that runs were not the same.

**Root cause (found and verified).** The self-drawn menu (the theme-
proof popup we paint ourselves) computes the clicked row with `_hit()`,
which returns a SELECTABLE-ROW number (separators do not count). The
click handler then did `self.items[idx]` with that raw number - but
`self.items` ALSO contains `("sep",)` separator entries. The tray menu
has two separators, so every item AFTER the first separator was shifted:

| You clicked | What actually ran (old build) |
| --- | --- |
| Open dashboard | Open dashboard - OK |
| Print test page | Print test page - OK |
| Pause queue | **nothing** (it hit the separator) |
| Start at Windows logon | **paused / resumed the queue** |
| Restart hub | **toggled autostart** |
| Allow LAN in firewall | **RESTARTED the hub** |
| Exit | **opened the firewall UAC prompt** |

The hover highlight and the hit band always agreed (the same ordinal
math everywhere) - only the final text->action lookup was shifted. That
is exactly why it felt like "text and click in different areas".

**Fix.** A new `_pos_of(ordinal)` maps the row number to the REAL items
position before the command is read. Every menu item now triggers its
own action. A regression test (`test_v301_tray_menu_click_targets`)
execs the shipped `_hit()` + `_pos_of()` code, simulates a click on the
text area of every row of the real menu layout and asserts the command
of each row - the old build fails it on five rows.

**Zero migration**: pure tray_windows.py fix. Update the hub and the
tray icon picks it up on the next start.

## 2. Intercept window.print() moved into Options > Power switches

The "Intercept window.print()" switch used to sit mid-page in the
Behavior section. It now lives in the **Power switches** block, right
next to the master switch and Queue mode - the same place the popup
keeps its "window.print() hook" toggle.

- Same `hookPrint` setting as before - the popup toggle and the Options
  switch share one value and always agree.
- No migration: the checkbox id is unchanged, saved settings are kept.

## 3. Version

3.0.1 everywhere: hub `VERSION` / `VERSION_NAME` + dashboard badge +
tray tooltip, extension manifest / popup / Options / About (single
source = the manifest), `AdvPrint-Pro-Setup-3.0.1.exe` (NSIS
`VIProductVersion 3.0.1.0`), `advprint-pro_3.0.1_all.deb`, VERSION.txt,
README, CHANGELOG, Full Guide, START-HERE. Historical code comments
still record when earlier fixes landed (v2.9.1 audit items, v3.0.0
renumber) - live version strings say 3.0.1.

**Regression coverage**: 2 new tests (tray click targets, hook switch
placement) - 214 tests pass (+1 skipped environment test).

---

## Files in this release

| File | What |
| --- | --- |
| `AdvPrint-Pro-Setup-3.0.1.exe` | Windows installer (bundles Python 3.11.9, UAC once, silent `/S`) |
| `advprint-pro_3.0.1_all.deb` | Debian/Ubuntu/Mint package |
| `AdvPrint-Pro-3.0.1-source.zip` | Complete source (hub, extension, installer, tests, docs) |
| `AdvPrint-Pro-v3.0.1-FULL.zip` | Portable tree + docs + prebuilt installers |
| `AdvPrint-Pro-Extension-v3.0.1.zip` | Browser extension only |
| `SHA256SUMS-3.0.1.txt` | Checksums for everything above |

## Upgrade

Run the new setup over the old one (2.8.2 / 2.9.0 / 2.9.1 / 3.0.0 -
settings and history are kept), or replace the portable folder. The deb
upgrades with `sudo dpkg -i advprint-pro_3.0.1_all.deb`. The extension
updates by Remove + Load unpacked. On the dashboard press Ctrl+F5 once.
