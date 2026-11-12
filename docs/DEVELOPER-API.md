# AdvPrint Pro — Developer API (complete guide)

**v3.2.7** · by Bit Dream IT - Innovative Healthcare Solutions

Everything a developer needs to print through AdvPrint Pro — from a web
page, from a server, from a script, from any language. Every option,
every response field, every URL, and full worked examples for the real
cases: **one PC many printers**, **many PCs one hub**, **PDF + ZPL at
the same time**, scheduled jobs, urgent jobs, labels and receipts.

> The same guide ships inside the product: open
> `http://127.0.0.1:9235/docs?token=YOUR-TOKEN` (section 9) or the
> console UI → **? Quick start guide** (section 9 of the modal).

---

## 0. The 30-second overview

There are **three ways** to hand the hub a print job:

| # | Channel | Who uses it | Needs the extension? |
|---|---------|-------------|----------------------|
| 1 | `window.advprint.*` (JavaScript, injected into every page) | web apps, POS/kiosk pages, dashboards | yes (extension loaded) |
| 2 | `POST http://127.0.0.1:9235/print` (plain HTTP + token) | servers, scripts, cron, any language, other PCs on the LAN | **no** |
| 3 | `ipp://<lan-ip>:9235/ipp/print` (+ RAW 9100) — the hub IS a printer | OS "Add printer", phones, label software | no |

All three land in the **same pipeline**: one job row in the queue →
History → audit trail → printed on the destination printer. A job sent
from JavaScript and a job sent with `curl` are identical afterwards.

```
 browser page                 server / cron / other PC          OS / phone
      |  window.advprint.print()      |  POST /print (token)        |  IPP / RAW 9100
      v                               v                             v
 +------------------------------------------------------------------------+
 | AdvPrint Pro hub  :9235            (631 IPP mirror, 9100 JetDirect)    |
 |   auth -> payload -> render/route -> QUEUE (SQLite) -> printer backend |
 |                                          |                             |
 |   FIFO worker (priority first)    instant threads (queue:false)        |
 +------------------------------------------------------------------------+
      |                |                |                |
  HP LaserJet     XP-80C thermal    Zebra GK420t     file (archive PDF)
```

---

## 1. Concepts you need once

* **Hub** — the local print engine (`advprint.py`), listening on
  `http://127.0.0.1:9235`. On the LAN it also answers on
  `http://<lan-ip>:9235`, an IPP listener and a RAW JetDirect port 9100.
* **Token** — the API password, shown in the console (Hub tab) and by
  `python advprint.py token`. Every HTTP print call carries it.
* **Job** — one print request. Always gets a `job_id`, always appears
  in History, always audited.
* **Queue Mode** (default ON) — jobs print one-by-one, most-urgent
  first (`priority` 1 before 9), FIFO inside the same priority. Pause
  affects only queued jobs.
* **Instant mode** (`queue: false`) — the job skips the FIFO and prints
  **immediately in its own thread**, so two instant jobs for two
  different printers run at the same time. Pause has no effect.
* **Destination** — a printer name, a printer group, the OS default,
  an upstream IP printer (`dest_mode: "ip"`), or `file` (save as PDF,
  no paper).

---

## 2. `window.advprint` — the browser API

### 2.1 Availability and mechanics

* Injected into **every http(s) page** by the extension (MAIN world,
  browser-initiated — immune to page CSP). No setup in the page, no
  import, works even with "Intercept window.print()" off.
* Every method returns a **Promise** that resolves with the hub's JSON
  response. The call-based methods resolve — even on failure — with
  `{ok:false, error:"..."}`; `printPdfLink` is the one that **rejects**
  (after opening its fallback tab).
* A call times out after 30 s (configurable per call) with
  `{ok:false, error:"AdvPrint timeout - is the extension connected..."}`.
* The extension maps your camelCase fields to the hub's snake_case
  fields for you (`pdfBase64` → `pdf_base64`, `pageUrl` → `page_url`, …).

```js
window.advprint.status();    // -> Promise<health JSON>
window.advprint.version;     // -> "3.3.0" (the extension version)
```

### 2.1.1 Website API permission — WHO may call the API (read once!)

By default **every** website may call the API (the allowlist is `*`).
If your deployment restricted it, your page's origin must match one
pattern — otherwise every method answers:

```
{ok:false, error:"AdvPrint page API is not allowed for http://your.host
 - open the AdvPrint Pro Console (/ui), Connections tab > Website API,
 and add this site (one line: *://your.host/*, or * for ALL sites)"}
```

