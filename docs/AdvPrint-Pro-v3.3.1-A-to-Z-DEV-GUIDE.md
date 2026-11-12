# AdvPrint Pro v3.3.1 — A-to-Z DEVELOPMENT & BUILD GUIDE

> **v3.3.1 = "THE LAN PC + WINDOWS IPP CONNECTION RELEASE" on top of
> v3.3.0.** Four user reports from the real two-PC lab, all fixed and
> locked by `tests/test_v331.py` plus the live repro
> `scripts/repro_v331_ipp.py`. Everything from v3.3.0 (any-PC invite,
> dual-stack listeners, Unicode queue slugs), v3.2.9 (multi-PC IPP
> echo, 128 backlog, per-device hub URLs) and v3.2.2–v3.2.8 stays
> unchanged. The deep architecture reference (ONE UI anatomy, print
> pipeline, IPP engine, build internals) lives in
> `docs/AdvPrint-Pro-v3.2.7-A-to-Z-DEV-GUIDE.md`; this guide documents
> the v3.3.1 delta.

> **BUG 1 — Windows "couldn't connect to the printer".** RFC 8011
> requires `printer-uri-supported` / `uri-authentication-supported` /
> `uri-security-supported` to be three PARALLEL 1setOf lists with the
> same value count. v3.3.0 emitted two fixed auth values and no
> security list, so echoing the LAN client's URI broke the cardinality
> and the Microsoft IPP Class Driver refused the printer.
> `_ipp_printer_group()` now emits the full parallel triple ("none"
> per plain-http URI) for the generic queue, every per-printer queue
> and every echoed extra URI.
>
> **BUG 2 — per-printer queues 404 right after hub start.** The queue
> resolver only read the ASYNC printer cache (empty until the
> background enumeration landed). `_lp_refresh_sync()` now enumerates
> synchronously (rate-limited 1 per 2 s, single-flight) when the cache
> is empty, and the negative-match force-refresh uses it too.
>
> **BUG 3 — the "Another PC (LAN PC)" card was a demo mockup.** Connect
> read the SELF PC URL (`input.inp.mono[0]`) and toasted; the renderer
> overwrote the LAN PC URL with the own address every refresh
> (`pcUrl.value = lanBase()`); Clear toasted "(demo value)"; the
> CONNECTED chip was hardcoded; Share Send Mode did not exist. The
> card is real now: server-side probe (`POST /peer-probe`), atomic
> `/config` save of `{url, token}` into `peer_hubs`, live chip, real
> Clear, real instant-save Share Send Mode switch (`#lanPcSendSw`).
>
> **BUG 4 — Share Send Mode sends EVERY job to the LAN PC.** New config
> key `share_send_all`; the worker forwards every printable job
> (`_share_send_forward`) and HOLDS it with a readable reason when the
> LAN PC is unreachable (Print now overrides). Virtual PDF printers
> and raw/receipt jobs stay local. `peer_forwarding` alone keeps the
> v2.9.1 offline-fallback behaviour.

---

## 1. The three files that must stay in sync

| File | Role |
| --- | --- |
| `tool/unix/hub/advprint.py` | the hub source of truth (VERSION 3.3.1) |
| `tool/windows/portable/hub/advprint.py` | byte-identical copy (installer + tests import THIS one) |
| `tool/unix/hub/console.html` | ONE UI source; embedded into BOTH hub copies by `scripts/embed_console.py` |

After editing the UI: `python3 scripts/embed_console.py` (re-embeds the
console into both hub copies, mirrors console.html to the portable hub,
verifies the copies are byte-identical). After editing hub code:
`cp tool/unix/hub/advprint.py tool/windows/portable/hub/advprint.py`.

## 2. v3.3.1 code map (delta only)

### BUG 1 — the RFC 8011 uri triple

```
_ipp_printer_group(queue_slug, queue_name, extra_uris)   advprint.py
  ├─ uris  = canonical (+ queue URIs first) + echoed extra URIs
  ├─ auths = ["none"] * len(uris)          # NEW: grows with uris
  ├─ secs  = ["none"] * len(uris)          # NEW: the missing attribute
  └─ emits printer-uri-supported 1setOf  (V_URI)
            uri-authentication-supported 1setOf (V_KEYWORD)
            uri-security-supported 1setOf (V_KEYWORD)
     -> every value list has len(uris) entries - the exact validation
        the Microsoft IPP Class Driver runs during Add Printer
```

### BUG 2 — synchronous cold-start queue resolution

```
_lp_refresh_sync()            NEW: runs _lp_refresh() inline; single-
                              flight via _SWR_BUSY, rate-limited by
                              _LP_SYNC_TS (2 s) and skipped when the
                              cache already has names
_ipp_queue_match(name)        NEW: if _LP_CACHE["v"] is empty ->
                              _lp_refresh_sync() BEFORE the compare
_ipp_queue_match_cached(name) negative path: _lp_refresh_sync()
                              instead of the async force-refresh, so
                              the memo never stores "unknown" for a
                              printer that exists
```

