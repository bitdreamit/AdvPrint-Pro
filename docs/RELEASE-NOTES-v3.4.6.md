# v3.4.6 - ONE PORT FOR EVERYTHING + POPUP REMEMBERS THE LAST PRINTER (2026-11-14)

**Base: v3.3.5** - the manual LAN/IPP re-scan, the auto-CRX-on-install
machinery, the per-queue mDNS uuids and the idempotent set-default all
stay. Both v3.4.6 changes are locked by `tests/test_v346.py`.

---

## 1. ONE PORT FOR EVERYTHING - "why not the hub default port only?"

**The question (user, verbatim):** quoting the v3.3.5 changelog -
"One DEDICATED TCP port per printer (9236, 9237, ... right after the
hub port) ... Firewall: the Setup now opens TCP 9235-9259" - the user
asked: **"why not hub default port only one port to handel diffrent pc
to connect throug ipp or other"**.

**The answer: one port IS enough - and it is the design again.** The
v3.3.5 dedicated ports worked, but they were masking tape. A CUPS
server has served MANY queues from ONE port (631) forever, and Windows
adds them side by side happily: a print client keys a queue on the
FULL URI plus the printer attributes, not on host:port alone. The
v3.3.4-era failure ("only default or only one add possible") was the
queues sharing an IDENTITY - every path answered with the same
printer-name/uuid, so the second add looked like the printer that was
already installed. Identity has been per-queue since v3.3.4/v3.3.5.
With identity fixed, one port is correct, simpler and safer.

**What the hub serves now - all on ONE TCP port (9235):**

| Address form | Routes to |
|---|---|
| `http://<lan-ip>:9235/ipp/print` | central queue (hub default destination) |
| `ipp://<lan-ip>:9235/ipp/print` | same, ipp scheme (macOS/CUPS form) |
| `http(s)://<lan-ip>:9235/ipp/print/<printer>` | that ONE printer (raw name, URL-encoded, slug or Unicode slug) |
| mDNS service per printer (`rp=ipp/print/<slug>`, unique uuid) | discovered as separate printers by Windows / phones |

- The per-queue identity that makes this safe: unique `printer-name`
  per queue, STABLE unique `printer-uuid`
  (md5 of token|hostname|slug - survives restarts), the exact client
  URI echoed back in `printer-uri-supported` (http + ipp forms), one
  mDNS service per queue with its own `rp` and uuid - every SRV now
  points at the SAME hub port.
- **Removed**: the dedicated queue-port listeners, the stable port
  map, the `Handler.queue_binding` routing, the config keys
  `ipp_queue_ports` / `ipp_queue_port_map` (old config.json values are
  silently ignored), the `/printers` fields `ipp_port` /
  `ipp_dedicated`, and the firewall range rule.
- **Firewall back to ONE rule**: TCP 9235 (hub) + TCP 9100 (RAW) +
  TCP 631 (IPP standard-port mirror) + UDP 5353 (mDNS). The Setup
  still DELETES the old "AdvPrint Pro Queues" 9235-9259 rule so a
  v3.3.5 upgrade cleans up automatically.
- Fewer sockets, no port exhaustion with 24+ printers, and every
  printer of the hub still adds side by side from every PC, phone and
  tablet on the LAN.

## 2. The popup shows the RIGHT printer - and REMEMBERS it

**The report (user, verbatim):** "popup selected printer every time
new page or same page reload it show selected first it not show
current selected default seletected printer cache show last selected
selected auto in popup."

**Root cause:** the popup read `r.default_printer` - a field the hub
NEVER sends. The hub's `/printers` answers `"default": ...`. So
`_printerApplied` was always empty and the selector fell back to the
FIRST printer on every popup open/reload, no matter what the user had
picked before.

**The fix (extension/popup.js):**

1. **Field fix** - `_printerApplied = r.default || r.default_printer
   || ""`: the popup opens on the hub's CURRENT OS default.
2. **Memory** - every real user pick is saved to
   `chrome.storage.local.advLastPrinter`; the next popup open
   auto-selects the remembered printer whenever the hub's default is
   unknown or not in the list. Priority: hub default -> remembered ->
   first.
3. **Visibility** - the OS default is marked `[default]` in the
   dropdown (EN "default" / BN "ডিফল্ট"); when the remembered choice
   (not the hub default) is auto-selected the tooltip says
   "Last used:".
4. **Safety unchanged** - the v3.3.4 change-only guard stays: popup
   open/reload sends ZERO set-default commands (a programmatic select
   fires no change event, the in-flight guards hold, the hub endpoint
   is idempotent). Picking a different printer still makes it the OS
   default with exactly one command.

---

**Upgrade notes:** queues added on v3.3.5 via a dedicated port
(`http://<ip>:9236/ipp/print`) keep printing through the hub, but
re-add them from the printer card's COPY URL
(`ipp://<ip>:9235/ipp/print/<printer>`) when convenient - the extra
ports no longer exist. Everyone else: nothing to do.

**Verification:** `python3 -m pytest tests/ -q` - 630 passed,
1 skipped (the CRX-freshness checks validate after
`bash scripts/build-all.sh`). Developer delta:
`docs/AdvPrint-Pro-v3.4.6-A-to-Z-DEV-GUIDE.md`.
