# v3.3.2 - SHARE SEND MODE + WINDOWS IPP ADD-FIX RELEASE (2026-11-12)

**Base: v3.3.0** (any-PC invite + dual-stack listener release) with the
v3.3.1 LAN-PC work redone properly. Four real-world reports from the
LAN, all fixed and locked by `tests/test_v332.py`.

---

## BUG 1 - Windows: "Windows couldn't connect to the printer" (IPP add from any PC)

**The report:** *"CURRENT IPP NOT ADDED NOW ipp://192.168.1.101:9235/ipp/print
OR ipp://192.168.1.101:9235/ipp/print/printer-name both not work
correctly"*, then the exact Windows dialog text.

**The root cause:** the Get-Printer-Attributes response was missing the
**`uri-security-supported`** printer description attribute - a REQUIRED
attribute in RFC 8011 §4.2.5.2. The Microsoft IPP Class Driver (what
Windows 10/11 uses for "Add a printer -> IPP Device") runs a strict
parser over the required attribute set: one missing attribute and the
whole response is rejected. Everything else in the v3.0.8 wire set was
correct, which is why every other client kept working.

**The fix:**

| Item | v3.3.0 | v3.3.2 |
| --- | --- | --- |
| `uri-security-supported` | absent | present, one `none` per URI |
| `uri-authentication-supported` values | hardcoded 2 | exactly one per `printer-uri-supported` entry (RFC 1setOf parity) |
| Additional-value wire order | n/a | ALL auth values before the security values - an additional value (empty name) belongs to the attribute right before it, never interleaved |
| Multi-adapter echo | client URI echoed into the URI list but the auth list kept 2 values -> parity broken | parity holds no matter how many URIs are echoed |

**Also fixed in the same pass:**

### BUG 2 - tokenless IPP Print-Job over 1 MB died mid-transmit
`_preauth_gate()` answered 401 BEFORE reading a >1 MB body without a
token. Windows speaks IPP **without any token** (like a physical
network printer) and its Print-Job bodies are routinely over 1 MB, so
the still-transmitting client got a connection abort - every real print
died even where the add had succeeded. IPP routes are exempt now; the
hub keeps its own IPP guards (ipp_printer switch, browser-Origin
refusal, 25 MB cap, per-request audit).

### BUG 3 - unknown per-printer queue hard-404'd the add flow
A queue name that matched no local printer answered a JSON 404 to
Get-Printer-Attributes -> the same Windows error dialog again. Now:
Get-Printer-Attributes / Validate-Job answer as the generic queue with
the requested name as `printer-name` (the add SUCCEEDS), Print-Job
prints on the hub's default destination with an audit note, and the
browser landing page of an unknown queue is the generic how-to page.

### BUG 4 - SHARE SEND MODE ("auto redirect own ip") is REAL now
The Connections panel's "Another PC (LAN PC)" card was a demo mockup:
its Connect button read the SELF PC URL field (hence "it redirects own
ip") and a reload wiped the state. Rebuilt end to end:

| Layer | v3.3.2 |
| --- | --- |
| `POST /peer/pair {url, token}` | validates the URL, **refuses self-pairs** (loopback / own IPs on own port), probes the OTHER PC with its token, requires ITS LAN sharing ON, persists the `lan-pc` entry in config.json |
| `GET /peer/status` | the card's state source on every poll: pairing + live probe (peer version, ITS LAN sharing / IP printer state, its printers, latency) + switch state; probes cached 8 s |
| `POST /peer/unpair` | the Clear button - forgets the pairing, Share Send OFF |
| Share Send Mode switch | `POST /config {share_send}`; the server REJECTS ON without a persisted pairing, so "Connect the LAN PC first" can never be a transient UI lie again |
| Forwarding | when ON, the worker forwards EVERY new job to the paired PC first; the peer lacking the printer prints locally with an audit note |
| LAN PC hub URL input | never auto-filled with this PC's own address any more; the saved OTHER-PC URL is restored from config; the token is never rendered back |
| `POST /peer/test-page {printer}` | prints a test page on the paired PC's printer through a server-side relay (no cross-origin browser call, no token in the page) |

### Printers panel - devices from a different IP
New **"Show other PCs (LAN / IPP)"** switch (`show_remote_printers`):
the paired PC's devices appear as extra cards with a **LAN PC · IPP**
badge, the source ip:port, the device's own `ipp://` URL and Test Page
/ Set Default (disabled - the default belongs to that other PC) /
Details.

---

## Verification
- `python3 -m pytest tests/` - 560+ tests green, including the new
  `tests/test_v332.py` (IPP conformance for the required-attribute set
  and the parity rule, the >1 MB tokenless Print-Job, the unknown-queue
  add flow, the whole pairing/forwarding/relay matrix with a scripted
  peer hub, and the console UI wiring).
- The v3.0.8 strict wire lint (`tests/test_ipp.py`) now covers
  `uri-security-supported` and the parity rule on the generic AND
  per-printer queues.
