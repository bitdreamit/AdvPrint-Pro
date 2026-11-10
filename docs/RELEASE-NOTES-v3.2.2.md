# Release Notes - AdvPrint Pro v3.2.2

**"ALL IPP PATTERNS BACK + INSTANT DISCOVERY + ONE TOOLBAR"**

Base: v3.2.1 - the approved All-in-One UI, the embedded `CONSOLE_HTML`
and every v3.0.x-v3.2.1 feature ship unchanged. This release repairs the
two things the v3.2.1 feedback reported: the **standard `ipp://` printer
URL stopped working** ("standerd ipp://ip:9235 add previously but now it
missing") and **Android could not connect to any of the given
addresses**. It also reduces the UI duplication ("same button different
area in same UI") for a cleaner, more professional view.
by **Bit Dream IT - Innovative Healthcare Solutions**.

---

## 1. Every IPP URL pattern answers again (v2.9.0 + v3.0.8 lineage)

The v3.0.8 professional IPP engine was still in the hub, but v3.2.x
routed only `/ipp/print`, `/ipp` and `/ipp/` to it. The **root pattern**
- `ipp://<ip>:9235` / `http://<ip>:9235` with NO path, exactly what
Windows "Add a printer -> IPP Device", macOS IP printing and CUPS send
when the user types just the address - fell into the token-protected
API and answered `400 bad request body` JSON. v3.2.2 restores it:

- **Any POST whose `Content-Type` is `application/ipp` goes to the IPP
  engine on every path** - `/ipp/print`, `/ipp`, `/ipp/`, the
  per-printer `/ipp/print/<printer>` queues AND the bare root. Web
  pages can never send `application/ipp`, so this is unambiguous.
- **Phone-sized jobs no longer die at the gate**: the v2.9.1 big-body
  preauth guard 401'd any unauthenticated body over 1 MB BEFORE the IPP
  engine saw it - a phone's photo or policy PDF (2-10 MB) could never
  print. Native IPP is token-free by design (a physical network printer
  has no token either) and stays bounded by its own `MAX_PDF` 413 limit,
  browser-Origin refusal and per-IP audit.
- The browser how-to page (`GET /ipp/print`) now documents **all URL
  forms**: standard `ipp://<ip>:9235/ipp/print`, Windows add-by-URL
  `http://<ip>:9235/ipp/print`, and the short root form
  `ipp://<ip>:9235`.

## 2. Discovery that phones can actually catch (AirPrint / Mopria)

Android's Default Print Service and iOS AirPrint cannot add a printer
by hand - they only DISCOVER via mDNS. The v3.2.1 responder answered
**one** query and then slept 3 s, so a phone's few-second scan window
kept missing the hub. v3.2.2:

- **The responder drains every queued packet back-to-back** - a query
  is answered immediately, never after a sleep (config switches are
  re-read every ~30 s of quiet instead of between packets).
- **RFC 6762 §8.3 startup burst**: the record set is announced twice,
  ~1 s apart, so listeners that join mid-announce still catch it.
- **Multi-hub record-poisoning fix**: the responder used to answer SRV
  queries for ANY `<instance>._ipp._tcp.local` name - on a LAN with two
  AdvPrint hubs each one claimed the other's instance and phones could
  reach the wrong PC. It now answers only the service names, its own
  instances and its own host target.
- **One-click firewall repair now also (re)adds the UDP 5353 mDNS rule**
  (the Setup EXE already added it; after a cleanup tool removed it,
  phones could never SEE the printer even though every TCP rule was
  fine).

## 3. THE ONE UI - same button, one place

- **Toolbar reduced to real actions**: New Job, Pause/Resume Queue
  (label follows the state), Release ALL, Test Page - plus two live
  status chips (LAN, IPP). The ten tab shortcuts that duplicated the
  sidebar one-to-one are gone; navigation lives in the sidebar and the
  menus only.
- **Address bar reduced to the two QR pills** (QR codes, Send Portal) -
  the Connections/DropZone/THE-ONE-UI pills duplicated the sidebar too.
- **LAN tab - the complete IPP printer card** (restores what the old
  dashboard showed, in rev-4 style):
  - `Network printer (IPP)` - the Windows add-by-URL form
  - `Standard printer URL` - the **ipp://** form (RECOMMENDED) with
    Copy + QR
  - `Short form (root)` - `ipp://<ip>:9235` with Copy
  - `AirPrint discovery (mDNS)` - live ON/OFF chip
  - a **per-OS add guide**: Windows 10/11, macOS, iPhone/iPad (AirPrint),
    Android (Default Print Service / Mopria) - including the honest
    note that Android has no manual-add path, discovery is the only way
- **Network menu**: new "Copy IPP printer URL (ipp://...)" item; the QR
  modal for the IPP URL shows all three forms.
- Pause/Resume buttons keep their label honest everywhere after a
  toggle.

## 4. API correctness fix

- `POST /print` (queue mode OFF) answered `auto_queued` as the
  `held_reason` STRING when the instant worker had already held the job
  (printer offline) - a Python and/or-chain returning a string where the
  API promises a boolean. Now always a proper boolean.

## 5. Tests

- **312 passed** (was 302): new conformance tests for the root IPP
  pattern (Get-Printer-Attributes + >1 MB Print-Job on `/`), the `/ipp`
  pattern, the how-to page content, and a full mDNS suite (back-to-back
  answering, RFC 6762 unicast/multicast reply rules, AirPrint `_universal`
  subtype + Mopria TXT records, SRV port, multi-hub silence, drain-loop
  structure).

## Upgrade notes

- Install over the existing v3.2.x - config, history and pairing are
  kept. On Windows run `UNINSTALL-WINDOWS.bat` first ONLY if an old
  hub/service is still running (see START-HERE).
- After installing, verify: LAN tab shows the `ipp://` URL + mDNS ON;
  on the phone open any printable item -> Print -> the printer appears
  by itself.
