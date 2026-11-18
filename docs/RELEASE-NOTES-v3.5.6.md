# Release Notes — AdvPrint Pro v3.5.6
**LAN ADMIN CONSOLE + IPP:// PRINTER URLS** — 2026-11-18
by Bit Dream IT - Innovative Healthcare Solutions

v3.5.6 answers two owner asks:

1. *"any ip allow to access admin console ui if permission like loopback
   127.0.0.1 and self ip auto add extra ips also access admin controlled
   from different ip same network. so control more easy"*
2. *"is it correct http i think it be ipp://"* — the add-printer URL the
   hub displays must say `ipp://` because Android's manual-add screen
   refuses `http://` (its Save button stays disabled).

---

## 1 · Console admin from any device (THE ONE UI everywhere)

The console gate is now **two independent controls** — printing rules
and console-admin rules never share logic:

| Control | Layer | Decides | Empty means |
|---|---|---|---|
| `allowed_ips` (v3.2.3, unchanged) | L1 | who may **reach** the hub: print, send, IPP, API | `*` = whole LAN |
| `ui_admin_mode` (new) | L2 | which of those may **open the console** | — |
| `admin_ips` (new) | L2 | **extra admins from ANY network** | nobody extra |

**`ui_admin_mode`** — three values, factory default `"lan"`:

- `"lan"` *(default)* — the hub PC **and every device on its own
  subnet** (IPv4 same /24, IPv6 same /64) may open THE ONE UI. The
  admin-centre PC `192.168.1.2` keeps `127.0.0.1` + `192.168.1.2`, and
  a PC or phone on any other IP of the same network opens
  `http://192.168.1.2:9235/ui`.
- `"self"` — the exact v3.2.6 lock: only the hub PC.
- `"any"` — every address the Allowed-IPs gate already lets in.

**`admin_ips`** — exact IP / CIDR / wildcard entries that may control
the console **from any network in every mode** (the office PC on 10.x,
a phone on mobile data, a VPN peer). The hub PC itself is **always** an
admin — loopback + own IPs are auto-added and never listed — and an
EMPTY list never widens the gate (`ip_allowed_by_list` maps `[]` to
`["*"]`, which is correct for `allowed_ips` and was explicitly
neutralised for `admin_ips` with the dedicated `admin_ips_hit()` /
`ui_admin_allows()` helpers).

**Visibility** — every remote console session is audited as
`ui.remote_admin` (IP + how it got in, throttled 1 per 10 s per IP).
The v3.2.6 branded 403 became the *"console is gated"* page: it names
the three modes, the device's own IP and the one-click fix.

**In THE ONE UI** — LAN Sharing gained the **Console admin access**
card: the three mode chips, the admin IP editor, the hub's own subnet
chips and copyable console URLs for the other devices. The security
note and the built-in docs modal describe the new model. `/health`
exposes `ui_admin_mode`, `admin_ips`, `ui_admin_subnets`,
`ui_admin_urls`; `/config` GET/POST round-trips both keys (mode
validated, list cleaned + capped at 32).

## 2 · Printer URLs display ipp:// (Android manual add works)

- **What changed (display only)** — the standard-port 631 chip, the
  Android row of the add-printer guide, the IPP landing page and the
  gated page now show `ipp://IP:631/ipp/print`. Android accepts
  `ipp://` or just the bare IP (it assumes port 631 + `/ipp/print`
  itself); an `http://` URL keeps its Save button disabled.
- **What did NOT change** — the hub still **speaks plain HTTP/IPP** on
  9235 and 631 (IPP runs over HTTP; `ipp://` is only the client-side
  scheme hint). Windows' add-by-URL guide keeps `http://` (the Windows
  IPP Device box wants it). The QR payload stays `http://` because
  phone cameras cannot open `ipp://` links (v3.2.6 rule, still
  test-pinned).

## 3 · Upgrade + compatibility

- The v3.5.5 build kit is untouched: `build.cmd` /
  `scripts/build-all.py`, tree guard, twin guard, NSIS pre-validation,
  abs-path compile pipeline, `wipe()`, CRX signature gate. Same stable
  key, same extension ID (`likldbkamojokkfdlcjibiljpgbbnohc`) —
  pairing, settings and auto-update all survive.
- Config files from v3.5.5 keep working: missing keys fall back to
  `ui_admin_mode: "lan"` + `admin_ips: []`.
- Locked by `tests/test_v356.py` (27 checks) on top of the full
  regression suite; the v3.2.6 gate matrix still runs under mode
  `"self"` so the old lock stays provable.

## 4 · Try it in 60 seconds

1. Build: `build.cmd` (Windows) or `python3 scripts/build-all.py`.
2. Install / restart the hub, open `http://127.0.0.1:9235/ui`.
3. **LAN Sharing → Console admin access**: pick the mode, add an
   admin IP if you need one, copy a console URL.
4. On the other PC / phone: open that URL, paste the hub token once —
   the full console answers. Audit tab shows the `ui.remote_admin`
   row.
5. Android manual add: Default Print Service → Add printer → paste
   `ipp://<hub-ip>:631/ipp/print` (or just the IP) → Save is enabled.
