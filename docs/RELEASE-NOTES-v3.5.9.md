# Release Notes — AdvPrint Pro v3.5.9
**UNBREAKABLE DEB BUILD (SCANNER-PROOF STAGING)** — 2026-11-18
by Bit Dream IT — Innovative Healthcare Solutions

## What the owner reported

The first v3.5.8 build run died in the `-- DEB` stage of
`build.cmd`:

```
File "D:\Software\Python\AdvPrint-Pro\scripts\build-all.py", line 845, in _tar_from_dir
    data = open(full, "rb").read()
FileNotFoundError: [Errno 2] No such file or directory:
'D:\\Software\\Python\\AdvPrint-Pro\\dist\\deb-build\\advprint-pro_3.5.8\\
 opt\\advprint\\hub\\console.html'
```

Running the build a second time succeeded (`-- DONE - artifacts in
dist/`) — so the file was never really missing. This release makes the
first run succeed every time.

## 1. Root cause — a scanner race, not a missing file

The pure-Python DEB packer works in two steps:

1. **Stage** — copy every payload file into
   `dist\deb-build\advprint-pro_<V>\` (the hub, the console HTML, the
   CRX, the launcher scripts, the service source, the DEBIAN control
   dir).
2. **Tar** — `os.walk` the staged tree to collect the entries, then
   `open()` each one and pack it into `data.tar.gz`.

`os.walk` had **just listed** `console.html`. Between that listing and
the `open()` a moment later, the Windows on-access scanner (Defender
real-time protection) hid the freshly copied file while it scanned it.
Python's `open()` saw `FileNotFoundError` — the build died.

This is the **same failure class** as the v3.5.5 makensis
`stage/install/hub-stop.ps1 -> no files found` case (documented in the
build-all.py header since v3.5.5): an on-access scanner can make a
freshly staged file invisible for a moment, even while the build is
enumerating it. makensis got a defense-in-depth fix in v3.5.5; the DEB
path was the one remaining unprotected stage — and it is the stage that
copies the **largest, freshest batch of files** on every build, so the
scanner has the biggest window to strike.

## 2. The fix — the DEB cycle is now scanner-proof

`scripts/build-all.py` v3.5.9 defends the DEB stage in depth,
mirroring the makensis fix:

| Layer | What it does | What it protects against |
| --- | --- | --- |
| `_read_visible()` | Every staged file is read with a short visibility retry (6 attempts, 0.3 s doubling backoff; `_visible_mtime()` does the same for the tar mtimes). | The common case: a momentary hide self-heals in a few hundred ms **without any re-stage**. |
| Loud walk | `_tar_from_dir` passes an `onerror` hook to `os.walk` — a hidden directory **raises** instead of being silently skipped. | A silently omitted subtree would quietly produce an **incomplete .deb** with no error at all — the worst possible outcome. |
| `deb_expected_files()` + `verify_deb_stage()` | The staged tree is verified **file-by-file** against the complete expected layout (the whole `DEBIAN/` control dir, the hub payload, every hub `*.html`, the CRX, the launcher scripts, the service source) **before** tarring. | A file the scanner ate during the copy itself is caught immediately, with its name printed. |
| `build_deb(expect=...)` | The tar re-checks the expected files right before the walk — a vanish landing **between the verify and the walk** now fails loudly instead of quietly skipping the file. | The exact race window that produced the v3.5.8 failure. |
| `build_deb_scannerproof()` | The whole **stage → verify → tar** cycle (extracted from `main()` into `stage_deb_tree()`) runs in a retry loop: up to 3 attempts, automatic re-stage on any vanish, and the Defender exclusion hint printed on final failure. | Anything the first four layers cannot absorb is healed by a clean re-stage; a genuinely hostile scanner still gets a loud, actionable error instead of a half-built .deb. |

The retry messages are explicit:

```
   [!] DEB stage/tar hit FileNotFoundError: ...console.html
       (attempt 1/3) - re-staging...
   retry 2 SUCCEEDED (the scanner let go - add the Defender
       exclusion below to stop this early)
```

and if all three attempts fail, the build stops with the one-time fix:

```
  An on-access scanner (Defender real-time protection) is
  hiding/eating freshly staged files. One-time fix in an ADMIN
  PowerShell:
       Add-MpPreference -ExclusionPath "D:\Software\Python\AdvPrint-Pro"
  then run the build again.
```

## 3. Locked by tests

`tests/test_v359.py` reproduces the exact failure and proves every
layer works:

- a file hidden **between the walk and the open** is healed by the
  visibility retry (no re-stage needed);
- a hidden **directory** raises loudly through the `os.walk` onerror
  hook instead of being silently skipped;
- a staged file deleted **before the tar walk** is caught by
  `build_deb(expect=...)` with its name;
- the full `build_deb_scannerproof()` cycle **re-stages and succeeds**
  after a real mid-cycle vanish — and the resulting `.deb` is parsed
  member-by-member (`debian-binary`, `control.tar.gz`,
  `data.tar.gz`) to prove the payload really contains
  `./opt/advprint/hub/console.html` with the right modes;
- an exhausted retry loop stops the build with the Defender hint.

## Everything else

All v3.5.8 (REAL WINDOW BUTTONS + BRAND + TAB MEMORY), v3.5.7
(SILENT WINDOWS) and v3.5.6 features are untouched: the real window
buttons + brand title + tab memory (`?path=<tab>`), no machine id on
the Dashboard, SILENT WINDOWS (`CREATE_NO_WINDOW`, zero CMD flicker),
LAN admin console (`ui_admin_mode` + `admin_ips`), `ipp://` printer
URLs, signed CRX3 chain (extension ID
`likldbkamojokkfdlcjibiljpgbbnohc`), windowless hub + tray icon, NSIS
Setup EXE, DEB, full build kit, byte-identical unix/windows hub twins.

## Verify

```
python3 scripts/build-all.py
python tool/crx3.py verify dist/AdvPrint-Pro.crx 3.5.9
pytest tests/test_v359.py -q
python3 scripts/smoke_v359.py
```
