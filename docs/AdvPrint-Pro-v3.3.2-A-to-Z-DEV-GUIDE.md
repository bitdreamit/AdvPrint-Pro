# AdvPrint Pro v3.3.2 — A-to-Z DEVELOPMENT & BUILD GUIDE

> **v3.3.2 = "SHARE SEND MODE + WINDOWS IPP ADD-FIX RELEASE" on top of
> v3.3.0.** Four new real-world LAN reports, all fixed and locked by
> `tests/test_v332.py`. Everything from v3.3.0 (any-PC invite,
> dual-stack listeners, Unicode slugs), v3.2.9 (multi-PC IPP echo,
> 128 backlog, per-device hub URLs) and earlier stays unchanged. The
> deep architecture reference lives in
> `docs/AdvPrint-Pro-v3.2.7-A-to-Z-DEV-GUIDE.md`; this guide documents
> the v3.3.2 delta.

> **BUG 1 — Windows "couldn't connect to the printer" (IPP add from
> any PC).** The Get-Printer-Attributes response was missing the RFC
> 8011 REQUIRED `uri-security-supported` attribute, so the Microsoft
> IPP Class Driver rejected the whole response. v3.3.2 emits it, gives
> `uri-authentication-supported` / `uri-security-supported` exactly one
> value per `printer-uri-supported` entry (the RFC 1setOf parity rule
> the old hardcoded pair broke whenever a client URI was echoed on a
> multi-adapter hub), and orders the wire so ALL auth additional values
> precede the security primary (an empty-name value belongs to the
> attribute right before it).
>
> **BUG 2 — tokenless IPP Print-Job > 1 MB died mid-transmit.**
> `_preauth_gate()` answered 401 before reading a >1 MB body without a
> token; Windows speaks IPP without any token and its PDFs are
> routinely > 1 MB, so the client was aborted mid-body. IPP routes
> (`/ipp/print`, `/ipp/print/<queue>`, `/ipp`) are exempt now — the hub
> keeps its own IPP guards (ipp_printer switch, browser-Origin refusal,
> MAX_PDF cap, per-request audit).
>
> **BUG 3 — an unknown per-printer queue hard-404'd the whole add
> flow.** Get-Printer-Attributes on an unmatched slug now answers as
> the generic queue with the requested name as `printer-name` and the
> client URI echoed (the add succeeds), Validate-Job validates,
> Print-Job prints on the hub destination with an audit note, and the
> browser landing page of an unknown queue is the generic how-to page
> instead of raw JSON. The slug may also ride ONLY in the
> `printer-uri` operation attribute (Windows manual add) — handled.
>
> **BUG 4 — SHARE SEND MODE is real.** The Connections "Another PC
> (LAN PC)" card was a demo mockup whose Connect read the SELF PC URL
> field (the "auto redirect own ip" report) and a reload wiped the
> state. v3.3.2: `POST /peer/pair` (self-pair refusal + live probe +
> persists the `lan-pc` peer_hubs entry), `GET /peer/status` (pairing +
> 8 s-cached live probe + switch state), `POST /peer/unpair`,
> `POST /config {share_send}` (server-side ON-without-pairing refusal),
> forced forwarding in the worker (`_try_peer_forward(job, force=True)`
> — every job to the paired PC, local fallback when the peer lacks the
> printer), `POST /peer/test-page` relay, and the LAN PC URL input is
> NEVER overwritten with `lanBase()` again.
>
> **Printers panel — devices from a different IP.** The
> `show_remote_printers` switch lists the paired PC's devices with a
> LAN PC · IPP badge, source ip:port, per-device `ipp://` URL and
> Test Page / Set Default (disabled remotely) / Details.

---

## 1. The three files that must stay in sync

| File | Role |
| --- | --- |
| `tool/unix/hub/advprint.py` | the hub source of truth (VERSION 3.3.2) |
| `tool/windows/portable/hub/advprint.py` | byte-identical copy (installer + tests import THIS one) |
| `tool/unix/hub/console.html` | ONE UI source; embedded into BOTH hub copies by `scripts/embed_console.py` |

After editing the UI: `python3 scripts/embed_console.py`. After editing
hub code: `cp tool/unix/hub/advprint.py
tool/windows/portable/hub/advprint.py`.

## 2. v3.3.2 code map (delta only)

### IPP printer group — `tool/unix/hub/advprint.py`

```
_ipp_printer_group(queue_slug, queue_name, extra_uris)
  ├─ uris = queue URIs (per-printer) + canonical pair
  ├─ extra_uris  <- _ipp_scheme_swaps(request printer-uri)  (client echo)
  ├─ printer-uri-supported      V_URI        uris[0] + additional
  ├─ uri-authentication-supported V_KEYWORD  "none" × len(uris)
  ├─ uri-security-supported     V_KEYWORD    "none" × len(uris)   <- NEW
  └─ … the full RFC 8011 §4.2.5.2 set (v3.0.8) unchanged
```

### IPP request routing

```
POST /ipp/print[/<queue>]            Handler._do_post_impl
  ├─ preauth gate: SKIPPED for /ipp* routes (BUG 2)
  ├─ unknown slug    -> ipp_q_unknown (NO 404 any more, BUG 3)
  ├─ browser Origin  -> 403 (unchanged, audit H6)
  └─ ipp_handle(data, ip, printer=..., unknown_queue=...)
        ├─ printer-uri op attr carries an unresolvable queue tail
        │    -> unknown_queue (BUG 3, Windows manual add)
        ├─ Get-Printer-Attributes / Validate-Job -> generic group,
        │    printer-name = requested name, client URI echoed
        └─ Print-Job / Create-Job / Send-Document / Print-URI
             -> route_print_payload (unknown slug -> hub destination
                + audit "unknown per-printer IPP queue ... answered
                as generic queue")
```

