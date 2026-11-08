# Release notes - AdvPrint Pro v3.0.8

**PROFESSIONAL IPP PRINTER - Windows 10/11, macOS, iPhone/iPad, Android
can now actually CONNECT and print**

AdvPrint Pro (Advanced Printer) by Bit Dream IT - Innovative Healthcare
Solutions
MIT license - 100% local - no cloud, no tracking

## The bug this release fixes

The report, with screenshots, from 2026-11-08:

*"http://192.168.1.7:9235/ipp/print - this IPP printer mode does not
work. Windows (Add a printer → IPP Device → http://192.168.1.7:9235/ipp/
print) says: **'Windows couldn't connect to the printer. Check the
printer name and try again...'** Update and fix the IPP mode - correct
IPP mode, more professional, for connecting mobile or any OS easily."*

**Root cause found (three protocol defects in the v2.9 IPP engine):**

1. **Wrong wire types** - the RFC 8010 value tags were violated:
   `printer-state` was sent as the ASCII text `"3"` inside a URI-tagged
   attribute instead of a 4-byte enum; `printer-is-accepting-jobs` went
   out inside an enum tag (booleans are 0x22, enums are 0x23);
   `queued-job-count` (an integer) went out inside a boolean tag;
   `copies-supported` (a range) went out inside a boolean tag with a
   raw 8-byte value; `printer-name` used a text tag instead of a name
   tag; `job-state` used a URI tag with ASCII digits.
2. **Missing required attributes** - every RFC 8011 §4.2.5.2
   Get-Printer-Attributes response must carry `printer-uri-supported`,
   `uri-authentication-supported`, `operations-supported`,
   `charset-configured`, `natural-language-configured`,
   `document-format-default`, `document-format-supported`,
   `pdl-override-supported`, `printer-is-accepting-jobs`,
   `queued-job-count`, `printer-up-time`, `printer-current-time` -
   none of them were sent.
3. **Missing operations** - no Create-Job + Send-Document (how macOS
   CUPS, iOS PrintKit and Android Mopria actually submit jobs), no
   Get-Jobs / Get-Job-Attributes / Cancel-Job / Print-URI, no chunked
   request-body support.

Loose clients (the hub's own peer printing, simple scripts) still
worked - which is why everything else "worked fine". But the strict
**Microsoft IPP Class Driver** that Windows 10/11 uses for "Add a
printer → IPP Device" refuses the whole answer on the first mistyped
attribute → "Windows couldn't connect to the printer".

## What v3.0.8 ships

1. **Byte-exact RFC 8010/8011 wire layer** - every attribute carries
   the correct tag and encoding, verified attribute-by-attribute
   against CUPS' own `cups/ipp.h`. `printer-uri-supported` now lists
   BOTH schemes: `http://pc:9235/ipp/print` (what Windows types) and
   `ipp://pc:9235/ipp/print` (what macOS/iOS/CUPS speak), with a
   matching `uri-authentication-supported` count, a stable
   `printer-uuid`, an 11-byte RFC 2579 `printer-current-time`, the
   operation list, document-format default + supported, media /
   color / sides / finishings / copies job-template defaults.
2. **Every operation a real print stack uses**: Print-Job,
   Print-URI (SSRF-guarded), Validate-Job (no phantom job row),
   Create-Job + Send-Document multi-document sessions (ids ≥ 1000000,
   5-minute abandon timeout), Cancel-Job (RFC: missing job-id →
   bad-request; cancels queued db jobs and open sessions),
   Get-Job-Attributes, Get-Jobs (completed / not-completed / my-jobs).
3. **Chunked request bodies** - phone IPP stacks POST without
   Content-Length; the hub decodes `Transfer-Encoding: chunked` now
   and answers clean HTTP 400 instead of a traceback on bad bodies.
4. **NEW: AirPrint-grade discovery (mDNS/Bonjour)** - while LAN
   sharing is ON, the hub announces itself over UDP 5353
   (`_ipp._tcp` + `_universal` subtype, TXT with `rp=ipp/print`,
   `pdl`, `URF=V1.4`, `UUID`). Result:
   - Windows 10/11 "Add device" lists the printer **by itself**
   - iPhone/iPad AirPrint picker shows it (no URL typing)
   - Android Default Print Service / Mopria sees it
   - macOS "Add Printer" lists it under Bonjour
   Pure stdlib responder (RFC 6762/6763 subset) - fail-safe: any
   multicast problem only disables discovery, never printing.
   Turn it off with `config.json` → `"ipp_mdns": false`.
5. **Firewall** - the Setup exe now adds the **UDP 5353** rule next to
   TCP 9235 + 9100 (discovery is useless if the firewall silently
   drops the announcements). Uninstaller removes it.
6. **The printer info page** (`http://pc:9235/ipp/print` in a browser)
   is now a per-OS cheat sheet - exact steps for Windows 10/11,
   macOS, iPhone/iPad and Android. Full guide: **docs/IPP-GUIDE.md**.
7. **The v3.0.7 self-host extension chain ships unchanged** - signed
   .crx (same permanent extension ID `likldbkamojokkfdlcjibiljpgbbnohc`)
   + `/extension/updates.xml` + force-install policy. This release
   bumps the extension to 3.0.8, so Chrome/Edge/Brave **silently
   update** the extension when the hub updates.

## Verification

- `tests/test_ipp.py` - NEW 16-test conformance suite; a strict wire
  linter validates every attribute's tag/type on every response
  (the exact checks the Microsoft IPP Class Driver effectively runs),
  plus Windows-style, macOS-2.0-style and phone-style request flows,
  Create-Job + Send-Document sessions, chunked upload, cancel and
  error paths. Full suite: **259 passed, 1 skipped**.
- A live-boot smoke test (`scripts/live_ipp_smoke.py`) replays the
  exact Windows "IPP Device" Get-Printer-Attributes exchange, a
  chunked Print-Job, Get-Jobs and mDNS announce/answer packets -
  ALL PASS (it also caught and fixed a DNS header layout bug during
  development).

## Add the printer after updating (30 seconds)

| OS | Steps |
| --- | --- |
| Windows 10/11 | Settings → Printers → Add device → it appears → Add. Or Add manually → IP/hostname → **IPP Device** → `http://<pc-ip>:9235/ipp/print` |
| macOS | System Settings → Printers → Add Printer → Bonjour list, or IP tab → IPP → `<pc-ip>:9235` + queue `ipp/print` |
| iPhone/iPad | Share → Print → Select Printer → "AdvPrint Pro" appears by itself |
| Android | Print → Default Print Service / Mopria → "AdvPrint Pro" appears |

LAN sharing must be ON (dashboard toggle) - it is what binds the LAN
listener; the Setup exe already added the firewall rules.

## Files

| File | What |
| --- | --- |
| `AdvPrint-Pro-Setup-3.0.8.exe` | Windows installer (bundled Python runtime, silent `/S`, auto-run, firewall incl. UDP 5353) |
| `advprint-pro_3.0.8_all.deb` | Linux .deb (systemd user service + autostart + force-install policy) |
| `AdvPrint-Pro.crx` | the signed extension package 3.0.8 (stable ID) |
| `AdvPrint-Pro-3.0.8-source.zip` | full source tree |
| `SHA256SUMS-3.0.8.txt` | checksums of all of the above |

*Upgrading from 3.0.7: just run the new Setup exe (or `sudo dpkg -i`) -
it replaces the hub in place, keeps your config/history, and Chrome
updates the force-installed extension automatically on next start.*
