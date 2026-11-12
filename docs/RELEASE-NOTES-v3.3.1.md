# v3.3.1 - THE LAN PC + WINDOWS IPP CONNECTION RELEASE (2026-11-12)

**Base: v3.3.0** (any-PC invite + dual-stack listeners) - everything
from v3.3.0 and earlier stays unchanged. Four user reports from the
real two-PC lab, all fixed and locked by `tests/test_v331.py` plus the
live repro `scripts/repro_v331_ipp.py` (a real Windows-11-style IPP
Add-Printer session from a simulated LAN client socket).

---

## BUG 1 - Windows: "couldn't connect to the printer" on BOTH IPP URLs

**The report:** *"Windows couldn't connect to the printer. Check the
printer name and try again. If this is a network printer, make sure
that the printer is turned on, and that the printer address is
correct."* - adding `ipp://192.168.1.101:9235/ipp/print` OR
`ipp://192.168.1.101:9235/ipp/print/<printer-name>` from another PC on
the same network.

**The root cause:** RFC 8011 section 4.2.5.2 requires
`printer-uri-supported`, `uri-authentication-supported` AND
`uri-security-supported` to be **three parallel `1setOf` attributes
with the same number of values** - one authentication keyword and one
security keyword per printer URI. The v3.3.0 printer group emitted two
fixed auth values and **no `uri-security-supported` at all**, so every
response that echoed the LAN client's own URI (4 URIs vs 2 auth values,
no security list) failed the Microsoft IPP Class Driver validation -
Windows answered "Windows couldn't connect to the printer" while
CUPS/phones (which validate less strictly) kept working.

**The fix:** `_ipp_printer_group()` now builds the full parallel
triple: for every URI in `printer-uri-supported` (canonical generic +
per-printer queue URIs, both schemes, plus every echoed client URI)
there is exactly one `uri-authentication-supported` value and one
`uri-security-supported` value, both `"none"` - the same value the
Microsoft class driver itself uses for plain-http printers. Unit test
`test_ipp_printer_group_unit_triple_always_parallel()` proves the lists
stay parallel even with no extra URIs.

---

## BUG 2 - per-printer IPP queues 404ed right after hub start

**The report:** *"ipp://192.168.1.101:9235/ipp/print/ printer name both
not work correctly."*

**The root cause:** the per-printer queue resolver
(`_ipp_queue_match`) read `list_printers_cached()`, which answers from
the printer-name cache and only **kicks a background refresh** - the
cache is EMPTY until the background OS enumeration lands. Any LAN PC
that added a per-printer queue in the first seconds after hub start
got 404 "unknown per-printer IPP queue"; the negative result was even
memoized for 5 s.

**The fix:** `_lp_refresh_sync()` - a SYNCHRONOUS one-shot OS
enumeration (rate-limited to one per 2 s, single-flight guarded) runs
whenever the cache is empty, and the negative-match force-refresh in
`_ipp_queue_match_cached()` uses it instead of the async kick. The
queue resolves the moment the hub is up; new printers still appear
within the 2 s rate-limit window.

---

## BUG 3 - the "Another PC (LAN PC)" card was a demo mockup

**The report:** *"share send mode not active because of auto redirect
own ip that need other pc ip token why it redirect own ip."*

**The root causes (three real defects behind one symptom):**

1. The card's **Connect button read `input.inp.mono[0]`** - the FIRST
   mono input in the Connections panel - which is the **Self PC hub
   URL**. It "connected" this PC to itself and only toasted.
2. The live renderer **overwrote the LAN PC URL input with the hub's
   own address** (`pcUrl.value = lanBase()`) on every refresh, so the
   OTHER PC's address the user typed vanished.
3. **Share Send Mode did not exist** - the card only mentioned it in a
   note. Clear toasted `"(demo value)"`; the CONNECTED chip was
   hardcoded.

**The fix:**
- the card (`#lanPcCard`) carries real ids: `#lanPcHubUrl`,
  `#lanPcToken`, `#lanPcConnect`, `#lanPcClear`, `#lanPcChip`,
  `#lanPcState` and the switch `#lanPcSendSw`; the URL field is
  user-owned and only filled from the saved peer entry
