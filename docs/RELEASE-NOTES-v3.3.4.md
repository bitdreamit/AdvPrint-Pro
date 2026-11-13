# v3.3.4 - MULTI-PRINTER IPP ADD + POPUP PRINTER/RELOAD/NETWORK RELEASE (2026-11-14)

**Base: v3.3.3** (user-verified: "popup update and ipp work fine").
Three new real-world reports, all fixed and locked by
`tests/test_v334.py`.

---

## BUG 1 - "only default or only one add posible" - every printer of the hub can be added now

**The report:** *"only default or only one add posible if multiple
printer exist it not work fine when add one then it auto add one
ip:port/ipp/print show that when add aggaign another it show error to
add"* - on the LAN, Windows added the hub ONCE (the central queue,
bound to the hub PC's default printer); adding a SECOND, specific
printer queue `http://<hub-ip>:9235/ipp/print/<printer-name>` was
refused ("printer already exists" / add error).

**The root cause:** the per-printer IPP endpoints themselves were fine
(v3.0.9 queues, v3.2.9 per-queue IPP uuids and URI echo - that is why
the FIRST add worked). The blocker was DISCOVERY: the mDNS / Bonjour
announcer stamped the SAME `UUID` TXT record on EVERY advertised
`_ipp._tcp` service - the central queue AND all per-printer queues.
Windows and Bonjour use that uuid to tell printers apart, so the
second per-printer service looked like a re-announcement of the first
one and the add was rejected.

**The fix:** every service now carries its OWN stable printer-uuid -
the hub uuid for the central queue, a per-queue uuid
(`token|hostname|queue-slug`) for each printer queue - on BOTH answer
paths: the proactive announce packet AND the direct unicast TXT answer
(Windows asks one instance by name). With unique uuids every queue
adds cleanly side by side; phones and other PCs see every printer of
the hub as its OWN entry.

**If a queue was half-added before the upgrade:** remove that printer
once on the device, then add it again - Windows remembers queues by
uuid, and the old shared-uuid entry must go first.

## BUG 2 - "when reloads popup or set any printer select it continue cmd run multiple"

**The report:** the OS set-default command (Windows PowerShell
SetDefaultPrinter / Unix lpoptions -d) kept running over and over when
the popup reloaded or a printer was picked.

**The fix - two layers, so the command runs EXACTLY ONCE per real user
change and NEVER on a popup open/reload:**

- **Popup (new printer selector):** set-default is sent ONLY when the
  user picks a DIFFERENT printer. Opening/reloading the popup only
  SELECTS an option programmatically - a programmatic value set fires
  no change event, so nothing is sent. Even on re-entry the
  `_printerApplied` guard blocks a repeat for the same printer and
  `_settingPrinter` blocks parallel calls; a failed set reverts the
  selection. On top, `refresh()` gained an in-flight guard so the
  popup boot storm (load + reload + language render) can no longer
  stack duplicate hub calls.
- **Hub (POST /printers/set-default is IDEMPOTENT):** when the
  requested printer IS already the verified OS default (10 s cached
  read), the endpoint answers instantly with `unchanged: true` and
  spawns ZERO commands. A successful set caches the verified result,
  so even an immediate repeat runs nothing. A looping or old-UI client
  can no longer multiply the cmd.

## FEATURE - the popup is a control surface now (user-approved ONE design, UI update)

The popup ships the new ONE design (navy gradient header, overlapping
status pill, inline reload arrow next to the printer selector, three
Power switch tiles, wide Options card):

- **PRINTER selector** - the hub's printers with their statuses; the
  current OS default is preselected; picking another printer makes it
  the OS default (new `hubSetDefault` background message, one command
  per real change). The applied default shows in the selector tooltip.
- **RELOAD button** (the arrow beside the selector; the header network
  icon is clickable too) - re-reads hub state, switches, printers and
  jobs, with a spinning indicator and a one-reload-at-a-time guard.
  Reload NEVER sends set-default.
- **NETWORK icon** in the header: gray = hub offline, green = hub on
  this PC, teal + pulse = Sharing (Share Receive) is ON and the hub
  listens on the LAN (other PCs and phones can send jobs). The tooltip
  names the state and the listening address (hub /health
  `lan_bind_addrs`).
- **"Receive" is now "Sharing" + connection icon:** the Share Receive
  switch is labelled **Sharing** (English + Bangla) and carries the
  NETWORK/CONNECTION icon (network nodes) instead of the old
  download-tray arrow; Save PDF keeps its download icon. The switch
  keeps writing the hub `share_lan` key - behaviour unchanged.
- New i18n strings for everything above (English + Bangla); the popup
  version badge follows the manifest (3.3.4).

## FEATURE - AUTOCRX: browser auto-integration is INTERNAL (no extra .bat needed)

**The request:** "no need extra .bat existing - run similar bat-like
code internally with administrator run/PowerShell to active autocrx,
auto integrate AdvPrinter tool."

