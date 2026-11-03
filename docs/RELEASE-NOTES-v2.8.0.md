# AdvPrint Pro v2.8.0 — Release Notes

**AdvPrint Pro (Advanced Printer) — by Bit Dream IT - Innovative Healthcare Solutions — MIT license — 100% local, no cloud, no tracking.**

v2.8.0 delivers the ten requested features in one release, on top of the working v2.7.0 baseline. **Nothing was removed** — the v2.7.0 history manager, Share Receive/Send toggles and the live test tool are unchanged.

---

## 1. Two hub profiles — Self PC + LAN PC (share-send routing)

The extension now keeps **two complete hub profiles**:

| Profile | Where | Used when |
|---|---|---|
| **Self PC** (`hubUrl` + `token`) | Options → Settings → **Connection 1 - Self PC (this computer)** | Share Send Mode **OFF** (default) |
| **LAN PC** (`hubUrlLan` + `hubTokenLan`) | Options → Settings → **Connection 2 - LAN PC (share-send target)** | Share Send Mode **ON** |

- The popup **Share Send Mode** toggle is the routing switch: **ON → every print job goes to the LAN PC hub; OFF → jobs print on this PC's own hub.**
- The popup status line names the active target ("Printing on LAN PC - hub v2.8.0"); Recent jobs and Pause/Resume follow the active target.
- If Share Send is turned ON with no LAN PC configured, the popup opens Options right at the LAN PC section and asks for URL + token. The **Connect** button verifies reachability *and* the token before you rely on it.
- Management calls (config, debug, token auto-heal) always talk to the Self PC hub; the LAN token is never "auto-fixed" from this PC (that is impossible remotely — copy the token from the LAN PC's dashboard or `python advprint.py token` there).
- Retry-parked jobs are flushed to the target that is active when the hub comes back.

## 2. Share Receive Mode (this PC takes jobs from other PCs)

Unchanged mechanism, clearer placement: **Share Receive Mode** (popup or Options → LAN / PCs) is the hub-side `share_lan` switch — when ON, this hub listens on the LAN (`0.0.0.0:9235`) and other PCs (extension or send portal) print through this PC's printers. Receiving is configured **on the PC that owns the printer**; a sender only needs the URL + token (Connection 2 on the sender). v2.8.0 adds the firewall rule automatically during setup.

## 3. window.print() on/off — one click in the popup

The popup's **Power** section has a new **window.print() hook** switch (same setting as Options → Behavior → *Intercept window.print()*). ON: web apps that call `window.print()` (or Ctrl+P) print silently through the hub. OFF: pages use the normal browser print dialog again. Bangla + English strings included.

## 4. Dashboard + Audit log — Self and LAN managed separately

Four buttons in Options → Settings:

- **Open dashboard - Self PC** / **Open audit log - Self PC**
- **Open dashboard - LAN PC** / **Open audit log - LAN PC**

Each opens the right hub with the right token. The popup footer **Dashboard** link opens the **active** target (LAN PC while Share Send is on).

## 5. Close tab after auto-print — default OFF

`closeAfterPrint` now defaults to **false**: auto-printed URLs keep their tab open like any normal page. Turn it on in Options → Behavior → *Close tab after auto-print (default OFF)* if you want the zero-browser-view flow. Existing installs that explicitly enabled it keep it.

## 6. DropZone + Send portal — printing WITHOUT the extension

This is the "MS Word print share" feature, done 100% locally:

- **DropZone** (dashboard card + `GET /dropzone`): the hub watches a folder (default `<data dir>\DropZone`, configurable + optional delete-after-print). In Word / Excel / ANY Windows app: **Print → Microsoft Print to PDF → save into the DropZone** — AdvPrint prints the page seconds later and moves the PDF to `done\`. Live on/off switch; the watcher re-reads the config every poll, no restart needed. `POST /dropzone/open` opens the folder on the hub PC.
- **Send portal** (`GET /send`): a small upload page served by the hub — any phone, tablet or PC on the LAN can print a PDF through this PC's printers. Same token auth as every endpoint; `POST /send` accepts multipart (`curl -F file=@report.pdf`), a raw `application/pdf` body or JSON `pdf_base64`. 25 MB cap, PDF-magic check, audit-logged.

## 7. Restart hub — tray, tool and dashboard

- **Tray menu → Restart hub**: the hub relaunches itself as a NEW process and exits the old one. The new process waits (up to 12 s) for the old listener to release the port (`ADVPRINT_RESTART=1`), so the single-instance guard never fights the restart.
- **AdvPrint Tool → [14] Restart AdvPrint** (+ CLI `tool.py restart`): POSTs `/restart`, then polls until the hub answers again and prints the new version.
- **Dashboard → Restart hub button**: restart + automatic page reload when `/health` is back. Queued jobs, settings and history are kept; the restart is audit-logged (`hub.restart`).

## 8. Bullet-proof upgrade & uninstall (the "some file abort install" fix)

Root cause of the v2.7.x pain: the optional **AdvPrint** service (and a just-restarted hub) kept `runtime\*.exe`/DLLs locked while Setup tried to overwrite them, so some files aborted mid-install and the service survived uninstall.

The v2.8.0 setup runs **`hub-stop.ps1` before touching a single file**:

1. Stops the *AdvPrint* service (polite stop → 10 s wait → **PID kill** if stuck in STOP_PENDING).
2. **Deletes the service registration** (`sc delete AdvPrint`) so no half-dead service survives an upgrade — and `.onInit` pre-ticks the service section when the service existed, so it is **reinstalled fresh automatically**.
3. Kills every process whose image lives under the install folder, anything listening on TCP 9235, and the renamed hub images (`AdvPrintPro.exe`, `PrintHubPro.exe`).
4. Setup then **wipes the old `hub\`, `install\`, `extension\`, `docs\` and `runtime\` folders** before copying the new payload — no stale file can abort or shadow the new version.
5. The uninstaller uses the same stop script, removes the firewall rule, and **retries the folder sweep 3×**; if antivirus still holds files it says so plainly instead of leaving silent junk (no more Revo Uninstaller needed).

`service-remove.ps1` got the same hardening (verify + force removal + honest "marked for deletion, gone after reboot" message), and the portable `UNINSTALL-WINDOWS.bat` now stops/removes the service and the firewall rule too.

## 9. Silent install on any PC ("auto permission")

- `AdvPrint-Pro-Setup-2.8.0.exe /S` installs silently; the exe **requests administrator elevation via its manifest**, so Windows shows the UAC prompt by itself — on any PC, no manual right-click.
- After a silent install the hub **auto-starts** (no Finish page click needed).
- Setup adds the **firewall rule for LAN sharing** (`AdvPrint Pro`, TCP 9235, in) and removes it on uninstall.
- Silent uninstall: `uninstall.exe /S` (no interactive popups).

## 10. New A + printer logo

The mark is the letter **A drawn as a printer**: the crossbar is the output slot and a **printed page (two blue text lines) slides out of it** — one silhouette that reads as both "A" and "printer". Generated as crisp multi-size assets: extension icons (16/32/48/128), tray + installer `.ico` (16…256), dashboard/popup inline SVG, and a new 440×280 promo tile.

---

## For upgraders

- Install `AdvPrint-Pro-Setup-2.8.0.exe` over the old version — settings, history and the token are kept in `%USERPROFILE%\.advprint`. The service (if installed) is stopped, removed and reinstalled automatically; the hub auto-starts.
- The extension: `chrome://extensions` → AdvPrint Pro → **Reload** (files were updated on disk by the setup), or re-**Load unpacked** from the refreshed `$INSTDIR\extension` folder.
- New config keys (`drop_enabled`, `drop_dir`, `drop_delete`) appear automatically with safe defaults; nothing to migrate.

## Files in this release

| File | What |
|---|---|
| `AdvPrint-Pro-Setup-2.8.0.exe` | Windows setup (per-machine, UAC, silent `/S`, bundled Python 3.11.9 runtime) |
| `advprint-pro_2.8.0_all.deb` | Linux deb (hub + tool, systemd optional) |
| `AdvPrint-Pro-v2.8.0-FULL.zip` | Portable: hub + tool + extension + docs (no install needed) |
| `AdvPrint-Pro-2.8.0-source.zip` | Complete source (MIT) |
| `AdvPrint-Pro-Full-Guide.pdf / .html` | The A-to-Z guide, updated for v2.8.0 |
| `SHA256SUMS.txt` | Checksums of every artifact |

**Known non-issues (unchanged):** a stale `start pending` in services.msc after choosing Startup-app mode is a display artifact (services.msc → Restart, or pick ONE of Startup-app / service); two `canceled` rows right after install are the livetest's internal DB check; old `dead` jobs stay visible until Clear history.
