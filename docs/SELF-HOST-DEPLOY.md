# Self-Host Deployment: silent extension install via `ExtensionInstallForcelist`

**v3.0.7** — AdvPrint Pro (Advanced Printer) by Bit Dream IT - Innovative Healthcare Solutions

This is the "one download does everything" release. The browser extension is
packed as a **signed .crx**, the installers write Chrome's enterprise
**force-install policy**, and the hub itself serves the package so the browser
**updates the extension silently on every new release**. Nothing is dragged
onto `chrome://extensions` and nothing is downloaded from the Web Store.

---

## 1. How the chain works

```
 AdvPrint-Pro-Setup-3.0.7.exe / advprint-pro_3.0.7_all.deb
   |
   |-- installs the hub (+ ships AdvPrint-Pro.crx inside hub folder)
   |-- writes the browser policy:
   |     Windows : HKLM\SOFTWARE\Policies\<vendor>\<browser>\ExtensionInstallForcelist
   |               value "1" = likldbkamojokkfdlcjibiljpgbbnohc;http://127.0.0.1:9235/extension/updates.xml
   |     Linux   : /etc/{opt/chrome,chromium,opt/edge,brave}/policies/managed/advprint-pro.json
   |
   '-- starts the hub, which serves (open GET endpoints):
         /extension/updates.xml        <- Chromium update manifest (gupdate 2.0)
         /extension/AdvPrint-Pro.crx   <- the SIGNED package
         /extension/info               <- JSON (ID, version, policy value)

 Chrome starts -> reads the policy -> fetches updates.xml -> downloads the .crx
 -> verifies the signature against the policy's extension ID -> installs SILENTLY.
 Later: hub release with version 3.0.8 -> updates.xml says 3.0.8 -> Chrome
 auto-updates with no prompt (IDs match, so it is the "same" extension).
```

The policy value has two halves separated by `;`:

- **extension ID** — `likldbkamojokkfdlcjibiljpgbbnohc`, 32 letters. It is
  derived from the **release signing key** (`extension-signing/advprint-printer.pem`)
  and is **permanent**. The browser only force-installs a package whose
  signature produces exactly this ID — that is how it "knows which extension".
- **update URL** — where the browser fetches the update manifest. The hub
  builds the `.crx` URL inside the XML from the request's own Host header, so
  the port is always correct.

## 2. What is on each machine after a default install

| Piece | Windows (Setup exe) | Linux (deb) |
| --- | --- | --- |
| Hub + .crx | `%ProgramFiles%\AdvPrintPro\hub\extension\AdvPrint-Pro.crx` | `/opt/advprint/hub/extension/AdvPrint-Pro.crx` |
| Policy (machine-wide) | `HKLM\...\ExtensionInstallForcelist` (5 browsers) | `/etc/*/policies/managed/advprint-pro.json` |
| Policy (per-user, dashboard button) | `HKCU\...\ExtensionInstallForcelist` | — |
| Uninstall removes | our policy values only | our JSON files only |

The Setup writes **HKLM** (machine, all users, it already runs elevated). The
dashboard card writes **HKCU** (this user, no elevation) — use it when Chrome
was installed after Setup, the hub port changed, or you are not an admin.
The install is **append-safe**: it takes the first free `1..n` slot and never
touches another company's force-installed entries.

## 3. Scenario A — one PC, one download (the easy default)

1. Download **one** file: `AdvPrint-Pro-Setup-3.0.7.exe` (Windows) or
   `advprint-pro_3.0.7_all.deb` (Linux).
2. Install. The policy is written, the hub starts, the extension installs
   silently (see the honest limits below).
3. Check: `chrome://extensions` shows **AdvPrint Pro** with the
   "installed by your administrator" badge; `chrome://policy` shows
   `ExtensionInstallForcelist`.
4. Every future hub release updates the extension by itself.

## 4. Scenario B — schools / workplaces (your own web server)

You do not have to use the hub PC as the update server. Host the **two files**
from `AdvPrint-Enterprise-Deploy-Kit` on any web server you already have
(internal IIS/nginx, GitHub Pages, any free static host):

| File | What it is |
| --- | --- |
| `AdvPrint-Pro.crx` | the signed package (never regenerate the key!) |
| `updates.xml` | update manifest — edit the `codebase` URL to your server |

**Steps**