**Where the list lives:** AdvPrint Pro Console (`http://127.0.0.1:9235/ui`)
→ **Connections** tab → **Website API permission** — one pattern per
line, saved live into the extension.

**The four pattern forms** (like the auto-print rules):

| Pattern | Matches |
|---|---|
| `*` | EVERY website (default) |
| `*://www.htncr.org/*` or `www.htncr.org` | that host, ANY scheme |
| `https://reports.example.com/*` | that host — **v3.2.8: BOTH `https://` and `http://`** |
| `*.example.org` | every subdomain of example.org, any scheme |

**The v3.2.8 scheme rule — the HOST is what you allow, not the
transport.** A pattern that pins `http://` or `https://` matches that
host on **both** web schemes, so a site served over `http://` and
`https://` works whichever form was typed. (`file://` and other
non-web schemes never match.)

**Troubleshooting — "works on https, not on http":** before v3.2.8 a
`https://host/*` pattern refused the `http://` twin of the same site.
Upgrade to v3.2.8 (no settings migration needed — your existing
pattern simply starts covering both), or change the pattern to
`*://host/*` on older builds. An EMPTY list means the page API is OFF
for every website; the extension's own pages (popup/options) are
always allowed.

**Troubleshooting — "I updated the hub but the page API still refuses
http":** the extension inside Chrome is auto-updated from the hub's
own package (`http://<hub>:9235/extension/updates.xml`), and Chrome
installs an update only when that package shows a HIGHER version. If
the hub folder still holds an old `AdvPrint-Pro.crx`, every browser
silently keeps the OLD extension. Check
`http://<hub>:9235/extension/info` — if it answers `"stale":true`
(served version older than `hub_version`), copy the fresh
`AdvPrint-Pro.crx` from the release package over the hub's
`hub/extension/AdvPrint-Pro.crx` (no restart needed), then run
chrome://extensions → **Update** and confirm AdvPrint Pro shows the
new version. The same warning appears in `/health`
(`extension.stale`), on the `/extension` page and in the Console
Extension panel.

### 2.2 The methods

| Method | Hub call | Returns |
|---|---|---|
| `status()` | `GET /health` | `{ok, app, version, os, default_printer, paused, pending, jobs_today, token_set, …}` |
| `printers()` | `GET /printers` | `{ok, printers:[{name, is_default, status?}], default}` |
| `history(limit=20)` | `GET /jobs?limit=N` (1–100) | `{ok, jobs:[{id, created_at, title, printer, kind, status, …}]}` |
| `printPage({title, printer?, destination?})` | DOM render of the current tab → `POST /print` | job JSON |
| `printPdf(url, {title, printer?, …})` | downloads the URL **with your login cookies**, uploads raw PDF | job JSON |
| `print({…})` | generic `POST /print` | job JSON |
| `printPdfLink(url, title?, {timeout?, fallback?})` | silent print; on failure opens the URL in a tab (browser fallback) then **rejects** | job JSON |

`destination: "file"` (or `printer: "__file__"`) saves as a PDF file
instead of printing — no paper.

### 2.3 `window.advprint.print()` — full option reference (camelCase)

```js
const r = await window.advprint.print({
  title: 'Receipt 12',
  printer: '',                    // '' = hub destination; or exact name; or group
  copies: 1,                      // 1-50
  priority: 1,                    // 1 urgent … 9 low (default 5)
  pages: '1-3,5',                 // range | 'odd' | 'even'
  per_sheet: 2,                   // n-up 1,2,4,6,9,16 (CUPS)
  quality: 'draft',               // draft|normal|high | '600' | '600dpi'
  dpi: 600,                       // explicit DPI 72-2400 (wins over quality)
  scale_pct: 150,                 // 25-400 (html/text renders)
  margin_mm: 8,                   // page margins (html/text renders)
  duplex: 'duplex',               // simplex|duplex|duplexlong|duplexshort
  paper_size: 'A4',               // A4 A5 A3 Letter Legal …
  orientation: 'landscape',       // or 'portrait'
  tray: 'Tray2',                  // CUPS only
  profile: 'Invoice',             // hub print profile (Settings)
  destination: 'printer',         // or 'file' (archive as PDF)
  queue: true,                    // false = INSTANT print (skip FIFO)
  run_at: '+5m',                  // ISO datetime or +Ns/+Nm/+Nh/+Nd
  dedupe: true,                   // false = allow identical repeats
  reason: 'ward reprint',         // recorded in the audit trail
  watermark: true,                // stamp watermark_text on the PDF
  watermark_text: 'REPRINT',
  // ---- payload: exactly ONE of these ----
  text: '|center|HELLO',          // plain text / ESC-POS markers
  lang: 'escpos',                 // with text: 'escpos' (default) | 'zpl'
  html: '<h1>Invoice</h1>',
  pageUrl: 'https://…/report.html',
  pdfBase64: 'JVBERi0…',
  pdfUrl: 'https://…/report.pdf',
  rawBase64: 'XlhBCg…',           // pre-built ZPL/ESC-POS bytes
});
// r = {ok:true, job_id:41, kind:'a4', copies:1, destination:'printer',
//      queue_mode:'on', instant:false, auto_queued:false, duplicate:false,
//      priority:1, status:'queued', message:'queued to printer'}
```

