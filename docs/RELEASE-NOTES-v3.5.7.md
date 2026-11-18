# Release Notes — AdvPrint Pro v3.5.7
**SILENT WINDOWS — no CMD window flashes** — 2026-11-18
by Bit Dream IT - Innovative Healthcare Solutions

v3.5.7 answers one owner ask:

> *"when windows run first multiple time cmd run is it you advprint
> tools run cmd if it by advprint please run this silently not show
> on screen"*

On Windows the hub has always been started **windowless** — the Setup
finish page, the Startup-apps entry and START-ADVPRINT.vbs all launch
it through `pythonw` / the bundled `AdvPrintPro.exe`. What the owner
saw was the hub's own **child processes**: a handful of helper
launches were missing `CREATE_NO_WINDOW`, so Windows gave each one
its own console window. Most visible on the **first run** (policy
setup + firewall + service checks all at once) and afterwards on
every console poll of the extension-policy status.

---

## 1 · What flashed, and what it costs

| Site | Command | Before | After |
|---|---|---|---|
| `_ext_reg_query_values` (policy status) | `reg query` | **flash** — 5 browsers x 2 hives = 10 per poll | hidden |
| `_ext_reg_add` (policy install) | `reg add` | **flash** — up to 15 per install | hidden |
| `_ext_reg_delete` (policy remove) | `reg delete` | **flash** | hidden |
| service-install / service-remove helper | `powershell` | **flash** (long-lived parent) | hidden |
| CUPS `lp` fallback print | `lp` | **flash** (only when SumatraPDF absent) | hidden |
| firewall check / add, schtasks, sc query, taskkill, SumatraPDF, renderer, relaunch | — | already hidden | unchanged |

Every one of them now runs with the hub's existing `HIDE` constant —
`CREATE_NO_WINDOW` (`0x08000000`) on Windows, plain `0` on
macOS/Linux. The **UAC prompt still appears** whenever elevation is
genuinely requested (firewall rule, service install, CRX policy
pass): that prompt is Windows' own secure-desktop dialog, it must be
approved by a human, and hiding it is neither possible nor wanted.
Everything else is invisible.

## 2 · A build gate so the flashes can never come back

`tests/test_v357.py` adds a **source sweep**: it walks every
`subprocess.run` / `subprocess.Popen` / `check_output` call in
`advprint.py` and `tool.py` (both hub twins), extracts the full
argument list, and **hard-fails if any call whose command is a known
console binary — `reg`, `powershell`, `schtasks`, `netsh`, `sc`,
`taskkill`, `tasklist`, `lp` — does not carry `creationflags=HIDE`**.
It also pins:

- the exact reg-helper / helper call sites (the 5 fixes of this
  release, by source text);
- `HIDE = 0x08000000 if IS_WIN else 0` in both hub files and tool.py;
- simulated-Windows behaviour: with `IS_WIN`/`HIDE` patched, all
  three reg helpers pass `creationflags=0x08000000` to `subprocess`;
- the NSIS installer + VBS launcher stay silent (`nsExec` everywhere,
  `LaunchHub` reads the `PythonW` registry value, `sh.Run ...,
  0, False`);
- version coherence 3.5.7 across hub, console, extension, installer,
  DEB, VERSION.txt + byte-identical hub twins.

## 3 · Upgrade + compatibility

- The v3.5.6 features are all present and untouched: LAN admin
  console (`ui_admin_mode` + `admin_ips`), ipp:// displayed printer
  URLs, signed CRX chain, LAN Sharing card, Android guide.
- The v3.5.5 build kit is untouched: `build.cmd` /
  `scripts/build-all.py`, tree guard, twin guard, NSIS pre-validation,
  abs-path compile pipeline, `wipe()`, CRX signature gate. Same stable
  key, same extension ID (`likldbkamojokkfdlcjibiljpgbbnohc`) —
  pairing, settings and auto-update all survive.
- No config keys changed; no data format changed; upgrading is
  "install over" (or re-extract the source zip and rebuild).
- macOS/Linux behaviour is byte-for-byte identical (`HIDE` is 0
  there; every touched call site is either Windows-only or guarded).

## 4 · Try it in 60 seconds

1. Build: `build.cmd` (Windows) or `python3 scripts/build-all.py`.
2. Install the new `AdvPrint-Pro-Setup-3.5.7.exe` (or restart the
   portable hub). First run: **no CMD windows flash** — only the UAC
   prompt for the firewall rule, if you accept it.
3. Open the console → Extension tab → "Check policy status":
   previously 10 flashing windows per click, now nothing.
4. Confirm the hub is still fully functional: print a test page,
   check the tray icon, read `%UserProfile%\.advprint\hub.log` —
   the same lines as before, just without the window noise.