1. Upload both files, e.g. `https://your-server/advprint/`.
2. Edit `updates.xml`: `codebase='https://your-server/advprint/AdvPrint-Pro.crx'`.
3. Point the policy at your XML on every managed machine (GPO, Intune, MDM,
   or a one-time .reg import — templates are in the kit):
   - Chrome: `HKLM\SOFTWARE\Policies\Google\Chrome\ExtensionInstallForcelist`
   - Edge: `HKLM\SOFTWARE\Policies\Microsoft\Edge\ExtensionInstallForcelist`
   - Brave: `HKLM\SOFTWARE\Policies\BraveSoftware\Brave\ExtensionInstallForcelist`
   - Chromium: `HKLM\SOFTWARE\Policies\Chromium\ExtensionInstallForcelist`
   - Vivaldi: `HKLM\SOFTWARE\Policies\Vivaldi\ExtensionInstallForcelist`
   - value `1` = `likldbkamojokkfdlcjibiljpgbbnohc;https://your-server/advprint/updates.xml`
   - Linux JSON: `{"ExtensionInstallForcelist":["likldbkamojokkfdlcjibiljpgbbnohc;https://your-server/advprint/updates.xml"]}` in `/etc/opt/chrome/policies/managed/advprint-pro.json`
4. Restart the browser on the clients (or `chrome://policy` → *Reload policies*).
   The extension appears, silent, unremovable by users.
5. **Every future release**: upload the new `.crx`, keep the same file name,
   raise `version='3.0.8'` in `updates.xml`. Done — every client updates
   automatically within a few hours or at next browser start.

**Server requirements (the two classic traps)**

- The server must send the `.crx` with header
  **`Content-Type: application/x-chrome-extension`** — otherwise Chromium
  downloads it and silently refuses to install (Microsoft documents this for
  Edge policy deployments; same engine). IIS: add a MIME map for `.crx`.
  nginx: `types { application/x-chrome-extension crx; }` or
  `default_type application/x-chrome-extension;` in that location.
- The manifest must be valid XML with the exact same appid, and the version
  must be numeric (`3.0.7`), never `3.0.7-beta`.

## 5. Honest limits (per browser)

| Machine | Chrome | Edge | Brave | Chromium | Vivaldi |
| --- | --- | --- | --- | --- | --- |
| Windows, **domain-joined / enrolled** (school, workplace) | silent ✔ | silent ✔ (AD-joined) | silent ✔ | silent ✔ | silent ✔ |
| Windows, **normal home PC** | policy written but **ignored** (off-store force-install is blocked) | ignored | varies | varies | varies |
| **Linux** (any machine) | silent ✔ | silent ✔ | silent ✔ | silent ✔ | silent ✔ |
| macOS | needs MDM/DDM management | needs MDM | — | — | — |

Google and Microsoft deliberately block silent off-store installs on
unmanaged Windows machines — that restriction is theirs, not ours. Home users
keep the classic path: `chrome://extensions` → *Developer mode* → *Load
unpacked* → the `extension/` folder that still ships inside the install
directory. On **Linux there is no restriction at all**: the deb policy
installs silently everywhere.

## 6. Verify & troubleshoot

| Symptom | Check | Fix |
| --- | --- | --- |
| Extension not in `chrome://extensions` | `chrome://policy` lists the policy? | No → policy not written (wrong browser path / not restarted). Yes → see next row |
| Policy listed, still not installed | `curl -I http://127.0.0.1:9235/extension/AdvPrint-Pro.crx` | `Content-Type` must be `application/x-chrome-extension`; hub not running → start it |
| `ERR_NAME_NOT_RESOLVED` in update checks | Host unreachable from the client | Use `127.0.0.1` on the hub PC, the LAN IP from other PCs (firewall rule is installed), or your own web server |
| Extension installs but no updates | `updates.xml` `version=` older than installed | Raise it; Chrome checks every few hours and at every browser start |
| "Extensions installed by policy" removal attempts fail | expected | force-installed extensions cannot be removed by users — uninstall AdvPrint Pro / remove the policy instead |
| Dashboard card shows nothing served | the `.crx` is missing | reinstall, or drop `AdvPrint-Pro.crx` into `hub\extension\` (hot-swapped, no restart) |

## 7. For AdvPrint developers: releasing a new version

1. Bump `manifest.json` `version` (numeric only) and the hub `VERSION`.
2. Repack: `python3 tool/crx3.py pack extension extension-signing/advprint-printer.pem prebuilt/AdvPrint-Pro.crx`
   - the SAME pem → same ID → updates keep flowing; **never regenerate** it.
3. Build the installers (`scripts/build_307.sh`): the .crx rides inside the
   Setup exe and the deb, and lands in the hub's `extension/` folder.
4. The hub re-reads the package when its file changes — a server admin can
   even drop a newer `.crx` onto a live hub without restarting it.
