# AdvPrint Pro v3.2.3 — A-to-Z DEVELOPMENT & BUILD GUIDE

> **v3.2.3 = "CLEAN UI, ONE BUTTON + EVERY SWITCH VERIFIED + ALLOWED
> IPS" on top of v3.2.2.** (1) The Hub-tab switch bug is fixed for
> real — `escpos_codepage`/`thermal_text_engine` were missing from the
> accepted config types, so every Hub-panel save died with 400 and no
> Hub switch ever persisted; they are now accepted + validated, the
> Hub panel refreshes on every poll and demo placeholder paths can no
> longer reach config.json. Every switch is verified end-to-end in a
> real browser (click → POST /config → server state → reload).
> (2) ONE UI, ONE BUTTON — the toolbar carries only the four real
> actions (New Job, Pause Queue, Release ALL, Test Page) + LAN/IPP
> status chips; the ten nav buttons that duplicated the sidebar, the
> five address-bar pills, the dashboard Quick-actions card and the
> dashboard Test Page / Open Printers duplicates are GONE; the sidebar
> is the only tab switcher. (3) NEW Allowed IPs — LAN Sharing >
> Allowed IPs: default ["*"] = whole LAN; once real IPs are added ONLY
> those may connect (console, portal, API, IPP 9235 + 631, RAW 9100 —
> all 403 / closed; 127.0.0.1 always allowed; denials audited as
> acl.denied). (4) The extension options page is branding-only with
> the footer "100% local · no cloud. AdvPrint by Bit Dream IT -
> Innovative Healthcare Solutions."

> **Build flow (unchanged since v3.2.1, one command each):**
> 1. edit `tool/unix/hub/console.html` (the ONE UI source),
> 2. re-embed it: `python3 scripts/embed_console_v322.py` (writes the
>    `CONSOLE_HTML` constant into BOTH advprint.py copies and syncs the
>    windows console.html),
> 3. build everything: `bash scripts/build-all.sh` (CRX3 + extension
>    zip + NSIS Setup EXE + DEB + SHA256SUMS into dist/),
> 4. verify: `python3 -m pytest tests/` + `python3
>    /home/z/my-project/scripts/switch_verify_v323.py` (live browser
>    switch verification) + Playwright screenshots of all 17 tabs.

## 2.3 What changed in v3.2.3 (the exact code map)

| Area | File | Change |
|---|---|---|
| Hub switch 400 bug | `advprint.py` | `CONFIG_TYPES` += `escpos_codepage: str`, `thermal_text_engine: str` (validated in POST /config: codepage `^[a-z0-9_-]{1,24}$`, engine `auto|builtin|browser`); these were MISSING, so every Hub-panel switch save was rejected 400 |
| Hub panel live refresh | `console.html` | `poll()` now calls `refreshHubPanel()` every 3 s (was only on tab open) — inputs can no longer carry demo values into a save |
| Demo-path guard | `console.html` | `saveHub()` includes `file_dir`/`sumatra_path` only when the value differs from the live config |
| Toolbar dedupe | `console.html` | toolbar = New Job + Pause Queue + Release ALL + Test Page (ids `tbNew/tbPause/tbRelease/tbTest`, no `data-tab`) + status chips `chipLan`/`chipIpp`; Pause label flips with `pausedState` in `renderFrame()`; the 10 nav `tbtn`s removed |
| Address bar dedupe | `console.html` | the five pill buttons removed (QRs: Network menu + LAN tab) |
| Dashboard dedupe | `console.html` | Quick-actions card removed; p-head keeps Refresh; printer-card Test Page / Open Printers removed |
| ALLOWED IPS matcher | `advprint.py` | `ip_allowed_by_list(ip, rules)` — `*`, exact IP, CIDR (`ipaddress`), wildcard (`fnmatch`); `::ffff:` + zone-suffix normalisation; bad CIDR falls back to text compare (typos can only tighten) |
| ALLOWED IPS gate | `advprint.py` | `Handler._ip_gate()` runs in `do_GET`/`do_POST` before auth; branded 403 HTML (footer branding) + JSON 403; audits `acl.denied` (1 per 10 s/IP); `IPP631Handler` gates GET+POST (+ own `_is_loopback`); RAW 9100 accept-loop closes denied IPs |
| ALLOWED IPS config | `advprint.py` | CFG `allowed_ips` default `["*"]`; in CONFIG_KEYS + CONFIG_TYPES(list); POST /config cleans the list (empty / `*` → `["*"]`); /health reports `allowed_ips` + `acl_restricted` |
| ALLOWED IPS UI | `console.html` | LAN tab card: mode chip `aclMode`, input `aclInput`, buttons `aclAdd`/`aclAllowAll`, list `aclList`; `renderAcl()` (called from `renderLanRows()`), `saveAcl()`, `aclWire()` (Enter-to-add) |
| Options = branding | `extension/options.html`+`options.js` | brand card + footer "100% local · no cloud. AdvPrint by Bit Dream IT - Innovative Healthcare Solutions."; auto-opens the console (click to retry); token row only when the hub refuses |
| Version | everywhere | VERSION.txt, `VERSION`/`VERSION_NAME`, manifest 3.2.3, NSIS `VIProductVersion 3.2.3.0` + OutFile …3.2.3.exe, DEB control (auto from VERSION.txt) |

