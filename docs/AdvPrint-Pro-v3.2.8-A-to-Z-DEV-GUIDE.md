# AdvPrint Pro v3.2.8 — A-to-Z DEVELOPMENT & BUILD GUIDE

> **v3.2.8 = "THE ipp:// + HTTP-PAGE FIX RELEASE" on top of v3.2.7.**
> Two real-world bugs the user hit on the AI-Lab PC, both fixed and
> locked by `tests/test_v328.py`. Everything from v3.2.7 — the complete
> Developer API guide, full extension-API parity, and every v3.2.2 -
> v3.2.6 fix — stays unchanged. The deep architecture reference (ONE UI
> anatomy, print pipeline, IPP engine, build internals) lives in
> `docs/AdvPrint-Pro-v3.2.7-A-to-Z-DEV-GUIDE.md` and is still exactly
> how v3.2.8 works; this guide documents the delta and the NEW
> delivery-layer fix.

> **BUG 1 — `ipp://http://` double protocol on the IPP landing page.**
> `ipp_landing_html()` prepended `ipp://` to `lan_share_url("ipp")` —
> but since the v3.2.6 QR fix that function returns an **http://** URL,
> so the page showed `ipp://http://192.168.1.101:9235/ipp/print` and
> Windows / macOS / iOS / CUPS refused the pasted address. The new
> `_ipp_scheme_url()` / `ipp_scheme_bare()` helpers strip the web
> scheme FIRST; the page now shows `ipp://192.168.1.101:9235/ipp/print`.
>
> **BUG 2 — `window.advprint.printPdf()` (and every page-API method)
> refused on http:// pages.** TWO layers, both fixed in v3.2.8:
>
> * **Code layer** — the v2.9.1 Website API allowlist (`background.js`
>   `apiSiteAllowed()`) pinned the SCHEME: `https://host/*` matched
>   https pages only. v3.2.8 rule: **the HOST is what you allow, not
>   the transport** — a pattern pinning http:// or https:// matches
>   that host on BOTH web schemes.
> * **Delivery layer (why the user still saw the bug)** — the hub
>   serves its embedded signed package at
>   `/extension/updates.xml` + `/extension/AdvPrint-Pro.crx` and Chrome
>   auto-updates ONLY when that package shows a HIGHER version. The
>   v3.2.8 build shipped a fresh 3.2.8 CRX to `dist/` and the installer
>   stage but **left the embedded hub copies stale at 3.2.6**
>   (`tool/unix/hub/extension/`, `tool/windows/portable/hub/extension/`)
>   — so every paired browser silently stayed on extension 3.2.6 with
>   the old scheme-pinned refusal. v3.2.8 syncs the embedded copies at
>   build time, hard-fails the build on drift, and the hub now reports
>   a `stale` flag (/health, /extension/info, /extension page) plus a
>   red Console warning when the served package is older than the hub.

> **Build flow (same as v3.2.7, one command each):**
> 1. edit `tool/unix/hub/console.html` (the ONE UI source),
> 2. re-embed it: `python3 scripts/embed_console.py` (NEW
>    version-agnostic helper — writes the `CONSOLE_HTML` constant into
>    BOTH advprint.py copies and mirrors console.html to the windows
>    portable hub; a stale embed means a stale UI),
> 3. build everything: `bash scripts/build-all.sh` (CRX3 + embedded-CRX
>    sync guard + extension zip + NSIS Setup EXE + DEB + SHA256SUMS
>    into dist/),
> 4. verify: `python3 -m pytest tests/` (full suite incl. the new
>    v3.2.8 locks).

---

## 2.8 What changed in v3.2.8 (the exact code map)

