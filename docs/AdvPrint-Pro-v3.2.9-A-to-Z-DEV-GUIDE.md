# AdvPrint Pro v3.2.9 — A-to-Z DEVELOPMENT & BUILD GUIDE

> **v3.2.9 = "THE MULTI-PC IPP RELEASE" on top of v3.2.8.**
> Three real-world multi-PC reports from the AI-Lab LAN, all fixed and
> locked by `tests/test_v329.py` (22 tests). Everything from v3.2.8 —
> the clean `ipp://` URL, the scheme-free Website API rule, the stale-CRX
> guard — and every v3.2.2 – v3.2.7 fix stays unchanged. The deep
> architecture reference (ONE UI anatomy, print pipeline, IPP engine,
> build internals) lives in `docs/AdvPrint-Pro-v3.2.7-A-to-Z-DEV-GUIDE.md`;
> this guide documents the v3.2.9 delta.

> **BUG 1 — a per-printer queue refused to connect from other PCs.**
> `ipp://<ip>:9235/ipp/print/<printer-name>` failed on a SECOND PC
> ("Windows cannot connect") while the generic `/ipp/print` kept
> working. Root cause: `Get-Printer-Attributes` answered with only the
> generic `printer-uri-supported` pair — the client never saw the queue
> URI it asked for, and `printer-name` was the hub hostname. v3.2.9
> echoes the queue end to end (`_ipp_printer_uris()` /
> `_ipp_queue_uris()` / `_ipp_scheme_swaps()`), names the queue after
> the real printer, gives each queue a stable per-queue
> `printer-uuid`, and honours a queue name that arrives ONLY in the
> request's `printer-uri` attribute.
>
> **BUG 2 — one hub, MANY PCs: professional + optimized + powerful.**
> Accept backlog 5 → 128 on every listener (9235 / 631 / 9100), all
> `_IPP_JOBS` session mutations under the session lock, memoized
> queue-name resolution (`_ipp_queue_match_cached`), unique
> `_write_atomic` temp names + serialized virtual-PDF saves
> (`_VPDF_LOCK`), and every ACL 403 echoes the ACTIVE `allowed_ips`
> rules (`*` / exact / CIDR / wildcard — enforced identically on 9235,
> 631 and RAW 9100).
>
> **BUG 3 — every LAN PC saw the SAME hub URL.** All pages showed
> `http://<hub-lan-ip>:9235` (the hub's default-route address — on a PC
> with a VPN/adapter that can be an address the client can NOT reach).
> v3.2.9 builds every URL from the address THE OPENING DEVICE used
> (sanitized Host header via `_sanitize_host_hdr()` /
> `Handler._req_host()`), ships the per-device boot JSON
> (`self_host`/`self_port`/`client_ip`/`lan_ips`), and the LAN panel
> lists every hub interface IP (`list_lan_ips()`) as copyable chips.
>
> **Delivery-layer fix — `scripts/embed_console.py`.** The old embed
> wrote the closing quotes WITHOUT the leading newline, so the NEXT
> embed's delimiter search overshot into `DOCS_HTML` and silently
> deleted `docs_html()` / `DOCS_HTML` / `console_page_bytes()` /
> `dashboard_html()` from the hub (/docs and /ui answered 500). The
> block now ends `OPEN + html + CLOSE` and a regression test locks it.

---

## 1. What changed in v3.2.9 (the exact code map)

### BUG 1 — the per-printer queue echo (IPP engine)

| Where | What |
| --- | --- |
| `_ipp_queue_uris(slug)` (NEW) | the `http://` + `ipp://` pair for ONE queue path |
| `_ipp_scheme_swaps(uri)` (NEW) | both scheme forms of ANY requested printer URI |
| `_ipp_printer_group(queue_slug, queue_name, extra_uris)` | queue URIs FIRST in `printer-uri-supported`, queue `printer-name`/`printer-info`, per-queue `printer-uuid` (`_ipp_printer_uuid(queue_slug)`), queue `printer-more-info` |
| `_ipp_job_group(..., queue_slug)` | `job-uri` under `/ipp/print/<slug>/job/<id>` |
| `ipp_handle()` | resolves a queue name that arrives ONLY in `printer-uri`; threads `q_slug` + the requested URI (both schemes) through EVERY response |

Behaviour after the fix (from `tests/test_v329.py`):

