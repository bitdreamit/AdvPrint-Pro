# AdvPrint Pro — Hub HTTP API

Base URL: `http://127.0.0.1:9235` (default)
Auth: header `X-AdvPrint-Token: <token>` (fresh installs: a private random token - read it with `python advprint.py token`; legacy `X-PrintHub-Token` header accepted), or `?token=` query on GET navigation, or `"token"` JSON field.
All responses are JSON with an `"ok"` field. The API is CORS-open with `Access-Control-Allow-Private-Network: true`, so browser JS from any site can call it.

---

## POST /ipp/print — IPP network printer endpoint *(v2.9.0, no token)*

The hub is a real IPP printer. Binary IPP/1.1 bodies only (this is what
Windows / phone print services send - do not call it by hand unless you
speak IPP):

- `Get-Printer-Attributes (0x000B)` → printer-state, make-and-model
  `AdvPrint Pro <version> (virtual)`, document formats
  `application/pdf`, `image/jpeg`, `application/octet-stream`.
- `Print-Job (0x0002)` → routes the document by content:
  `%PDF` → the normal PDF pipeline (queue, History, audit, reprint);
  JPEG → single-page PDF (DCTDecode); PostScript / PCL / ESC/POS / ZPL
  → RAW passthrough to the selected printer. Answers `successful-ok`
  with `job-id` / `job-state`, or
  `client-error-document-format-not-supported`.
- `Validate-Job (0x0004)` → `successful-ok`.
- Anything else → `server-error-operation-not-supported (0x040F)`;
  unparseable body → `client-error-bad-request (0x0400)`.

The printer URL for the "Add a printer" dialogs is
`http://<lan-ip>:9235/ipp/print` (shown on the dashboard LAN card with
a QR: `GET /qr?kind=ipp`). IPP needs no token - it is a printer
protocol - but it only accepts print data, is bounded by the same size
limit as uploads, every job is audited with the source IP, and it can
be turned off with `"ipp_printer": false` (config.json or
`POST /config`). Browsers opening the URL with GET get a how-to page.

### RAW JetDirect printer port - TCP 9100 *(v2.9.0, no token)*

While LAN sharing is ON, the hub also listens on TCP 9100 (config
`raw_printer_port`, 0 = off) and speaks plain JetDirect: open a socket,
stream the bytes, close. Windows "Add a printer using TCP/IP address"
(device type *Generic Network Card*) and label/receipt apps use this.
Payload routing is the same as IPP. The listener binds the PC's LAN IP
(never 0.0.0.0), follows `share_lan`, rebinds on DHCP changes and stops
when LAN sharing is turned off.

---

## GET /health *(no token)*

```json
{
  "ok": true,
  "app": "AdvPrint Pro",
  "version": "1.0.0",
  "os": "windows",
  "default_printer": "HP LaserJet Pro",
  "sumatra_found": true,
  "browser_found": true,
  "paused": false,
  "pending": 0,
  "jobs_today": 12,
  "token_set": true
}
```

---

## GET /printers

```json
{ "ok": true,
  "printers": [ {"name": "HP LaserJet Pro", "is_default": true},
                {"name": "XP-80C Thermal", "is_default": false} ],
  "default": "HP LaserJet Pro" }
```

---

## POST /print

One of the payload sources is required. Common optional fields: `title`, `printer` (empty = default), `copies` (1–50), `source` (free tag shown in history), `destination` (`"printer"` default or `"file"` to save as PDF without printing).

| Source field | Meaning | Notes |
|---|---|---|
| `pdf_base64` | Raw PDF bytes, base64 | Must start with `%PDF-` |
| `pdf_url` | Download a PDF | Max 25 MB, must be a real PDF |
| `image_base64` | JPEG bytes, base64 | Wrapped to PDF (`paper: a4|thermal`, `landscape`) |
| `html` | HTML string | Rendered by headless Chrome/Edge |
| `page_url` | URL of a page | Rendered by headless Chrome/Edge |
| `text` | Plain text | `paper:"thermal"` → 80 mm roll; `paper:"a4"` → A4. Markers: `#big `, `|center| ` |

```bash
curl -X POST http://127.0.0.1:9235/print \
  -H "X-AdvPrint-Token: $TOKEN" -H "Content-Type: application/json" \
  -d '{"pdf_base64":"JVBERi0...","title":"Invoice 42","printer":"HP LaserJet Pro","copies":2}'
```

Response: `{"ok": true, "job_id": 17, "kind": "a4", "copies": 2, "destination": "printer", "message": "queued to printer"}`