Every field is optional except the payload. Unknown fields are ignored.
`run_at`, `queue`, `dedupe`, `tray` and `watermark_text` have full
parity with the HTTP API since **v3.2.7**.

### 2.4 Error handling pattern

```js
async function safePrint(payload) {
  const r = await window.advprint.print(payload);   // resolves always
  if (!r.ok) { console.warn('print failed:', r.error); return null; }
  return r.job_id;                                  // poll /jobs/{id} if needed
}
```

---

## 3. Direct HTTP API — `POST /print`

### 3.1 Auth and base URLs

| Where | Base URL |
|---|---|
| The hub PC itself | `http://127.0.0.1:9235` |
| Another PC / phone on the LAN | `http://<lan-ip>:9235` (Allowed-IPs must admit it — default `*`) |

Three ways to send the token — pick one per request:

1. **Header** (recommended): `X-AdvPrint-Token: <token>` (legacy
   `X-PrintHub-Token` also accepted)
2. **Query**: `POST /print?token=<token>`
3. **JSON field**: `{"token": "<token>", …}`

Bodies larger than 1 MB are refused **before reading** unless the token
arrives via header or query — always put big payloads behind the header.

### 3.2 Four body styles — all equivalent

```bash
# a) JSON (any payload source + every option)
curl -X POST http://127.0.0.1:9235/print \
  -H "X-AdvPrint-Token: $TOKEN" -H "Content-Type: application/json" \
  -d '{"pdf_base64":"JVBERi0…","title":"Invoice 42","copies":2}'

# b) RAW PDF bytes - no base64, no JSON (-33% size) — options on the query
curl -X POST "http://127.0.0.1:9235/print?title=Lab%20report&copies=1" \
  -H "X-AdvPrint-Token: $TOKEN" -H "Content-Type: application/pdf" \
  --data-binary @report.pdf

# c) RAW ESC/POS or ZPL bytes - add kind=raw so %PDF is not expected
curl -X POST "http://127.0.0.1:9235/print?kind=raw&printer=Zebra%20GK420t" \
  -H "X-AdvPrint-Token: $TOKEN" -H "Content-Type: application/octet-stream" \
  --data-binary @label.zpl

# d) multipart (file field pdf|file|document; text fields = options)
curl -X POST http://127.0.0.1:9235/print \
  -H "X-AdvPrint-Token: $TOKEN" \
  -F file=@report.pdf -F title="Lab report" -F copies=2
```

Strict-CSP fallback: POST `application/x-www-form-urlencoded` with one
field `payload` = the JSON text. Every option is also accepted on the
query string (`?printer=X&copies=2`).

### 3.3 Payload sources — checked in this order

| Order | Field | Meaning | Notes |
|---|---|---|---|
| 0 | raw body | PDF bytes (`application/pdf`) or label bytes (`?kind=raw`) | must start `%PDF-` unless `kind=raw`; ≤ 25 MB |
| 1 | `raw_base64` | pre-built ESC/POS/ZPL bytes | becomes a `raw` job |
| 2 | `text` + `lang: escpos\|zpl` | raw receipt/label text | `zpl` = verbatim `^XA…^XZ`; `escpos` = marker builder |
| 3 | `pdf_base64` | base64 PDF | must start `%PDF-` |
| 4 | `pdf_url` | hub downloads the PDF | ≤ 25 MB; private-address guard (400) unless the host is in `pdf_url_allowed_hosts` |
| 5 | `image_base64` | **JPEG** only | wrapped to one-page PDF (`paper: a4\|thermal`) |
| 6 | `html` | HTML string | rendered by headless Chrome/Edge (max 2 concurrent renders) |
| 7 | `page_url` | URL of a page | rendered by headless Chrome/Edge; same private-address guard |
| 8 | `text` | plain text | `paper:"thermal"` → 80 mm roll; else A4; Bangla/Unicode auto-renders via the browser engine |

