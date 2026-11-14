# v3.3.5 - DEDICATED QUEUE PORTS + MANUAL RE-SCAN + AUTO-CRX-ON-INSTALL (2026-11-14)

**Base: v3.3.4** - everything v3.3.4 shipped stays: the per-queue
mDNS uuids, the popup printer/reload/network release, the idempotent
set-default, the internal autocrx admin button. All three v3.3.5
changes are locked by `tests/test_v335.py`.

---

## BUG 1 (deep fix) - "only default or only one add posible ... when add aggain another it show error to add"

**The report:** the SAME multi-printer symptom, still on v3.3.4.
Adding one queue worked; adding a second printer errored, and
`ip:port/ipp/print` always behaved as the hub's DEFAULT printer.

**Why v3.3.4 was not enough:** v3.3.4 fixed identity (unique uuid per
queue) but not the ENDPOINT. Every queue still resolved to the same
host:port - one shared mDNS SRV record - and rode the same
`ip:9235/ipp/print` URL family. Windows' Add-Printer flow keys a
connection on host:port FIRST: the second queue resolved to the
endpoint that was already installed, so the wizard refused it.

**The fix - one port per printer, so every queue IS a different
printer:**

| Address form | Port | Routes to |
|---|---|---|
| `http://<lan-ip>:9235/ipp/print` | hub port | central queue (hub default destination) |
| `http://<lan-ip>:9235/ipp/print/<printer>` | hub port | that ONE printer (path queue, v3.0.9) |
| `http://<lan-ip>:9236/ipp/print` | printer #1's OWN port | printer #1 only |
| `http://<lan-ip>:9237/ipp/print` | printer #2's OWN port | printer #2 only |

- Ports allocate from hub-port+1 upward, capped at 24 printers; the
  allocation is STABLE and persisted (`ipp_queue_port_map` in
  config.json), so an installed queue keeps working across restarts.
  A printer that goes away frees its port; a new printer takes the
  lowest free port.
- Each queue-port listener serves that printer for ALL `/ipp/print*`
  paths (`Handler.queue_binding`) - Windows adds
  `http://<ip>:9236/ipp/print` with NO path tail and lands on exactly
  that printer. Get-Printer-Attributes echoes the queue's name/uuid;
  Print-Job routes there; the browser landing page describes the
  bound printer.
- mDNS: every service advertises its OWN SRV port now - the announce
  packet AND direct unicast SRV queries. With unique uuid (v3.3.4) +
  unique port (v3.3.5) + unique instance name, no two queues can
  collide in any discovery path.
- Firewall: the Windows Setup adds the "AdvPrint Pro Queues" rule
  (TCP 9235-9259). Without the rule the hub logs a hint and the path
  queues keep working.
- The console Printers panel shows each printer's DEDICATED URL (with
  COPY) and `/printers` returns `ipp_port` + `ipp_dedicated`.
- Ports off / bind refused degrade gracefully to path queues.

**Upgrade note:** if a queue was added while the OLD behavior was
running, remove it once on the device and re-add - Windows remembers
queues by their endpoint, and the old shared-port entry must go
first.

---

## FEATURE 2 - "Show other PCs (LAN / IPP)" is manual now

**The report:** "printer page when Show other PCs (LAN / IPP) on it
auto load every time no need this page has re-scan option it just
manually trigger when need."

**Before:** the console's 3 s poll called `/peer/status` and rebuilt
the remote printer cards EVERY tick - a constant background probe of
the other PC.

**Now:**
- The remote list renders from the LAST MANUAL SCAN - the poll costs
  zero network calls.
- A FRESH probe of the other PC happens ONLY when the user asks:
  - the Printers panel **Re-scan** button (when the switch is ON it
    also re-reads the other PC's printers - one fresh probe with a
    toast summary), or
  - flipping "Show other PCs (LAN / IPP)" ON.
- `GET /peer/status?fresh=1` skips the hub's 8 s probe cache - that is
  what the manual scan calls; the plain poll keeps the cache.
- With the switch ON and nothing scanned yet, a hint card shows:
  "Other PCs' printers: press Re-scan - no automatic loading."
- Turning the switch OFF forgets the cached scan (fresh state on the
  next ON).

The Connections panel's LAN-PC card still updates every poll - only
the PRINTERS PAGE remote list became manual.

---

## FEATURE 3 - AUTO CRX ON INSTALL: the tool installs its own extension

**The report:** "when tool install it auto add update crx extention so
extention also built in in this tool auto update or install this
extention."

**Now the extension is fully self-installing:**

1. **The Windows Setup writes the FULL policy itself**
   (`EXT_FORCELIST_FULL` macro): `ExtensionInstallForcelist` +
   `ExtensionInstallAllowlist` + `ExtensionInstallSources` for Google
   Chrome, Microsoft Edge, Brave, Chromium, Vivaldi and Opera - both
   HKLM (machine) and HKCU (current user). Allowlist + Sources are
   what let Chrome accept the hub-served CRX cleanly. The installer
   section can be unticked on company-managed PCs.
2. **The hub re-applies the per-user pass SILENTLY on every start**
   (`autocrx_hkcu_auto()`): HKCU needs no elevation, so this is no
   UAC, no PowerShell script, no .bat - the hub simply keeps every
   user of the PC pointed at its own `/extension/updates.xml`, which
   means the CRX installs by itself at the browser's next start and
   auto-updates on every later release. Config switch
   `autocrx_hkcu` (default ON) + the console Extension tab switch
   "Auto-install/update the extension (this PC)".
3. The v3.3.4 "Auto-integrate (admin)" button stays for the HKLM
   machine-wide pass (one UAC prompt), and `prebuilt/
   allow_extention_advprint_pro.bat` remains the offline manual
   fallback.

---

## Verification

`pytest tests/` - the v3.3.5 suite (`tests/test_v335.py`) locks:
distinct + stable port allocations, per-service SRV ports in the
announce packet AND unicast answers, dedicated URLs in `/printers`,
queue-binding routing, the manual re-scan decoupling (poll renders
cache, no network), the `?fresh=1` endpoint, the silent HKCU pass
(all three policies per browser, points at this hub's updates.xml,
runs once, honest off-Windows), the installer's full policy + port
range, and release coherence (VERSION.txt / hub / manifest / popup /
i18n all 3.3.5; both hub copies byte-identical).