### Raw binary PDF — no base64 (fastest path)

POST the PDF bytes **directly** with `Content-Type: application/pdf` — no base64 encode, no JSON, no +33% size overhead. Parameters ride the **query string** (`title`, `printer`, `copies`, `destination`, `paper`, `token` also accepted as query param).

```bash
curl -X POST "http://127.0.0.1:9235/print?title=Lab%20report&copies=1" \
  -H "X-AdvPrint-Token: $TOKEN" \
  -H "Content-Type: application/pdf" \
  --data-binary @report.pdf
```

**Laravel (mPDF, zero encoding):**

```php
Http::withHeaders(['X-AdvPrint-Token' => '$TOKEN'])
    ->withBody($pdf->output(), 'application/pdf')
    ->post('http://127.0.0.1:9235/print?title=' . urlencode('Lab report 197253'));
```

**Laravel multipart (`Http::attach`)** — file field `pdf`/`file`, text fields become parameters:

```php
Http::withHeaders(['X-AdvPrint-Token' => '$TOKEN'])
    ->attach('pdf', $pdf->output(), 'report.pdf')
    ->post('http://127.0.0.1:9235/print', ['title' => 'Lab report 197253']);
```

**No bytes at all — `pdf_url`:** the hub downloads the PDF itself (max 25 MB). For login-protected Laravel routes use a signed URL: `URL::temporarySignedRoute('reports.pdf', now()->addMinutes(5), [...])`.

Raw limits: max 25 MB, body must start with `%PDF-`; anything else → `400`.

### Destination "file" — save as PDF, no paper

Add `"destination": "file"` (or set `printer` to the extension alias `"__file__"`) and the hub **saves the rendered PDF into a folder instead of printing** — no dialog, no paper, no queue. Default folder: `~/Downloads/AdvPrint` (override with `ADVPRINT_FILE_DIR`).

```bash
curl -X POST http://127.0.0.1:9235/print \
  -H "X-AdvPrint-Token: $TOKEN" -H "Content-Type: application/json" \
  -d '{"text":"Daily summary","paper":"a4","title":"summary","destination":"file"}'
```

Response: `{"ok": true, "job_id": 18, "kind": "a4", "destination": "file", "status": "saved", "file": "/home/me/Downloads/AdvPrint/summary-20240101-120000.pdf", "url_path": "/jobs/18/file", "message": "saved as PDF file - no paper used"}`

The job appears in history with status `saved`; download it any time via `GET /jobs/18/file`, or print it later with `POST /jobs/18/reprint` (goes to the OS default printer).

Errors: `400` bad payload · `401` bad token · `500` render failure (html/page).

---

## Queue control

| Endpoint | Effect |
|---|---|
| `GET /queue` | `{"ok":true,"paused":false,"pending":2,"current":{...job...}}` |
| `POST /queue/pause` | Worker stops taking jobs (already-running job finishes) |
| `POST /queue/resume` | Worker continues; queued jobs print in FIFO order |
| `POST /queue/clear` | All `queued` jobs become `canceled` |

The queue is **DB-driven** (SQLite): pending jobs survive hub restarts, and jobs stuck in `printing` after a crash are re-queued at startup.

---

## Jobs & history