No payload → `400 {"ok":false,"error":"provide pdf_base64, pdf_url, …"}`.

### 3.4 Full option reference (snake_case)

| Field | Type / values | Default | Notes |
|---|---|---|---|
| `title` | string ≤ 60 | `"document"` | shown in queue/history |
| `printer` | string ≤ 120 | `""` | `""` = hub destination (Settings); exact printer name wins; group name = first ready member; `"__file__"` = archive |
| `copies` | 1–50 | 1 | |
| `priority` | 1–9 | 5 | **1 prints first** (`ORDER BY priority ASC`) |
| `pages` | `"1-3,5"` \| `odd` \| `even` | all | PDF jobs |
| `duplex` | `simplex` `duplex` `duplexlong` `duplexshort` (aliases `long`/`short`/`true`) | driver | |
| `paper_size` | `A4` `A5` `A3` `Letter` `Legal` `Tabloid`… | driver | sanitized to `A-Za-z0-9` |
| `tray` | string | — | CUPS only (Windows logs a notice) |
| `per_sheet` | 1 2 4 6 9 16 | 1 | n-up, CUPS only |
| `quality` | `draft` `normal` `high` (`best`/`fine`→`high`), `600`, `"600dpi"` | — | `dpi:` form is stored |
| `dpi` | 72–2400 | — | explicit DPI wins; becomes `quality:"dpi:N"` |
| `scale_pct` (or `scale`) | 25–400 | — | html/text renders |
| `margin_mm` (or `margins`) | number | — | html/text renders |
| `orientation` | `landscape` (`land`/`horizontal`) \| portrait | portrait | `landscape:true` also accepted |
| `paper` | `a4` \| `thermal` | auto | text/image width |
| `profile` | profile name | — | named preset (paper/tray/duplex/copies/printer); unknown → 400 |
| `destination` | `printer` \| `file` | `printer` | `file` = save PDF, no paper |
| `queue` | bool | `true` | `false` = instant; aliases `mode:"instant"|"direct"|"now"`, `instant:true` |
| `run_at` | ISO datetime \| `+Ns\|+Nm\|+Nh\|+Nd` | — | schedules the job; bad value → 400 |
| `dedupe` | bool | `true` | `false` disables identical-job blocking |
| `reason` | string ≤ 200 | — | recorded in the audit trail |
| `watermark` | bool | `false` | stamps `watermark_text` on the PDF (never on raw jobs) |
| `watermark_text` | string ≤ 24 | `"REPRINT"` | |
| `source` | string ≤ 20 | `"api"` | free tag shown in History |
| `lang` | `escpos` \| `zpl` | `escpos` | with `text` in raw mode |
| `cut` / `drawer` | bool | `true` / `false` | ESC/POS only |

### 3.5 The response

```json
{
  "ok": true,
  "job_id": 41,
  "kind": "a4",
  "copies": 2,
  "destination": "printer",
  "queue_mode": "on",
  "instant": false,
  "auto_queued": false,
  "duplicate": false,
  "priority": 5,
  "status": "queued",
  "message": "queued to printer"
}
```

* `status` — `queued` (FIFO) · `printing` (instant) · `scheduled`
  (run_at) · `saved` (destination file, adds `"file": "<path>"` and
  `"url_path": "/jobs/<id>/file"`) · later `printed/failed/held/…`
  (watch `GET /jobs/{id}`).
* `run_at` jobs add `"scheduled_for": "<the ISO time>"` to the response.
* `auto_queued: true` — you asked for instant but the printer reported
  offline/paper-out/error, so the hub queued it instead (prints when
  the printer comes back). Raw jobs skip this probe.
* `duplicate: true` — an identical job (title+printer+kind+content
  hash) was accepted within the dedupe window (default 5 min); the
  block message names the original job id.

### 3.6 Errors

