# AdvPrint Pro v3.4.6 — A-to-Z DEVELOPMENT & BUILD GUIDE

AdvPrint Pro (Advanced Printer) by Bit Dream IT - Innovative Healthcare
Solutions. This guide covers ONLY the v3.4.6 delta on top of v3.3.5.
Read `AdvPrint-Pro-v3.3.5-A-to-Z-DEV-GUIDE.md` first for the manual
re-scan + auto-CRX machinery and `AdvPrint-Pro-v3.3.4-A-to-Z-DEV-GUIDE.md`
for the base architecture (hub, THE ONE UI, extension, build chain);
everything there still applies except where this file says otherwise.

---

## 0. The one-paragraph delta

v3.4.6 answers the user's question - *"why not [the] hub default port
only, one port to handle different PCs to connect through IPP or
other?"* - with: **it is enough, and that is the design again.** The
v3.3.5 DEDICATED PER-PRINTER QUEUE PORTS (one extra TCP port per
printer: 9236, 9237, ... + the TCP 9235-9259 firewall range + the
`ipp_queue_port_map` config) are REMOVED. ONE TCP port - the hub port
9235 - serves every queue for every PC, phone and tablet, exactly
like a CUPS server serves many queues from port 631: the queues are
distinguished by their FULL URI (`/ipp/print` = the default queue,
`/ipp/print/<printer>` = that one printer) plus the per-queue
IDENTITY the hub already answers - unique `printer-name`, STABLE
unique `printer-uuid` (token|hostname|slug), the exact client URI
echoed in `printer-uri-supported`, one mDNS service per queue with its
own `rp` and uuid on the SAME SRV port. The v3.3.4-era multi-add
failure was the shared queue identity, not the shared port - the
identity has been fixed since v3.3.4/v3.3.5, so the extra ports were
masking tape. PLUS: the popup printer selector now shows the RIGHT
printer - it read `default_printer` (a field the hub never sends; the
hub answers `default`), so every popup open/reload fell back to the
FIRST printer - and it REMEMBERS the last printer you picked
(`chrome.storage.local advLastPrinter`) and auto-selects it on the
next open.

## 1. The files that must stay in sync (edit BOTH, always)

```
tool/unix/hub/advprint.py              <- the canonical hub
tool/windows/portable/hub/advprint.py  <- byte-identical copy
                                          (tests/conftest.py imports
                                           THIS one - a stale copy runs
                                           the WRONG code in tests)
tool/unix/hub/console.html             <- THE ONE UI source
tool/windows/portable/hub/console.html <- mirrored by embed script
```

After editing console.html ALWAYS run the embed step (it rewrites the
`CONSOLE_HTML` r-string inside BOTH advprint.py copies and mirrors the
html):

```
python3 scripts/embed_console.py
cp tool/unix/hub/advprint.py tool/windows/portable/hub/advprint.py
md5sum tool/*/hub/advprint.py     # must be identical
```

Extension files (`extension/`) are packed by the build; there is no
second copy since v3.2.8 (the stale-CRX guard syncs every embedded
CRX at build time and hard-fails on mismatch).

## 2. v3.4.6 code map (delta only)

### REMOVED (the v3.3.5 experiment, all of it)

| Removed | Was | Now |
| --- | --- | --- |
| `ippq_reconcile` / `ippq_stop_all` / `_ippq_stop_one` / `_IPPQ_HTTPDS` / `_IPPQ_LOCK` / `_IPPQ_MAX_QUEUES` | per-printer TCP listeners (9236+) | nothing - one port |
| `ipp_queue_port_base` / `ipp_queue_port_allocations` | stable port map | nothing |
| `ipp_queue_dedicated_url` | per-printer `ip:port` URL | `ipp_queue_url()` (path URL on the hub port) |
| `Handler.queue_binding` binding in GET landing + POST IPP | per-port routing | plain `_ipp_queue_match_cached` path routing |
| CFG `ipp_queue_ports`, `ipp_queue_port_map` | config keys | gone from `CFG` / `CONFIG_KEYS` / `CONFIG_TYPES`; old config.json values are silently ignored |
| `/printers` fields `ipp_port`, `ipp_dedicated` | payload | only `ipp_queue` + `ipp_path` remain |
| firewall add-rule `AdvPrint Pro Queues` (TCP 9235-9259) | setup.nsi | the delete-rule SURVIVES so an upgrade from v3.3.5 removes the leftover range rule |

### UNCHANGED and now the whole story: ONE-port queue identity

* `POST /ipp/print` - generic queue; `POST /ipp/print/<printer>` -
  routed by `_ipp_queue_match_cached` (raw name, URL-encoded, slug,
  Unicode-aware; unknown slugs still answer as the generic queue so
  the Windows add never dies - v3.3.2 BUG 3).
* `_ipp_printer_group()` answers Get-Printer-Attributes with the
  queue's own `printer-name`, `printer-uuid`
  (`_ipp_printer_uuid(slug)` = md5(token|hostname|slug) - stable
  across restarts), `printer-info`, `printer-more-info` and echoes
  the client's URI (http + ipp forms) in `printer-uri-supported`.
* mDNS: `_mdns_services()` returns ONE service per queue (central +
  up to 24 printers); EVERY service carries the HUB port in its SRV
  (the tuple keeps 6 slots so the wire format is unchanged); TXT has
  `rp=ipp/print/<slug>` + unique uuid per queue; unicast TXT/SRV
  answers ride the same data.