| Change | File | Detail |
|---|---|---|
| BUG 1 helpers | `tool/unix/hub/advprint.py` | NEW `_ipp_scheme_url(url)` + `ipp_scheme_bare(url)` right after `lan_share_url()` — strip `http://`/`https://`, prepend `ipp://`, idempotent |
| BUG 1 landing | `tool/unix/hub/advprint.py` | `ipp_landing_html()` uses `ipp_scheme_bare(lan_share_url("ipp"))` — the page shows `ipp://ip:9235/ipp/print` + the http:// URL; served by the hub port AND the 631 mirror |
| BUG 2 matcher | `extension/background.js` | `apiSiteAllowed()`: pattern pinning http/https matches that host on BOTH web schemes (`WEB && PINNED_WEB` clause); `*://`, bare host, `*.wildcard`, `file://` semantics unchanged |
| BUG 2 message | `extension/background.js` | `handleApi()` refusal now points to Console > Connections > Website API and suggests `*://<host>/*` |
| BUG 2 UI hint | `console.html` + embedded `CONSOLE_HTML` | Website API card documents the scheme rule inline |
| BUG 2 docs | `docs/DEVELOPER-API.md` | NEW "Website API permission" section (default `*`, four pattern forms, scheme rule, https-vs-http troubleshooting) |
| BUG 2 DELIVERY: build sync | `scripts/build-all.sh` | after CRX3 signing the fresh package is copied to `tool/unix/hub/extension/`, `tool/windows/portable/hub/extension/` and the installer stage; `cmp` + version parse HARD-FAIL the build if any embedded copy drifts or is older than `VERSION.txt` |
| BUG 2 DELIVERY: hub guard | `tool/unix/hub/advprint.py` | NEW `_ver_lt(a,b)` + `ext_health()` now returns `hub_version` and `stale` (served CRX older than hub); `/extension/info` returns both; the `/extension` page renders a red "Stale package — your browsers are NOT auto-updating" box with the exact fix |
| BUG 2 DELIVERY: console | `console.html` + embedded `CONSOLE_HTML` | Extension panel: hidden `#extStaleWarn` banner; `renderExt()` fetches `/extension/info` (open endpoint, no token), shows the REAL served version in the "CRX v… READY" chip (not the hub version) and the warning when `stale:true` |
| Embed helper | `scripts/embed_console.py` | NEW — version-agnostic replacement for the per-release embed_console_v3XX scripts; asserts no `"""` inside the UI source and byte-identical hub copies |
| Version | everywhere | VERSION.txt, VERSION/VERSION_NAME, manifest.json, popup.html, options.html, i18n.js (en+bn), api.js fallback, console boot fallback, setup.nsi, DEB control, README "What's new" |
| Release docs | `docs/RELEASE-NOTES-v3.2.8.md`, `docs/AdvPrint-Pro-v3.2.8-A-to-Z-DEV-GUIDE.md`, `CHANGELOG.md` | full notes + this guide + changelog entry |
| Tests | `tests/test_v328.py` | both fixes AND the delivery guard locked (see below); rolling version pins in older suites moved to 3.2.8 |

### 2.8.1 WHERE the http/https bug actually was (the full causal chain)

The user's report: *"advprint developer api window.advprint.printPdf —
https site ok work, but only http site not; direct URL open works on
both"*. Reproduced and verified live (Chromium + the REAL extension +
the REAL hub, both extension versions):

