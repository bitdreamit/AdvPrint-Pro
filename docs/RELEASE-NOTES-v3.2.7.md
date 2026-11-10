# AdvPrint Pro v3.2.7 - Release Notes
### by Bit Dream IT - Innovative Healthcare Solutions

**THE DEVELOPER API RELEASE.** The print API — `window.advprint` in
every web page and `POST /print` over plain HTTP — is now documented
A-to-Z: every method, every option, every response field, with full
worked examples for the real cases. Base: v3.2.6 (every fix and the
local-only UI security model unchanged).

---

## 1. The Developer API guide — three places, one click away

**a) `docs/DEVELOPER-API.md` (new, ~600 lines)** — the complete guide:

- **`window.advprint`** method by method — `status()`, `printers()`,
  `history(n)`, `printPage()`, `printPdf()`, `print()`,
  `printPdfLink()` — with the camelCase → hub field mapping, the
  Promise + 30 s timeout mechanics, the "resolves `{ok:false,error}`"
  pattern vs the `printPdfLink` fallback-reject, and a safePrint
  error-handling example.
- **Direct HTTP** `POST /print` — three token placements
  (`X-AdvPrint-Token` header / `?token=` / JSON `token`), FOUR body
  styles (JSON, raw PDF bytes with query options, raw label bytes
  `?kind=raw`, multipart + the strict-CSP form fallback), the
  payload-source priority order (raw body → `raw_base64` →
  `text+lang` → `pdf_base64` → `pdf_url` → `image_base64` → `html` →
  `page_url` → `text`), the full option table, the response fields
  (`job_id`, `status`, `queue_mode`, `instant`, `auto_queued`,
  `duplicate`, `scheduled_for`…) and the 400/401/403/421/500 error map.
- **SAME PC, MANY PRINTERS** — how targeting resolves (exact name with
  typo self-heal → group → hub destination → `destination:"file"`),
  and the two concurrency models: Queue Mode (one-by-one, `priority:1`
  first) vs `queue:false` INSTANT (one thread per job — receipt on the
  thermal roll + invoice on the laser at the same moment). One call
  per printer loops print the same PDF to 3 printers — never dedupe-
  blocked, because the dedupe key includes the printer name.
- **MANY PCs, ONE HUB** — every PC POSTs to
  `http://<lan-ip>:9235/print`; Allowed-IPs decide who reaches the
  print surface, the console UI stays local-only (v3.2.6). A table of
  what actually serializes (FIFO worker, max 2 headless renders, dedupe
  window) vs what runs in parallel (instant threads, raw jobs, every
  HTTP request) — plus peer-hub queue shifting.
- **PDF + ZPL AT THE SAME TIME** — raw jobs skip the printer-ready
  probe and run beside the PDF pipeline; full `^XA…^XZ` label examples
  (curl / JS / Python; latin-1 verbatim — YOU own `^PW`, `^LL`, `^PQ`)
  and the ESC/POS marker builder (`#big`, `|center|`, `|right|`,
  `|cut|`, `|drawer|`, `|barcode:123|`, `|qr:text|`).
- **URL & token map** — `ipp://` (OS Add-printer) vs `http://`
  (browsers/code; the QR encodes http:// since v3.2.6), per-printer
  queue slugs (`HP LaserJet Pro` → `hp-laserjet-pro`, URL-encoded names
  accepted too), the 631 mirror, RAW 9100, `/send`, local-only `/ui`.
- **Case studies a–i** — POS receipt, Laravel signed-URL invoices,
  Python ZPL labels, scheduled `run_at` reports, `priority:1` urgent
  jobs, duplex + n-up booklets, archive-as-PDF, watermarked reprints
  with audit reasons, kiosk printer-by-paper routing — plus a cheat
  sheet card at the end.

**b) The hub `/docs` page — new section 9 "Developer API"** (9a
methods · 9b HTTP from any language · 9c one PC many printers / many
PCs one hub · 9d ESC/POS + ZPL · 9e URL & token map), TOC entry added.

**c) The in-UI Docs modal (console → ? Quick start guide) — new
section 9** with the live hub URL and port baked into the examples, so
the API answers live inside the ONE UI.

## 2. window.advprint.print() — FULL API PARITY (code change)

The extension's generic print now also passes **`run_at`** (scheduled
printing), **`queue`** (instant mode), **`dedupe`** (repeat override),
**`tray`** (CUPS tray select) and **`watermark_text`** to the hub —
the browser API and the HTTP API accept exactly the same option set
(extension `background.js`; documented in `api.js` and
`EXTENSION-API.md`).

## 3. Version 3.2.7 everywhere

VERSION.txt, hub `VERSION`/`VERSION_NAME`, extension manifest, popup,
options, i18n branding, api.js fallback version, console boot default,
CHANGELOG, this file and the A-to-Z DEV GUIDE.

## 4. Everything from v3.2.6 — unchanged

History/Queue clear really cleans · printer details URL no longer
doubles `/ipp/print` · LAN panel top switch + token-carrying Copy URL +
independent IPP toggle · IPP auto-ON with LAN sharing · QR encodes
`http://`, copy keeps `ipp://` · docs inside the UI · the console UI
local-only (loopback or own IP) while LAN PCs keep FULL print access
per the Allowed-IPs list · CLI menu gone, tray = Dashboard / Restart /
Exit.

---

*AdvPrint Pro v3.2.7 — by Bit Dream IT - Innovative Healthcare
Solutions — MIT license — 100% local, no cloud.*
