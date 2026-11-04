# AdvPrint Pro v2.8.2 — LAN SHARING APPLIES LIVE + WINDOWS FIREWALL ONE-CLICK

**Built 2026-11-04 · by Bit Dream IT - Innovative Healthcare Solutions · MIT license · 100% local - no cloud, no tracking**

Fixes the field report: **"LAN sharing is ON, but `http://<this-PC-LAN-ip>:9235` does not answer — only `127.0.0.1` works, so how can another PC use this IP?"**

---

## 1. Why the LAN IP did not answer in 2.8.1

In 2.8.1 the dashboard's **LAN sharing** switch only *saved* the setting; the
hub's single listener stayed on `127.0.0.1:9235` until the hub process was
**manually restarted** (the dashboard even printed "RESTART the hub to
apply"). If the restart was missed, the LAN IP kept refusing connections —
even on the same PC. And on a *second* PC, Windows Defender could silently
drop inbound TCP 9235 even after a correct rebind.

## 2. What changed in 2.8.2

### 2.1 Live LAN rebind — no restart, zero downtime
- The **loopback listener (`127.0.0.1:9235`) always stays up** — the dashboard, the extension and local printing never blink.
- Toggling **LAN sharing ON** (dashboard, extension Options, or `POST /config`) starts a **second listener bound to this PC's specific LAN IP** (e.g. `192.168.1.244:9235`) **inside the same HTTP request**. Toggling OFF stops it at once.
- A specific-IP bind coexists with the loopback bind on every OS, so a failed LAN bind is only logged — **it can never take local printing down**.
- **DHCP-proof:** a watcher (every 3 s) follows LAN IP changes — if the router hands the PC a new address, the LAN listener rebinds itself and logs `[LAN] LAN IP changed ... - rebinding`.
- `/health` now reports the real state: `lan_active`, `lan_ip`, `lan_bind_ip`.
- `ADVPRINT_HOST` power users keep the old behaviour (a pinned bind is respected; the switch then says "restart to apply").

### 2.2 Windows firewall — visible, and one click to fix
- `/health` reports **`firewall_ok`** (netsh rule query, cached 30 s; `null` off-Windows).
- The dashboard LAN card shows **`Windows firewall: ALLOWED / BLOCKED / unknown`** and, when not allowed, an **Allow in firewall** button — one UAC prompt, standard netsh rule `name="AdvPrint Pro"` for the **current** port (`POST /firewall/allow`, loopback-only by design).
- New tray-menu item **"Allow LAN in firewall"** (runs in a helper thread so the tray never freezes behind the UAC dialog).
- The installer already added the rule since 2.8.0; now a removed rule (port change, cleanup tool) is **detected and flagged** instead of failing silently.

### 2.3 Test LAN — answers "which side is broken?" in one click
- New **`GET /lan/selftest`**: the hub connects to **its own LAN URL** and reports PASS/FAIL with the exact reason.
- Dashboard button **Test LAN** in the same row. Interpretation:
  - **PASS + another PC still cannot connect → it is the firewall** (click *Allow in firewall*);
  - **FAIL → listener problem** (hub.log says exactly why).

### 2.4 Dashboard copy rewritten
- No more "RESTART the hub to apply" — enabling now says: *"LAN sharing ON - other PCs can connect RIGHT NOW (no restart needed)."*
- If a bind fails, the card shows the honest error text instead of pretending.

## 3. API additions

| Endpoint | Description |
| --- | --- |
| `GET /lan/selftest` | Server-side LAN check (token required): PASS/FAIL + reason |
| `POST /firewall/allow` | One-click Windows firewall rule for the hub port (loopback-only, one UAC prompt) |
| `POST /config` (share_lan) | Now applies **live**; response carries `"lan":{"rebound":true,"lan_error":null}` |

## 4. Nothing removed

Every v2.8.1 feature (send-portal QR for phones, one-click LAN invite,
DropZone, dual hub profiles, Restart, window.print switch, close-tab switch)
is unchanged. Upgrade paths: run `AdvPrint-Pro-Setup-2.8.2.exe` over the old
install, or `sudo dpkg -i advprint-pro_2.8.2_all.deb`.

## 5. Immediate relief for a running 2.8.1 hub

If you stay on 2.8.1 for a moment: after toggling LAN sharing, **restart the
hub once** (tray icon → *Restart hub*), and check the firewall rule:

```
netsh advfirewall firewall add rule name="AdvPrint Pro" dir=in action=allow protocol=TCP localport=9235
```

Then `http://192.168.1.244:9235` answers from every PC/phone on the same
network. 2.8.2 removes the restart step entirely.

## 6. Quality gates

- **pytest: 150 passed** — including 4 new v2.8.2 tests:
  `test_v282_share_lan_applies_live` (binds a real second listener, verifies HTTP answers on the LAN IP, then tears it down),
  `test_v282_firewall_route_loopback_ok`, `test_v282_health_has_lan_diagnostics`, `test_v282_dashboard_has_live_rebind_ui`.
- `py_compile` clean on hub + tray; setup.nsi bumped to VI 2.8.2.0.

---
AdvPrint Pro (Advanced Printer) — by Bit Dream IT - Innovative Healthcare Solutions — MIT license — 100% local - no cloud, no tracking
