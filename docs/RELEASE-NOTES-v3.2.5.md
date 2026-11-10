# AdvPrint Pro v3.2.5 — RELEASE NOTES
**Six user-reported bugs, all fixed, all tested.**
by Bit Dream IT - Innovative Healthcare Solutions · 100% local · no cloud

Base: v3.2.4 - every feature unchanged (the toolbar popup, ONE UI ONE
BUTTON, Allowed IPs, branding-only options page). v3.2.5 fixes exactly
what you reported and adds the verification to prove it.

---

## BUG 1 — "Set Default" never saved (Windows flipped it back)

**You said:** *Always Default Printer of windows selected even set
selected Printer set as default — why auto change to windows default
when Hub set other printer as default, why not save it.*

**Root cause:** the old button only wrote the hub's own config key.
Windows kept ITS default, and the Windows 10/11 factory feature
**"Let Windows manage my default printer"** silently re-pointed the
default at the last-printed printer — so your choice looked lost.

**Fixed:** the Set Default button now performs the real OS-level change:

1. disables the auto-manage feature first
   (`HKCU\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Windows →
   LegacyDefaultPrinterMode = 1` — the per-user equivalent of turning
   OFF "Let Windows manage my default printer" in Settings; no UAC);
2. sets the default via `WScript.Network.SetDefaultPrinter("<name>")`;
3. reads the default back and reports success only when it VERIFIES;
4. keeps the hub destination key in sync (Printers → Print destination
   follows).

On Linux/CUPS the hub runs `lpoptions -d <name>` (per-user default).
The toast now tells the truth: *"Windows default printer is now '…'
(auto-manage disabled: LegacyDefaultPrinterMode=1)"*.

> If you ever want Windows to manage the default again:
> Settings → Bluetooth & devices → Printers & scanners → turn ON
> "Let Windows manage my default printer" — then the hub card shows
> the OS default but does not fight it.

## BUG 2 — Job History: selection wiped by auto-refresh + missing actions

**You said:** *Job History select it auto refresh not select. also clear
selected option need, reprint and cancel print individual also need.*

**Fixed (all four asks):**
- **Selection survives the 3 s auto-refresh** — ticked rows stay ticked
  (`histSel` re-applied on every render);
- **Clear selected** — unticks everything (never touches the jobs);
- **Reprint selected** and a live **"n selected"** counter were already
  there, now they stay usable while the poll runs;
- **Cancel individual** — every queued / held / printing history row
  shows a red **Cancel** button (finished rows keep **↻ Reprint**);
- **Cancel selected** — cancels every ticked job; already-finished ones
  are skipped and counted honestly ("2 job(s) canceled (1 already
  finished)");
- the header checkbox is a real **select-all** for visible rows.

## BUG 3 — Live Queue: checkboxes like History

**You said:** *Queue check box → like History so clear cancel individual
and selected also.*

**Fixed:** the queue table now has the full set — checkbox column,
header select-all, per-row **Cancel** / **⚡ Release** / **↻ Retry** /
**↻ Reprint** (by status), **✖ Cancel selected** and **⌦ Clear
selected** with a live counter, and the selection survives the poll.

## BUG 4 — "Is ipp://10.26.94.206:9235/ipp/print/hp-laser-103-107-108 workable?"

**You said:** *are you sure ipp/print/ printer name is it work able or
not check.*

**Checked — YES, it works.** The hub resolves the queue name three ways,
case/punctuation-insensitively (`_ipp_queue_match`):

| what a client types | resolves to |
|---|---|
| `ipp://10.26.94.206:9235/ipp/print/hp-laser-103-107-108` (slug) | HP Laser 103 107 108 |
| `ipp://10.26.94.206:9235/ipp/print/HP%20Laser%20103%20107%20108` (URL-encoded raw name) | HP Laser 103 107 108 |
| `ipp://10.26.94.206:9235/ipp/print/HP-Laser-103-107-108` (dashes) | HP Laser 103 107 108 |