1. The page (http://localhost or any http:// site) calls
   `window.advprint.printPdf(url)` — the MAIN-world `api.js` hook is
   injected on http pages exactly like on https pages (manifest
   `content_scripts.matches` is `<all_urls>`; the dynamic
   `registerContentScripts` registrations are `<all_urls>` too — the
   manifest was NEVER the problem).
2. The ISOLATED-world `relay.js` forwards the call to the service
   worker (`chrome.runtime.sendMessage type:"api"`).
3. `handleApi()` checks the Website API allowlist. The site pattern was
   typed with the scheme pinned (`https://host/*` — following the
   docs' example style), and v3.2.6's `apiSiteAllowed()` compared
   scheme == pattern-scheme → `http://` origin REFUSED with
   `{"ok":false,"error":"AdvPrint page API is not allowed for
   http://host ..."}`.
4. The page's helper (the user's `AdvPrintHelper.url()`) sees
   `res.ok === false` → marks the hub down → falls back to the hidden
   iframe / `window.open(url)` → **the browser's own print path
   delivers the PDF**. That is why "urlopen pdf works for both" while
   the silent API "only works on https" — the PDF and the hub were
   never the problem; the page-API permission was.
5. **Why updating the hub did not fix it:** the extension inside
   Chrome is auto-updated from the hub's OWN package
   (`/extension/updates.xml`), and that embedded copy was still
   **3.2.6** — Chrome compares versions, sees no higher one, and never
   installs the fixed build. The v3.2.8 code fix existed, but the
   browser never received it.

Live proof (both runs with `apiSites = ["https://127.0.0.1/*"]`, call
from an `http://127.0.0.1:8093` page):

| Extension | `window.advprint.printPdf('http://…/test.pdf')` |
|---|---|
| 3.2.6 (the stale served package) | `{"ok":false,"error":"AdvPrint page API is not allowed for http://127.0.0.1:8093 …"}` |
| 3.2.8 (the release package) | `{"ok":true,"job_id":4,"status":"queued","message":"queued to printer"}` |

And the guard proof: with the hub running, swapping the embedded CRX
back to the 3.2.6 package makes `/extension/info` return
`{"version":"3.2.6","hub_version":"3.2.8","stale":true}` within a
second (no restart — `crx_package()` re-parses on file change), the
`/extension` page renders the red warning, `/health.extension.stale`
flips to `true`, and the Console Extension panel shows the banner.
Restoring the fresh package flips everything back.

### 2.8.2 The three-layer delivery fix (v3.2.8)

1. **Build layer** — `scripts/build-all.sh` step 1 now copies the
   freshly signed CRX into EVERY embedded location
   (`tool/unix/hub/extension/`, `tool/windows/portable/hub/extension/`,
   `installer/stage/hub/extension/`), byte-compares each against
   `dist/AdvPrint-Pro.crx`, parses the CRX manifest version and
   hard-fails (`exit 1`) unless it equals `VERSION.txt`. A future
   release can never again ship with a stale served package.
2. **Hub layer** — `ext_health()` (the `/health` `extension` block),
   `/extension/info` and the `/extension` page all expose
   `stale` + `hub_version`. The `/extension` page prints the red
   warning box with the exact remediation ("re-run the Setup, or copy
   the current AdvPrint-Pro.crx over hub/extension/AdvPrint-Pro.crx —
   no restart needed").
3. **Console layer** — the Extension panel chip shows the REAL served
   version (fetched from `/extension/info`, not the hub version) and
   the `#extStaleWarn` banner explains the trap in one sentence.

**How to get the fix into an already-paired browser (user-facing):**
update the hub to the v3.2.8 build, then EITHER re-run the Setup EXE
or copy `prebuilt/AdvPrint-Pro.crx` (v3.2.8) over the running hub's
`hub/extension/AdvPrint-Pro.crx` — Chrome picks the update up from
`/extension/updates.xml` within minutes (chrome://extensions >
Update, or just wait). No settings migration: an existing
`https://host/*` pattern simply starts covering the http:// twin.

### 2.8.3 v3.2.8 verification (what the tests lock)

- **Landing page**: with LAN sharing on, `ipp_landing_html()` contains
  `ipp://<lan-ip>:9235/ipp/print`, `http://<lan-ip>:9235/ipp/print`,
  and the string `ipp://http://` appears NOWHERE; the per-printer
  landing is untouched; the 631 mirror serves the same HTML.
- **Helper table**: `ipp_scheme_bare()` over `http://ip:p/x`,
  `https://ip:p/x`, `ipp://ip:p/x`, bare `ip:p/x`, `HTTP://IP:P/X`
  (uppercase scheme) — all yield the clean bare host:port/path.
- **Allowlist matrix** (`apiSiteAllowed` port — asserted in the JS
  source + mirrored in a Python re-implementation so it runs as a
  real test): `https://host/*` allows `http://host` AND `https://host`;
  `http://host/*` allows both too; `*://host/*` and bare `host` allow
  both; `*.example.org` covers subdomains on both schemes; an unrelated
  host and `file://` origin are still refused; empty list = API OFF.
- **Refusal text**: background.js contains the Console-pointing,
  pattern-suggesting error string; the old "Options > Website API"
  pointer is gone.
- **Console hint**: `SCHEME does not matter` present in console.html
  AND the embedded `CONSOLE_HTML`; hub copies byte-identical
  (unix vs windows portable, advprint.py + console.html).
- **NEW stale-CRX locks**: `_ver_lt()` truth table; BOTH embedded CRX
  copies parse to the hub VERSION; `ext_health()` reports
  `stale:false` with `hub_version` present; build-all.sh contains the
  sync + version-fail guard lines; console.html contains
  `extStaleWarn`/`extStaleTxt` and the `/extension/info` fetch.
- **Version 3.2.8 coherence** across VERSION.txt, hub, manifest,
  popup, options, i18n, api.js, console boot, setup.nsi.

### 2.8.4 How to verify by hand in 5 minutes

1. Open `http://<lan-ip>:9235/ipp/print` in a browser — the printer
   URL line must read `ipp://<lan-ip>:9235/ipp/print` (no
   `ipp://http://`).
2. Open `http://127.0.0.1:9235/extension/info` — must say
   `"version":"3.2.8","hub_version":"3.2.8","stale":false`. If it
   ever says `stale:true`, copy the fresh CRX over
   `hub/extension/AdvPrint-Pro.crx` and re-check (no restart).
3. In the Console, Connections tab > Website API, set the list to
   `https://your.host/*`, save.
4. On an `http://` page of the same host run in DevTools:
   `await window.advprint.status()` → answers `{ok:true,...}` (before
   v3.2.8 this returned the allowlist refusal).
5. `await window.advprint.printPdf('http://your.host/report.pdf')`
   prints silently, exactly like from the https site.
6. chrome://extensions → AdvPrint Pro must show **3.2.8** (if it is
   older, the hub was still serving a stale package — see step 2).

## 2.7 What changed in v3.2.7 (recap — see the v3.2.7 guide for full detail)

The Developer API release: `docs/DEVELOPER-API.md` (~600 lines), the
/docs + in-UI docs section 9, `window.advprint.print()` FULL API
parity (run_at / queue / dedupe / tray / watermark_text). All unchanged
in v3.2.8.

## 2.6 What changed in v3.2.6 (recap — see the v3.2.7 guide for full detail)

ONE UI v2 (self/center views), loopback-only UI security, IPP landing
page + mDNS, printer-details ipp:// URL fix, QR/http split, Website
API editor in the Connections tab. All unchanged in v3.2.8.

---

# (v3.2.0 architecture reference below — still exactly how it works)

## 0. What this product is (30-second map)

* **One local hub** (`advprint.py`, stdlib-only Python, port 9235):
  prints PDFs/pages/raw streams on the PC's real printers, keeps the
  queue/history/audit, serves the ONE UI console at `/ui` and the
  signed browser extension at `/extension/*`.
* **One Chromium extension** (`extension/`, MV3): hooks
  `window.print()` / Ctrl+P, prints the current tab silently, exposes
  the `window.advprint` developer API to allowed sites, talks ONLY to
  the local hub. Auto-installed and auto-updated from the hub itself
  (policy forcelist + `updates.xml`).
* **ONE UI** (`tool/unix/hub/console.html` → embedded `CONSOLE_HTML`
  constant inside BOTH `advprint.py` copies): self view + center view,
  zero external files, loopback-only by default.
* **Everything is local**: no cloud, no telemetry, token-authed HTTP,
  LAN sharing + IPP printer mode are explicit opt-ins.

## 1. Development environment

```bash
# any Linux with python3; Windows features build from the same tree
cd AdvPrint-Pro-3.2.8
python3 tool/unix/hub/advprint.py serve      # run the hub (port 9235)
python3 -m pytest tests/ -q                  # full suite (484 tests)
# data dir: ~/.advprint (config.json holds the API token)
# token:   cat ~/.advprint/config.json | python3 -c \
#           "import json,sys;print(json.load(sys.stdin)['token'])"
```

## 2. THE ONE UI — how it works (unchanged, see v3.2.7 guide §2)

`console.html` is the editable source. `scripts/embed_console.py`
writes it into the `CONSOLE_HTML = r"""…"""` constant of BOTH
`advprint.py` copies and mirrors the file to the windows portable hub —
the hub serves the embedded constant (the "console.html not found"
error can never happen). After ANY console.html edit: re-embed, then
build.

## 3. Rebuilding every artifact

```bash
bash scripts/build-all.sh
# dist/AdvPrint-Pro.crx                       signed CRX3 (repo key)
# dist/AdvPrint-Pro-Extension-3.2.8.zip       unpacked (store/dev)
# dist/AdvPrint-Pro-Setup-3.2.8.exe           NSIS installer (embedded CRX!)
# dist/advprint-pro_3.2.8_all.deb             Linux hub + embedded CRX
# dist/SHA256SUMS-3.2.8.txt
# NEW v3.2.8: build FAILS if any embedded hub CRX is stale or the CRX
# version does not equal VERSION.txt - the Bug-2 delivery trap is
# structurally impossible now.
```

## 4. Release checklist (the exact v3.2.8 process)

1. Code + tests green: `python3 -m pytest tests/ -q`.
2. Docs bumped: CHANGELOG.md, RELEASE-NOTES-v3.2.8.md, this guide,
   README "What's new", DEVELOPER-API.md troubleshooting.
3. `bash scripts/build-all.sh` — watch the NEW
   `embedded CRX copies synced + verified v…` line.
4. `python3 scripts/crx3.py info dist/AdvPrint-Pro.crx` → 3.2.8.
5. Live smoke on the running hub: `/extension/info` stale:false,
   `/ipp/print` clean `ipp://` URL, http-page `printPdf` queues a job.
6. Copy dist/* + the full package zip to the delivery folder.

## 5. Where things live (code map, v3.2.8)

```
advprint.py (hub, ONE file, both copies byte-identical)
  ├─ _ipp_scheme_url() / ipp_scheme_bare()   BUG 1 (v3.2.8)
  ├─ _ver_lt() / ext_health()                stale-CRX guard (v3.2.8)
  ├─ ipp_landing_html()                      /ipp/print how-to page
  ├─ crx_package() / _crx_paths()            served package (re-parses on change)
  ├─ route /extension, /extension/info, /extension/updates.xml
  └─ CONSOLE_HTML                            the ONE UI (embedded)
extension/
  ├─ manifest.json        <all_urls>, MV3, relay.js static
  ├─ content/api.js       window.advprint (MAIN world, CSP-immune)
  ├─ content/hook.js      window.print / Ctrl+P interception
  ├─ content/relay.js     MAIN⇄ISOLATED⇄service-worker bridge
  └─ background.js        apiSiteAllowed() scheme rule + handleApi()
tool/unix/hub/extension/AdvPrint-Pro.crx     embedded package (SERVED!)
tool/windows/portable/hub/extension/…        embedded package (SERVED!)
scripts/build-all.sh      build + NEW CRX sync guard
tests/test_v328.py        the v3.2.8 locks (36 tests)
```

## 6. Local verification workflow (how the release was UI-checked)

```bash
python3 tool/unix/hub/advprint.py serve &
# browser:
#   http://127.0.0.1:9235/ui            → SELF PC UI
#   http://127.0.0.1:9235/ui?view=center → CENTER PC UI banner + note
#   http://127.0.0.1:9235/extension     → served-package page (stale guard)
#   http://127.0.0.1:9235/ipp/print     → clean ipp:// URL (BUG 1)
# DevTools on any http:// page:
#   await window.advprint.status()      → {ok:true,…}   (BUG 2)
#   await window.advprint.printPdf(url) → job JSON      (BUG 2)
# then: pytest suite + build-all + smoke print via POST /print
```
