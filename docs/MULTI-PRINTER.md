# Multiple printers on one PC — how AdvPrint Pro routes every job
**AdvPrint Pro (Advanced Printer) - by Bit Dream IT - Innovative Healthcare Solutions**
MIT license - 100% local - no cloud, no tracking

This is the lab guide: one PC, several printers at the same time - the
A4/A5 **PDF report printer** AND the **Zebra (or any other) label
printer** running side by side, each job landing on the right machine,
in the right format. Everything below is what the hub actually does
(v3.0.2 code) - no theory.

---

## 1. The one rule: the per-job printer name always wins

`resolve_dest()` in the hub is three lines of priority:

1. **The job carries a printer name** -> it prints EXACTLY there
   (always a local printer on this PC).
2. No printer name? -> the **Print destination** card decides
   (`dest_mode`): OS default / the selected printer / an upstream IP
   printer (RAW JetDirect or IPP). An unreachable IP printer holds the
   job (reason in the queue row; **Print now** overrides).
3. A name that matches a **printer group** -> the group's first healthy
   member prints it (failover, see section 4).

So multi-printer routing is simply: **make sure each job is addressed**.
Every sending path can address a printer:

| Sender | How to pick the printer |
| --- | --- |
| Extension auto-print rule | the rule's **printer** dropdown (Options > Auto-print rules - every rule has its own printer, paper, tray, duplex, copies) |
| Extension default | Options > Connection > **Default printer** dropdown (lists every printer + groups from the hub) |
| Page API (`window.advprint`) | `printPage({printer:"Zebra ZD421"})` / `printPdf(..., {printer:...})` - per call |
| `POST /print` (your app) | `"printer": "Zebra ZD421"` field |
| Print profile | `profiles` in config: `{"LabReport": {"printer": "HP...", "paper_size": "a4", "duplex": true}}` + `profile=LabReport` in the job |
| Hub dashboard | reprint / shift a job to another printer from the queue row |
| Phone / other PC via IPP or RAW 9100 | these jobs carry NO printer name - they follow the Print destination card (or a group name if you send one in the IPP job data flow you control) |

## 2. Payload types are routed by CONTENT (the same PC prints everything)

The hub sniffs every job's bytes and picks the right pipeline - this is
why one PC can serve the report printer and the label printer at the
same time:

| Bytes start with | Detected as | What the hub does |
| --- | --- | --- |
| `%PDF` | PDF | the full PDF pipeline (Sumatra/lp) - paper A4/A5/letter, tray, duplex, pages range, copies, quality, n-up |
| JPEG | image | wrapped into a single-page PDF (fit-to-page), then printed |
| `^XA` | **ZPL** | **RAW passthrough** - the byte stream goes to the target printer untouched; the Zebra renders its own labels |
| `\x1b@` | **ESC/POS** | RAW passthrough (receipt printers) |
| `%!PS` | PostScript | RAW passthrough |
| `\x1b%-12345X` / `\x1bE` | PCL | RAW passthrough |
| plain text | text | rendered to a real PDF - A4 page or 80 mm receipt roll (`paper=thermal`); Bangla/complex scripts shaped via headless Chrome |

RAW passthrough is also enqueued: every label/receipt job lands in
History with its printer name, and can be reprinted or canceled like a
PDF job.

## 3. The lab scenario, step by step (worked example)

**Setup**: one Windows PC, two printers installed in Windows as usual -
`HP LaserJet M404` (A4/A5 lab reports, PDFs from the LIS portal) and
`Zebra ZD421` (specimen labels, ZPL from the label page).

