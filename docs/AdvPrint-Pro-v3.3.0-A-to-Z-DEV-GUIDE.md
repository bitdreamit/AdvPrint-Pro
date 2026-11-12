# AdvPrint Pro v3.3.0 — A-to-Z DEVELOPMENT & BUILD GUIDE

> **v3.3.0 = "THE ANY-PC INVITE + DUAL-STACK LISTENER RELEASE" on top
> of v3.2.9.** Three new real-world LAN reports, all fixed and locked
> by `tests/test_v330.py`. Everything from v3.2.9 (multi-PC IPP echo,
> 128 backlog, per-device hub URLs), v3.2.8 (clean `ipp://` URL,
> scheme-free Website API rule, stale-CRX guard) and v3.2.2–v3.2.7
> stays unchanged. The deep architecture reference (ONE UI anatomy,
> print pipeline, IPP engine, build internals) lives in
> `docs/AdvPrint-Pro-v3.2.7-A-to-Z-DEV-GUIDE.md`; this guide documents
> the v3.3.0 delta.

> **BUG 1 — the invite page connected the WRONG PC ("it redirect own
> pc").** `connect_page_html()` built the peer URL from the serving
> hub's `lan_ip()` guess and a loopback visitor could add the hub to
> ITSELF. v3.3.0: the page builds the peer URL from the request's
> sanitized Host header (`Handler._req_host()` / `_req_port()`), a
> loopback visitor gets `connect_self_html()` instead of the add-to-
> self form, `POST /peer-connect` refuses self-invites (own LAN IPs /
> hostname / localhost on the hub port), the page probes the visiting
> PC's own hub (`127.0.0.1:9235/health`) and retries the POST via
> fetch with readable failures, and a `?t=` mismatch explains the
> "token from a DIFFERENT PC's hub" case.
>
> **BUG 2 — every listener answers on IPv4 AND IPv6, every
> interface.** The 9235 LAN hub, the 631 mirror and RAW 9100 each
> bound ONE IPv4 address (`lan_ip()`) — deaf on all other adapters,
> silent on IPv6. v3.3.0 adds `bind_listener_sockets()` (one IPv4
> socket per interface IP + one `[::]` socket with `IPV6_V6ONLY=1`,
> backlog 128, graceful partial binds), `_bind_signature()` rebinds
> the listeners when the INTERFACE SET changes, the mDNS announce
> carries an AAAA record (`_mdns_rrset(..., ip6=...)`), and the
> health/boot JSON exposes `raw_addrs` / `ipp_std.addrs` /
> `lan_bind_addrs` / `lan_ips6` so the ONE UI shows the REAL bound
> sockets (`hubHost()` brackets IPv6 literals).
>
> **BUG 3 — per-printer IPP queues work for ANY printer that exists.**
> The old `[^a-z0-9]` slug folded every non-ASCII printer name to the
> single slug `printer` — all those queues collided. v3.3.0 makes
> `_ipp_queue_slug()` Unicode-aware (`\w`), percent-encodes it in
> `ipp_queue_url()` / `_ipp_queue_uris()`, matches through the
> collision-tolerant `_ipp_queue_key()` join key (dash / underscore /
> %20 all resolve), force-refreshes the OS printer list once on a
> negative match (`_QMATCH_LAST_FORCE`), lists the live queues in the
> unknown-queue 404 (`_active_queue_hint()`), and raises the mDNS
> per-printer cap 12 → 24.

---

## 1. The three files that must stay in sync

| File | Role |
| --- | --- |
| `tool/unix/hub/advprint.py` | the hub source of truth (VERSION 3.3.0) |
| `tool/windows/portable/hub/advprint.py` | byte-identical copy (installer + tests import THIS one) |
| `tool/unix/hub/console.html` | ONE UI source; embedded into BOTH hub copies by `scripts/embed_console.py` |

After editing the UI: `python3 scripts/embed_console.py` (re-embeds the
console into both hub copies, mirrors console.html to the portable hub,
verifies the copies are byte-identical). After editing hub code:
`cp tool/unix/hub/advprint.py tool/windows/portable/hub/advprint.py`.

## 2. v3.3.0 code map (delta only)

### BUG 1 — the invite flow

```
GET /connect?t=<token>&n=<name>     Handler (advprint.py ~line 5700)
  ├─ token mismatch  -> connect_error_html("...or it belongs to a
  │                    DIFFERENT PC's hub...")            [403]
  ├─ share_lan off   -> connect_error_html("enable LAN sharing first")
  │                                                            [403]
  └─ ok -> connect_page_html(token, name,
                req_host=self._req_host(),      # the VISITOR's address
                req_port=self._req_port(),
                visitor_is_hub=self._is_loopback())
                    ├─ visitor_is_hub -> connect_self_html()  (explainer)
                    └─ else the form page (probes 127.0.0.1:9235/health,
                       "use this" address chips, fetch-retried POST)

POST /peer-connect                  Handler._peer_connect (~line 5110)
  └─ NEW self-invite guard: peer host in {localhost, 127.0.0.1, ::1,
     lan_ip(), hostname, list_lan_ips()} AND port == hub port
       -> 400 "That is this hub's own invite" (nothing saved)
```

### BUG 2 — the dual-stack listeners

```
bind_listener_sockets(port, label)  -> ([socks], [errs]) | raises OSError
  ├─ IPv6: socket AF_INET6, IPV6_V6ONLY=1, bind ("::", port), listen(128)
  └─ IPv4: one socket per list_lan_ips() entry (skip 127.*), listen(128)

_httpd_on(sock, handler, server_cls)      server on a PRE-BOUND socket
_ipp631_server_on(sock)                   ditto for the 631 mirror
_sock_label(sock)                         "192.168.1.101:9100" / "[::]:9100"
_bind_signature()                         (sorted v4 IPs, dualstack?) —
                                          the rebind trigger for
                                          lan/raw/ipp631 ensure()
```

Globals renamed (ALL references updated): `_LAN_HTTPD/_LAN_THREAD/
_LAN_BIND_IP` → `_LAN_HTTPDS/_LAN_THREADS/_LAN_BINDS/_LAN_BIND_SIG`;
`_RAW_TCP/_RAW_THREAD/_RAW_BIND_IP` → `_RAW_SOCKS/_RAW_THREADS/
_RAW_BINDS/_RAW_BIND_SIG`; `_IPP631_HTTPD/_IPP631_THREAD/_IPP631_BIND_IP`
→ `_IPP631_HTTPDS/_IPP631_THREADS/_IPP631_BINDS/_IPP631_BIND_SIG`.
`ipp631_listen_stop()` stays SYNCHRONOUS (the ensure() rebind path must
not race old sockets still open).

Health/boot additions: `raw_addrs`, `ipp_std.addrs`, `lan_bind_addrs`,
`lan_ips6` (health snapshot ~line 1720; boot JSON in
`console_page_bytes()`).

### BUG 3 — Unicode queue slugs

```
_ipp_queue_slug(name)   \w-based, Unicode kept, dash-collapsed, or "printer"
_ipp_queue_key(name)    JOIN key: every non-word char REMOVED (compare)
_ipp_queue_match(name)  unquote -> key-compare against list_printers_cached
_ipp_queue_match_cached + _QMATCH_LAST_FORCE  (negative -> ONE forced
                          list_printers_cached(max_age=0.0), rate-limited 3 s)
_active_queue_hint()    " Active queues right now: a, b, c." for the 404s
```

Percent-encoding lives in `ipp_queue_url()` and `_ipp_queue_uris()`
(`quote(slug, safe="")` — ASCII slugs pass through unchanged, so
pre-3.3.0 saved queue URLs keep working).

## 3. Rebuild everything from source

```bash
# 0) sanity
python3 -m py_compile tool/unix/hub/advprint.py \
                      tool/windows/portable/hub/advprint.py
cmp tool/unix/hub/advprint.py tool/windows/portable/hub/advprint.py

# 1) tests (boots a REAL hub on a random port; no printer needed)
python3 -m pytest tests/ -x -q

# 2) re-embed the ONE UI (if console.html changed)
python3 scripts/embed_console.py

# 3) full build: CRX3 + extension zip + NSIS Setup.exe + DEB + SHA256SUMS
bash scripts/build-all.sh
# -> dist/AdvPrint-Pro.crx, AdvPrint-Pro-Extension-3.3.0.zip,
#    AdvPrint-Pro-Setup-3.3.0.exe, advprint-pro_3.3.0_all.deb,
#    SHA256SUMS-3.3.0.txt
# the build HARD-FAILS if any embedded CRX copy is stale (v3.2.8 guard)
```

NSIS for the Setup EXE: `apt-get install nsis` (or the repo's
`.build-bin/makensis` wrapper when present). The Setup EXE embeds the
Python runtime from `tool/windows/portable/installer/runtime/` — keep
that directory in place or the build warns.

## 4. Upgrade/delivery checklist (same as every release)

1. Version anchors: `VERSION.txt`, `advprint.py` `VERSION` +
   `VERSION_NAME` (BOTH copies), `extension/manifest.json`,
   `extension/popup.html`, `extension/options.html`,
   `extension/i18n.js` (en + bn brandLine),
   `extension/content/api.js` `_apVerFallback`, `installer/setup.nsi`
   (OutFile, VIProductVersion, FileVersion/ProductVersion,
   DisplayVersion, silent-install comment, runtime error text),
   console fallbacks `BOOT.version || "3.3.0"`, README, START-HERE.txt,
   CHANGELOG.md.
2. New docs: `docs/RELEASE-NOTES-v3.3.0.md`,
   `docs/AdvPrint-Pro-v3.3.0-A-to-Z-DEV-GUIDE.md`, CHANGELOG entry,
   README what's-new.
3. Tests: `tests/test_v330.py` (version coherence, invite flow,
   dual-stack binds, Unicode slugs, docs existence).
4. `bash scripts/build-all.sh`, then verify
   `http://127.0.0.1:9235/extension/info` shows `"stale": false` and
   version 3.3.0 after installing (the extension auto-updates FROM the
   hub — the stale-CRX trap).
5. Smoke: `python3 scripts/smoke_v330.py` (boots the hub on 127.0.0.1,
   checks /health, the invite pages, /printers queue URLs and the
   listener state end to end).

## 5. Regression risks and how they are covered

| Risk | Guard |
| --- | --- |
| Hub adds ITSELF again | self-invite guard in `_peer_connect` + `connect_self_html` on loopback GET — both locked by tests |
| Old dash-slug queues stop resolving after the Unicode slug change | `_ipp_queue_key()` join-key compare — test adds a printer named `HP Laser 103` and resolves `hp-laser-103` |
| Double-bind of the loopback hub port | v4 binds skip 127.*; v6 socket is V6ONLY — test binds the helper on a free port next to a live loopback hub |
| Rebind race on interface change | `ipp631_listen_stop()` synchronous; LAN stop clears the globals before the async close — signature compare happens only on the NEXT ensure() tick |
| mDNS announce breaks on IPv6-less PCs | AAAA is added only when `list_lan_ips6()` is non-empty, wrapped in try/except |
| Console shows a stale URL for IPv6 | `hubHost()` brackets every IPv6 host before URL-building (lanBase / chips / RAW row) |
