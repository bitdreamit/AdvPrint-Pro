# v3.4.7 - CONFIGURABLE HUB PORT + DROPZONE WATCH FIX + STRICT LAN SHARE + URL RULES THAT REALLY MATCH (2026-11-14)

**Base: v3.4.6** — one port for every queue, the popup printer memory,
the manual LAN/IPP re-scan and the auto-CRX-on-install machinery all
stay. Every item below is locked by `tests/test_v347.py`.

---

## 1. The hub port is configurable (default 9235 — but not anymore, if you need it)

**You asked:** *"port hub by default 9235 but user can also change hub
port to dynamic any port set and hub restart it show default port for
this hub. it needed if any pc has already exist same port for
different software."*

The Settings > HUB PORT field existed in the ONE UI for years — but it
only showed a toast. Now it really saves:

| Way to change | How |
|---|---|
| ONE UI | Settings → HUB PORT → type the port → **Save & Apply** → **Restart hub** |
| Classic dashboard | (restart via the dashboard, then the ONE UI field above) |
| CLI | `python advprint.py port 9300` (no argument = show the current port) |
| config.json | `"port": 9300` in the data dir |
| Environment | `ADVPRINT_PORT=9300` (wins over config.json, as always) |

- Validation: 1024–65535; 631 / 5353 / 9100 are refused (the hub's own
  IPP mirror, mDNS and RAW listener).
- After **Restart hub** the hub listens on the new port and shows it
  everywhere — banner, /health, the Settings field, the pairing URLs,
  the IPP printer URL, mDNS.
- Saving answers with a loud note: the hub keeps answering on the OLD
  port until the restart, and every hub URL (this browser, other PCs,
  IPP printer URLs) must use the NEW port afterwards.
- If another program owns the port at boot, hub.log prints all the
  ways to move the hub to a free one.

## 2. DropZone watch really toggles now

**You asked:** *"Drop zone not work last few version alwase disable
dropzone watch off when click to open."*

Found it: the ONE UI DropZone header button was a static **"Disable"**
that ALWAYS sent `drop_enabled:false`. Clicking it when the watch was
ON killed the watch; when it was OFF nothing could ever turn it on.
The watcher itself was never broken. The button is a real
**Enable / Disable toggle** now — the label follows the live state,
clicking posts the opposite, and the "watching" stat shows ON/OFF.

## 3. Strict LAN share — see who hits the hub, allow with one click

**You asked:** *"Strict mode lan share if on it show which ip hit this
printer all diffrent hited ip show here then hit add allow list then
this printer can print through hub."*

- ONE UI → **LAN Sharing → Strict LAN mode** (switch + table) or the
  classic dashboard LAN card.
- While the switch is ON, the hub records EVERY distinct IP that
  touches it — console, send portal, print API, IPP — **even refused
  ones**, with hit count, first-seen and last-hit.
- Each row has **Allow** (adds the IP to Allowed IPs; if the list was
  `*` it becomes that IP ONLY — the lock-down moment, the toast says
  so) or **Remove** (blocks it again). Clear + Refresh included.
- Nothing is blocked by the switch itself — blocking is exactly what
  the Allowed-IPs list does. The workflow: switch ON → watch the hits
  → Allow the real PCs → the list locks the hub down by itself.

## 4. URL print rules that really match (your htncr.org lab set)

**You asked:** *"how set rule ... give proper doc how current design
solve this ... how handel those kind regex uri/url rule dynamic id or
any needed or domain or more."*

Two defects were hiding in the old Rules UI: the editor never saved a
pattern TYPE (the hub stripped it — every rule silently degraded to a
`*`-glob, so regex with dynamic ids was impossible), and the "Test
which rule fires" card was dead demo content. Now:

- **Pattern type** select in the editor: **Glob** (`*` wildcard) /
  **Regex** (dynamic ids) / **Contains** (easiest) — saved and kept.
- **Ready recipes** dropdown preloaded with your lab set:

| Your URL | Recipe (type + pattern) | Printer |
|---|---|---|
| `…/medical_reports/pdf/203182?tests%5B%5D=671839` | regex `htncr\.org/lab/medical_reports/pdf/\d+\?tests%5B%5D=\d+$` | Report printer |
| `…/medical_reports/pdf/…?tests%5B%5D=671843&tests%5B%5D=…` (many ids) | **no rule needed** — the `$` anchor makes it fall through | OS default (A4) |
| `…/lab/sample/203182` | regex `htncr\.org/lab/sample/\d+$` (action: raw ZPL) | Zebra |
| `…/lab/receipt-print/203695/client` (all/lab/admin too) | regex `htncr\.org/lab/receipt-print/\d+/(client\|all\|lab\|admin)$` | A5 receipt printer |

- **The Test box is real**: paste an address → *Which rule fires?* →
  the hub answers which rule + printer (or "no rule → OS default"),
  with a second row that simulates a detected page kind (ZPL / PDF /
  image / text / web) for content rules. Nothing is printed. Same
  engine via API: `POST /rules/test {"url": …}` or
  `GET /rules/test?url=…`.
- **The proper doc**: `docs/PRINT-RULES-RECIPES.md` — all four recipes
  verbatim, why the `$` anchor separates one test id from many, `%5B%5D`
  vs `[]`, dynamic `\d+` ids, alternations, domain locking, and how to
  verify.

## 5. No more version prefixes in the UI notes

**You asked:** *"no need show version so diffrent area show difrent
version note it show ugly so only not show version before note."*

All of them are gone — "v2.8 ·", "v3.2.6 ·", "- v2.2:", "since
v2.6.4", "v3.3.5 -" and friends (24 spots across the ONE UI and the
dashboard). Notes now just say what the feature does. The /docs manual
keeps its version history — that is what docs are for.

---

## Files in this release

| File | What |
|---|---|
| `AdvPrint-Pro-Setup-3.4.7.exe` | Windows installer (bundles Python + the signed CRX) |
| `AdvPrint-Pro-Extension-3.4.7.zip` / `.crx` | the browser extension |
| `advprint-pro_3.4.7_all.deb` | Linux deb |
| `AdvPrint-Pro-v3.4.7-FULL.zip` | the whole source + tool tree |
| `docs/PRINT-RULES-RECIPES.md` | the URL rules guide |
| `docs/AdvPrint-Pro-v3.4.7-A-to-Z-DEV-GUIDE.md` | developer/build guide for this delta |
| `RELEASE-NOTES-v3.4.7.md` | this file |
