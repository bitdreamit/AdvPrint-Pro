# v3.2.9 - THE MULTI-PC IPP RELEASE (2026-11-12)

**Base: v3.2.8** - everything from the ipp:// scheme fix and the
http/https Website API rule stays unchanged. Three real-world
multi-PC reports from the AI-Lab LAN, all fixed and locked by
`tests/test_v329.py`.

---

## BUG 1 - `ipp://ip:9235/ipp/print/<printer-name>` refused to connect from other PCs

**The report:** adding a NAMED queue (`ipp://10.26.94.206:9235/ipp/print/HP-Laser`)
on a second PC failed with "Windows cannot connect to the printer",
while the generic `ipp://.../ipp/print` kept working everywhere.

**The root cause:** Windows, macOS and CUPS validate an IPP queue
during "Add printer" by sending `Get-Printer-Attributes` for the URI
they were given. The hub answered with ONLY the generic
`printer-uri-supported` pair (`.../ipp/print`) - the named queue URI
the client asked about was never echoed, and `printer-name` was the
hub hostname instead of the queue. The client-side validation failed
and the queue refused to connect.

**The fix - the queue is echoed end to end:**

| Attribute | v3.2.8 behaviour | v3.2.9 behaviour |
| --- | --- | --- |
| `printer-uri-supported` | generic pair only | queue URIs FIRST (`http://ip:port/ipp/print/<slug>` + `ipp://...`), then generic pair; the EXACT URI the client asked for is echoed in both schemes too |
| `printer-name` | hub hostname | the REAL printer name of the queue |
| `printer-info` | "AdvPrint Pro on host" | "AdvPrint Pro queue \<name\> on \<host\>" |
| `printer-uuid` | one uuid for the hub | one STABLE uuid per queue (`token\|hostname\|slug`) |
| `printer-more-info` | hub root | the queue's own landing page |
| `job-uri` | always generic `/ipp/print/job/<id>` | `/ipp/print/<slug>/job/<id>` for queue jobs |

Plus: some clients (Windows IPP class driver on a manual add, Android
print services) put the queue name ONLY inside the request's
`printer-uri` operation attribute even when the HTTP path is generic -
v3.2.9 resolves that name, so the job still lands on the RIGHT
printer.

## BUG 2 - one hub, MANY PCs: the IPP node is professional and optimized

**The report:** "one hub can connect multiple PC using IPP or LAN - now
it also problem when more than one; the IPP node needs to be more
professional and optimized and powerful; PCs can connect which IP is
allowed or `*` on the center hub condition."

What v3.2.9 hardened:

- **Accept backlog 5 -> 128** on every listener (main hub 9235, the
  standard-port IPP mirror 631, RAW 9100). Each PC/phone opens several
  parallel connections (status + job + UI poll); the default backlog
  REFUSED the burst connects - the classic "works alone, breaks when
  more than one PC prints" report.
- **Session lock everywhere:** `Send-Document` append/counter/join,
  `Cancel-Job` flags and `Get-Job-Attributes` reads now run under
  `_IPP_JOBS_LOCK` - parallel PCs feeding sessions can no longer
  interleave.
- **Memoized queue resolution** (`_ipp_queue_match_cached`): every IPP
  request resolves its queue name through the printer list; N PCs
  adding printers no longer re-run the OS enumeration per request
  (10 s positive TTL, 5 s negative TTL, thread-safe, bounded).
- **Unique atomic-write temp names + serialized virtual-PDF saves:**
  two jobs for the "File (PDF)" printer in the SAME second shared one
  `.part` file - the first `os.replace` moved it away and the second
  job failed with `[Errno 2]`. Every `_write_atomic` call now gets a
  unique temp name and the free-name check + write are serialized
  under `_VPDF_LOCK` (the second file simply gets a `-2` name).
- **Allowed-IPs transparency:** every ACL 403 JSON echoes the ACTIVE
  rules (`"allowed_ips": [...]`), the IPP landing page states who may
  print, and `*` / exact IP / CIDR / wildcard (`10.26.*`) are enforced
  identically on 9235, 631 and RAW 9100 - the host is what you allow,
  exactly like the v3.2.8 Website API rule.

## BUG 3 - every LAN PC saw the SAME hub URL

**The report:** "why does every Another PC (LAN PC) - print over the
network show `http://10.26.94.77:9235` - it needs its own local
ip:port."

The hub PC's `lan_ip()` UDP trick returns the DEFAULT-ROUTE address -
on a PC with a VPN / hotspot / virtual adapter that can be an address
(e.g. a 10.x carrier range) the LAN PCs cannot reach, while the real
192.168.x address never shows up.

**The fix - per-device URLs:**

- the hub now knows the address THE OPENING DEVICE used: the request
  Host header, sanitized by `_sanitize_host_hdr()` (host + port,
  nothing but `[a-z0-9._-:%]` survives - no header text can leak into
  page markup);
- every page builds its printer/queue URLs from that address FIRST:
  the IPP landing pages (9235 + 631), the per-queue landing pages, the
  `/printers` queue URLs and the console boot JSON
  (`self_host`/`self_port`/`client_ip`/`lan_ips`);
- the ONE UI `lanBase()` is now per-device (`hubIp()`/`hubPort()`):
  the address this browser used wins, loopback names never leak into
  shareable URLs;
- the LAN panel gained a **Hub addresses** row listing EVERY interface
  IP of the hub (`list_lan_ips()`, private ranges first) as copyable
  chips, so each PC/phone picks its own reachable ip:port - and the
  "LAN PC hub URL" input follows the device that opened the page.

---

## Also in this release

- `scripts/embed_console.py` close-sequence fix: the old embed wrote
  the closing quotes WITHOUT the leading newline, so the NEXT embed's
  delimiter search overshot into `DOCS_HTML` and silently deleted
  `docs_html()` / `DOCS_HTML` / `console_page_bytes()` /
  `dashboard_html()` from the hub (the /docs and /ui 500s). The block
  now ends `OPEN + html + CLOSE` and a regression test locks it.
- Extension surface bumped to 3.2.9 (manifest, popup, options, i18n
  brand lines, api.js fallback), embedded CRX copies re-signed with
  the repo key (extension id unchanged: `likldbkamojokkfdlcjibiljpgbbnohc`).
- New tests: `tests/test_v329.py` (22 regression tests), smoke
  `scripts/smoke_v329.py`.

## Upgrade

1. Install the new hub (Setup EXE / DEB / portable) - config.json,
   token, jobs and rules are kept.
2. Restart the hub; the tray icon shows v3.2.9.
3. Chrome: Extensions - Update (or reload the unpacked extension) -
   the served CRX is 3.2.9, so the hub `stale` flag stays `false`.
4. On the SECOND PC, re-add the named queue
   `ipp://<ip>:9235/ipp/print/<printer-name>` - it now installs on
   the first try.

*AdvPrint Pro v3.2.9 - by Bit Dream IT - Innovative Healthcare
Solutions - 100% local, no cloud.*