---

## 2.2 What changed in v3.2.2 (the exact code map)

| Area | File | Change |
|---|---|---|
| Standard-port IPP mirror | `advprint.py` | `IPP631Handler` + `ipp631_listen_start/stop/ensure()`; config `ipp_standard_port` (default 631); serves only /ipp/print(+/<printer>), landing page + redirects; health refresher hooks it every 3 s |
| IPP landing page shared | `advprint.py` | new `ipp_landing_html()` — one source for both ports, shows ipp:// AND http:// URLs + the 631 note when the mirror is up |
| Discovery decoupling | `advprint.py` | `_ipp_mdns_loop` want = `ipp_printer AND ipp_mdns` (share_lan removed); `lan_listen_ensure` want = `share_lan OR ipp_printer` |
| mDNS TXT | `advprint.py` | adds `usb_MFG=Bit Dream IT`, `usb_MDL=AdvPrint Pro Hub` (Mopria display name) |
| Health fields | `advprint.py` | `/health` now returns `ipp_urls {ipp,http,std}`, `ipp_mdns_up`, `ipp_std {up,port,err}` |
| Switches that work | `console.html` | `bindSwitches()` = ONE delegated document-level click handler on `.switch` inside `.tgl/.f-row/#rulemodal`; `swSave()` debounces 400 ms → `saveExtPrefs()/saveHub()/saveSettingsPanel()`; `swDirty()` guards the 3 s poll; saves clear dirty keys |
| Menu linkups | `console.html` | 13 `data-toast="…(demo)"` items replaced with `data-act=`, `data-tool=`, `data-goto=`; menu clicks close the dropdown |
| Dedupe | `console.html` | removed both "Save & push to browsers" buttons, dashboard quick-action duplicates, DropZone double "Open folder" |
| IPP guide card | `console.html` | LAN tab: per-platform table (Windows 10/11, macOS, iPhone/iPad, Android) with live-filled ids `ippUrlIpp`, `ippUrlHttp`, `ippGuideWin/MacHost/Android/Android631/RawIp`; live chips rows `row-mdns`, `row-ipp631` |
| No popup | `extension/` | `popup.html`/`popup.js` deleted; manifest `action` has no `default_popup`; `chrome.action.onClicked` opens `<hubUrl>/ui?token=…`; wording switched to Console |
| Firewall | `installer/setup.nsi` | + TCP 631 rule "AdvPrint Pro IPP 631" |
| Version | everywhere | VERSION.txt, `VERSION`/`VERSION_NAME`, manifest 3.2.2, NSIS `VIProductVersion 3.2.2.0` + OutFile …3.2.2.exe, DEB control (auto from VERSION.txt) |

## 2.3 v3.2.2 verification (what the tests lock)

- `tests/test_v322.py` (16 tests): the mirror answers a REAL IPP
  Print-Job (RFC 8010 wire form) with `successful-ok` and queues the
  job; landing page + redirect behavior; `ipp_standard_port` config
  round-trip; `/health` carries the new fields; discovery no longer
  depends on share_lan; LAN listener follows ipp_printer; AirPrint TXT
  keys; the delegated switch handler + instant-save wiring; tray-managed
  switches refuse; NO popup files + manifest has no default_popup +
  onClicked opens /ui; ZERO demo-stub menu items; all 13 real menu
  actions present; no duplicate "Save & push" buttons; LAN tab
  platform guide + live fill.
- Full suite: **318 passed, 1 skipped** (was 302 on v3.2.1).

