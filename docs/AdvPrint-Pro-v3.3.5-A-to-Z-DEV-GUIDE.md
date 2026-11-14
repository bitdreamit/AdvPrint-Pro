# AdvPrint Pro v3.3.5 — A-to-Z DEVELOPMENT & BUILD GUIDE

AdvPrint Pro (Advanced Printer) by Bit Dream IT - Innovative Healthcare
Solutions. This guide covers ONLY the v3.3.5 delta on top of v3.3.4.
Read `AdvPrint-Pro-v3.3.4-A-to-Z-DEV-GUIDE.md` first for the base
architecture (hub, THE ONE UI, extension, build chain); everything
there still applies.

---

## 0. The one-paragraph delta

v3.3.5 makes every printer a genuinely separate network endpoint: the
hub opens ONE EXTRA TCP PORT PER PRINTER (9236, 9237, ...), each
serving exactly one queue, mDNS advertises one SRV per printer with
its own port, and the port map persists in config. The Printers
panel's "Show other PCs (LAN / IPP)" list became MANUAL (Re-scan
button / switch only - the 3 s poll never probes the peer). And the
extension became self-installing: the Setup writes the full browser
policy (Forcelist + Allowlist + Sources, HKLM + HKCU, + Opera) and the
hub silently re-applies the per-user HKCU pass on every start
(`autocrx_hkcu`).

## 1. The files that must stay in sync (edit BOTH, always)

```
tool/unix/hub/advprint.py              <- the canonical hub
tool/windows/portable/hub/advprint.py  <- byte-identical copy
                                          (tests/conftest.py imports
                                           THIS one - a stale copy runs
                                           the tests against old code!)
extension/*                            <- the CRX source
installer/setup.nsi                    <- the Windows Setup
VERSION.txt / extension/manifest.json  <- must both show 3.3.5
```

`tests/test_v335.py::test_hub_copies_byte_identical` and
`test_version_coherence_335` catch drift. When you bump a version:
VERSION.txt line 1, `VERSION =` in advprint.py, manifest.json,
popup.html badge, i18n.js brandLine (en + bn), setup.nsi OutFile.

## 2. v3.3.5 code map (delta only)

### BUG 1 - dedicated per-printer queue ports (advprint.py)

- **Config**: `ipp_queue_ports` (bool, default True),
  `ipp_queue_port_map` (dict) - both in `CONFIG_KEYS`/`CONFIG_TYPES`.
- `ipp_queue_port_base()` - first queue port = `CFG["port"] + 1`.
- `ipp_queue_port_allocations()` - the stable {printer: port} map.
  Keeps valid existing assignments, hands new printers the lowest free
  port, drops stale ones; updates CFG in memory ALWAYS, writes
  config.json ONLY when it already exists on disk (keeps probe/test
  calls side-effect free).
- `ippq_reconcile()` - start/stop the per-printer listeners to match
  the printer list. Called from `lan_listen_start()`, from the 3 s
  `lan_listen_ensure()` hook, and effectively stopped by
  `lan_listen_stop()` via `ippq_stop_all()`.
- Each listener is built with `_httpd_on(s, Handler, HubServer)` and
  gets `httpd.queue_binding = <printer name>` - THE routing flag.
- `Handler.do_POST` (main handler): when `self.server.queue_binding`
  is set, EVERY `/ipp/print*` route is that printer (`ipp_q_printer =
  binding`); the slug branch yields to the binding. The GET landing
  page passes `queue_name=...` to `ipp_landing_html`.
- `_mdns_services()` is a 6-TUPLE now: `(instance, rp, ty, note,
  slug, port)`. `_mdns_rrset()` builds one SRV per service;
  `_mdns_answer_query()` answers a direct SRV query with that
  instance's own port.
- `/printers` payload: `ipp_port` (int) + `ipp_dedicated` (URL) per
  printer; the console pcard shows the dedicated URL (COPY copies it).

Windows-side contract: `http://<ip>:<queue-port>/ipp/print` (no path)
- that is what users add. Firewall: Setup adds "AdvPrint Pro Queues"
  TCP 9235-9259.