| Code | When |
|---|---|
| 400 | no payload · not a PDF · PDF > 25 MB · bad `run_at` · unknown `profile` · `page_url`/`pdf_url` blocked (private address) · raw + destination file |
| 401 | wrong token · body > 1 MB without header/query token |
| 403 | IPP Print-Job from a browser Origin · non-local caller touching a UI-only route |
| 421 | `Host` header is not this hub |
| 500 | html/page render failure |

---

## 4. Printing to MULTIPLE printers — one PC

### 4.1 Discover what is installed

```js
const { printers, default: dflt } = await window.advprint.printers();
// printers: [{name:"HP LaserJet Pro", is_default:true},
//            {name:"XP-80C Thermal", is_default:false},
//            {name:"Zebra GK420t",    is_default:false}]
```

`GET /printers` (HTTP) returns the same list; every local printer also
gets `ipp_path` — its bare queue slug for per-printer IPP URLs (§8.3).

### 4.2 Targeting rules (one job = one printer)

The `printer` field is resolved in this order:

1. **Exact name** (case/spacing typos are self-healed: `"hp laserjetpro"`
   → `HP LaserJet Pro`; unknown → 4xx with the installed list).
2. **Group name** (Settings → printer groups): the first member that is
   not offline/paper-out/error, else the first member.
3. **Empty `""`** → the hub destination (Settings: OS default /
   selected printer / upstream IP printer).
4. `destination:"file"` (or `printer:"__file__"`) → save as PDF, no
   printer at all.

### 4.3 CASE — receipt + invoice at the SAME time (2 printers, parallel)

Queue Mode prints one job after another. For true parallelism send the
jobs **instant** — each instant job prints in its own thread:

```js
// checkout page: thermal receipt + A4 invoice, at the same moment
await Promise.all([
  window.advprint.print({
    title: 'Order ' + order.id,
    printer: 'XP-80C Thermal',
    queue: false,                       // INSTANT -> own thread
    text: '|center|MY SHOP\n' + order.lines.join('\n') +
          '\n|cut|',
  }),
  window.advprint.print({
    title: 'Invoice ' + order.id,
    printer: 'HP LaserJet Pro',
    queue: false,
    pdfBase64: invoicePdfBase64,        // or html: invoiceHtml
  }),
]);
```

Both jobs answer immediately with `status:"printing"`; the two
physical printers run at the same time.

### 4.4 CASE — queue mode (ordered, one at a time)

Without `queue:false` the two jobs join the FIFO and print **in
priority order** — use this when the printer is shared and order
matters:

```bash
curl -X POST http://127.0.0.1:9235/print -H "X-AdvPrint-Token: $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"title":"Urgent lab result","priority":1,"pdf_base64":"JVBERi0…"}'
curl -X POST http://127.0.0.1:9235/print -H "X-AdvPrint-Token: $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"title":"Daily archive","priority":9,"pdf_base64":"JVBERi0…"}'
```

The `priority:1` job prints before the `priority:9` one, even if it
arrived second.

### 4.5 CASE — one call per printer, same payload (loop)

```python
import requests, json
HUB, TOKEN = "http://127.0.0.1:9235", "YOUR-TOKEN"
pdf = open("menu.pdf", "rb").read()
import base64
b64 = base64.b64encode(pdf).decode()
for p in ["HP LaserJet Pro", "XP-80C Thermal", "Zebra GK420t"]:
    r = requests.post(f"{HUB}/print",
        headers={"X-AdvPrint-Token": TOKEN},
        json={"title": "Menu of the day", "printer": p,
              "pdf_base64": b64})
    print(p, "->", r.json()["job_id"])
```

Three jobs, three `job_id`s, three printers. The identical-content
dedupe does **not** block this — the dedupe key includes the printer
name (title+printer+kind+hash), so the same PDF to three printers is
three different jobs.

---

## 5. MANY PCs, ONE hub (LAN printing)

### 5.1 Who may call

* **Print surface** — open to every address the Allowed-IPs list admits
  (default `*` = whole LAN): `POST /print`, `POST /send`, `/ipp/*`,
  the 631 mirror, RAW 9100, `GET /jobs`, `GET /printers`, `GET /health`.
* **The console UI** — local-only since v3.2.6: only the hub PC itself
  (loopback or one of its own IPs) can open `/ui`, change settings,
  clear history. Other PCs can print **but not configure**.
* The hub PC (127.0.0.1) always passes.

### 5.2 CASE — three PCs print PDFs concurrently