---

# (v3.2.0 architecture reference below - still exactly how it works)

**AdvPrint Pro** by Bit Dream IT — Innovative Healthcare Solutions
The complete development process: architecture, every artifact, every
build command, from `git clone` to a deployed LAN. No prebuilt binaries
required — everything rebuilds from this tree alone.

---

## 0. What this product is (30-second map)

```
AdvPrint Pro
├── hub (Python, pure stdlib, port 9235)
│     tool/unix/hub/advprint.py          the whole hub (one file, twin copies)
│     tool/*/hub/console.html            THE ONE UI (dev copy; the hub
│                                        serves the EMBEDDED CONSOLE_HTML)
│     tool/*/hub/tool.py                 desktop tool menu [1]…[14] (14 tools)
│     tool/*/hub/tray_windows.py         Windows tray icon
│     tool/*/hub/gui_app.py              native window wrapper (loads /ui)
│     tool/*/hub/service_main.py         Windows service entry
├── extension (Chrome / Edge / Brave / Chromium / Vivaldi, MV3)
│     extension/manifest.json · background.js · options.html/js · popup
├── installer/
│     setup.nsi                          Windows Setup EXE (NSIS)
│     deb/                               Linux DEB (systemd user service)
├── tool/crx3.py                          CRX3 packer/signer (repo key)
├── extension-signing/advprint-printer.pem fixed extension id key
├── scripts/build-all.sh                  builds EVERYTHING into dist/
└── tests/                                pytest suite (301 tests)
```

Two rule that never changed:

1. **Print traffic** = extension → hub (`X-AdvPrint-Token` header) → OS
   printer (or per-printer IPP queue, or DropZone, or rules).
2. **Management traffic** = same token, same hub: `/health /stats
   /queue /printers /jobs /audit /config /debug /tool …`.

---

## 1. Development environment

| Tool | Used for | Install |
|---|---|---|
| python3 ≥ 3.9 | hub, tests, CRX3 packer, QR generator | preinstalled (Win: python.org) |
| pytest | 290-test suite | `pip install pytest` |
| zip | extension zip | `apt-get install zip` |
| dpkg-deb | DEB package | preinstalled on Debian/Ubuntu |
| NSIS 3.x (`makensis`) | Setup EXE | `apt-get install nsis` |
| Node.js ≥ 18 (optional) | JS syntax check, ONE-UI regression | nodejs.org |
| Playwright (optional) | UI screenshot / interaction checks | `pip install playwright` |

First run:

```bash
git clone https://github.com/bitdreamit/AdvPrint-Pro.git
cd AdvPrint-Pro
python3 -m pytest tests/ -q          # 290 passed, 1 skipped
python3 tool/unix/hub/advprint.py serve    # hub on http://127.0.0.1:9235
```

Run the hub against a scratch data dir while developing:

```bash
ADVPRINT_DATA=/tmp/ap-data python3 tool/unix/hub/advprint.py serve
# token: cat /tmp/ap-data/config.json | python3 -c "import json,sys;print(json.load(sys.stdin)['token'])"
```

---

## 2. THE ONE UI — how it works (v3.2.0 architecture)

### 2.1 One page, three URLs

`console.html` is a single self-contained file (CSS + HTML + JS, no
dependencies). The hub serves it on **every** browser route:

| route | served by | view |
|---|---|---|
| `GET /` | `do_GET` root branch (Accept: text/html only) | self / center |
| `GET /ui` | `do_GET` `/ui` branch | self / center |
| `GET /dashboard` | `do_GET` `/dashboard` branch | self / center |

`console_page_bytes(view)` (advprint.py) reads the file and replaces the
placeholder `<script id="bootjson" type="application/json">
__ADVPRINT_BOOT_JSON__</script>` with real JSON:

```json
{"view":"self|center","host":"AI-Lab-PC","lan_ip":"10.26.94.206",
 "port":9235,"version":"3.2.0"}
```