1. **Install** the hub (Setup exe / deb) + the extension
   (chrome://extensions > Load unpacked). Connect the extension
   (popup > Connect - token auto-detected on this PC).
2. **Reports (PDF, A4 or A5)** - Options > Auto-print rules > Add rule:
   - pattern `*://lis.hospital.local/*` (your LIS/portal URL)
   - printer: `HP LaserJet M404`
   - paper: `A4` (or `A5` - the option is passed straight to the print
     engine as media size; A5 halves the sheet for short reports)
   - every PDF opened on that portal now prints silently on the HP -
     other tabs keep the OS default printer.
3. **Labels (ZPL)** - pick whichever flow matches your label software:
   - **Browser label page**: call the page API with the printer name -
     `window.advprint.printPage({printer:"Zebra ZD421"})` for page
     print-outs, and for ZPL push the label bytes to the hub API with
     `lang:"zpl"` + the label text (curl example in section 5) - the
     hub streams the ZPL to the Zebra untouched.
   - **Desktop label software** (NiceLabel, BarTender, ZebraDesigner...):
     install the hub as a NETWORK PRINTER for it - add
     `http://<this-PC-IP>:9235/ipp/print` (IPP) or a RawTCP 9100 port
     (JetDirect). The software sends ZPL, the hub sniffs `^XA`, enqueues
     it and streams it to the **Print destination**. In a mixed lab set
     the destination card to the Zebra (`dest_mode:"selected"`) for this
     flow - or address the job explicitly (API/`printer` name) so both
     printers keep working from the same hub without flipping the card.
4. **Paper sizes per job**: `/print` accepts `paper=a4|a5|letter|...`
   (media size), `paper_size`, `tray`, `duplex`, `copies` (1-50),
   `pages` (e.g. `1-2`), `quality`/`dpi`, `per_sheet` (n-up),
   `orientation`, `margin_mm`/`scale_pct` for generated PDFs - per rule
   or per API call. Named `profiles` bundle them:
   `{"LabReportA5": {"paper_size":"a5","tray":"Tray 2"}}` then
   `profile=LabReportA5`.
5. **Failover with a group** - dashboard Settings (`printer_groups`):
   `{"Lab": ["HP LaserJet M404", "HP Backup M402"]}`. Address a job to
   `Lab` and the first member that is not offline/paper-out/error prints
   it (checked live, in your order). Groups appear in the extension
   dropdowns and in `GET /printers` with their members.
6. **Watch it work** - dashboard Printers card shows every printer with
   live status (ready / offline / paper-out / printing + default badge);
   the Queue and History rows name the printer of every job; the audit
   trail records who printed what where (site, IP, doc hash).

## 4. When the chosen printer is down (hold, group, peer)

- Single printer named in the job + it is offline/paper-out/error:
  with **Printer status hold** ON the job is HELD with the reason shown
  (**Print now** overrides; switch off for fire-and-forget).
- Group named in the job: the next healthy member takes it
  automatically (no hold).
- Optional **peer forwarding**: a LAN PC hub with the same printer can
  take the job when this PC's printer reports a real failure
  (offline/paper-out/error only - never on unknown states; dead peers
  get a 60 s skip cache).
- `dest_mode:"ip"` upstream printer unreachable: job held until the
  TCP probe succeeds again (that probe is also the **Test** button in
  the Print destination card).

## 5. Quick reference - address a printer from anywhere

```bash
# A5 lab report, 2 copies, on the HP
curl -X POST http://127.0.0.1:9235/print \
  -H "X-AdvPrint-Token: $TOKEN" -H "Content-Type: application/json" \
  -d '{"title":"Lab report 4711","kind":"pdf","printer":"HP LaserJet M404",
       "paper":"a5","copies":2}'

# ZPL specimen label on the Zebra (raw passthrough - verbatim ZPL II)
curl -X POST http://127.0.0.1:9235/print \
  -H "X-AdvPrint-Token: $TOKEN" -H "Content-Type: application/json" \
  -d '{"title":"Specimen 4711","kind":"raw","printer":"Zebra ZD421",
       "lang":"zpl","text":"^XA...your label...^XZ"}'
# or pre-encoded bytes: {"kind":"raw","printer":"Zebra ZD421",
#                       "raw_base64":"<base64 ZPL starting with ^XA>"}

# named profile + group
curl -X POST http://127.0.0.1:9235/print ... \
  -d '{"title":"Report","kind":"pdf","printer":"Lab","profile":"LabReportA5"}'
```

```js
// page API (allowlisted sites): printer per call
await window.advprint.printPage({ title: "Invoice 42",
                                  printer: "Zebra ZD421" });
await window.advprint.printers();   // live list incl. groups
```

That is the whole story: **name the printer on the job, let the payload
decide the pipeline, use groups when you want failover** - any number of
printers on one PC, PDFs to the laser and ZPL to the Zebra, at the same
time, from the same hub.