PC-A (Laravel, signed URL), PC-B (Python script), PC-C (browser page)
all `POST http://192.168.1.101:9235/print` at the same time. Every
request is handled by its own HTTP thread, every job gets its own
`job_id`, and the queue interleaves them by priority. Nobody waits for
nobody: while job #40 is still rendering on PC-C, #38 and #39 are
already queued from A and B.

```php
// PC-A: Laravel — print a stored report, fire-and-forget
Http::withHeaders(['X-AdvPrint-Token' => config('advprint.token')])
    ->withBody($pdf->output(), 'application/pdf')
    ->post('http://192.168.1.101:9235/print?title='
           . urlencode('Report ' . $report->id)
           . '&printer=' . urlencode('HP LaserJet Pro'));
```

```python
# PC-B: Python
requests.post("http://192.168.1.101:9235/print",
    headers={"X-AdvPrint-Token": TOKEN},
    files={"pdf": ("report.pdf", open("report.pdf", "rb"))},
    data={"title": "Report 605310", "copies": "2"})
```

### 5.3 CASE — PDF from one PC + ZPL label from another, same time

Nothing special to do — raw and PDF jobs run side by side:

* Raw jobs (`lang: zpl|escpos` / `kind=raw`) skip the printer-ready
  probe (receipt/label printers rarely report a usable status) and go
  straight to the backend.
* PDF jobs route through the queue/worker as always.
* With **instant mode** on both calls, the PDF spools on the laser
  while the label feeds on the Zebra — truly simultaneous, even when
  the calls come from different PCs.

```bash
# PC-B: ZPL label straight to the Zebra on the hub PC
curl -X POST "http://192.168.1.101:9235/print?kind=raw&printer=Zebra%20GK420t&title=Label%2048021" \
  -H "X-AdvPrint-Token: $TOKEN" -H "Content-Type: application/octet-stream" \
  --data-binary @label.zpl
```

### 5.4 What actually serializes (plan your load)

| Resource | Limit | Effect |
|---|---|---|
| FIFO worker | 1 printer job at a time (queue mode) | queued jobs print one-by-one, priority first |
| Instant jobs | one thread each | parallel; different printers truly simultaneous |
| Headless renders (`html`/`page_url`) | 2 concurrent | the 3rd render waits for a free browser slot |
| Dedupe window | 5 min (config) | identical resubmits are blocked, not duplicated |

### 5.5 Peer hubs (optional)

Hubs can be connected (LAN tab → invite link): dead peers are skipped
and a whole queue can be **shifted** to another PC
(`POST /queue/shift {target, scope|ids}`) — handy when THIS PC's
printer is down but the other PC's is not.

---

## 6. RAW printing — ZPL labels and ESC/POS receipts

### 6.1 When raw, when PDF?

| Content | Send as |
|---|---|
| Invoice / report / anything laid out | PDF (`pdf_base64`, `pdf_url`, raw body, `html`) |
| Receipt on a thermal roll with markers | `text` + `lang:"escpos"` (default) |
| Shipping / barcode label on a Zebra | `text` + `lang:"zpl"` (verbatim ZPL II) |
| Bytes you built yourself (PCL, pre-rendered ESC/POS) | `raw_base64` or raw body + `?kind=raw` |

Raw delivery: Windows → winspool `DATATYPE RAW`; Linux/macOS →
`lp -o raw`; a configured upstream IP printer → direct socket (RAW 9100
/ IPP 631, `application/octet-stream`).

### 6.2 ZPL — `^XA … ^XZ` verbatim

With `lang:"zpl"` the hub encodes your text **latin-1** and sends the
bytes untouched: you own the whole label — size, fonts, barcodes,
quantities. No header, no cut, nothing is added.

```json
{
  "title": "Label 48021",
  "printer": "Zebra GK420t",
  "lang": "zpl",
  "text": "^XA\n^PW400\n^LL0160\n^FO30,30^A0N,36,30^FDPARACETAMOL 500mg^FS\n^FO30,80^A0N,28,24^FDLOT 2408-B   EXP 2027-08^FS\n^FO30,110^BY2^BCN,90,Y,N,N^FD(01)09506000123456^FS\n^XZ\n"
}
```

```bash
# same label from the shell (query form, raw bytes)
curl -X POST "http://127.0.0.1:9235/print?kind=raw&lang=zpl&printer=Zebra%20GK420t" \
  -H "X-AdvPrint-Token: $TOKEN" \
  --data-binary $'^XA\n^PW400\n^LL0160\n^FO30,30^A0N,36,30^FDHELLO^FS\n^XZ'
```

