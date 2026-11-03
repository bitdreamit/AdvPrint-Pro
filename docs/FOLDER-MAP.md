# AdvPrint Pro — Folder Map (v2.5.0)

**This package and your git repo are now the SAME tree.**

`github.com/bitdreamit/AdvPrint-Pro` ↔ `full.zip` → `AdvPrintPro/`, 1:1.
Extract the zip over your repo working copy → `git status` shows only real
changes, never renames.

---

## 1. Why folders kept changing (the short history)

| Era | Layout | Problem |
|---|---|---|
| v1.x | loose files at the zip root | mixed old+new on extract |
| v2.0–v2.4.1 | version in the root folder (`AdvPrintPro-2.4.0/`) + `hub/` + `install/` | every release = a NEW folder; hub folder named differently from your repo (`tool/`) |
| **v2.5.0+** | **repo-parity: `tool/`, `extension/`, `docs/`, `tests/` + `pytest.ini` — root folder always `AdvPrintPro/`** | **frozen. Package = git repo.** |

One-time cleanup in your repo: you have BOTH `doc/` and `docs/` — `doc/` is an
old duplicate of a `docs/` subset. Delete it once: `git rm -r doc`. The
package only ships `docs/`.

---

## 2. The tree (frozen from v2.5.0 on)

```
AdvPrintPro\
│
├── START-HERE.txt / VERSION.txt / SHA256SUMS.txt
├── README.md / CHANGELOG.md / LICENSE
├── pytest.ini              ← pytest config (tests/ at the root)
├── .gitignore              ← same file you commit to the repo
│
├── tool\                            ← the DESKTOP TOOL (the hub)
│   ├── windows\
│   │   ├── README.txt
│   │   └── portable\
│   │       ├── hub\                 advprint.py (2.5.0), tray_windows.py,
│   │       │                        tool.py (menu), service_main.py +
│   │       │                        service\AdvPrintProService.cs (Windows
│   │       │                        service), advprint.ico
│   │       ├── install\             install-windows.bat, START-PRINT-HUB.vbs,
│   │       │                        UNINSTALL-WINDOWS.bat, Windows-SERVICE
│   │       │                        install/remove (.bat + .ps1), unix scripts
│   │       │                        v2.8: hub-stop.ps1 (bullet-proof
│   │       │                        service + process stop for setup)
│   │       └── installer\runtime\   bundled Python 3.11 (gitignored in the
│   │                                repo; shipped here so the zip is
│   │                                self-contained)
│   │       └── AdvPrint-Tool.bat    launches tool.py menu
│   └── unix\
│       ├── hub\                     same advprint.py for Linux/macOS
│       ├── install-unix.sh
│       └── uninstall-unix.sh
│
├── extension\              ← the CHROME EXTENSION (load unpacked / reload)
│   ├── manifest.json  background.js  popup.html/.js  options.html/.js
│   ├── managed.json (GPO/MDM)  i18n.js (English + Bangla UI strings)
│   ├── content\ (relay.js, api.js, hook.js)  icons\
│
├── docs\                   ← ALL DOCUMENTATION
│   ├── EXTENSION-TEST.md   5-minute end-to-end extension tool test
│   ├── FOLDER-MAP.md       this file
│   ├── API.md  EXTENSION-API.md  Full-Guide (.html/.pdf)
│   ├── RELEASE-NOTES-v2.3.0.md / v2.0.0 / v1.7.2   history
│   ├── HOW-TO-RELEASE.md  HOW-TO-PUBLISH.html  index.html  auto-demo.html
│   └── store\ (privacy policy, store texts)  fonts/  screenshots
│
├── tests\                  ← pytest suite (78 tests) + conftest.py
│
└── release artifacts (built, gitignored in the repo — GitHub Releases carry them):
    AdvPrint-Pro-Setup-2.5.0.exe · advprint-pro_2.5.0_all.deb ·
    AdvPrint-Pro-2.5.0.zip · AdvPrint-Pro-Extension-v2.5.0.zip ·
    Chrome-WebStore-Kit\
```

Only artifact **file names** carry the version — **folders never change**.

---

## 3. Where YOUR data lives (never touched by updates)

| Data | Location |
|---|---|
| Settings (token, debug, sumatra_path, share_lan…) | `%USERPROFILE%\.advprint\config.json` |
| Job history (SQLite) | `%USERPROFILE%\.advprint\jobs.db` |
| Audit log | `%USERPROFILE%\.advprint\audit.log` (and SQLite) |
| Saved PDFs (virtual printer / Save as PDF) | `%USERPROFILE%\Downloads\AdvPrint` |

The installed app keeps its runtime layout (`%LOCALAPPDATA%\AdvPrintPro\hub`,
`/opt/advprint/hub` for the deb) — that is the machine layout, independent of
the source tree above.

---

## 4. Update routine (from v2.5.0 on — always the same)

1. `AdvPrint-Pro-Setup-2.5.0.exe` over the old install (or extract full.zip
   over the same folder for portable use).
2. Chrome → `chrome://extensions` → AdvPrint Pro → **Reload**.
3. `http://127.0.0.1:9235/dashboard?token=…` → **Send test print & watch live**.

For the git repo: extract full.zip into the repo working copy → `git add -A`
→ commit. `doc/` (old duplicate) can be `git rm -r`'d once.
