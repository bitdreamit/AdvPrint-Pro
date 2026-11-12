# v3.3.0 - THE ANY-PC INVITE + DUAL-STACK LISTENER RELEASE (2026-11-12)

**Base: v3.2.9** - the multi-PC IPP release (per-printer queue echo,
128 backlog, per-device hub URLs) stays unchanged. Three new
real-world reports from the LAN, all fixed and locked by
`tests/test_v330.py`.

---

## BUG 1 - the invite page connected the WRONG PC ("it redirect own pc")

**The report:** *"when `http://192.168.1.104:9235/connect?t=<token>` why
it redirect own pc - it need any pc of other connect using other pc ip
port and token that shared, but now redirect it own pc - also bug."*

**The root causes (two real defects behind one symptom):**

1. `connect_page_html()` built the peer URL from the **serving hub's own
   `lan_ip()`** - a server-side guess that can be an adapter the visitor
   cannot reach, and the wrong identity entirely whenever two PCs share
   one token (common in labs). The page never showed the address the
   visitor actually typed.
2. There was **no self-invite protection**: opening the invite ON the
   hub PC itself rendered the normal "Add ... as a LAN print peer"
   form; clicking it POSTed `url=http://<own-lan-ip>:9235` to the own
   loopback hub and wrote the hub into ITS OWN `peer_hubs` - the hub
   "connected itself".

**The fix:**

| Layer | v3.2.9 behaviour | v3.3.0 behaviour |
| --- | --- | --- |
| Peer URL on the page | `http://lan_ip():port` (server guess) | the sanitized **Host header** address the visitor used; loopback falls back to `lan_ip()` only for the hub owner |
| Visitor = hub PC (loopback GET) | normal add-to-self form | NEW `connect_self_html()` explainer: what went wrong, the 3 steps, the invite link with a Copy button |
| `POST /peer-connect` | accepted `url` = own LAN IP / hostname / localhost | **refuses self-invites** (`peer.connect.denied` audit) with a readable result page - nothing saved |
| Visiting PC has no hub | raw browser "127.0.0.1 refused to connect" error | the page probes `127.0.0.1:9235/health` first: green "your PC's hub is running" or a clear warning + the `peer_hubs` config snippet; the submit is retried via fetch and failures are explained inline |
| `?t=` token mismatch | "the invite link is old or mistyped" | explains the token may belong to a **DIFFERENT PC's hub** (the exact confusion behind the report) |
| Wrong address typed | dead end | the hub's other addresses (IPv4 + IPv6) appear as one-click **"use this"** chips that swap the peer URL the form saves |

A LAN visitor opening the invite still gets the one-click flow:
page -> click -> the visitor's own hub saves the peer -> dashboard.

## BUG 2 - every listener answers on IPv4 AND IPv6, on every interface

**The report:** *"many other also listening, other like raw printer,
show only ipv6 - why not also ipv4."*

**The root cause:** all three LAN listeners - the 9235 LAN hub, the 631
standard-port IPP mirror and the RAW JetDirect port 9100 - each bound
exactly **one** socket to `lan_ip()` (the default-route IPv4). On a PC
with several adapters (Ethernet + Wi-Fi + VPN + Hyper-V/WSL virtual
switches) the hub was DEAF on every other address, and no listener
ever spoke IPv6.

**The fix - `bind_listener_sockets(port, label)`:**

- **IPv4:** one listening socket per non-loopback interface IP
  (`list_lan_ips()`), backlog 128 on each. Specific binds never
  conflict with each other, nor with the 127.0.0.1 loopback hub.
- **IPv6:** one `[::]` socket with `IPV6_V6ONLY=1` - answers every
  IPv6 address of this PC (and future ones) without taking IPv4
  traffic from the v4 sockets.
- **Graceful degradation:** a partial bind set (v4-only PC, IPv6
  disabled by the OS, one busy address) logs the failures and keeps
  the working sockets; only when NOTHING binds does the listener stay
  off with a clear error.
- **Rebind on interface-set change:** the ensure() refreshers compare
  `_bind_signature()` (every interface IP + dual-stack capability)
  against what is actually bound - a new Wi-Fi/VPN adapter is picked
  up automatically, not just when `lan_ip()` moves.
- **mDNS:** the announce carries an **AAAA record** (and AAAA queries
  are answered) when the hub has a usable global/ULA IPv6; fe80::
  link-local is skipped (needs a zone id, useless in a printer URL).
- **UI truth:** `/health` now reports `raw_addrs`, `ipp_std.addrs`,
  `lan_bind_addrs` and boot `lan_ips6`; the console "Hub addresses"
  chips list IPv4 AND IPv6 (bracketed), the RAW row and the 631 chip
  show the REAL bound sockets, and every URL builder wraps IPv6
  literals in brackets (`hubHost()`).
- **Security unchanged:** `allowed_ips` (`*` / exact / CIDR / wildcard)
  gates every connection on every bound socket (RAW + 631 + 9235), and
  the console UI stays loopback/own-IP only - widening the bind never
  widened who may DO anything.

## BUG 3 - per-printer IPP queues work for ANY printer that exists

**The report:** *"ipp work default fine `ipp://ip:port/ipp/print` but
also separate printer ipp like `ipp://ip:port/ipp/print/` - any printer
that exist also separately active - need."*

**The root cause:** `_ipp_queue_slug()` stripped everything outside
`[a-z0-9]` - every **non-ASCII printer name** (Bangla, Arabic, CJK -
common in real labs and shops) collapsed to the single slug
`printer`. All those printers shared ONE queue path and none of them
was separately addressable; the negative-match memo (5 s) plus the
30 s printer-list cache also kept a newly added printer queue-less for
minutes.

**The fix:**

- `_ipp_queue_slug()` is **Unicode-aware** (`\w`, `re.UNICODE`):
  `প্রিন্টার ১` -> `প্রিন্টার-১` while ASCII names slug exactly as
  before, so queues added by older releases keep resolving.
- The slug is **percent-encoded** in `ipp_queue_url()` and
  `_ipp_queue_uris()` (the IPP `printer-uri-supported` echo) - valid
  URLs/URIs for every script.
- Queue matching runs through `_ipp_queue_key()` (a collision-tolerant
  JOIN key: all non-word chars dropped): dash / underscore / space /
  %20 variants all resolve to the same printer.
- A **negative queue match force-refreshes** the OS printer list once
  (rate-limited to 3 s between forced refreshes): a printer added on
  the hub PC gets its queue in seconds.
- The **unknown-queue 404 lists the live queues** ("Active queues
  right now: hp-laser-103, ...") on both the 9235 endpoint and the 631
  mirror.
- The **mDNS announce cap went 12 -> 24** per-printer services, so
  bigger labs see every queue in their phone/PC printer picker.

---

## Locked by `tests/test_v330.py`

Version coherence 3.3.0 everywhere, byte-identical hub copies, the
invite flow (per-device peer URL, self-invite refusal on page + POST,
self-explainer page, token-mismatch text), the dual-stack helper
(both stacks, V6ONLY, graceful partial binds, signature rebind),
health/boot carrying the new address fields, the Unicode slug +
join-key matching (incl. legacy dash-slug compatibility), the forced
refresh on negative matches, the 404 queue hint, and the release docs.
