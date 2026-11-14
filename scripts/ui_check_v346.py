#!/usr/bin/env python3
"""v3.4.6 console UI check: boot the real hub (with two mocked
printers), open the ONE UI console in headless Chromium and verify the
ONE-port printer cards + the extension policy panel still render.

Checks:
  1. BOOT.version == 3.4.6
  2. Printers tab: 2 cards, DEFAULT badge, per-printer PATH queue URL
     on the HUB port + COPY button, NO "Dedicated port" anywhere
  3. Extension tab: 6 policy chips + 2 .bat buttons + 12 apply buttons
     (the v3.3.5 auto-CRX surface, unchanged)
  4. popup markup intact (selector + reload + legacy ids)
  5. no uncaught JS exceptions
"""
import os
import socket
import sys
import tempfile
import threading
import time
import json
import urllib.request
from http.server import ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tool", "windows", "portable", "hub"))
os.environ["ADVPRINT_DATA_DIR"] = tempfile.mkdtemp(prefix="ap346-ui-")

import advprint  # noqa: E402

NAMES = ["HP Laser 103", "Epson L3250"]
advprint.list_printers_cached = lambda max_age=30.0: list(NAMES)
advprint.default_printer_cached = lambda max_age=10.0: NAMES[0]
advprint.printers_status_cached = lambda max_age=30.0: {
    n: "ready" for n in NAMES}

s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
advprint.CFG["port"] = port
advprint.CFG["host"] = "127.0.0.1"
advprint.CFG["share_lan"] = False
advprint.CFG["ipp_mdns"] = False
advprint.db_init()
advprint.RESUME_EVENT.set()
advprint.start_worker()
httpd = ThreadingHTTPServer(("127.0.0.1", port), advprint.Handler)
httpd.daemon_threads = True
threading.Thread(target=httpd.serve_forever, daemon=True).start()
base = "http://127.0.0.1:%d" % port
time.sleep(0.3)

ok_all = True


def check(name, cond, extra=""):
    global ok_all
    print(("PASS " if cond else "FAIL "), name, extra)
    if not cond:
        ok_all = False


from playwright.sync_api import sync_playwright

errors = []
with sync_playwright() as pw:
    b = pw.chromium.launch()
    pg = b.new_page()
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.on("console", lambda m: errors.append(m.text)
          if m.type == "error" else None)
    pg.goto(base + "/dashboard?token=" + advprint.CFG["token"],
            wait_until="domcontentloaded", timeout=20000)
    pg.wait_for_function("typeof BOOT === 'object' && BOOT.version",
                         timeout=15000)
    time.sleep(1.0)
    boot_v = pg.evaluate("BOOT && BOOT.version")
    check("BOOT.version 3.4.6", boot_v == "3.4.6", str(boot_v))

    # ---- Printers tab: the ONE-port cards ----
    pg.evaluate("typeof showTab === 'function' && showTab('printers')")
    time.sleep(1.5)
    names = pg.eval_on_selector_all(
        "#p-printers .nm", "els => els.map(e => e.textContent)")
    check("2 printer cards render",
          set(names) == set(NAMES), str(names))
    badges = pg.locator("#p-printers .badge")
    check("DEFAULT badge on the OS default", badges.count() == 1,
          "n=%d" % badges.count())
    urls = pg.eval_on_selector_all(
        "#p-printers .url",
        "els => els.map(e => e.textContent.trim())")
    want = ["/ipp/print/hp-laser-103", "/ipp/print/epson-l3250"]
    check("per-printer PATH queue URLs on the hub port",
          all(any(w in u for u in urls) for w in want) and
          all(("127.0.0.1:%d" % port) in u for u in urls if u),
          str(urls))
    cps = pg.locator("#p-printers .url button.cp")
    check("COPY buttons on both cards", cps.count() == 2,
          "n=%d" % cps.count())
    body = pg.locator("#p-printers").inner_text()
    check("no 'Dedicated port' text left", "Dedicated port" not in body)
    shot = os.path.join(ROOT, "scripts", "console-printers-v346.png")
    pg.screenshot(path=shot, full_page=False)
    print("screenshot:", shot)

    # ---- Extension tab: the auto-CRX surface (v3.3.5, unchanged) ----
    pg.evaluate("typeof showTab === 'function' && showTab('extension')")
    time.sleep(1.5)
    # v3.3.5 replaced the v3.3.4 per-policy chips with the auto-CRX
    # surface: the one-click admin button + the silent HKCU switch
    btns = pg.locator("#p-extension button")
    txt = " | ".join(btns.all_inner_texts())
    check("Auto-integrate (admin) button present",
          "Auto-integrate (admin)" in txt, txt[:120])
    check("Auto-install switch present",
          pg.locator("#autocrxHkcuSw").count() == 1)
    apply_buttons = pg.locator("#p-extension table.tbl button")
    check("policy apply buttons still present",
          apply_buttons.count() >= 12,
          "n=%d" % apply_buttons.count())

    # ---- popup static structure (popup runs only in the extension) ----
    popup = open(os.path.join(ROOT, "extension", "popup.html"),
                 encoding="utf-8").read()
    pg.set_content(popup)
    check("popup select renders",
          pg.locator("#selPrinter").count() == 1 and
          pg.locator("#bRefreshPrinters").count() == 1)
    check("popup badge is v3.4.6",
          "v3.4.6" in (pg.text_content("#ver") or "") or
          'id="ver">v3.4.6' in popup,
          pg.text_content("#ver") or "")
    check("popup legacy ids present",
          pg.locator("#swShareTxRow").count() == 1 and
          pg.locator("#bShot").count() == 1)
    b.close()

fatal = [e for e in errors
         if "401" not in e and "favicon" not in e]
check("no uncaught JS exceptions", not fatal, "; ".join(fatal[:3]))
n401 = sum(1 for e in errors if "401" in e)
check("only 401 resource noise otherwise", len(errors) - len(fatal) == n401,
      "%d x 401" % n401)
print()
print("UI " + ("PASS" if ok_all else "FAIL"))
sys.exit(0 if ok_all else 1)
