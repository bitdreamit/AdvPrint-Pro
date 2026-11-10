# AdvPrint Pro v3.2.8 - Release Notes
### by Bit Dream IT - Innovative Healthcare Solutions

**THE ipp:// + HTTP-PAGE FIX RELEASE.** Two real-world bugs reported
against v3.2.7 on the AI-Lab PC (2026-11-11), both fixed and locked by
new tests. Base: v3.2.7 - the complete Developer API guide
(`docs/DEVELOPER-API.md`), full extension-API parity and every earlier
fix unchanged.

---

## BUG 1 - the IPP landing page printed the protocol twice

**What the user saw** - opening the printer URL in a browser:

```
http://192.168.1.101:9235/ipp/print        <- typed in the browser

AdvPrint Pro - IPP network printer
This URL is the IPP print endpoint of AI-Lab.
Add it as a printer - do not open it in a browser:

ipp://http://192.168.1.101:9235/ipp/print  <- protocol TWICE - refused
```

**Root cause** - `ipp_landing_html()` (v3.2.2) built the printer URL
from `lan_share_url("ipp")`. Since the v3.2.6 QR fix that function
returns the **`http://`** URL (`http://192.168.1.101:9235/ipp/print`),
so the old `ipp_url.replace("ipp://", "")` call was a no-op and the
template's literal `ipp://` prefix landed in front of a full web URL.

**The fix** - new helpers in `tool/unix/hub/advprint.py`:

- `_ipp_scheme_url(url)` - strips `http://` / `https://` FIRST, then
  prepends `ipp://`. Idempotent: an URL already carrying `ipp://` (or
  a bare `host:port/path`) passes through unchanged.
- `ipp_scheme_bare(url)` - the same URL without the `ipp://` prefix,
  for the landing-page template which writes `ipp://` inside `<code>`.

`ipp_landing_html()` now renders (served by the hub port AND the 631
standard-port mirror - one source, both ports):

```
ipp://192.168.1.101:9235/ipp/print          <- add-printer URL (clean)
http://192.168.1.101:9235/ipp/print         <- browser-friendly URL
```

The per-printer landing page (`/ipp/print/<printer>`) already used the
correct `ipp_queue_url()` and needed no change. The console LAN tab,
QR modal and Copy buttons already built `ipp://` correctly (regex
`lanBase().replace(/^http:/, "ipp:")`) and stay as-is - locked since
v3.2.6 by `tests/test_v326.py`.

## BUG 2 - window.advprint worked on https:// but not on http:// pages

**What the user saw** - `window.advprint.printPdf(...)` (and every
other page-API method) worked from `https://` sites but was refused on
`http://` pages of the SAME site.

**Root cause** - the v2.9.1 Website API allowlist
(`extension/background.js`, `apiSiteAllowed()`) pinned the SCHEME: a
pattern typed as `https://host/*` matched `https://` pages only, so the
same site over `http://` was refused. Worse, the refusal message told
the user to add the site in "AdvPrint Pro **Options** > Website API" -
but the editor actually lives in the **Console** (Connections tab),
the extension Options page never had such a section, and nothing in
the docs explained the matching rules.

**The fix** - the HOST is what you allow, not the transport:

| Pattern in the list | v3.2.7 behavior | v3.2.8 behavior |
|---|---|---|
| `*` | every site, every scheme | unchanged |
| `*://host/*` | every scheme of host | unchanged |
| `host` (bare) | every scheme of host | unchanged |
| `https://host/*` | https://host ONLY | **http://host + https://host** |
| `http://host/*` | http://host ONLY | **http://host + https://host** |
| `*.example.org` | every scheme, subdomains | unchanged |
| `file://...` | (never matched web pages) | still never matches |

- `apiSiteAllowed()` scheme logic: a pattern pinning `http` or `https`
  matches that host on **both** web schemes; everything else keeps the
  old semantics. Host matching (exact / `*.subdomain` wildcards) is
  untouched - the allowlist stays as strict as before about WHO may
  print, it just stops refusing the insecure twin of a site you
  already trust.
- The refusal error now says exactly what to do and offers a
  ready-made pattern:
  `AdvPrint page API is not allowed for http://host - open the AdvPrint
  Pro Console (/ui), Connections tab > Website API, and add this site
  (one line: *://host/*, or * for ALL sites)`.
- The console Website API card hint documents the scheme rule inline
  (embedded `CONSOLE_HTML` + `console.html`, kept in sync by the new
  `scripts/embed_console.py`).
- `docs/DEVELOPER-API.md` gained a full **"Website API permission"**
  section: the default `*`, all four pattern forms, the v3.2.8 scheme
  rule, and the troubleshooting case "works on https, not on http".

