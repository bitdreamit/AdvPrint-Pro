# AdvPrint Pro v3.2.6 - Release Notes
### by Bit Dream IT - Innovative Healthcare Solutions

**Seven user-reported bugs fixed, one new feature, two removals and a
new security model.** Base: v3.2.5 (everything there stays locked by
tests - 397 passed, 1 skipped). Verified live: real hub + real browser
(`scripts/render_v326.py` - ALL CHECKS PASSED, zero page errors).

---

## 1. History and Queue "clear but not clean" - FIXED

**What you saw:** clicking Clear in the Queue or the History left the
rows on screen.

**Why:** `POST /queue/clear` only flipped *queued* jobs to "canceled"
and never deleted anything; the console's "Clear ALL history" button
POSTed `/queue/clear` with `{finished:true}` - a body the hub ignored
completely - so nothing was ever removed.

**Now:**
- **Clear queue** cancels every waiting / held / scheduled / printing
  job AND removes all finished records - the queue AND the history
  come back genuinely empty (the confirm dialog says exactly that).
- **Clear ALL history** (History tab + Tools menu "Clear ALL finished
  jobs") calls `POST /history/clear` - finished records removed,
  waiting jobs never touched.
- `POST /queue/clear {finished:true}` now works as an alias of
  `/history/clear` for API clients.
- "Clear selected" still only unticks rows (v3.2.5 design: never
  deletes jobs).

**Proven live:** 3 seeded jobs → `/queue/clear` → `{canceled:0,
removed:3}` → `/jobs` answers 0 rows.

## 2. Printer → Details double `/ipp/print` - FIXED

**What you saw:**
`http://127.0.0.1:9235/ipp/print/ipp/print/microsoft-print-to-pdf?token=...`

**Why:** the hub returned `ipp_path = "ipp/print/<slug>"` AND the
console prepended `/ipp/print/` a second time.

**Now:** the hub returns the bare slug, the console joins it once.
Details opens
`http://<host>:9235/ipp/print/<printer-slug>?token=...` - the same
per-printer queue URL v3.2.5 proved workable.

## 3 + 4. LAN Sharing top switch + Copy URL token - FIXED

**What you saw:** the panel-header **Disable/Enable** did nothing and
**Copy URL** copied `http://192.168.1.101:9235/ui` without the token.

**Why:** the header button was never wired (only the rows were), and
the copy action built the URL without the token.

**Now:**
- Header **Disable/Enable** toggles LAN sharing live (and its label
  follows the state like the rows).
- Header **Copy URL** and the LAN-share row **Copy URL** both copy
  `http://<ip>:9235/ui?token=<token>`.
  The URL opens the console **on the hub PC** (loopback or the hub's
  own IP - see the security model below). Other PCs that open it get
  the friendly locked page with the print instructions.
- **NEW IPP toggle** in the same header: `IPP: ON/OFF` - an extra,
  independent Enable/Disable for the IPP printer.

## 5. QR code scheme - FIXED

**What you asked:** the IPP QR must contain
`http://192.168.1.101:9235/ipp/print` (scanning it in a browser must
open the page - phones Google-search `ipp://` URLs), while the shown /
copied printer URL stays `ipp://192.168.1.101:9235/ipp/print`.

**Now:**
- `/qr?kind=ipp` encodes the **http://** URL - hard-pinned + test
  locked.
- The QR modal shows `ipp://...` as the URL line, the Copy button
  copies `ipp://...`, and the note spells out both:
  "QR code contains: http://... · printer-add URL (copy): ipp://...".

## 6. Install doc backdated to 3.0.7 + Docs in the UI - FIXED

- The self-host extension server page (the "install link" document)
  now shows the current version - `(v3.2.6)`, never a hardcoded one.
- The /docs "Browser extension - silent install" section is versioned
  from the build, not stuck at v3.0.7.
- **NEW in-UI Docs button:** Help → "Quick start guide", About →
  "Docs" / "Release notes" all open the guide **inside the console**
  (8 sections + release notes, jump-to-section support). No extra
  old-UI view needed; the classic /docs page stays one click away
  ("Full guide page" in the modal footer).

## 7. SECURITY - the console UI is local-only (new in 3.2.6)

**Your report:** "anyone on the same LAN can open the hub UI and
change settings - that is dangerous. Only own IP or loopback should
show the UI. LAN Sharing / Send / IPP must keep working from other
IPs. Printing must not be blocked when allowed_ips is `*` or a list."

**The rule now:**

| Caller | Console UI + settings | Print surface |
| --- | --- | --- |
| Hub PC (127.0.0.1 / its own IP) | full access (never locked out) | full access |
| Other LAN PC / phone | **branded 403 page** with print instructions | **works** per Allowed-IPs |

- **Locked to the hub PC:** `/ui`, `/dashboard`, `/docs`, `/`,
  `/config` (POST), `/token/*`, `/autostart`, `/queue/*` control,
  `/history/clear`, `/jobs/release_all`, `/tool`, `/restart`,
  `/printers/set-default`, `/extension/policy/*`, `/firewall/*`,
  `/livetest`, `/qr`, `/stats`, `/audit`, `/export/*`, `/debug`,
  `/diagnostics`, `/peers`, `/dropzone`, `/lan/selftest`.
- **Open to allowed IPs (default `*`):** `POST /print`, `GET+POST
  /send`, `GET+POST /ipp/*` (+ 631 mirror, RAW 9100), `GET /jobs`,
  `POST /jobs/<id>/cancel`, `POST /jobs/<id>/print-now`,
  `POST /jobs/bulk-reprint`, `GET /printers`, `GET /health`,
  `GET /extension/*` (child-PC extension self-update), `GET /connect`,
  `GET /testprint`, error reports.
- A LAN PC opening the share URL now sees a clean page: *"The console
  runs on the hub PC only. Printing still works - Send portal / IPP
  printer URL / print API."* - with the hub's IPP URL on it.
- Every refusal is audited (`ui.locked`) + logged `[SECURITY]`.
- The Allowed-IPs list (v3.2.3) still gates EVERYTHING as before -
  both layers stack: allowlist first, then local-only for management.

## NEW - IPP follows LAN sharing

- Switching **LAN sharing ON** automatically switches the **IPP
  printer ON** (one request, audited, live listeners start
  immediately - no restart, no 3 s wait).
- An explicit `ipp_printer` value in the same request always wins -
  the extra **IPP: ON/OFF** header toggle and the row button can keep
  IPP off on a LAN-on hub.

## REMOVED - the CLI tool menu

- The numbered ASCII menu (`[1] Start ... [14] Restart ... [0] Exit`)
  is gone. `python tool.py` (or the portable **AdvPrint-Tool.bat**)
  now opens THE ONE UI console in the browser.
- All one-shot commands stay for scripts and repairs:
  `status · start · stop · restart · testprint · history · autorun
  on|off · livetest [print] · diagnose · dashboard · service-install
  · service-remove · service-status · update-check · uninstall`.
- Start Menu: **"AdvPrint Console"** replaces the old Tool shortcut.

## REMOVED - tray menu reduced

The tray icon menu is exactly what you asked: **Open dashboard ·
Restart hub · Exit** (plus the double-click = dashboard). Everything
else lives in the console.

---

## Upgrade

1. Run `AdvPrint-Pro-Setup-3.2.6.exe` over the old install (or unzip
   the portable / install the deb). Settings, history and printers
   are kept.
2. The extension auto-updates from the hub (CRX 3.2.6, same ID);
   Chrome applies it at the next browser restart.
3. Nothing to reconfigure - token, printers and Allowed-IPs carry
   over.

## Verification (for the record)

- `tests/test_v326.py` - 30 new locks (clear endpoints, bare slug,
  copy-token, QR payload, in-UI docs, 37-row security matrix, CLI
  removal, tray items, IPP linkage, version coherence). Full suite:
  **397 passed, 1 skipped**.
- `scripts/render_v326.py` - live hub + Chromium: version boot 3.2.6,
  header toggles flip + labels follow, Copy URL carries the token,
  Details opens the undoubled URL, QR modal shows both URLs and copies
  ipp://, docs modal opens inside the UI, zero page errors. Screenshots:
  `docs/v326-*.png`.

*100% local · no cloud. AdvPrint by Bit Dream IT - Innovative
Healthcare Solutions.*