| Endpoint | Meaning |
|---|---|
| `GET /jobs?limit=100` | Last N jobs (newest first). Statuses: `queued printing printed saved failed canceled` |
| `GET /jobs/{id}/file` | Download the original PDF of a job |
| `POST /jobs/{id}/reprint` | Queue an exact copy of the job |
| `POST /jobs/{id}/cancel` | Cancel a queued job; if it is printing, the print process is killed |
| `GET /dropzone` | **v2.8.0** DropZone status (enabled, folder, waiting/done counts) |
| `POST /dropzone/open` | **v2.8.0** Open the DropZone folder on the hub PC (loopback only) |
| `GET /send` | **v2.8.0** The send portal page (upload a PDF from any device; token required) |
| `POST /send` | **v2.8.0** Upload + print a PDF (`multipart -F file=@x.pdf`, `application/pdf` body, or JSON `pdf_base64`) |
| `GET /qr` | **v2.8.1** QR code as SVG (`kind=send` = phone upload URL, `kind=invite` = PC invite link, `kind=ipp` = v2.9 printer URL; token required) |
| `GET /connect` | **v2.8.1** One-click invite landing page (`?t=<hub-token>&n=<PC-name>`; validates its own token) |
| `POST /peer-connect` | **v2.8.1** Auto-add a LAN peer from an invite (loopback + Origin-validated form POST; no token by design) |
| `GET /lan/selftest` | **v2.8.2** Server-side LAN check: the hub connects to its own LAN URL and reports PASS/FAIL with the reason (token required) |
| `POST /firewall/allow` | **v2.8.2** One-click Windows firewall rule for the hub port (loopback-only; triggers one UAC prompt) |
| `GET /lan/selftest` | **v2.8.2** Server-side LAN check: the hub connects to its own LAN URL and reports PASS/FAIL with the reason (token required) |
| `POST /firewall/allow` | **v2.8.2** One-click Windows firewall rule for the hub port (loopback-only; triggers one UAC prompt) |
| `POST /config` (share_lan) | **v2.8.2** now applies LIVE - the response carries `"lan":{"rebound":true,"lan_error":null}` once the LAN listener is already serving |
| `POST /config` (share_lan) | **v2.8.2** now applies LIVE - the response carries `"lan":{"rebound":true,"lan_error":null}` once the LAN listener is already serving |
| `POST /restart` | **v2.8.0** Restart the hub cleanly (it relaunches itself; queued jobs are kept) |
| `POST /jobs/bulk-reprint` | **v2.7.0** Reprint many jobs in one call |
| `POST /history/clear` | **v2.7.0** Delete every FINISHED job from the history |

### POST /send (v2.8.0) - print WITHOUT the extension
```bash
curl -X POST -H "X-AdvPrint-Token: $TOKEN" -F "file=@report.pdf" \
     "http://127.0.0.1:9235/send?title=Lab report"
# or raw body:
curl -X POST -H "X-AdvPrint-Token: $TOKEN" -H "Content-Type: application/pdf" \
     --data-binary @report.pdf "http://127.0.0.1:9235/send"
```
Accepts multipart (`file`/`pdf` field), a raw `application/pdf` body or JSON
`{"pdf_base64": "..."}`. Only real PDFs are accepted (25 MB cap). The job is
queued on the hub's printers exactly like any other job - `source: "send"`.

### GET /dropzone + POST /dropzone/open (v2.8.0)
`GET` returns `{"ok":true,"enabled":true,"dir":"...","waiting":0,"done":2,
"delete":false,"custom_dir":"","is_default":true}`. Change the settings with
`POST /config {"drop_enabled":true,"drop_dir":"C:\\Drop","drop_delete":false}`.
Every PDF that lands in the watched folder is printed and moved to `done\`
(or deleted when `drop_delete` is true) - this is the "MS Word style"
print path for apps without the extension.

### POST /restart (v2.8.0)
The hub relaunches ITSELF as a new process (the new process waits for the
old listener to release the port). Queued jobs, settings and history are
kept. The tray menu (Restart hub), AdvPrint Tool [14] and the dashboard
button all use this endpoint.

### GET /qr (v2.8.1) - QR code as SVG
```bash
curl -H "X-AdvPrint-Token: $TOKEN" \
     "http://127.0.0.1:9235/qr?kind=send" -o send-qr.svg
```
`kind=ipp` (v2.9.0) encodes the IPP printer URL
`http://<lan-ip>:9235/ipp/print` for the other PC's "Add a printer" dialog.
`kind=send` (default) encodes `http://<lan-ip>:9235/send?token=...` so any
phone on the Wi-Fi can scan it and upload a PDF through the Send portal;
`kind=invite` encodes `http://<lan-ip>:9235/connect?t=...&n=<hostname>` for
the one-click PC invite. The QR is generated by a pure-stdlib encoder
embedded in the hub (verified bit-exact against an independent
implementation) - no internet access is ever made. Answer is
`image/svg+xml` with `Cache-Control: no-store`.

### GET /connect + POST /peer-connect (v2.8.1) - one-click LAN invite
The hub PC's dashboard LAN card offers **Copy invite link**
(`http://<ip>:9235/connect?t=<hub-token>&n=<PC-name>`). Opened on the
OTHER PC, `/connect` serves a confirmation page; its button form-POSTs
to the OTHER PC's own hub at `http://127.0.0.1:9235/peer-connect` with
`url`, `token`, `name`, `confirm=1`. The receiving hub saves the peer
into `config.json` (`peer_hubs`, dedupe by URL), health-probes it and
replies with a success page.

