# RELEASE NOTES - AdvPrint Pro v3.0.0
**AdvPrint Pro (Advanced Printer) - by Bit Dream IT - Innovative Healthcare Solutions**
MIT license - 100% local - no cloud, no tracking - 2026-11-05

## 1. Why 3.0.0 (the same-version conflict, solved)

The v2.9.1 packages were already released and installed on PCs. Shipping
new content under the same 2.9.1 number would collide with those copies
(same version, different bytes - Windows Setup / deb / extension stores
cannot tell them apart). So this release ships the **identical v2.9.1
feature set under the clean new number 3.0.0**:

- No feature was added or removed - the hub, extension, installer and
  docs code is exactly the v2.9.1 code, renumbered.
- Every surface reports 3.0.0: hub `VERSION` / `VERSION_NAME` +
  dashboard badge + tray, extension manifest / popup / Options / About
  (single source = the manifest), `AdvPrint-Pro-Setup-3.0.0.exe`
  (NSIS `VIProductVersion 3.0.0.0`), `advprint-pro_3.0.0_all.deb`,
  VERSION.txt, README, CHANGELOG, Full Guide, START-HERE.
- Installs straight over 2.8.2 / 2.9.0 / 2.9.1 - settings and history
  are kept, the service is reinstalled fresh, the firewall rules are
  re-added (TCP 9235 + 9100).
- Historical code comments still say "v2.9.1 (audit fix)" on purpose:
  they record when each fix landed. The live version strings say 3.0.0.

## 2. What is inside (unchanged from v2.9.1 - summary)

- **Network printer mode**: add this PC like a real IP printer -
  IPP `http://<lan-ip>:9235/ipp/print` (Windows "Select a shared
  printer by name" + phone print services) and JetDirect RAW on TCP 9100
  ("Add a printer using TCP/IP address"). PDF, JPEG, PostScript, PCL,
  ESC/POS and ZPL payloads are routed automatically.
- **Print destination - ANY printer**: the OS default, any installed
  printer, or an upstream IP printer (RAW or IPP) via the dashboard
  "Print destination" card + `POST /ip-printer/test`; unreachable IP
  printers hold jobs (Print now overrides).
- **Responsive dashboard tables**: every column, button and option is
  visible on load - nothing hides inside an inner scroll (the fix the
  "view all option on load" report asked for).
- **Phone "Auth fail" on the Send portal QR: fixed** (the token rides
  the portal link in every token mode).
- **Security hardening**: all 27 confirmed audit findings fixed (job
  collisions, headless render isolation, DNS-rebinding, IPP/CORS,
  SSRF guards, slow-client defence, token redaction, extension Website
  API allowlist, ...).
- **base64 PDF payload chain confirmed in the field**: multi-language
  fonts and symbols print correctly - no PDF-pipeline changes.
- 212 tests pass (164 hub + 23 audit-fix + destination/IPP suite).

## 3. Files in this release

| File | What |
| --- | --- |
| `AdvPrint-Pro-Setup-3.0.0.exe` | Windows installer (bundles Python 3.11.9, UAC once, silent `/S`) |
| `advprint-pro_3.0.0_all.deb` | Debian/Ubuntu/Mint package |
| `AdvPrint-Pro-3.0.0-source.zip` | Complete source (hub, extension, installer, tests, docs) |
| `AdvPrint-Pro-v3.0.0-FULL.zip` | Portable tree + docs + prebuilt installers |
| `AdvPrint-Pro-Extension-v3.0.0.zip` | Browser extension only |
| `SHA256SUMS-3.0.0.txt` | Checksums for everything above |

## 4. Upgrade

Run the new setup over the old one (2.8.2, 2.9.0 **or the already
distributed 2.9.1** - settings and history are kept), or replace the
portable folder. On the dashboard press Ctrl+F5 once so the browser
drops the old stylesheet. The extension updates by Remove + Load
unpacked. The deb upgrades with `sudo dpkg -i
advprint-pro_3.0.0_all.deb` (3.0.0 > 2.9.1, so dpkg treats it as a real
upgrade - no same-version "already newest" refusal).

See `RELEASE-NOTES-v2.9.1.md` for the full feature/audit detail of the
feature set this release carries.