```python
# same label from Python — note the JSON string form
zpl = ("^XA^PW400^LL0160^FO30,30^A0N,36,30^FDHELLO^FS"
       "^FO30,80^BY2^BCN,90,Y,N,N^FD(01)09506000123456^FS^XZ")
requests.post(HUB + "/print", headers=AUTH,
              json={"title": "Label", "printer": "Zebra GK420t",
                    "lang": "zpl", "text": zpl})
```

Gotchas the guide answers up front:

* `^XA` must open and `^XZ` must close the label — the hub does not
  add them.
* Non-latin-1 characters become `?` — ZPL is a latin-1 byte stream.
* Need two copies? Send `"copies": 2` **or** `^PQ2` inside the label —
  either works.
* Label printers with a Windows driver can also print PDFs — but for
  variable labels ZPL raw is faster and exact-size.

### 6.3 ESC/POS — the marker builder

With `text` (and no `lang`, or `lang:"escpos"`) the hub builds the
ESC/POS bytes for you — alignment, sizes, barcode, QR, cut, drawer:

| Marker | Effect |
|---|---|
| `#big ` (line start) | double-size line (headers, totals) |
| `\|center\|` / `\|right\|` | center / right-align that line |
| `\|cut\|` (own line) | feed + partial cut here |
| `\|drawer\|` (own line) | kick the cash drawer |
| `\|barcode:12345\|` (own line) | CODE128 barcode |
| `\|qr:text\|` (own line) | QR code |

```json
{
  "title": "Receipt 12",
  "printer": "XP-80C Thermal",
  "text": "|center|#big MY SHOP\n|center|123 Main Road\n--------------------------------\nItem 1            10.00\nItem 2             5.50\n--------------------------------\n|right|TOTAL       15.50\n|qr:order-12|\n|drawer|\n|cut|"
}
```

A small `AdvPrint Pro` banner is printed at the top automatically and
the receipt is cut at the end automatically (disable with
`"cut": false`). Bangla/Unicode plain text (without `lang`) is rendered
through the browser engine so it never prints as `????`.

---

## 7. URL & token handling — the full map

| URL | Purpose | Token |
|---|---|---|
| `http://127.0.0.1:9235` | hub base on this PC | required for print calls |
| `http://<lan-ip>:9235` | hub base from other PCs/phones | required |
| `/print` | THE print API (§3) | `X-AdvPrint-Token` / `?token=` / JSON `token` |
| `/send` (+ `/send?token=`) | phone upload portal | token |
| `/ipp/print` | the hub as an IPP printer (`ipp://<ip>:9235/ipp/print`) | none (printer protocol) |
| `/ipp/print/<printer-slug>` | per-printer IPP queue | none |
| TCP 9100 | RAW JetDirect listener | none (Allowed-IPs still apply) |
| `/jobs`, `/jobs/{id}`, `/jobs/{id}/file` | monitor / download | token |
| `/ui` | the console — **local-only PC** (v3.2.6) | token |
| `/docs?token=` | this guide served by the hub | token |
| `/qr?kind=send\|invite\|ipp` | QR as SVG | token |

**`ipp://` vs `http://`** — use the right one for the job:

* `ipp://<ip>:9235/ipp/print` — for the OS **Add a printer** dialog
  (Windows/macOS/CUPS understand the scheme). Copy button = `ipp://`.
* `http://<ip>:9235/ipp/print` — for browsers, curl, code. Since
  v3.2.6 the **QR encodes the http:// URL** (phone browsers cannot open
  `ipp://` — they Google-search it).
* The 631 mirror: `ipp://<ip>:631/ipp/print` answers too, for clients
  that insist on the classic IPP port.

**Per-printer queues** — every installed printer gets its own queue so
one hub serves the whole LAN:

```
ipp://192.168.1.101:9235/ipp/print/hp-laserjet-pro
http://192.168.1.101:9235/ipp/print/zebra-gk420t
```

Slug rules: lowercase, every non-alphanumeric run → `-`
(`"HP LaserJet Pro"` → `hp-laserjet-pro`). Matching is case-insensitive
and punctuation-blind, and the raw URL-encoded name
(`HP%20LaserJet%20Pro`) works too. `GET /printers` returns the ready
slug in `ipp_path`; the full URL is always
`BASE + "/ipp/print/" + ipp_path`.

