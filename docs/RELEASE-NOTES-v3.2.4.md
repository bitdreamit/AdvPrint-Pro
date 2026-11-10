# Release Notes - AdvPrint Pro v3.2.4
**THE TOOLBAR POPUP IS BACK**
by Bit Dream IT - Innovative Healthcare Solutions · 2026-11-10 · MIT license · 100% local

Base: v3.2.3 — every feature and fix unchanged. v3.2.4 delivers exactly
one change, the one asked for after the v3.2.3 rollout: **the quick
toolbar popup is back** (v3.2.2 had removed it; the toolbar icon opened
the console directly). The user kept the popup files and asked:
*"option need — why remove this feature popup — add again."*

---

## 1. The popup is BACK (with the Options button)

Clicking the toolbar icon opens the 340px quick popup again
(`manifest.json` carries `default_popup` again). The restored popup is
the full v3.2.1 feature set, adapted to the v3.2.3 branding decisions:

| Area | What you get |
|---|---|
| Header | brand logo + **AdvPrint Pro** + live version chip (v3.2.4) |
| Status | hub dot + "Connected - hub v…" (or LAN PC target), Connect link |
| Banners | offline + **Retry now** (flushes parked jobs) · default-token warning · token-rejected + one-click **Fix token** (`/token/current`) · held-jobs **Print now** |
| Power switches | **AdvPrint enabled** (master) · **Queue mode** (ordered queue + pause vs instant print) |
| LAN sharing switches | **Share Receive Mode** (hub `share_lan`, saved straight to the hub config) · **Share Send Mode** (print route to the LAN PC hub; refuses without a configured LAN PC) |
| Actions | **Print this page · Save as PDF · Print screenshot · Test page · Options** |
| Queue bar | queue state (RUNNING / red **PAUSED**) + pending count + Pause/Resume |
| Recent jobs | last 8 jobs with per-job one-click **Print now** for queued / held / failed / dead / scheduled / saved jobs |
| Footer | **branding only** — *100% local · no cloud. By Bit Dream IT - Innovative Healthcare Solutions.* |

### Branding decisions kept (from v3.2.3)

- The footer carries **no Console / Dashboard / Debug / API links** —
  every advanced option lives in THE ONE UI console; the popup's
  **Options** button opens the options page, which opens the console.
- The four footer-link listeners were removed from `popup.js` (their
  elements no longer exist — the old listeners would have thrown and
  killed every handler registered after them).
- "Change" token help now opens the branding-only options page, which
  shows its token field exactly when the hub refuses the token.
- Share-Send-without-URL opens the options page (console) instead of
  the removed `options.html#lan-settings` anchor.

### background.js / i18n.js

- The disabled-state error messages point at the popup again:
  *"enable it in the popup (toolbar icon)"*.
- The `chrome.action.onClicked` console-open handler stays as a
  built-in fallback (it only fires in builds without `default_popup`).
- Every popup string is verified present in **both UI languages**
  (36 keys, English + Bangla) — `tests/test_v324.py` locks this.

## 2. Everything else is UNCHANGED (all v3.2.3 fixes)

- Hub-panel switch save bug: fixed (both config types accepted +
  validated; live poll refresh; demo paths can never reach config.json).
- ONE UI, ONE BUTTON: toolbar = 4 real actions + LAN/IPP chips; the
  sidebar is the only tab switcher; no duplicated About/Settings.
- **Allowed IPs**: LAN Sharing → Allowed IPs — default `["*"]` = the
  whole LAN; real entries restrict to exactly those IPs / CIDR subnets /
  wildcards; console, portal, API, IPP 9235, the 631 mirror and RAW
  9100 all answer 403 / close; `127.0.0.1` can never be locked out;
  denials audited (`acl.denied`).
- Branding-only extension options page.
- Both IPP URL styles on 9235 + the 631 standard-port mirror, mDNS /
  AirPrint discovery, working switches, real menu actions.

## 3. Verification (what the tests lock)

`tests/test_v324.py` locks the popup contract:

- manifest has `action.default_popup: "popup.html"` and version 3.2.4;
- `popup.html` / `popup.js` / `i18n.js` exist in `extension/`;
- popup.html footer is branding-only (no `lnkDash`/`lnkConsole`/
  `lnkDebug`/`lnkApi` elements);
- popup.js contains NO references to the removed footer links and NO
  dead `options.html#…` anchors;
- every `AdvPrintI18n.t("…")` / `data-i18n` key used by the popup
  exists in i18n.js for both languages;
- every `chrome.runtime.sendMessage` type used by popup.js
  (`getCfg, saveCfg, hubStatus, hubJobs, hubConfigSet, printTab,
  printScreenshot, queueAction, jobPrintNow, flushRetries, retryInfo,
  tokenDetect`) exists in background.js;
- NSIS `setup.nsi` packs `popup.html` + `popup.js` again;
- version coherence: manifest 3.2.4 == hub `VERSION` == VERSION.txt.

Full suite result for this release: **347 passed, 1 skipped**
(335 on v3.2.3 + the 12 new v3.2.4 popup contract locks).

Known pre-existing suite flake (present before v3.2.4, unchanged): one
hub-thread timing test (`test_v23_instant_auto_queue` /
`test_virtual_pdf_printer_queue_saves_file`) can fail inside a FULL run
and passes on re-run / in isolation — a shared-state race between the
hub's background threads, not a product defect.

## 4. Upgrade

Run `AdvPrint-Pro-Setup-3.2.4.exe` over any previous install (or
`sudo dpkg -i advprint-pro_3.2.4_all.deb`). The extension updates
itself from the hub's `/extension/` auto-update endpoint; on a manual
"Load unpacked" install, reload it from `chrome://extensions`. After
update, click the toolbar icon — the popup opens.