### SHARE SEND MODE endpoints

```
POST /peer/pair    {url, token, name?}   _peer_pair(self, body, ip)
  ├─ url/token missing                 -> 400 "both ... are needed"
  ├─ loopback / own IP on own port     -> 400 "that is THIS PC's own hub"
  │    (peer.pair.denied audit)
  ├─ probe /health with the token      -> dead: 400 with the reason
  │    -> peer share_lan OFF: 400 "enable it there first"
  ├─ ok -> peer_hubs lan-pc entry persisted (config.json)
  └─ 200 = the full /peer/status payload

GET  /peer/status                    _lan_peer_status(fresh=False)
  └─ {configured, url, label, token_set, share_send,
      peer:{alive, version, peer_host, share_lan, ipp_printer,
            default_printer, printers:[{name,status,is_default,ipp}]}}
     (probes cached 8 s: _LANPC_PROBE_CACHE)

POST /peer/unpair {}                 _peer_unpair(self, ip)
POST /peer/test-page {printer}       _peer_test_page(self, body, ip)
POST /config {share_send: true}      rejected 400 without the lan-pc
                                     entry (the persisted-state check)
```

Worker forwarding:

```
_execute_job(job, t0)
  ├─ share_send ON  -> _try_peer_forward(job, force=True)
  │     ├─ probes the lan-pc entry (60 s dead-peer skip list)
  │     ├─ peer lacks the printer -> audit peer.share_send.skipped
  │     │    + prints locally (the job is never lost)
  │     └─ ok -> db status "forwarded" + job.forwarded audit
  └─ else the classic pipeline (peer_forwarding offline fallback
     unchanged, printer groups unchanged)
```

### Console (CONSOLE_HTML / console.html)

```
Connections > Another PC (LAN PC) card
  ├─ lanPcHubUrl  / lanPcToken inputs (placeholders, no own-IP fill)
  ├─ lanPcConnect -> POST /peer/pair -> renderLanPeer()
  ├─ lanPcClear   -> POST /peer/unpair -> renderLanPeer()
  ├─ shareSendSw  -> POST /config {share_send} (bindSwitches branch)
  └─ loadLanPeer() every poll -> GET /peer/status -> chip + status line

Printers panel
  ├─ showRemoteSw -> POST /config {show_remote_printers}
  └─ renderRemotePrinters(st) -> [data-remote] cards: LAN PC · IPP
      badge, peer ip:port, per-device ipp:// URL, Test Page via
      POST /peer/test-page (hub-relayed), disabled Set Default
```

## 3. New config keys

| Key | Type | Default | Meaning |
| --- | --- | --- | --- |
| `share_send` | bool | false | EVERY new job prints on the paired LAN PC |
| `show_remote_printers` | bool | false | Printers panel lists the paired PC's devices |

Both are in `CONFIG_KEYS` + `CONFIG_TYPES` (a missing entry would make
every switch save die with "unknown config key" - the v3.2.3 lesson).

## 4. Tests (tests/test_v332.py)

- `test_gpa_answers_uri_security_supported` / `_parity_holds_when_client_uri_is_echoed`
  / `_wire_order_auth_values_before_security` / `_per_printer_queue_parity`
  - the BUG 1 matrix (strict parse with additional-value grouping).
- `test_ipp_print_job_over_1mb_no_token` - BUG 2 (1.5 MB, no token,
  HTTP 200 + successful-ok, real queued job).
- `test_unknown_queue_gpa_answers_add` / `_print_job_falls_back` /
  `_landing_page_is_html` - BUG 3.
- `test_pair_*` / `test_status_offline_shows_error` /
  `test_share_send_*` / `test_unpair_clears_everything` /
  `test_peer_test_page_relay` / `test_peer_status_shape` /
  `test_redacted_config_masks_peer_token` - BUG 4 against a scripted
  fake peer hub (ThreadingHTTPServer with /health, /printers, /print).
- `test_console_lan_pc_card_is_wired` /
  `test_console_lan_pc_card_never_autofills_own_url` - the UI delta
  (no demo mockup, no `lanBase()` fill, real endpoints).

Run: `python3 -m pytest tests/test_v332.py -q` (and the whole suite
before shipping).

## 5. Build + release checklist

```bash
python3 -m pytest tests/ -q            # full suite green
python3 scripts/embed_console.py       # after ANY console.html edit
cp tool/unix/hub/advprint.py tool/windows/portable/hub/advprint.py
bash scripts/build-all.sh              # CRX3 + extension zip + NSIS exe + deb + SHA256SUMS
```

`build-all.sh` re-signs the CRX (repo key
`extension-signing/advprint-printer.pem`), syncs EVERY embedded CRX
copy and hard-fails if any copy or version drifts (the v3.2.8
stale-CRX guard). Deliverables land in `dist/`.

## 6. Upgrade notes for users

- Install over the old version (Setup exe / deb). config.json is kept;
  `share_send` / `show_remote_printers` default OFF.
- LAN PC pairing: Connections > Another PC (LAN PC) > enter the OTHER
  PC's hub URL + its token (read there: Self PC card / `python
  advprint.py token`) > Connect. The pairing survives reloads and hub
  restarts.
- Windows add-printer: `ipp://<hub-ip>:9235/ipp/print` (whole hub) or
  `ipp://<hub-ip>:9235/ipp/print/<printer>` (one queue) - both validate
  on the MS IPP Class Driver now. The 631 mirror and RAW 9100 keep
  working for Android / Standard TCP/IP ports.