Verified live in this release: GET of both URL forms returns the
per-queue landing page ("Add it as a printer - do not open it in a
browser", shows the exact ipp:// URL + current printer state), the IPP
POST queue routes the job to exactly that printer, and an unknown queue
answers HTTP 404 with "unknown per-printer IPP queue - see GET
/printers". The URL on every printer card comes from the hub itself, so
card, landing page and this document always agree.

**How to add on a child PC / phone:** Settings → Printers & scanners →
Add device (mDNS announces it) — or Add manually → "Select a shared
printer by name" → paste the ipp:// URL from the card.

## BUG 5 — "policy install failed: HTTP 200"

**You said:** *policy install failed: HTTP 200. how fix work able this
feature how apply details also.*

**What actually happened:** the hub answered `{ok:false, message:"…"}`,
but the console showed a blind "HTTP 200" and swallowed the reason.

**Fixed on three layers:**
1. the console `api()` helper now surfaces the server's real message
   (`error → message → HTTP status`);
2. the hub tries `reg add` first and falls back to PowerShell
   `New-ItemProperty` when reg.exe is blocked by AV/app-control suites;
3. every policy response carries an honest `error` field plus a
   per-browser report ("written (HKCU entry N)" / "write failed…").

### Force-install policy — how to apply (details)

What it does: writes the Chromium
`ExtensionInstallForcelist` policy so Chrome / Edge / Brave / Chromium /
Vivaldi install and pin the AdvPrint Pro extension
(`<ext-id>;http://127.0.0.1:9235/extension/updates.xml`).

**One click (recommended):** Hub console → **Extension** tab →
**Policy install** (per-browser buttons + Apply HKCU / Apply HKLM).

**What a success looks like:**
- toast: *"HKCU policy written for 5 browser(s) - restart the browser
  once, then chrome://policy shows it"*
- verify: open `chrome://policy` → **Reload policies** →
  `ExtensionInstallForcelist` shows the value
  `<ext-id>;http://127.0.0.1:9235/extension/updates.xml`;
- `chrome://extensions` shows the extension as
  *"Installed by your administrator"* (no Remove button — by design).

**Important honesty about Chrome:** silent off-store force-install only
works on **managed machines** (domain-joined / enrolled, or a machine
already applying other policies). On a normal home PC, Chrome ignores
the forcelist for unknown sources — in that case use
`chrome://extensions → Developer mode → Load unpacked` (the
`extension/` folder) or drag the signed `AdvPrint-Pro.crx` onto that
page in Edge/Brave. The policy does no harm there; it simply activates
when the PC becomes managed.

**If the toast still reports a failure, it now tells you why:**
- *"HKLM write failed … needs an admin console"* → HKLM is machine-wide
  and needs elevation. Use **HKCU** (per-user, no UAC) or run the
  console once as administrator.
- *"reg.exe AND PowerShell blocked"* → an AV / App-Control is guarding
  policy keys. Apply manually (below), then whitelist AdvPrint Pro.

**Manual apply (works everywhere, no hub needed):** save as
`advprint-policy.reg` and double-click it (replace `<ext-id>` with the
id from `chrome://extensions` after a dev-load, e.g.
`likldbkamojokkfdlcjibiljpgbbnohc` for the repo-signed CRX):

```reg
Windows Registry Editor Version 5.00

[HKEY_CURRENT_USER\SOFTWARE\Policies\Google\Chrome\ExtensionInstallForcelist]
"1"="<ext-id>;http://127.0.0.1:9235/extension/updates.xml"

[HKEY_CURRENT_USER\SOFTWARE\Policies\Microsoft\Edge\ExtensionInstallForcelist]
"1"="<ext-id>;http://127.0.0.1:9235/extension/updates.xml"

[HKEY_CURRENT_USER\SOFTWARE\Policies\BraveSoftware\Brave\ExtensionInstallForcelist]
"1"="<ext-id>;http://127.0.0.1:9235/extension/updates.xml"
```

Restart the browser → `chrome://policy` → Reload policies.
Machine-wide (all users, needs admin): put the same entries under
`HKEY_LOCAL_MACHINE\...` or push them with GPO / `gpedit.msc`
(Administrative Templates → Google Chrome → Extensions →
"Configure the list of force-installed apps and extensions" → Enabled →
paste `<ext-id>;http://127.0.0.1:9235/extension/updates.xml`).

**Linux:** no registry — the DEB installs
`/etc/chromium/policies/managed/advprint-pro.json` (plus the Google/
Edge/Brave twins) at package install time; check that file.
**Remove:** Extension tab → Policy remove (deletes exactly our entries)
or delete the registry values / the JSON file.

## BUG 6 — Start with Windows: tray ON but UI OFF (and it refused to act)

**You said:** *Start with Windows is managed by the service/tray (use
the Hub tools) — when in tray it show checked but ui it show no check,
it also has bug.*

**Root causes (two):** the UI read a config.json key the hub never
wrote (so it always showed OFF), and the switch refused with a toast
instead of doing anything.

**Fixed:** the Settings switch now reads the REAL Startup-folder state
from `/health` (the same source the tray icon uses) and actually
toggles it via `POST /autostart` — ON creates
`shell:startup\AdvPrint Pro.lnk` (visible in Task Manager → Startup
apps, with the AdvPrint icon), OFF removes it. The hub rebuilds its
health snapshot immediately, so the switch cannot flip itself back.
Tray icon, console switch and Task Manager now always agree.

---

## What else is in v3.2.5

- `POST /printers/set-default` added to the API (`docs/API.md`);
- audit event `printers.set_default` records every default change
  (who → which printer → verified/failed);
- the hub ships ONE embed pipeline: `console.html` → `CONSOLE_HTML`
  constant (stale UI impossible if you follow the build flow);
- new tests: `tests/test_v325.py` (19 locks) + live Playwright
  verification `scripts/render_v325.py`; full suite **366 passed,
  1 skipped**;
- SHA256SUMS-3.2.5.txt covers all FOUR artifacts (CRX, extension zip,
  DEB, Setup EXE) - the v3.2.4 build script still had the v3.2.2 bug
  where the Setup-EXE line silently vanished (the existence check
  looked in the wrong folder); fixed and locked by a test.

## Files (dist/)

| File | What |
|---|---|
| `AdvPrint-Pro-Setup-3.2.5.exe` | Windows installer (silent: `/S`) |
| `advprint-pro_3.2.5_all.deb` | Linux DEB (hub + policy JSON + autostart) |
| `AdvPrint-Pro.crx` | signed extension (CRX3, repo key) |
| `AdvPrint-Pro-Extension-3.2.5.zip` | unpacked extension (Load unpacked / store upload) |
| `SHA256SUMS-3.2.5.txt` | checksums of all of the above |

100% local · no cloud. AdvPrint Pro by Bit Dream IT - Innovative
Healthcare Solutions.
