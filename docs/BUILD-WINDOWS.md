# BUILD ON WINDOWS — step by step (v3.5.6)

**AdvPrint Pro** by Bit Dream IT - Innovative Healthcare Solutions

This guide builds **every artifact from source on a Windows PC**:

| Artifact | File in `dist\` | Needs |
|---|---|---|
| Signed extension (CRX3) | `AdvPrint-Pro.crx` | Python + `cryptography` |
| Unpacked extension zip (store / dev) | `AdvPrint-Pro-Extension-<V>.zip` | Python (built-in) |
| Windows installer | `AdvPrint-Pro-Setup-<V>.exe` | + NSIS 3.x |
| Linux DEB | `advprint-pro_<V>_all.deb` | Python only (pure-Python builder — **no WSL needed**) |
| Checksums | `SHA256SUMS-<V>.txt` | Python (built-in) |

`<V>` is the version from `VERSION.txt` (currently 3.5.6).

> **Got "no files found" inside makensis?** Since v3.5.5 the build
> cannot hit that any more: it checks the complete file list FIRST and
> names exactly what is missing. If it ever prints
> `your source tree is MISSING ...`, your tree is incomplete — re-extract
> the full source release zip and build again.

---

## 1) One-time setup (about 10 minutes)

### 1.1 Install Python 3.9 or newer

1. Download from <https://www.python.org/downloads/> (Windows installer 64-bit).
2. Run it. **On the first page tick `Add python.exe to PATH`** — this is the
   one box everybody misses.
3. Click *Install Now*, then verify: open **Command Prompt**

       python --version
       pip --version

### 1.2 Install NSIS 3.x (only needed for the Setup EXE)

1. Download `nsis-3.x-setup.exe` from <https://nsis.sourceforge.io/Download>.
2. Install with the default options — the default folder is
   `C:\Program Files (x86)\NSIS` and the build script finds it there
   automatically. **You do not need to add it to PATH.**

### 1.3 Get the source

Either with Git:

    git clone https://github.com/bitdreamit/AdvPrint-Pro.git
    cd AdvPrint-Pro
    git checkout v3.5.6

or without Git: open <https://github.com/bitdreamit/AdvPrint-Pro>,
green **Code** button → **Download ZIP**, then right-click the zip →
*Extract All…*

> Use the **full source release zip** (`AdvPrint-Pro-3.5.6-src.zip` or
> the tag archive) so every file is present. Mixing an old tree with
> new kit files is what caused the "no files found" support case.

---

## 2) Build — one command

Open **Command Prompt** in the source folder, then:

    build.cmd

(or double-click `build.cmd` in Explorer). It:

1. checks Python and installs the single build dependency `cryptography`
   the first time,
2. verifies the tree is COMPLETE (every file the build needs) and that
   the unix/windows hub copies are byte-identical — if Windows Defender
   quarantined one of the install `.ps1`/`.bat`/`.vbs` helpers, it is
   restored automatically from a copy embedded inside `build-all.py`,
3. packs the extension into `dist\AdvPrint-Pro.crx` with the **repo's
   stable signing key** (`extension-signing\advprint-printer.pem`),
4. syncs the CRX into all 4 embedded copies and **verifies the signature
   the same way Chrome does** (`tool\crx3.py verify`) — a broken/stale CRX
   fails the build instead of reaching your users,
5. zips the unpacked extension for the Web Store,
6. stages the hub + installers + bundled Python runtime into
   `installer\stage\`, then pre-validates **every `File` reference in
   `setup.nsi`** (no more mid-compile surprises),
7. builds the **DEB in pure Python** (no WSL, no dpkg-deb),
8. runs **makensis** to produce `dist\AdvPrint-Pro-Setup-<V>.exe` — if an
   on-access scanner removes a staged file mid-compile, the build names
   it, prints the one-time Defender exclusion fix and retries with
   freshly staged copies,
9. writes `dist\SHA256SUMS-<V>.txt`.

PowerShell users: `python scripts\build-all.py` does the same thing.
Linux/macOS: `python3 scripts/build-all.py` or the older
`bash scripts/build-all.sh`.

Expected output at the end:

    == DONE - artifacts in dist/ ==
        ~74 KB  AdvPrint-Pro.crx
        ~74 KB  AdvPrint-Pro-Extension-3.5.6.zip
         10.2 MB  AdvPrint-Pro-Setup-3.5.6.exe
        ~550 KB  advprint-pro_3.5.6_all.deb
          ~400 B  SHA256SUMS-3.5.6.txt

**Antivirus note (one-time).** Real-time scanners sometimes quarantine
build helper scripts (`.ps1` / `.bat` / `.vbs`) the moment they are
written into `installer\stage\`. The build now survives this — it
carries embedded copies of all nine helpers — but to stop the scanner
from interfering at all, allow the source folder once in an **admin**
PowerShell:

    Add-MpPreference -ExclusionPath "D:\Software\Python\AdvPrint-Pro"

---

## 3) Verify what you built

    python tool\crx3.py verify dist\AdvPrint-Pro.crx 3.5.6

must print three `verify:` lines and `PASS` (ID matches key, RSA
signature OK over the archive actually inside, payload zip OK). This is
the exact check that would have caught the v3.5.3
"CRX signature verification failed" bug.

Cross-check the checksums (PowerShell):

    Get-FileHash dist\AdvPrint-Pro.crx -Algorithm SHA256
    type dist\SHA256SUMS-3.5.6.txt

---

## 4) Install the pieces

**CRX (paired browsers)** — the normal way is nothing to do at all: the
hub serves `/extension/updates.xml` from its embedded copy, so browsers
already paired to `http://<hub>:9235` auto-update to the new version. For
a first manual install: `chrome://extensions` → enable **Developer mode**
→ drag `dist\AdvPrint-Pro.crx` onto the page (Chrome may refuse a raw
drag on some channels — then use *Load unpacked* on the `extension\`
folder, or install via the Setup EXE which registers the force-install
policy for the stable ID `likldbkamojokkfdlcjibiljpgbbnohc`).

**Setup EXE** — run `dist\AdvPrint-Pro-Setup-<V>.exe` (SmartScreen will
show *Windows protected your PC* because the EXE is not code-signed —
*More info* → *Run anyway*). Silent: `AdvPrint-Pro-Setup-<V>.exe /S`.

**Extension zip** — upload `AdvPrint-Pro-Extension-<V>.zip` to the Chrome
Web Store dashboard.

**DEB** — copy to any Debian/Ubuntu machine: `sudo apt install
./advprint-pro_<V>_all.deb`.

---

## 5) Golden rules (do not skip)

1. **NEVER regenerate `extension-signing\advprint-printer.pem`.** The
   extension ID `likldbkamojokkfdlcjibiljpgbbnohc` is derived from that
   file; a new key means a new ID, force-install policies break and
   paired browsers see a different extension. The build fails on purpose
   if the ID ever changes.
2. **Never edit a `.crx` after signing.** Any change to the payload
   invalidates the signature (that is exactly the v3.5.3 bug). Always
   change `extension\` and rebuild.
3. **Always build through the script.** It re-signs, syncs all embedded
   CRX copies (`stage\`, `tool\unix\hub\extension\`,
   `tool\windows\portable\hub\extension\`, `prebuilt\`), verifies, and
   refuses to ship anything stale. Hand-copying a CRX around is how the
   stale-signature bug happened.
4. Keep `extension-signing\` out of any public fork you do not control —
   whoever holds the key can sign updates your hub serves.
5. **Edit the hub in `tool\unix\hub\` only**, then let the build/tests
   confirm the windows twin still matches — the build refuses to run on
   drifted copies.

---

## 6) Releasing a new version (checklist)

1. Bump the version everywhere it lives: `VERSION.txt`,
   `extension\manifest.json`, `installer\setup.nsi` (`OutFile
   "../dist/AdvPrint-Pro-Setup-<V>.exe"` + `VIProductVersion` +
   `DisplayVersion` — the build hard-fails if `OutFile` is forgotten),
   popup/i18n/api.js labels, hub `VERSION`/`VERSION_NAME` in
   `tool\unix\hub\advprint.py` (+ windows twin), console title +
   `BOOT.version` fallbacks + stat card, deb `control` — see
   `docs\HOW-TO-RELEASE.md` for the full list.
2. Run `build.cmd`.
3. `python tool\crx3.py verify dist\AdvPrint-Pro.crx <V>` → PASS.
4. Commit (including the 4 refreshed embedded CRX copies), tag `v<V>`,
   publish.

---

## 7) Troubleshooting

| Message | Fix |
|---|---|
| `'python' is not recognized…` | Reinstall Python and tick **Add python.exe to PATH**, or use `py -3` instead of `python`. |
| `pip install` fails behind a proxy | `pip install cryptography --proxy http://proxy:port` |
| `your source tree is MISSING …` | The tree is incomplete — re-extract the full source release zip (do not mix old trees with new kit files) and build again. |
| `makensis NOT found` | Install NSIS 3.x (step 1.2). The rest of the build still completes; run `cd installer` then `makensis setup.nsi` afterwards. |
| `CRX3 signature verification FAILED` | Someone edited `dist\AdvPrint-Pro.crx` or an embedded copy after signing, or the key changed. Do not hand-patch — rebuild with `build.cmd`. |
| `extension ID changed!` | `extension-signing\advprint-printer.pem` was replaced. Restore the original key file. |
| `installer/setup.nsi OutFile is …` | The version was bumped but `setup.nsi` was not — change its `OutFile` line to `../dist/AdvPrint-Pro-Setup-<V>.exe`. |
| `setup.nsi needs N file(s) that do not exist` | The build could not stage or re-stage a file — follow the per-file hint printed under the message (missing runtime = re-extract the source zip). |
| `…was MISSING from the tree - it was restored from the copy embedded inside build-all.py` | Informational: your antivirus had removed an install helper and the build healed itself. Run the exclusion command in section 2 to stop it recurring. |
| `staged file(s) DISAPPEARED …` then a retry | An on-access scanner removed a staged file while `makensis` compiled. The build re-staged and retried — also run the exclusion command it prints (admin PowerShell: `Add-MpPreference -ExclusionPath "<repo folder>"`). |
| `twin files drifted apart` | Copy the edited hub file from `tool\unix\hub\` over its `tool\windows\portable\hub\` twin, then rebuild. |
| SmartScreen blocks the Setup EXE | Expected (unsigned EXE): *More info* → *Run anyway*, or sign the EXE with a code-signing certificate. |
| `WARNING: runtime missing` | `tool\windows\portable\installer\runtime\` was deleted — restore it from the repo, or the installed hub will need system Python. |
| Antivirus flags the `.bat`/`.vbs`/`.ps1` helpers | False positive on script helpers; add the source folder to exclusions (`Add-MpPreference -ExclusionPath "<repo folder>"`). Since v3.5.5 the build also self-heals these files from copies embedded in `scripts\build-all.py`. |