```text
GET ipp Get-Printer-Attributes  printer-uri = http://ip:9235/ipp/print/HP-Laser-103
->  printer-uri-supported:
      1. http://<hub-ip>:9235/ipp/print/hp-laser-103   (canonical, BOTH schemes)
      2. ipp://<hub-ip>:9235/ipp/print/hp-laser-103
      3. http://ip:9235/ipp/print/HP-Laser-103         (EXACT requested form, both schemes)
      4. ...generic /ipp/print pair
    printer-name  = HP Laser 103
    printer-uuid  = per-queue, stable across restarts
    job-uri       = ipp://<hub-ip>:9235/ipp/print/hp-laser-103/job/<id>
```

### BUG 2 — the optimized multi-PC node

| Where | What |
| --- | --- |
| `HubServer.request_queue_size = 128` | accept backlog on the main listener |
| `_IPP631Server` (NEW) + `request_queue_size = 128` | same for the 631 mirror; `IPP631Handler.timeout = 30` |
| `Handler.timeout = 30` | already v2.9.1; idle LAN clients release their thread |
| `_ipp_queue_match_cached()` (NEW) + `_QMATCH_*` | thread-safe memo (10 s hit / 5 s negative TTL) used by the queue landing page, both IPP POST paths and `ipp_handle` |
| `_IPP_JOBS_LOCK` in `ipp_handle` | Send-Document append/counter/join, Cancel-Job flag, Get-Job-Attributes snapshot |
| `_write_atomic()` | temp name `path.part<pid>.<seq>` — unique per call (`_ATOMIC_SEQ`) |
| `_save_virtual_pdf()` + `_VPDF_LOCK` | free-name check + write serialized; second job gets `-2` |
| `_ip_gate()` 403 JSON | echoes `"allowed_ips": [...]` |
| `ipp_landing_html()` | states who may print (`*` → "every device on the LAN"; restricted → the rules) |

### BUG 3 — per-device URLs