### BUG 3 — the real LAN PC card (ONE UI)

```
#p-connections card #lanPcCard
  ├─ #lanPcHubUrl  user-owned input (NEVER overwritten by the
  │                renderer - the old pcUrl.value = lanBase() is gone)
  ├─ #lanPcToken   the OTHER PC's token (password field)
  ├─ #lanPcConnect -> POST /peer-probe {url, token}  (server-side probe)
  │                  -> POST /config {peer_hubs:[{url,token,name}],
  │                                   peer_forwarding:true}
  ├─ #lanPcClear   -> POST /config {peer_hubs:[], peer_forwarding:false,
  │                                 share_send_all:false}
  ├─ #lanPcChip    live from /peers + /config: CONNECTED / OFFLINE /
  │                NOT CONFIGURED (the hardcoded demo chip is gone)
  └─ #lanPcSendSw  Share Send Mode switch -> POST /config
                   {peer_forwarding:v, share_send_all:v} (instant save);
                   refuses ON while peer_hubs_count == 0

POST /peer-probe    Handler (token-gated, in _do_post_impl after auth)
  ├─ validates the URL shape (http/https + netloc) and refuses
  │  non-private hosts (400)
  ├─ GET <url>/health with X-AdvPrint-Token
  └─ -> {ok, up, version, hostname, share_lan, token_ok} or
        {ok, up:false, error:"no answer from ..."}
```

### BUG 4 — Share Send Mode in the worker

```
CFG["share_send_all"]  DEFAULTS/CONFIG_KEYS/CONFIG_TYPES + /config

worker loop (after resolve_dest, BEFORE the offline checks):
  if dkind != "ip" and share_send_all and peer_forwarding and peers:
      sent, why = _share_send_forward(job)
      sent  -> continue                      # job forwarded
      raw or virtual-PDF printer -> fall through to local printing
      else  -> _hold_job(job, why); continue # LAN PC unreachable

_share_send_forward(job) -> (True, None) | (False, reason)
  ├─ skips raw jobs and virtual PDF printers (stay local)
  ├─ reads the document, POST <peer>/print
  │    {pdf_base64, title, printer, copies, kind, source:"share-send:PORT"}
  ├─ ok -> db_update(status="forwarded", peer=url) + audit
  └─ dead/absent peer -> (False, "LAN PC hub unreachable - job held ...")

health snapshot additions: peer_forwarding, share_send_all,
peer_hubs_count (the ONE UI chip/switch render the REAL state)
```

## 3. Tests (tests/test_v331.py)

| Group | What it locks |
| --- | --- |
| version coherence | 3.3.1 in VERSION/VERSION_NAME, VERSION.txt, manifest, CHANGELOG, NSI, console |
| copies | byte-identical hub copies + console mirror |
| BUG 1 | Windows lint of the uri triple: generic queue, per-printer queue, aliased echo, unit-level builder |
| BUG 2 | cold-start queue resolution, negative-match retry |
| BUG 3+4 config | share_send_all round-trip, health keys |
| /peer-probe | live peer (version/hostname/share_lan/token_ok), dead peer, non-LAN host 400, auth 401 |
| BUG 4 worker | every job forwarded (fake peer hub), hold on unreachable LAN PC, legacy offline fallback unchanged |
| BUG 3 UI | card ids present, own-IP overwrite gone, demo toasts gone, probe+save chain, instant-save switch |

Live repro: `python3 scripts/repro_v331_ipp.py` — boots the real hub,
binds the client socket to a non-loopback interface (LAN-looking
source), sends the exact Get-Printer-Attributes / Print-Job /
Create-Job + Send-Document sequences a Windows 11 client sends and
lints every response with a strict wire parser (26 checks).

## 4. Build + release (unchanged order)

```bash
python3 scripts/embed_console.py     # after any console.html edit
python3 -m pytest tests/ -q          # 563+ tests green
python3 scripts/repro_v331_ipp.py    # 26/26 Windows LAN checks
python3 scripts/smoke_v330.py        # v3.3.0 behaviour still locked
bash scripts/build-all.sh            # NSIS + CRX3 + DEB + SHA256SUMS
```

`build-all.sh` verifies the CRX copies (unix hub / portable hub /
prebuilt) are byte-identical, stages `dist/AdvPrint-Pro-v3.3.1.zip`,
builds `AdvPrint-Pro-Setup-3.3.1.exe` (NSIS + bundled Python runtime)
and `advprint-pro_3.3.1_all.deb`, then writes `SHA256SUMS-3.3.1.txt`.