- **Connect** validates the URL shape, probes the OTHER PC's hub
  server-side via the new `POST /peer-probe` (token included - no CORS,
  no mixed-content pain) and saves `{url, token, name}` into
  `peer_hubs` + `peer_forwarding: true` in ONE atomic `/config` write;
  the chip flips to CONNECTED with the peer's version or stays OFFLINE
  with a readable error (URL / firewall / LAN sharing hints)
- **Clear** wipes `peer_hubs`, `peer_forwarding` AND `share_send_all`
- the chip renders from `/peers` + `/config` live data (CONNECTED /
  OFFLINE / NOT CONFIGURED)
- a REAL **Share Send Mode** power switch saves instantly (POST
  `/config` with both keys) and refuses to turn ON while no LAN PC is
  connected

### The /connect invite page (v3.3.0 behaviour, locked again)
The invite page keeps the v3.3.0 per-device URL logic (verified by the
repro: the peer URL keeps the visitor's Host, the form still posts to
the VISITING PC's own hub at 127.0.0.1, a loopback visitor gets the
self-invite explainer).

---

## BUG 4 - Share Send Mode now sends EVERY job to the LAN PC

**The report (expected behaviour):** *"Turning Share Send Mode ON sends
every print job to that PC. OFF (default) prints on the Self PC above.
Receiving is the OTHER PC's switch (Share Receive Mode)."*

**The fix:** new config key `share_send_all` (DEFAULTS + CONFIG_KEYS +
CONFIG_TYPES + /config validation + /health). Worker behaviour:

- `share_send_all` ON + `peer_forwarding` ON + peers configured →
  `_share_send_forward(job)` sends EVERY printable job to the first
  alive peer hub (`POST /print` with `pdf_base64`, peer token, source
  `share-send:<port>`); the job is marked `forwarded` with the remote
  job id and audited (`job.forwarded`)
- the LAN PC unreachable / rejects → the job is **HELD** with a
  readable reason ("LAN PC hub unreachable - job held until it
  answers") - nothing prints locally behind the user's back; **Print
  now** overrides and prints on this PC
- **stays local:** virtual PDF printers (Microsoft Print to PDF) and
  raw/ESC-POS receipt jobs - saving a PDF file or driving a
  locally-attached receipt printer on ANOTHER PC makes no sense
- `peer_forwarding` WITHOUT `share_send_all` keeps the v2.9.1 M4
  offline-fallback behaviour exactly (regression-locked by
  `test_legacy_peer_forwarding_offline_fallback_unchanged`)

### New: POST /peer-probe
Token-gated management endpoint used by the console Connect button:
probes `<url>/health` server-side with the given token and returns
`{ok, up, version, hostname, share_lan, token_ok}` plus a readable
error when the peer is down. LAN-only: non-private hosts are refused
(400). Every probe is audited (`peer.probe`).

### Health JSON additions
`peer_forwarding`, `share_send_all`, `peer_hubs_count` - the ONE UI
chip and switch render the REAL state (no more hardcoded demo values).

---

## Version coherence 3.3.1

- `tool/unix/hub/advprint.py` + `tool/windows/portable/hub/advprint.py`
  (byte-identical): `VERSION = "3.3.1"`, VERSION_NAME describes the
  release
- `VERSION.txt`, `extension/manifest.json`, `extension/popup.html`,
  `extension/options.html`, `extension/i18n.js` (EN + BN brand lines),
  `extension/content/api.js` fallback version
- `installer/setup.nsi` (OutFile, VIProductVersion, File/Product,
  DisplayVersion, error text), `installer/deb/DEBIAN/control`
  (also caught up from 3.2.8 - the v3.3.0 packaging missed it)
- `CHANGELOG.md` entry, `README.md` What's-new section,
  `START-HERE.txt` rewritten, `docs/RELEASE-NOTES-v3.3.1.md` (this
  file), `docs/AdvPrint-Pro-v3.3.1-A-to-Z-DEV-GUIDE.md`
