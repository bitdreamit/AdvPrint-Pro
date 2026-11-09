# RELEASE NOTES v3.2.0 — THE ONE ALL-IN-ONE UI EVERYWHERE

**AdvPrint Pro** by Bit Dream IT — Innovative Healthcare Solutions
2026-11-09 · base: v3.1.3 · full source, no prebuilt binaries needed

---

## 1. One UI — no separate URLs any more

| URL | What it serves in v3.2.0 |
|---|---|
| `http://127.0.0.1:9235/` | THE ONE UI (browser opens the console directly) |
| `http://127.0.0.1:9235/ui` | THE ONE UI |
| `http://127.0.0.1:9235/dashboard` | THE ONE UI |
| `http://<LAN-IP>:9235/ui` | THE ONE UI in **CENTER PC UI** mode |
| extension `options.html → Console` | THE ONE UI in an iframe |

17 live panels — Dashboard · Queue · History · Printers · LAN Sharing ·
DropZone · Connections · Hub · Rules · Power Switches · **Tools (14)** ·
Extension · Debug · Audit · Logs · Settings · About — plus 9 working
menus, glossy toolbar, real QR codes, shortcuts (Ctrl+1…8, Ctrl+T,
Ctrl+N, Ctrl+R, F1, F5) and a toast confirmation on every action.

API clients are not affected: `GET /` still answers JSON for them.

## 2. SELF PC UI vs CENTER PC UI

The hub detects who opened the page:

- **Self PC** (the owner, on `127.0.0.1`): full control — all panels,
  all 14 tools, settings saving, token rotation, service management.
- **Center PC** (a LAN PC opening the share URL): the amber banner
  “CENTER PC UI — you are viewing the center printing PC’s hub” —
  printing, queue, history, rules, IPP queues and test pages work live;
  the 14 system tools show a note that they run on the center PC itself.

`?view=self` / `?view=center` forces a view (for previews/screenshots).

## 3. Tools (14) — the desktop tool menu inside the UI

`POST /tool {"action": ...}` (loopback + token only):

| # | action | what it does |
|---|---|---|
| 1 | `start` | hub already running (no-op) |
| 2 | `stop` | clean stop of the hub process |
| 3 | `status` | service + autostart + firewall + queue snapshot |
| 4 | `testprint` | A4 test page job |
| 5 | `service-install` | Windows service install (UAC) |
| 6 | `service-remove` | Windows service removal (UAC) |
| 7 | `autorun-toggle` | start-at-logon ON/OFF |
| 8 | `check-update` | GitHub latest-release check |
| 9 | `recent-jobs` | last 15 jobs from the hub DB |
| 10 | `uninstall` | remove autostart + service (files stay) |
| 11 | `livetest` | full A-to-Z self-test (steps returned) |
| 12 | `open-dashboard` | open the console in the OS browser |
| 13 | `diagnose` | combined diagnosis report |
| 14 | `restart` | clean relaunch |

The console **Tools (14)** panel renders exactly these — nothing extra
shown, nothing missing. `POST /tool` also accepts `fw-allow` (firewall
UAC) used by the Network menu.

## 4. Central rule manager (two-way sync)

- Console Rules panel: full editor — URL / address filter (glob,
  quick-fill chips incl. `*` = every site), **Match by** URL type or
  page content (ZPL / text / PDF / image / HTML), **What to print**,
  **Printer** picker, **Copies**, **Paper**, **On/Auto** toggle,
  **Runs** counter, per-rule Edit / Duplicate / Delete.
- Storage: hub config key `rules_mirror` (validated dict list via
  `POST /config`).
- The extension pushes its rules (live `runs` from ruleStats) to the
  hub after every change and adopts hub rules on a 5-minute alarm —
  **only when the local rules are unchanged** since the last sync
  (local edits always win; conflicts push local → hub).

## 5. Website whitelist — default `*` (ALL domains)

- `DEFAULTS.apiSites = ["*"]` in the extension: every website may call
  `window.advprint` / `printPdfLink` out of the box.
- Old installs without a stored list migrate to `["*"]`; a stored list
  is never overwritten.
- Restrict any time: Options → Connections → Website API permission.
- The live list is mirrored to the hub (`ext_api_sites`) and shown in
  the ONE UI Rules + Extension panels.

## 6. Silent install & multi-browser (Extension panel)

Policy force-install per browser (removes the “not listed in the Chrome
Web Store” warning, installs silently on every PC):

| Browser | Registry key (`HKLM\SOFTWARE\…` or `HKCU\Software\…`) |
|---|---|
| Chrome | `Google\Chrome\ExtensionInstallForcelist` |
| Edge | `Microsoft\Edge\ExtensionInstallForcelist` |
| Brave | `BraveSoftware\Brave-Browser\ExtensionInstallForcelist` |
| Chromium | `Chromium\ExtensionInstallForcelist` |
| Vivaldi | `Vivaldi\ExtensionInstallForcelist` |

Value: `1` = `<extension_id>;<hub>/extension/updates.xml` — the ONE UI
Extension panel shows the exact value with a one-click Copy.

## 7. Testing

`tests/test_one_ui_v320.py` (new): one-UI on all 3 routes, boot JSON
(self/center), ONE-UI content markers, `/tool` status + recent-jobs +
unknown action 400 + auth required, rules_mirror round-trip + junk
rejection, ext sites mirror, `apiSites ["*"]` default. Suite total:
**290 passed, 1 skipped**.

## 8. Files that changed

- `tool/unix/hub/advprint.py`, `tool/windows/portable/hub/advprint.py`
  (identical twins): VERSION 3.2.0, VERSION_NAME, console boot JSON
  injection, `/` `/ui` `/dashboard` rewired, `POST /tool`,
  `rules_mirror` validation, config keys.
- `tool/*/hub/console.html`: THE ONE UI v3.2.0 (replaces the 8-tab skin).
- `extension/background.js`: whitelist default `*`, migration, rules
  runs counter, hub two-way sync, site-list mirror.
- `extension/options.html`, `popup.html`: v3.2.0 chips, Website API
  copy, Console tab description.
- `extension/manifest.json`: version 3.2.0.
- `tests/*`: version pins + new v3.2.0 test file.
- `installer/setup.nsi`: 3.2.0. `VERSION.txt`, `CHANGELOG.md`.