### FEATURE - popup printer memory (extension/)

* `popup.js loadPrinters()` selection priority:
  1. the hub's CURRENT OS default - read from `r.default` (v3.4.6
     field fix; `r.default_printer` never existed),
  2. the remembered choice `chrome.storage.local advLastPrinter`
     (set on every real user change in the `selPrinter` change
     handler),
  3. the first printer in the list.
* The OS default is marked `[default]` in the dropdown
  (`popPrinterDefaultTag` i18n, EN "default" / BN "ডিফল্ট"); when the
  remembered choice (not the hub default) is auto-selected the
  tooltip says "Last used:" (`popPrinterLastUsed`).
* The change-only guard is untouched: a programmatic `sel.value =`
  fires no change event, `_printerApplied`/`_settingPrinter` block
  re-entry, and the hub endpoint is idempotent - so popup
  open/reload/re-select still sends ZERO set-default commands.
* `popup.html` badge `#ver` = v3.4.6; `manifest.json` = 3.4.6;
  `extension/content/api.js` `_apVerFallback` = "3.4.6";
  `i18n.js` brandLine EN+BN = Version 3.4.6.

### Console (THE ONE UI)

* Printer cards lead with the per-printer PATH queue URL
  (`p.ipp_queue`, `ipp://ip:9235/ipp/print/<printer>`) + COPY button;
  the dedicated-port branch is gone (`var leadUrl = p.ipp_queue || ""`).
* `BOOT.version` fallbacks = "3.4.6".

## 3. Config keys

`ipp_queue_ports` and `ipp_queue_port_map` are REMOVED from
`CONFIG_KEYS` - do not re-add them. An upgraded install's config.json
may still contain the two keys; `init_config()` only applies keys in
`CONFIG_KEYS`, so they are ignored and dropped on the next config
write (locked by `test_legacy_config_keys_are_ignored`).

## 4. Tests (tests/test_v346.py)

| Test | Locks |
| --- | --- |
| `test_mdns_services_all_announce_the_hub_port` | every mDNS service = hub port |
| `test_mdns_rrset_one_srv_per_service_all_on_hub_port` | announce packet: SRV per service, ONE port |
| `test_mdns_unicast_srv_query_answers_the_hub_port` | direct SRV query = hub port |
| `test_per_queue_uuids_stay_unique_and_stable` | the identity that makes one port safe |
| `test_printers_payload_carries_path_queue_only` | `/printers`: ipp_queue + ipp_path, no ipp_dedicated/ipp_port |
| `test_get_printer_attributes_one_port_three_queues` | THE proof: same port, 3 queues, 3 names, 3 uuids |
| `test_unknown_queue_still_validates_on_the_one_port` | v3.3.2 behaviour preserved |
| `test_dedicated_port_machinery_removed` | no ippq_* symbols, no queue_binding, keys out of CONFIG_KEYS |
| `test_legacy_config_keys_are_ignored` | upgrade tolerance |
| `test_firewall_back_to_the_single_hub_port` | nsi: no 9235-9259 add-rule, delete-rule survives |
| `test_popup_reads_the_real_default_field` / `..._remembers_and_autoselects_the_last_printer` / `..._i18n_keys_exist_en_and_bn` | the popup fix + memory |
| `test_console_cards_lead_with_the_path_queue` | ONE UI cards |

`tests/test_v335.py` keeps the manual re-scan + auto-CRX locks (the
dedicated-port locks moved here as their inversion).

## 5. Build + release checklist

```
# 0. sync the ONE UI + hub copies (after ANY console.html edit)
python3 scripts/embed_console.py
cp tool/unix/hub/advprint.py tool/windows/portable/hub/advprint.py

# 1. tests
python3 -m pytest tests/ -q            # 630 passed expected

# 2. everything (CRX3 + extension zip + Setup EXE + DEB + SHA256SUMS)
bash scripts/build-all.sh

# 3. artifacts land in dist/ - copy to the delivery folder:
#    AdvPrint-Pro.crx, AdvPrint-Pro-Extension-3.4.6.zip,
#    AdvPrint-Pro-Setup-3.4.6.exe, advprint-pro_3.4.6_all.deb,
#    SHA256SUMS-3.4.6.txt (+ the FULL zip incl. sources)
```

Version strings that must agree (locked by the test sweep):
`VERSION.txt`, `advprint.py VERSION/VERSION_NAME`, `manifest.json`,
`popup.html #ver`, `options.html` brand, `i18n.js` brandLine EN+BN,
`extension/content/api.js _apVerFallback`, `console.html
BOOT.version` fallbacks, `installer/setup.nsi` (OutFile +
VIProductVersion + DisplayVersion), deb control (build-time).

## 6. Upgrade notes for users

* From v3.3.5: queues added via a DEDICATED port
  (`http://<ip>:9236/ipp/print`) keep printing (the path routing
  answers on the hub port for every queue), but the port goes away -
  re-add from the printer card's COPY URL
  (`ipp://<ip>:9235/ipp/print/<printer>`) when convenient. The Setup
  removes the old TCP 9235-9259 firewall rule automatically.
* From v3.3.4 / older: nothing to do - the path queue URLs are the
  same as before; the popup now shows the actual default and
  remembers your last pick.
* The firewall is back to ONE rule: TCP 9235 (plus RAW 9100, IPP
  631 mirror, mDNS 5353) - no port range needed any more.
