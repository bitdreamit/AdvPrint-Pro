# RELEASE NOTES v3.5.5 — FULL SOURCE + WINDOWS BUILD KIT

**AdvPrint Pro** by Bit Dream IT - Innovative Healthcare Solutions
Released 2026-11-16 · follows v3.5.4 (CRX signature verified)

## Why this release exists

A user build report —

    -- NSIS Setup EXE (C:\Program Files (x86)\NSIS\makensis.exe)
    File: "stage/install/hub-stop.ps1" -> no files found.
    Error in script "setup.nsi" on line 198 -- aborting creation process

— showed two problems: (1) an incomplete local source tree failed
minutes deep inside the installer compiler with an error that named the
SYMPTOM, not the CAUSE (the staging step had silently skipped the
missing file), and (2) building any artifact at all still required a
Linux box (bash script, `zip`, `dpkg-deb`).

A second report of the same error — on a tree where every source file
was present — pinned the remaining cause: **on-access antivirus
quarantine of staged `.ps1` files**. v3.5.5 now survives that too: the
nine install helpers are embedded inside `build-all.py`, and the
makensis step diagnoses vanished files, prints the one-time Defender
exclusion fix and retries.

v3.5.5 fixes all of it. No hub or extension behaviour changes
otherwise — everything is exactly the working v3.5.4 build.

## 1. Build everything on Windows with one command

New in-tree toolchain:

| File | Purpose |
|---|---|
| `build.cmd` | one-click Windows launcher (finds Python, installs `cryptography`, runs the build, pauses) |
| `scripts/build-all.py` | cross-platform canonical builder (Windows/Linux/macOS) |
| `docs/BUILD-WINDOWS.md` | step-by-step Windows guide + troubleshooting |
| `README-BUILDKIT.txt` | quick-start card for the kit files |

`scripts/build-all.py` mirrors `scripts/build-all.sh` artifact for
artifact — same names, same guards — and adds:

- **Pure-Python DEB builder** (`ar` + `tar.gz` via the stdlib, root
  ownership, explicit 0755/0644 modes): Windows needs **no WSL and no
  dpkg-deb**. Validated with `dpkg-deb --info/--contents` on Linux.
- **makensis auto-discovery**: `PATH`, `C:\Program Files (x86)\NSIS`,
  `C:\Program Files\NSIS`, or the `~/nsis-root` local prefix.
- Extension zip + SHA256SUMS via the stdlib.

## 2. Loud, early failure guards (the support-case fix)

- **REQUIRED-TREE CHECK** — the full list of files the stage needs
  (hub + installers + runtime + docs + deb data + signing key) is
  verified before anything is built. A missing file now fails in one
  second with its exact name and the fix hint, instead of dying inside
  makensis.
- **setup.nsi PRE-VALIDATION** — every `File "…"` reference in
  `installer/setup.nsi` must resolve on disk, and the script's
  `OutFile "../dist/AdvPrint-Pro-Setup-<V>.exe"` must match
  `VERSION.txt`, or the build stops with fix-it instructions.
- **TWIN-SYNC GUARD** — `tool/unix/hub/advprint.py`, `console.html`
  and `gui_app.py` must stay byte-identical to their
  `tool/windows/portable/hub/` twins.
- The stage copy step no longer skips missing files silently.
- **SELF-HEAL: the 9 install scripts are embedded (base64) inside
  `build-all.py`** — if Windows Defender (or any on-access scanner)
  quarantines a `.ps1`/`.bat`/`.vbs` out of the tree, the build
  restores it from the embedded copy, prints a warning and continues.
- **MAKENSIS POST-MORTEM + RETRY** — if staged files disappear *during*
  the compile (the exact "stage/install/hub-stop.ps1 -> no files found,
  line 198" round-2 support case), the build names the vanished files,
  prints the one-time fix (`Add-MpPreference -ExclusionPath "<repo
  folder>"`, admin PowerShell) and retries makensis once with freshly
  staged copies.

The CRX pipeline is unchanged and still gated: fresh pack with the
stable key → 4-copy byte-compare sync → payload-version guard →
`tool/crx3.py verify` (Chrome-identical). A stale-signed CRX still
cannot ship.

## 3. Version coherence 3.5.5

Hub `VERSION`/`VERSION_NAME`, `VERSION.txt` (built 2026-11-16),
`extension/manifest.json`, popup, i18n (EN + Bangla brand lines),
`content/api.js` fallback, console title + the three
`(BOOT.version || "…")` fallbacks + hub stat card, NSIS
`VIProductVersion 3.5.5.0` / `FileVersion` / `ProductVersion` /
`DisplayVersion` / exe name, deb `control`, and the new
`scripts/smoke_v355.py` copy.

Small fix: the extension **Options page version chip** was still stuck
on v3.5.1 (the popup-comeback release missed it) — it now shows v3.5.5.

## 4. Artifacts (rebuilt for 3.5.5)

- `AdvPrint-Pro.crx` — signed, ID `likldbkamojokkfdlcjibiljpgbbnohc`
  unchanged, 5 synced copies
- `AdvPrint-Pro-Extension-3.5.5.zip`
- `advprint-pro_3.5.5_all.deb`
- `AdvPrint-Pro-Setup-3.5.5.exe`
- `SHA256SUMS-3.5.5.txt` (+ copy in `docs/`)

## 5. Locked by tests

`python3 tests/test_v355.py` (or `python3 -m pytest tests/ -q`) locks:
complete required-file list, build-all.py guards present, twin files
byte-identical, CRX verifies with the stable ID, version 3.5.5
everywhere, BUILD-WINDOWS.md + kit files in place, setup.nsi refs
resolvable, deb control version.