**No data migration needed** - existing https-pinned patterns keep
working exactly as before AND now also cover http; no stored settings
are rewritten.

---

## BUG 2 - DELIVERY layer: the hub was still serving extension 3.2.6

**Why the bug survived the update** - the browser extension is
auto-updated from the hub's own signed package
(`/extension/updates.xml`), and Chrome installs a new version ONLY
when that package shows a HIGHER version. The first v3.2.8 build put
the fresh 3.2.8 CRX into `dist/` and the installer stage but left the
EMBEDDED hub copies stale at **3.2.6** - so every paired browser
silently kept running the old extension with the old scheme-pinned
refusal. The fix existed; the browser never got it.

**The v3.2.8 delivery fix (three layers):**

1. `scripts/build-all.sh` now copies the freshly signed CRX into BOTH
   embedded hub locations (`tool/unix/hub/extension/`,
   `tool/windows/portable/hub/extension/`) plus the installer stage,
   byte-compares every copy and HARD-FAILS the build when any copy is
   stale or the CRX version does not equal the hub version.
2. The hub reports the state: `/health` (`extension.stale`,
   `extension.hub_version`), `/extension/info` (same fields) and the
   `/extension` page (red "Stale package - your browsers are NOT
   auto-updating" warning with the exact remediation). Dropping a
   fresh CRX over the old one heals a RUNNING hub - no restart
   (`crx_package()` re-parses when the file changes).
3. The ONE UI Console Extension panel shows the REAL served version in
   the "CRX v... READY" chip and a red warning banner when stale.

**User-facing upgrade path** - re-run the v3.2.8 Setup EXE, or copy
`prebuilt/AdvPrint-Pro.crx` (3.2.8) over the running hub's
`hub/extension/AdvPrint-Pro.crx`; then let Chrome update
(chrome://extensions > Update) and confirm it shows **3.2.8**.

---

## Everything else - unchanged from v3.2.7

- The complete Developer API guide in three places
  (`docs/DEVELOPER-API.md`, hub `/docs` section 9, in-UI Docs modal
  section 9): `window.advprint` method-by-method, `POST /print` with
  the four body styles, SAME PC MANY PRINTERS, MANY PCs ONE HUB,
  ZPL `^XA...^XZ` + ESC/POS marker raw printing, `run_at` scheduling,
  `priority`, page ranges + odd/even, n-up, duplex, quality/DPI,
  profiles, `queue:false` instant mode, dedupe, watermark.
- Full extension-API parity (`run_at`, `queue`, `dedupe`, `tray`,
  `watermark_text` ride along from `window.advprint.print()`).
- All v3.2.2-v3.2.6 fixes: history/queue clear really cleans, printer
  Details no longer doubles `/ipp/print`, LAN panel switches +
  token-carrying Copy URL, QR encodes `http://` while copy keeps
  `ipp://`, docs button inside the UI, LOCAL-ONLY console.

## Verification

- `tests/test_v328.py` (new): the landing page shows one clean
  `ipp://` URL and never `ipp://http://`; `_ipp_scheme_url` /
  `ipp_scheme_bare` table tests (http, https, already-ipp, bare,
  uppercase scheme); `apiSiteAllowed` scheme-equivalence matrix
  (https-pinned pattern allows the http twin, http-pinned allows the
  https twin, file:// still refused, host wildcards intact, `*` and
  bare-host unchanged); the refusal message points to the Console;
  console hint text present in the embedded UI; version coherence
  3.2.8 everywhere; hub copies byte-identical.
- Rolling version pins in test_hub_v2 / test_one_ui_v321 / v322 /
  v323 / v324 / v325 / v326 / v327 moved to 3.2.8 - the historical
  content checks are untouched.
- Full suite: `python3 -m pytest tests/` (484 passed, 1 skipped).
- NEW stale-CRX locks: both embedded hub CRX copies parse to 3.2.8;
  `ext_health()` reports `stale:false` + `hub_version`; `_ver_lt()`
  truth table; build-all.sh carries the sync + hard-fail guard; the
  console carries the `#extStaleWarn` banner + `/extension/info`
  fetch.
- Live proof (Chromium + real extension + real hub, `apiSites` pinned
  to `https://127.0.0.1/*`, call from an `http://127.0.0.1` page):
  extension 3.2.6 -> `"AdvPrint page API is not allowed for
  http://..."`; extension 3.2.8 -> `{"ok":true,...,"status":"queued"}`.
  Swapping the embedded CRX back to 3.2.6 flips `/extension/info` to
  `stale:true` within a second, without a hub restart.
