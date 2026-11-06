# Release notes - AdvPrint Pro v3.0.7

**Self-host extension auto-install: one download, the browser extension installs itself (.crx + ExtensionInstallForcelist + updates.xml)**

AdvPrint Pro (Advanced Printer) by Bit Dream IT - Innovative Healthcare Solutions
MIT license - 100% local - no cloud, no tracking

## The question this release answers

*"Self-host using 'Extension Install Force-list' (for schools/workplaces):
host the packed .crx file and a small XML manifest file on your own web
server. Is it possible that when the tool exe installs, it auto-installs the
extension in the browser too — so only one exe or deb download auto-installs
the extension, and the extension ships as .crx with auto-update on every
version?"*

**Yes — and it now ships exactly like that.** This release adds the whole
self-host chain to the product itself:

1. The extension is packed as a **signed CRX3 package** with a **permanent
   release key** — the extension ID `likldbkamojokkfdlcjibiljpgbbnohc` is
   derived from the key and will never change.
2. The **Setup exe and the deb write Chrome's enterprise force-install
   policy** (`ExtensionInstallForcelist`) pointing at the hub's own update
   manifest.
3. The **hub serves the package** at `/extension/updates.xml` +
   `/extension/AdvPrint-Pro.crx`.
4. Chrome/Edge/Brave install the extension **silently** and **auto-update it
   on every newer release** — same ID + higher version in the manifest is
   exactly the signal Chromium uses.
5. For schools/workplaces the **Enterprise-Deploy-Kit** hosts the same two
   files on any web server with GPO/Intune/.reg templates.

## 1. The stable signing key = the stable ID

`extension-signing/advprint-printer.pem` (RSA-2048, kept in the tree, never
regenerated) signs every release. The ID is `sha256(public key)[0:16]` with
every hex nibble mapped to letters a–p — the Chromium rule. Because the key
never changes:

- the policy entry never goes stale,
- every new `.crx` is accepted as the SAME extension,
- updates flow silently with zero user interaction.

The packer (`tool/crx3.py`, pure Python, shipped in the tree) was verified
byte-for-byte against Chrome's own `--pack-extension` output for the same
key: identical header structure, identical signature scheme (RSA-PKCS1v15
over `CRX3 SignedData` + header-length + header + zip).

## 2. The hub is now also an extension update server

Open GET endpoints (Chrome's updater cannot send our token; the usual
Host-header rule — localhost / LAN IP only — still applies):

| Endpoint | What it serves |
| --- | --- |
| `/extension/updates.xml` | Chromium update manifest (gupdate 2.0): appid + `codebase` (built from the request Host, so the port is always right) + `version` read from the package |
| `/extension/AdvPrint-Pro.crx` | the signed package — with the **required** `Content-Type: application/x-chrome-extension` (missing it = policy installs silently fail) |
| `/extension/info` | JSON: ID, served version, updates/crx URLs, the exact policy value |
| `/extension` | small landing page for IT admins to verify from a browser |

The package is parsed once and re-parsed when the file changes: dropping a
newer `.crx` into `hub\extension\` updates every Chrome **without touching
the hub**. `/health` now carries `"extension": {"served", "id", "version"}`.

## 3. The installers do the policy work

- **Windows Setup (NSIS)**: new section *"Silent extension install in
  Chrome/Edge/Brave (policy)"* writes the machine-wide (HKLM) forcelist for
  **Chrome, Edge, Brave, Chromium, Vivaldi** — append-safe (enumerates the
  existing entries, reuses our slot if present, otherwise takes the first
  free `1..n`, never touching another company's entries). The slot names are
  recorded under `HKLM\Software\AdvPrintPro` and the uninstaller removes
  exactly our entries. The signed `.crx` ships inside the hub folder.
- **install-windows.bat** (portable): writes the per-user (HKCU) twin — no
  admin needed.
- **Dashboard card "Browser extension - silent install"**: shows the served
  ID + version, one-click **check / write / remove** of the per-user policy
  (repair after a port change or a late Chrome install), copies the
  `updates.xml` URL, and states the honest expectation in plain English.
  Backed by token-gated `/extension/policy/status|install|remove` endpoints.
- **deb**: ships `/opt/advprint/hub/extension/AdvPrint-Pro.crx`; postinst
  writes `/etc/{opt/chrome,chromium,opt/edge,brave}/policies/managed/advprint-pro.json`,
  prerm removes them (removing the policy auto-uninstalls the extension at
  the next browser start). `install-unix.sh` / `uninstall-unix.sh` do the
  same for tarball users (root or passwordless sudo).

## 4. Enterprise-Deploy-Kit (schools / workplaces)

`AdvPrint-Enterprise-Deploy-Kit/` (also zipped) contains everything an IT
admin needs to host the extension on their own server:

- `AdvPrint-Pro.crx` — the signed package
- `updates.xml` — ready template (edit one URL)
- `make-updates-xml.py` — regenerates the manifest for any URL/version
- `forcelist-chrome.reg` / `forcelist-edge.reg` — HKLM import templates
- `chrome-policy-linux.json` — managed-policy template
- `DEPLOY-GUIDE.md` — the 5-minute walkthrough (upload, one URL edit, one
  registry key / GPO / Intune setting, the Content-Type trap)

Full documentation: **docs/SELF-HOST-DEPLOY.md** in this package.

## 5. The honest limits (please read once)

| Machine | Silent install |
| --- | --- |
| Windows, domain-joined / enrolled (school, workplace) | **works** — exactly the scenario you asked about |
| Windows, normal home PC | Chrome/Edge **ignore** silent off-store install (Google/Microsoft policy, not ours). Use the classic `chrome://extensions` → *Load unpacked* — the `extension/` folder still ships, and the dashboard card explains it |
| Linux, any machine | **works** — no domain requirement |
| macOS | needs MDM management (documented) |

## 6. Verify it worked (30 seconds)

1. `chrome://policy` → `ExtensionInstallForcelist` shows
   `likldbkamojokkfdlcjibiljpgbbnohc;http://127.0.0.1:9235/extension/updates.xml`
2. `chrome://extensions` → AdvPrint Pro with the "installed by your
   administrator" badge
3. Print a test from the popup — done.

## 7. Version

- Extension manifest, hub, Setup exe, deb, docs: **3.0.7**
- Extension functionality unchanged from 3.0.6 (content rules, 9-tab
  Options, power switches) — this release is the deployment layer.