**The implementation:** the hub now runs the .bat's policy pass
itself. `ext_policy_activate()` generates
`advprint-activate-extension.ps1` in the data dir - the SAME policy
writes the fixed .bat does (Forcelist + Allowlist + Sources for
Chrome, Edge, Brave, Vivaldi, Chromium and Opera, HKLM machine-wide
AND HKCU for the current user, duplicate-skip, never deletes) - and
starts it ONCE via `Start-Process powershell -Verb RunAs -Wait`
(a single UAC prompt). The elevated pass leaves a JSON result file
that the hub reads back, so callers get a real per-browser report
instead of a blind "OK".

Entry points:

- **THE ONE UI console** - Extension tab, the blue **Auto-integrate
  (admin)** button (shows the per-hive/per-browser report in the tool
  output and a toast);
- **`POST /extension/policy/activate`** - optional body
  `{"host": "192.168.1.10:9235"}` stamps a LAN-reachable address into
  the Forcelist for activations on OTHER PCs;
- **`POST /tool` action `autocrx`** (aliases `activate-extension`,
  `policy-activate`, loopback only);
- **CLI** - `python advprint.py activate-extension` (alias `autocrx`,
  optional `host:port` argument) - printed in `help`.

`prebuilt/allow_extention_advprint_pro.bat` stays as an OFFLINE manual
fallback (with its fixed Apply HKLM / Apply HKCU menu) for machines
where the hub cannot elevate.

## FIXED - allow_extention_advprint_pro.bat ("Apply HKLM / Apply HKCU not working")

**The root cause:** the old script DELETED
`ExtensionInstallForcelist` on every run and never wrote it back - so
the CRX force-install policy was silently wiped while the script
claimed success. It "worked" (Allowlist + Sources were written) while
removing the ONE policy that makes the extension install.

**The rewrite:**

- writes ALL THREE policies per browser (Chrome, Edge, Brave, Vivaldi,
  Chromium, Opera): `ExtensionInstallForcelist`
  (`ext-id;http://hub:9235/updates.xml` - the CRX auto-install value),
  `ExtensionInstallAllowlist`, `ExtensionInstallSources` - each with
  duplicate-skip, so re-running never churns slots;
- a real MENU: **[1] Apply HKLM** (machine-wide, every user; pops the
  UAC prompt by itself when double-clicked without admin),
  **[2] Apply HKCU** (current user, NO admin needed), **[3] Apply
  BOTH**, **[R] Remove**, **[0] Exit**;
- scriptable: `allow_extention_advprint_pro.bat HKLM|HKCU|BOTH|REMOVE`;
- asks once for the hub address (Enter = 127.0.0.1:9235; on LAN PCs
  enter the hub's IP so the policy points at the reachable URL);
- nothing is deleted in the apply path any more - Remove is explicit;
- the truncated success hint (`http://127.0`) is fixed.

---

## Verification

- `tests/test_v334.py`: 20 tests, one per fixed behaviour (uuid
  uniqueness per service, announce + unicast paths, idempotent
  set-default with a counted setter, popup change-only guard, ONE
  design surface incl. Sharing + connection icon, AUTOCRX script/
  wiring/off-Windows honesty, bat policy coverage, version coherence,
  byte-identical hub copies).
- Full suite: 602 passed, 1 skipped.
- `scripts/popup_check_v334.py` (Playwright, real Chromium): popup
  open/reload sends ZERO set-default; one real change = EXACTLY ONE
  command; same pick again = nothing; Reload + net-icon reload =
  still one; the switch reads Sharing; no JS exceptions. Screenshot:
  `scripts/popup-v334.png`.
- `scripts/build-all.sh`: CRX3 re-signed (v3.3.4, embedded copies
  verified byte-identical), extension zip, Windows Setup EXE, deb,
  SHA256SUMS.

## Files changed

- `tool/unix/hub/advprint.py` + `tool/windows/portable/hub/advprint.py`
  (byte-identical): mDNS per-service uuids, idempotent set-default,
  AUTOCRX (`ext_policy_activate` + `/extension/policy/activate` +
  `/tool` action + CLI + help), VERSION 3.3.4 / new VERSION_NAME.
- `extension/`: popup.html (the user-approved ONE design: Sharing +
  connection icon + header network icon), popup.js (change-only
  selector on the new IDs, refresh guard, net icon), background.js
  (hubSetDefault), i18n.js (en+bn strings incl. popSelectPrinter +
  Sharing), manifest.json 3.3.4.
- `tool/unix/hub/console.html` (+ embedded copies in both hub files):
  AUTOCRX "Auto-integrate (admin)" button + ACTIONS.autocrx + updated
  notes; mirrored to the windows portable hub.
- `tests/test_v334.py` (20 tests), `scripts/popup_check_v334.py` (new
  IDs + Sharing check).
- `prebuilt/allow_extention_advprint_pro.bat`: full rewrite (offline
  fallback).
- `installer/setup.nsi`: 3.3.4 naming.
- `VERSION.txt`, `README.md`, `CHANGELOG.md`, `START-HERE.txt`,
  `docs/AdvPrint-Pro-v3.3.4-A-to-Z-DEV-GUIDE.md` (new),
  `docs/RELEASE-NOTES-v3.3.4.md` (this file).
- `tests/test_v334.py` (new) + historical version pins updated.