Guards on `/peer-connect` (it works WITHOUT the receiving hub's token by
design): loopback requests only; a browser `Origin` header, when present,
must equal the peer URL being added (blocks drive-by CSRF); the peer URL
must be a private-LAN http(s) address; GET never mutates anything. Audit:
`peer.invite` / `peer.connected` / `peer.connect.denied`.

### POST /jobs/bulk-reprint (v2.7.0)

Body: either `{"ids":[12,13,14]}` (History tab "Reprint selected") or
`{"scope":"not_printed","limit":500}` (every `failed` / `dead` /
`canceled` job — "Reprint all non-printed"). Optional `reason`,
`watermark`, `watermark_text`, `printer` ride along exactly like the
single-job reprint. Per-job problems never abort the batch:

```json
{"ok":true,"queued":2,"skipped":1,
 "results":[{"id":12,"ok":true,"job_id":41},
            {"id":13,"ok":false,"error":"original file no longer stored"}]}
```

### POST /history/clear (v2.7.0)

Deletes every FINISHED job (`printed / failed / dead / canceled /
forwarded / saved`). Waiting jobs (`queued / printing / held /
scheduled`) are NEVER touched — clearing the history can not cancel a
real print. Audited as `history.cleared`.

```json
{"ok":true,"deleted":37,"message":"37 finished job(s) removed from the history"}
```

---

## GET /testprint?kind=a4|thermal

Queue a built-in test page/receipt. No body needed.

---

## CLI equivalents

```
python hub/advprint.py serve          # start (default command)
python hub/advprint.py testprint a4   # test page
python hub/advprint.py printers       # list printers
python hub/advprint.py history 20     # last 20 jobs
python hub/advprint.py reprint 17     # reprint job 17
python hub/advprint.py queue          # paused? pending? current?
python hub/advprint.py doctor         # environment self-check
```

## Browser fallback form

Strict CSP environments can POST `application/x-www-form-urlencoded` with a single field `payload` containing the JSON — same endpoints, same responses.

---

## v2.4.0 — debug, instant print, held jobs

### GET /debug?token=...
Full diagnostics — answers "why is it not printing?" in one JSON:
`version`, `uptime_s`, `worker_alive`, `paused`, `hold_offline`,
`instant_auto_queue`, `token` (masked), `printers[]` (name+status),
`default_printer`, `sumatra_found`, `sumatra_path`,
`sumatra_searched[]` (every path checked, when not found), `db`
(by_status, queue_size, success_rate, printed_7d, failed_7d),
`recent_jobs[]`, `problems[]` (level/check/message/fix),
`client_reports[]` (browser-side errors, when debug is on).

### GET /dashboard?token=...
The LIVE debug & test tool (HTML, open in a browser): send a real test
print to any printer, watch every status change live, final verdict
REAL PRINTER HIT / saved / held / failed (+fix). Release held jobs,
pause/resume, settings toggles.

### GET /audit?token=...[&limit=100]
Audit trail (SQLite, survives restarts). Events: `print.submitted`
(actor/site/ip/doc_hash), `print.held`, `print.requeued`, `print.saved`,
`auth.failed` (attempt counter), `config.changed`, `queue.paused`,
`queue.resumed`.

### GET /config?token=... · POST /config
Live settings, persisted to `<data dir>/config.json`.
POST body (header auth as usual): `{"debug":true, "hold_offline":true,
"instant_auto_queue":true, "sumatra_path":"C:\\...\\SumatraPDF.exe",
"file_dir":"D:\\pdfs", "printer":"", "token_header_only":true}`.
Response: `{"ok":true,"changed":["debug"]}`. Every change is audit-logged.

### POST /client/report
Browser-side error reports (extension sends them when Debug is on).
Body: `{"level":"error","message":"...","url":"https://..."}`.
Shown in `/debug` → `client_reports[]` and the dashboard.

### Instant / direct print
`POST /print` accepts `instant:true` or `mode:"instant"` — the job jumps
the queue (priority dispatch). If no printer is ready it auto-falls back
to the normal queue (`instant_auto_queue`), response then contains
`"auto_queued": true`. The job is never lost.

### Held jobs (hold_offline)
Jobs for an offline printer are parked as `held` with `held_reason`
(a watcher releases them when the printer is ready). Force-print:
`POST /jobs/{id}/release` (single) · `POST /jobs/release_all` (all).
`GET /jobs/{id}` returns one job (used by the live watcher).

### Virtual PDF printers
Printing to "Microsoft Print to PDF" is auto-routed to a direct PDF save
(status `saved`, `file` = full path) — no renderer, no Save-As dialog,
works with no physical printer installed.
