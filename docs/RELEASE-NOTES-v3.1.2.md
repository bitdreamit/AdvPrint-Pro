# v3.1.2 — PREMIUM GRAPHICAL WINDOW + CENTER MODE (2026-11-09)

**AdvPrint Pro (Advanced Printer)** by **Bit Dream IT - Innovative Healthcare Solutions**
Base: v3.0.9 — every previous feature ships unchanged.

## 1) THE ONE UI — console.html at /ui

`http://127.0.0.1:9235/ui?token=...` — a Windows-IDM style console
(blue gradient title bar, glossy toolbar, category sidebar, segmented
status bar) with **8 live tabs**:

| Tab | Live data / actions |
|---|---|
| Dashboard | jobs today, printed/failed 7d, queue, hub status, LAN, IPP, mDNS, recent jobs |
| Printers | every printer card, status, per-printer IPP URL + copy, Set default |
| Jobs | live queue with progress, filters, print-now / retry / cancel |
| Audit | full trail, CSV export |
| IPP Printer | every per-printer queue `ipp://ip:9235/ipp/print/<printer>` + copy all + add-steps for Windows / CUPS / phones |
| Extension | token, CRX + updates.xml links, force-install policy line, browser activity |
| Settings | live switches: LAN sharing, per-printer IPP, mDNS, queue mode, hold offline, instant fallback, debug; default printer; keep jobs |
| Logs | hub self-check + live activity feed (hub.log pointer) |

Same auth as the dashboard. Served from disk (`console.html` next to
`advprint.py`) so the installer/DEB payload ships it; a readable
fallback page if the file is missing. Tests: `tests/test_ui_console.py`.

## 2) gui_app v2 — the native window wraps THE ONE UI

New `gui_app.py` in the hub folder. Backend ladder, first available wins:

1. **pywebview** (WebView2 on Windows / WebKitGTK / Cocoa) — `pip install pywebview`
2. **Qt WebEngine** (PyQt6/PyQt5)
3. **GTK WebKit2** (preinstalled on Ubuntu GNOME)
4. **Chrome/Edge `--app=` window** (zero extra install)
5. **Default browser** (still THE ONE UI)

The hub auto-starts if not running. PySide6 (241 MB) is gone — the
Setup EXE is ~10-11 MB again. New `START-CONSOLE.vbs` launcher and a
**Console (THE ONE UI)** tray menu item.

## 3) CENTER MODE — one center PC, many child PCs

Child PCs install **only the Chrome extension** — no tool, no local
hub. Options → Connections → **Center PC / child PC mode**:

- `auto` (default): use the local tool's hub when it answers, else the
  Center PC — a PC with the tool behaves like always; a pure child PC
  transparently prints on the center PC.
- `local` / `center` force one side. Center PC URL + token fields.
  Local-hub probe cached 60 s (1.2 s timeout) — no per-job latency.
- The **Console** popup button and the options **Console** tab open
  `/ui` of the ACTIVE hub.
- Message API: `hubState` returns `{mode, isCenter, activeUrl, localUp}`.

## 4) Build everything from source (no prebuilt binaries)

    bash scripts/build-all.sh          # CRX + zip + Setup EXE + DEB + SHA256SUMS

Requirements: python3, zip, dpkg-deb (any Linux), NSIS 3.x for the EXE
(`sudo apt-get install nsis` — or the local-prefix recipe in the
script). The CRX signing key ships in `extension-signing/`, so the CRX
id stays `likldbkamojokkfdlcjibiljpgbbnohc` and Chrome auto-updates the
force-installed extension from your own hub. See
`docs/BUILD-FROM-SOURCE.md` for every step.

## Test kit

`python3 -m pytest tests/ -q` — **280 passed, 1 skipped** (v3.1.2):
per-printer IPP, /ui console serving + auth + fallback, dropdown
regression, RFC 8011 conformance, queue, audit, self-host chain.