- `view:"self"` — the request came from loopback (the hub PC's owner).
- `view:"center"` — the request came from the LAN: the page renders the
  amber **CENTER PC UI** banner and hides the 14 system tools.
- `?view=self|center` query overrides both (previews/screenshots).
- API clients (`Accept:` not text/html) still get JSON at `/`.

The classic dashboard function `dashboard_html()` remains in the code
(tests embed it), it is simply no longer the browser answer.

### 2.2 Page anatomy (console.html)

| Block | Content |
|---|---|
| title bar | AP logo, live `tSub` = version · PC name · view |
| menu bar | 9 menus (File/View/Queue/History/Printers/Network/Hub/Tools/Help), 40+ live items |
| toolbar | New Job · Test Page · Pause Queue · History · Release ALL · LAN · DropZone · Connections · Hub · Rules · Tools(14) · Power · Debug · Settings · About |
| address bar | live hub dot + `hubUrl` + token lock + QR pill |
| center banner | amber, only in center view |
| sidebar | 218px tree, 17 panels, live count badges |
| content | 17 `<section class="panel" id="p-…">` |
| status bar | hub state · version · view · queue · printers · URL |
| modals | QR enlarge, keyboard shortcuts, rule editor, confirm |
| cards | token card + offline card (shown when needed) |

### 2.3 JS wiring (all vanilla, no framework)

```js
api(path, opts)            fetch + X-AdvPrint-Token header, 401 → token card
poll()                     /health /stats /queue /printers /jobs /audit
                           /config every 3 s → renders all panels
ACTIONS{...}               every data-act button (queue ops, exports, QR,
                           copy, rotate, restart, firewall, LAN test…)
runTool(action)            POST /tool → dark output box (status / livetest
                           steps / recent jobs / diagnose / update check)
renderRules()              central rule manager table + editor modal
SWITCH_MAP / dirtyKeys     power switches save instantly (POST /config),
                           settings switches wait for Save
openQR(kind)               real SVG from hub /qr?kind=send|invite|ipp
```

Console ↔ extension sync (background.js):

```
options/rules edited  ──push──▶  POST /config {rules_mirror, ext_api_sites}
alarm (5 min)        ◀──pull──   GET /config → adopt rules_mirror ONLY if
                                  local rules unchanged since last sync
rule fired           ──runs──▶   ruleStats.runs merged into every push
```

### 2.4 The 14 tools (parity with tool.py)

`POST /tool {"action": …}` — loopback + token only. One handler, 14
actions + `fw-allow`: start, stop, status, testprint, service-install,
service-remove, autorun-toggle, check-update, recent-jobs, uninstall,
livetest, open-dashboard, diagnose, restart. Each action maps to the
same module functions the desktop tool calls (`service_state`,
`cmd_service`, `autostart_set`, `run_livetest`, `db_list`,
`firewall_rule_ok`, …) so behaviour is identical.

---

## 3. Rebuilding every artifact

### 3.1 One command

```bash
python3 -m pytest tests/ -q      # always test first
bash scripts/build-all.sh        # → dist/ (CRX, ext zip, EXE, DEB, SHA256)
```

`build-all.sh` reads the version from `VERSION.txt`, packs + signs the
CRX3, stages `tool/windows/portable/{hub,install}` + runtime + docs,
builds the NSIS EXE and the DEB, writes SHA256SUMS.

### 3.2 CRX3 + extension zip only

```bash
python3 tool/crx3.py pack extension \
        extension-signing/advprint-printer.pem dist/AdvPrint-Pro.crx
python3 tool/crx3.py info dist/AdvPrint-Pro.crx    # verify id + 3.2.0
( cd extension && zip -r ../dist/AdvPrint-Pro-Extension-3.2.0.zip . )
```

The repo key pins the extension id `likldbkamojokkfdlcjibiljpgbbnohc`
(keep the key, keep the id — force-installed browsers auto-update from
your hub's `updates.xml`).

### 3.3 Windows Setup EXE (NSIS)

```bash
( cd installer && makensis -V2 setup.nsi )   # → dist/AdvPrint-Pro-Setup-3.2.0.exe
```

What the EXE does: bundles Python runtime (`installer/stage/runtime/`),
installs hub + console.html, registers the `AdvPrint` service, writes
the `ExtensionInstallForcelist` policy for Chrome (Chrome/Edge/Brave
variants), adds the firewall rule, starts the tray.

### 3.4 Linux DEB

```bash
dpkg-deb --build --root-owner-group installer/deb dist/advprint-pro_3.2.0_all.deb
sudo dpkg -i dist/advprint-pro_3.2.0_all.deb
```

### 3.5 Silent / multi-browser deploy (per PC)

Value line for every Chromium browser (copy from the ONE UI Extension
panel): `<ext-id>;http://<hub-ip>:9235/extension/updates.xml`

| Browser | `HKLM\SOFTWARE\` path |
|---|---|
| Chrome | `Google\Chrome\ExtensionInstallForcelist` |
| Edge | `Microsoft\Edge\ExtensionInstallForcelist` |
| Brave | `BraveSoftware\Brave-Browser\ExtensionInstallForcelist` |
| Chromium | `Chromium\ExtensionInstallForcelist` |
| Vivaldi | `Vivaldi\ExtensionInstallForcelist` |

Registry commands (admin cmd):

```bat
reg add "HKLM\SOFTWARE\Google\Chrome\ExtensionInstallForcelist" /f /v 1 /t REG_SZ /d "likldbkamojokkfdlcjibiljpgbbnohc;http://10.26.94.206:9235/extension/updates.xml"
reg add "HKLM\SOFTWARE\Microsoft\Edge\ExtensionInstallForcelist" /f /v 1 /t REG_SZ /d "likldbkamojokkfdlcjibiljpgbbnohc;http://10.26.94.206:9235/extension/updates.xml"
```

Policy install is silent and never shows the “not listed in the Chrome
Web Store” warning. Drag-in installs (chrome://extensions, developer
mode) always show that warning — the policy is the fix.

---

## 4. Release checklist (the exact v3.2.0 process)

1. `VERSION.txt` → `3.2.0` (single source; NSIS + deb + CRX read it).
2. `advprint.py`: `VERSION`, `VERSION_NAME` (twin copies stay identical
   — `cp tool/unix/hub/advprint.py tool/windows/portable/hub/`).
3. `extension/manifest.json` version; options/popup ver chips.
4. `installer/setup.nsi` OutFile/VIProductVersion/DisplayVersion.
5. Tests: pin updates (`tests/test_hub_v2.py` version anchors) + new
   feature tests (`tests/test_one_ui_v320.py` for v3.2.0).
6. `python3 -m pytest tests/ -q` → all green.
7. `bash scripts/build-all.sh` → dist artifacts + SHA256SUMS.
8. `docs/RELEASE-NOTES-v3.2.0.md` + `CHANGELOG.md` entry.
9. Git: `git add -A && git commit -m "v3.2.0 THE ONE ALL-IN-ONE UI
   EVERYWHERE" && git tag v3.2.0 && git push --tags`.
10. GitHub Release → upload CRX, ext zip, EXE, DEB, SHA256SUMS.

---

## 5. Where things live (code map, v3.2.0)

| Change | File | Place |
|---|---|---|
| one-UI on / · /ui · /dashboard | `tool/*/hub/advprint.py` | `_do_get_impl`: root branch (Accept: text/html), `/ui`, `/dashboard`; helper `console_page_bytes()` |
| self/center detection | same | each route: `self._is_loopback()` + `?view=` override |
| 14 tools API | same | `do_POST` → `route == "/tool"` |
| rule mirror validation | same | `POST /config` list branch, `key == "rules_mirror"` |
| config keys | same | `CFG` defaults + `CONFIG_KEYS` + `CONFIG_TYPES` |
| ONE UI page | `tool/*/hub/console.html` | whole file (CSS → HTML → JS) |
| whitelist default `*` | `extension/background.js` | `DEFAULTS.apiSites`, onInstalled migration |
| rules sync / runs | same | `HUB_SYNC_ALARM` block + `bumpRuleStats` |
| policy per browser | `tool/*/hub/console.html` | Extension panel table |
| desktop 14 tools | `tool/*/hub/tool.py` | unchanged (menu parity) |

## 6. Local verification workflow (how every release is UI-checked)

```bash
python3 tool/unix/hub/advprint.py serve &                 # real hub
# browser:
#   http://127.0.0.1:9235/ui          → SELF PC UI
#   http://127.0.0.1:9235/ui?view=center → CENTER PC UI banner + note
#   http://127.0.0.1:9235/dashboard   → same ONE UI
#   http://127.0.0.1:9235/            → same ONE UI (browser)
# then: pytest suite + build-all + smoke print via POST /print
```

Playwright screenshot recipe (used for the release previews):
navigate each panel id (`#p-dashboard`, `#p-queue`, …, `#p-tools`),
click a menu, open the QR modal, press Ctrl+2 — assert no horizontal
overflow and no JS pageerror.

---

*by Bit Dream IT — Innovative Healthcare Solutions · full source, A-to-Z
rebuildable, 290 tests green.*