### FEATURE 2 - manual re-scan (console JS inside advprint.py)

- `remoteScanState = {scanned, st, busy}` - the last manual scan.
- `scanRemotePrinters(manual)` - `api("/peer/status?fresh=1")`, stores
  the result, renders; toasts only for manual calls.
- `loadLanPeer()` no longer renders remote printers (Connections card
  only). `poll()` calls `renderRemotePrinters()` (cache, zero
  network) right after `renderPrinters()`.
- Manual triggers: the panel Re-scan (`refresh-printers` action) and
  the `showRemoteSw` toggle ON. OFF forgets the cached scan.
- Hint card (`data-remotescan`) when ON + not scanned yet.
- Server: `GET /peer/status?fresh=1` -> `_lan_peer_status(fresh=True)`
  skips the 8 s probe cache.

### FEATURE 3 - auto CRX on install

- Config: `autocrx_hkcu` (bool, default True) in CONFIG_KEYS.
- `autocrx_hkcu_auto()` (advprint.py, after ext_policy_activate):
  silent HKCU pass - Forcelist + Allowlist + Sources for every browser
  in `EXT_ACTIVATE_BROWSERS`, idempotent (existing values kept),
  audited, runs ONCE per process (`_AUTOCRX_AUTO_STATE`). Returns
  None off-Windows / when disabled / already done.
- `_autocrx_auto_thread()` - sleeps 8 s, then runs the pass; started
  from the serve path right before `serve_forever`.
- Console: Extension tab switch `autocrxHkcuSw` ->
  `POST /config {autocrx_hkcu}`; mirrored from cfgCache in poll().
- installer/setup.nsi: `EXT_FORCELIST_FULL` macro (Forcelist HKLM via
  the old macro + Allowlist + Sources HKLM + the HKCU mirror for all
  three policies), Opera added to both apply and uninstall passes,
  firewall rule "AdvPrint Pro Queues" TCP 9235-9259 (+ uninstall
  removal), DescPolicy text, DisplayVersion 3.3.5.

## 3. Config keys (new in v3.3.5)

| Key | Type | Default | Meaning |
|---|---|---|---|
| `ipp_queue_ports` | bool | True | one extra TCP port per printer |
| `ipp_queue_port_map` | dict | {} | stable {printer_name: port} (managed) |
| `autocrx_hkcu` | bool | True | silent per-user CRX policy on every hub start |

## 4. Tests (tests/test_v335.py)

23 tests: allocation stability/keeping/staleness, per-service mDNS
ports (announce + unicast), dedicated URLs in `/printers`, reconcile
off-switch, queue-binding routing contract, the manual-scan decoupling
(poll renders the cache; `loadLanPeer` no longer re-renders), the
`?fresh=1` wiring + live endpoint, the silent HKCU pass (three
policies per browser pointing at this hub's updates.xml, once per
process, honest off-Windows/config-off), the installer's full policy +
port range, release coherence, byte-identical hub copies.

The v3.3.4 suite was updated in place (6-tuple mDNS services, version
asserts moved to 3.3.5) - all previous guarantees still hold.

## 5. Build + release checklist

```
python3 -m pytest tests/ -q          # full suite green
bash scripts/build-all.sh            # CRX3 + Setup exe + deb + SHA256SUMS
# artifacts land in dist/ (Setup name comes from setup.nsi)
```

The Setup opens TCP 9235-9259; if a user installs via the portable
zip instead, tell them to allow the ports once (the console LAN panel
covers 9235; queue ports log a hint when blocked).

## 6. Upgrade notes for users

- Already-installed queues keep their port (stable map). Queues added
  under v3.3.4 or earlier that half-broke should be removed once and
  re-added - Windows remembers the old shared endpoint.
- The multi-add recipe for Windows: Settings -> Printers -> Add device
  (each printer appears by itself while LAN sharing is on), or paste
  the printer's DEDICATED URL from the console card.
- "Show other PCs" is manual now: switch ON, then Re-scan.
- The extension installs itself after the hub starts (HKCU, silent).
  Corporate policy? Untick the installer section or flip the console
  switch off.