| Where | What |
| --- | --- |
| `list_lan_ips()` (NEW) | every IPv4 interface address, private ranges first, cached 15 s |
| `_sanitize_host_hdr(h)` (NEW) | Host header → (host, port) or ("", None); only `[a-z0-9._-:%]` survives, ≤253 chars |
| `Handler._req_host()` / `_req_port()` | the address THIS request used (loopback names → "" so the hub's shareable IP is used) |
| `console_page_bytes(view, req_host, req_port, client_ip)` | boot JSON gains `self_host`/`self_port`/`client_ip`/`lan_ips` |
| `ipp_landing_html(req_host, req_port)` | primary URLs per device (9235 + 631 mirror) |
| `/printers` | `item["ipp_queue"] = ipp_queue_url(n, host=_req_h)` — per request |
| GET `/ipp/print/<name>` | queue landing page per device |
| ONE UI JS | `isLoopHost()` / `hubIp()` / `hubPort()` replace the `BOOT.lan_ip`-first `lanBase()`; LAN panel gains `row-hubips` + `hubIpList` chips + `lanPcHubUrl` input fill; mDNS/631/RAW rows all use `hubIp()` |
| `/health` | new key `lan_ips` (top 8) |

### Delivery layer

| Where | What |
| --- | --- |
| `scripts/embed_console.py` | block ends `OPEN + html + CLOSE` (keeps the `\n` before the closing quotes) |
| `extension/manifest.json` | 3.2.9 (+ popup/options/i18n brand lines, `api.js` `_apVerFallback`) |
| embedded CRX copies | re-signed, version 3.2.9, extension id unchanged |

---

## 2. Development environment

```bash
# any Linux with python3; Windows features build from the same tree
cd AdvPrint-Pro
python3 -m pytest tests/ -q          # 484+ tests, the v3.2.9 set in tests/test_v329.py
# data dir: ~/.advprint (config.json holds the API token)
# token:   cat ~/.advprint/config.json | python3 -c \
#          "import json,sys;print(json.load(sys.stdin)['token'])"
```

## 3. Rebuilding every artifact

```bash
python3 tool/crx3.py pack extension extension-signing/advprint-printer.pem \
        dist/AdvPrint-Pro.crx            # signed CRX3 (repo key)
cp dist/AdvPrint-Pro.crx tool/unix/hub/extension/AdvPrint-Pro.crx
cp dist/AdvPrint-Pro.crx tool/windows/portable/hub/extension/AdvPrint-Pro.crx
python3 scripts/embed_console.py         # ONE UI -> both hub copies (v3.2.9 close fix)
cp tool/unix/hub/advprint.py tool/windows/portable/hub/advprint.py
bash scripts/build-all.sh                # NSIS Setup + DEB + zips + SHA256SUMS
# dist/AdvPrint-Pro-Setup-3.2.9.exe
# dist/advprint-pro_3.2.9_all.deb
# dist/AdvPrint-Pro-Extension-3.2.9.zip
# dist/SHA256SUMS-3.2.9.txt
# the build still FAILS on any stale embedded CRX or version drift
```

## 4. Release checklist (the exact v3.2.9 process)

1. Bump `VERSION`/`VERSION_NAME` in `tool/unix/hub/advprint.py`; sync to the
   windows portable copy.
2. Bump `extension/manifest.json` + the extension surface versions
   (popup.html, options.html, i18n brandLine x2, `api.js` `_apVerFallback`,
   console `BOOT.version` fallback) and `installer/setup.nsi` (OutFile,
   VIProductVersion, FileVersion/ProductVersion, DisplayVersion, hints).
3. Update `VERSION.txt`, `CHANGELOG.md` (new `## v3.2.9` section on top),
   `README.md` What's-new, `START-HERE.txt`.
4. Write `docs/RELEASE-NOTES-v3.2.9.md` + this guide.
5. Move the version pins in the older test files forward
   (test_hub_v2, test_one_ui_v321, test_v322 … test_v328) — they assert the
   CURRENT release everywhere; write `tests/test_v329.py`.
6. `python3 scripts/embed_console.py` → byte-identical hub copies.
7. Pack the CRX, refresh BOTH embedded hub CRX copies.
8. `python3 -m pytest tests/ -q` → all green.
9. `bash scripts/build-all.sh` → `dist/SHA256SUMS-3.2.9.txt` covers
   CRX + extension zip + DEB + Setup EXE.
10. Live smoke: `python3 scripts/smoke_v329.py` (boot a throwaway hub on a
    free port; check the landing page, a queue echo, the ACL 403, per-device
    URLs and 8 parallel IPP clients).

## 5. Where things live (code map, v3.2.9)

```text
tool/unix/hub/advprint.py            THE hub (one file; identical copy under
                                     tool/windows/portable/hub/)
  ├ CONSOLE_HTML                     the ONE UI (embedded; source of truth:
  │                                  tool/unix/hub/console.html)
  ├ lan_ip() / list_lan_ips()        one IP vs EVERY interface IP (v3.2.9)
  ├ _sanitize_host_hdr()             Host header -> safe (host, port)
  ├ Handler._req_host()/_req_port()  per-request device address
  ├ console_page_bytes()             boot JSON: self_host/self_port/client_ip/lan_ips
  ├ ipp_landing_html()               IPP how-to page (9235 + 631), per-device
  ├ ipp_queue_url(printer, host)     per-printer ipp:// URL, optional host override
  ├ _ipp_queue_match_cached()        memoized queue-name resolution (v3.2.9)
  ├ _ipp_queue_uris()/_ipp_scheme_swaps()  queue URI echo helpers (v3.2.9)
  ├ _ipp_printer_group(queue_slug…)  queue echo in Get-Printer-Attributes (v3.2.9)
  ├ _ipp_job_group(queue_slug)       queue job-uri (v3.2.9)
  ├ ipp_handle()                     RFC 8011 ops; _IPP_JOBS_LOCK discipline (v3.2.9)
  ├ HubServer/_IPP631Server          request_queue_size = 128 (v3.2.9)
  ├ _write_atomic()/_save_virtual_pdf()  unique temp names + _VPDF_LOCK (v3.2.9)
  └ _ip_gate()                       ACL 403 echoes allowed_ips (v3.2.9)
extension/                           the Chrome extension (manifest 3.2.9)
tool/crx3.py                         CRX3 pack/info (repo key)
scripts/embed_console.py             ONE UI embedder (v3.2.9 close fix)
scripts/build-all.sh                 the release builder
scripts/smoke_v329.py                the v3.2.9 live smoke
tests/test_v329.py                   the 22 v3.2.9 regression locks
```

## 6. Local verification workflow

```bash
python3 -m pytest tests/ -q                                   # full chain
python3 tool/unix/hub/advprint.py --port 9235                 # or the tray/app
# browser:
#   http://127.0.0.1:9235/ipp/print        -> landing page (ACL note, per-device URLs)
#   http://127.0.0.1:9235/ipp/print/hp-laser-103   -> queue landing page
#   http://127.0.0.1:9235/ui               -> ONE UI; LAN tab shows "Hub addresses"
python3 scripts/smoke_v329.py                                  # the automated live check
```

From a SECOND PC: open `http://<hub-ip>:9235/ipp/print` — the page shows the
address THAT PC used; add `ipp://<ip>:9235/ipp/print/<printer-name>` — the
queue installs on the first try now.

---

*AdvPrint Pro v3.2.9 — by Bit Dream IT - Innovative Healthcare Solutions —
100% local, no cloud.*