---

## 8. Case studies — copy, paste, adapt

**a) POS receipt on checkout (page JS)**
```js
document.querySelector('#checkout').addEventListener('click', async () => {
  const r = await window.advprint.print({
    title: 'Order ' + order.id,
    printer: 'XP-80C Thermal', queue: false,
    text: '|center|#big MY SHOP\n' + order.lines.join('\n')
        + '\n|right|TOTAL ' + order.total + '\n|qr:' + order.id + '|\n|cut|',
  });
  if (!r.ok) alert('Printer: ' + r.error);
});
```

**b) Invoice PDF from Laravel (signed URL, zero encoding)**
```php
$url = URL::temporarySignedRoute('reports.pdf', now()->addMinutes(5),
        ['report' => $report->id]);
Http::withHeaders(['X-AdvPrint-Token' => $token])
    ->post('http://127.0.0.1:9235/print', [
        'title' => 'Report ' . $report->id,
        'pdf_url' => $url,            // hub downloads it (max 25 MB)
        'copies' => 2, 'paper_size' => 'A4',
    ]);
```

**c) Shipping label ZPL from Python**
```python
zpl = f"^XA^PW400^LL0200^FO30,30^A0N,36,30^FD{order.name}^FS^FO30,80^BY2^BCN,100,Y,N,N^FD{order.tracking}^FS^PQ1^XZ"
requests.post(HUB + "/print", headers=AUTH,
              json={"title": order.tracking, "printer": "Zebra GK420t",
                    "lang": "zpl", "text": zpl, "queue": False})
```

**d) Scheduled end-of-day report (no cron needed)**
```bash
curl -X POST http://127.0.0.1:9235/print -H "X-AdvPrint-Token: $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"title":"EOD summary","pdf_base64":"JVBERi0…","run_at":"+8h","profile":"Night"}'
```

**e) Urgent lab result jumps the queue** — `priority: 1` (§4.4).

**f) Duplex booklet, 2-up, A4**
```json
{"pdf_base64":"…", "duplex":"duplexlong", "per_sheet":2, "paper_size":"A4"}
```

**g) Archive every opened report as PDF (no paper)**
```json
{"pdf_url":"https://…/report.pdf", "destination":"file", "title":"archive 605310"}
```

**h) Watermarked reprint with audit reason**
```bash
curl -X POST http://127.0.0.1:9235/jobs/17/reprint -H "X-AdvPrint-Token: $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"reason":"original lost - ward copy","watermark":true,"watermark_text":"COPY"}'
```

**i) Kiosk: pick the printer by paper at runtime**
```js
const { printers } = await window.advprint.printers();
const thermal = printers.find(p => /thermal|xp-8|tm-t/i.test(p.name));
await window.advprint.print({ title: 'Kiosk ticket', printer: thermal?.name || '',
                              text: '|center|#big NOW SERVING\n|center|B 042\n|cut|' });
```

---

## 9. Quick reference card

```text
PRINT (JSON)   POST /print          header X-AdvPrint-Token: <token>
PAYLOAD        pdf_base64 | pdf_url | image_base64 | html | page_url
               | text [+ lang:escpos|zpl] | raw_base64 | raw body (%PDF|kind=raw)
TARGET         printer:"" (dest) | "Exact Name" | "Group" | destination:"file"
SPEED          default FIFO (priority 1 first) · queue:false = instant+parallel
SCHEDULE       run_at:"2026-12-24T08:00:00" | "+5m" "+2h" "+1d"
PAGES          "1-3,5" | "odd" | "even"        COPIES 1-50
LAYOUT         duplex | paper_size | orientation | per_sheet(CUPS) | tray(CUPS)
QUALITY        draft|normal|high | dpi:72-2400  SCALE 25-400  MARGIN mm
WATCH          GET /jobs?limit=20 · GET /jobs/{id} · History tab
REPRINT        POST /jobs/{id}/reprint {reason, watermark}
LABELS         ZPL: text+lang:"zpl" (^XA…^XZ verbatim) · ESC/POS markers on text
MANY PRINTERS  one call per printer (instant = parallel) · groups = fallback
MANY PCs       POST to http://<lan-ip>:9235/print (Allowed-IPs; UI stays local)
```

*AdvPrint Pro v3.2.7 — Developer API — by Bit Dream IT - Innovative
Healthcare Solutions — 100% local, no cloud.*
