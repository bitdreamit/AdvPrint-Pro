# BUILD FROM SOURCE — every artifact, no prebuilt binaries (v3.1.2)

**AdvPrint Pro** by Bit Dream IT - Innovative Healthcare Solutions

Build ALL release artifacts from this tree alone. The CRX signing key
ships in `extension-signing/` (keeps the fixed extension id
`likldbkamojokkfdlcjibiljpgbbnohc` so Chrome auto-updates the
force-installed extension from your own hub).

## 0) What you need

| Tool | For | Install |
|---|---|---|
| python3 ≥ 3.9 | hub + tests + CRX3 packer | preinstalled on Linux; Windows: python.org |
| zip | extension zip | `sudo apt-get install zip` |
| dpkg-deb | DEB package | preinstalled on Debian/Ubuntu |
| NSIS 3.x (makensis) | Setup EXE | `sudo apt-get install nsis` |
| Node.js (optional) | one dropdown regression test | nodejs.org — the test skips without it |

Run the test suite first:

    python3 -m pytest tests/ -q

## 1) One command — everything

    bash scripts/build-all.sh

Produces in `dist/`:

    AdvPrint-Pro.crx                      signed CRX3 (repo key)
    AdvPrint-Pro-Extension-<V>.zip        unpacked extension (store upload / dev)
    AdvPrint-Pro-Setup-<V>.exe            Windows installer (NSIS, ~10 MB)
    advprint-pro_<V>_all.deb              Linux DEB (systemd user service)
    SHA256SUMS-<V>.txt                    checksums

## 2) What the script stages (all repo-relative now)

- `installer/stage/hub/` ← `tool/windows/portable/hub/*` (advprint.py,
  tool.py, tray_windows.py, service_main.py, gui_app.py, console.html,
  icon) + the freshly built CRX into `stage/hub/extension/`.
- `installer/stage/install/` ← `tool/windows/portable/install/*`
  (install .bat/.vbs/.ps1, hub-stop.ps1, START-CONSOLE.vbs, ...).
- `installer/stage/runtime/` ← the bundled Python 3.11 runtime
  (`tool/windows/portable/installer/runtime/`, ~21 MB → ~10 MB in the
  LZMA-solid EXE). Delete this folder to build a runtime-less EXE
  (then the installer falls back to a system Python).
- `installer/stage/docs/` ← `docs/AdvPrint-Pro-Full-Guide.html`.
- The DEB tree is built in `dist/deb-build/` from
  `installer/deb/DEBIAN/{control,postinst,prerm}` + `installer/deb/data/*`
  templates and cleaned up after `dpkg-deb --build`.

## 3) NSIS only (rebuild the EXE alone)

    ( cd installer && makensis -V2 setup.nsi )

NSIS without root (sandbox/CI recipe used for this release):

    apt-get download nsis nsis-common
    dpkg -x nsis_*.deb ~/nsis-root && dpkg -x nsis-common_*.deb ~/nsis-root
    ( cd installer && NSISDIR=$HOME/nsis-root/usr/share/nsis \
      LD_LIBRARY_PATH=$HOME/nsis-root/usr/lib/x86_64-linux-gnu \
      $HOME/nsis-root/usr/bin/makensis -V2 setup.nsi )

## 4) CRX / extension only

    python3 tool/crx3.py pack extension \
            extension-signing/advprint-printer.pem dist/AdvPrint-Pro.crx
    python3 tool/crx3.py info dist/AdvPrint-Pro.crx     # verify id + version
    ( cd extension && zip -r ../dist/AdvPrint-Pro-Extension.zip . )

Install the CRX: the hub serves it at `http://127.0.0.1:9235/extension/AdvPrint-Pro.crx`
and auto-installs it silently through the `ExtensionInstallForcelist`
policy (postinst / Setup EXE write it). Load-unpacked dev install:
chrome://extensions → Developer mode → Load unpacked → `extension/`.

## 5) DEB only

    dpkg-deb --build --root-owner-group installer/deb dist/  # after staging

(or just run `scripts/build-all.sh`). Install: `sudo dpkg -i
advprint-pro_<V>_all.deb` — installs `/opt/advprint/hub/` (advprint.py,
console.html, gui_app.py, CRX), `/usr/bin/advprint`, the systemd user
service and the silent-extension policy. Uninstall: `sudo dpkg -r advprint-pro`.

## 6) After a build — release checklist

1. `sha256sum -c dist/SHA256SUMS-<V>.txt` (in dist/).
2. Boot the hub once from the tree: `python3 tool/unix/hub/advprint.py serve`
   → open `http://127.0.0.1:9235/ui?token=<token>` → all 8 tabs live.
3. Load the CRX / zip in Chrome, print one test page, check History.
4. Windows VM: run the Setup EXE, confirm tray + START-CONSOLE window.
5. Child PC: extension only → Connections → Center PC URL+token → status
   line shows the active hub. Phone: add the IPP queue.
6. Tag: `git tag -a v<V> -m "..."` and push (`git push origin main --tags`).
   GitHub release → attach the 5 dist/ files + paste
   `docs/RELEASE-NOTES-v<V>.md`.

## 7) Where versions live (bump all of them together)

`tool/unix/hub/advprint.py` + `tool/windows/portable/hub/advprint.py`
(`VERSION`, `VERSION_NAME`), `extension/manifest.json`,
`extension/popup.html`, `extension/content/api.js`,
`extension/options.html` (verchip), `VERSION.txt`,
`installer/setup.nsi` (OutFile, VIProductVersion, DisplayVersion),
`installer/deb/DEBIAN/control`, `tests/test_hub_v2.py` (anchors),
`tests/test_ipp_perprinter.py` header. Keep the two hub copies
byte-identical (`cp` unix → windows after every edit; the test suite
imports the windows copy).
