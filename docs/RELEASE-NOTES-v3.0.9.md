# Release notes - AdvPrint Pro v3.0.9

**BUG-FIX RELEASE on the v3.0.8 professional IPP printer: (1) the
Default-printer dropdown doubling fix, (2) one IPP queue + Bonjour
service per LOCAL printer - the hub becomes the central IPP middleware
for every printer on the PC**

AdvPrint Pro (Advanced Printer) by Bit Dream IT - Innovative Healthcare
Solutions
MIT license - 100% local - no cloud, no tracking

## Bug 1 - the Default printer dropdown showed every name TWICE

The report from 2026-11-09:

*"The Default printer dropdown shows duplicated names:
"AdvPrint Pro @ AI-LabAdvPrint Pro @ AI-Lab", "OneNote (Desktop)
OneNote (Desktop)", "Microsoft Print to PDFMicrosoft Print to PDF",
"HP Laser 103 107 108HP Laser 103 107 108" - printer names are
concatenated twice in the select options. Need to fix."*

**Root cause:** the printer names reach the dropdown straight from the
OS query, and somewhere on that road (WMI output / stored settings -
the codebase already knew this family of bug: `healPrinterName` was
added to background.js in v2.6.8 for "typed-twice stored settings") the
name text got duplicated with no separator. The extension only healed
the name at PRINT time - never in the dropdown.

**The v3.0.9 fix - healing at the SOURCE + defense in depth:**

1. **Hub (the source):** `list_printers()`, `default_printer()` and the
   Windows/Unix status maps now run every name through
   `_heal_doubled_name()` (collapses `X X` -> `X`, loops for quad-
   doubled names) and dedupe case-insensitively. Every API client
   (extension dropdown, rules chips, status table, /printers, the
   console tool) is fixed at once.
2. **Extension options page:** a local `healPrinterName()` + a dedupe
   pass protect the dropdown, the rule printer selects and the chips
   even against an OLDER hub that still serves doubled names.
3. **Print time (unchanged since v2.6.8):** background.js still heals
   the printer name on every outgoing job, and the hub heals the queue
   name on every incoming IPP job.

## Bug 2 (the second half of the same report) - PER-PRINTER IPP

Every LOCAL printer now ALSO has its own queue:

```
ipp://<host>:9235/ipp/print/<printer>
```

- **IPP engine:** `Get-Printer-Attributes`, `Print-Job`, `Print-URI`,
  `Validate-Job`, `Create-Job` + `Send-Document` and `Cancel-Job` all
  work on `/ipp/print/<printer>` - the per-queue responses describe
  THAT printer (`printer-name`, per-queue stable `printer-uuid`,
  per-queue `printer-uri-supported`), and jobs are enqueued FOR that
  printer only. The main `ipp/print` queue keeps meaning the OS default
  destination, exactly as before. Unknown queue names are answered with
  the IPP `client-error-not-found` status - unless the OS enumeration
  is unavailable, which fails OPEN (a wedged WMI must never block
  printing).
- **mDNS / Bonjour:** one `_ipp._tcp` + `_universal` service PER
  printer (capped at 12, deduped, DNS-safe instance labels), each with
  its own `rp=ipp/print/<printer>` TXT and per-queue UUID - so iPhones
  (AirPrint), Androids (Mopria), Macs and other Windows PCs pick ANY
  printer on this PC BY NAME from their print dialog while LAN sharing
  is on.
- **`/printers` API:** each printer row now carries its own `ipp_url`
  (`ipp://host:9235/ipp/print/<printer>`), ready for dashboards and
  tools.
- **Browser info page:** opening `/ipp/print/<printer>` in a browser
  still explains the queue (now naming the printer).

## Compatibility

- Pure bug-fix on the v3.0.8 base - the RFC 8011/8010 wire engine, the
  self-host extension chain (ExtensionInstallForcelist + signed .crx +
  updates.xml), the Send portal, the RAW 9100 listener and every other
  endpoint ship unchanged.
- Upgrade in place: run the new Setup EXE over the old install (or
  `dpkg -i` the new .deb). The extension updates itself from the hub.
- No config changes, no new pip dependencies - still ONE Python file,
  zero third-party imports.

## Tests

17 new regression tests (`tests/test_309.py`): the exact bug-report
names heal correctly, list healing + dedupe, queue-name parsing
(including `%2F` slash names), fail-open queue validation, per-printer
route plumbing, a real HTTP Get-Printer-Attributes against a live hub
queue, unknown-queue rejection (0x0406), per-printer Print-Job landing
on the right printer, Create-Job + Send-Document sessions per printer,
`/printers` ipp_url contract, per-printer mDNS TXT/rrset + packet size
guard. Full suite: 276 passed.
