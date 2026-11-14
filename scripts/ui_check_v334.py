#!/usr/bin/env python3
"""v3.3.4 console UI check: boot the real hub, open the ONE UI console
in headless Chromium, switch to the Extension tab and verify the LIVE
policy chips + the two .bat download buttons render (the v3.3.4 console
delta). Also loads the popup.html in isolation and checks the printer
picker markup + script wiring (no chrome.* APIs outside the extension,
so only the static structure is asserted there)."""
import os
import re
import socket
import sys
import tempfile
import threading
import time
import json
import urllib.request
from http.server import ThreadingHTTPServer

ROOT = "/home/z/my-project/ap334-src"
sys.path.insert(0, os.path.join(ROOT, "tool", "windows", "portable", "hub"))
os.environ["ADVPRINT_DATA_DIR"] = tempfile.mkdtemp(prefix="ap334-ui-")

import advprint  # noqa: E402

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
    if not cond: ok_all = False

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
    # open the Extension tab
    pg.evaluate("typeof showTab === 'function' && showTab('extension')")
    time.sleep(1.5)
    chips = pg.locator("#p-extension [data-pol]")
    n = chips.count()
    check("6 policy status chips render", n == 6, "n=%d" % n)
    if n:
        first = chips.first.inner_text()
        check("chip painted live (not '…')", first.strip() != "…" and
              ("LINUX" in first or "NOT SET" in first or "INSTALLED" in first),
              first.strip())
    check("bat buttons present",
          pg.locator("#polBatHklm").count() == 1 and
          pg.locator("#polBatHkcu").count() == 1)
    # the Apply buttons must still be present and bound
    apply_buttons = pg.locator("#p-extension table.tbl button")
    check("12 apply buttons (6 rows x 2)", apply_buttons.count() == 12,
          "n=%d" % apply_buttons.count())
    # capture the console boot object sanity
    boot_v = pg.evaluate("BOOT && BOOT.version")
    check("BOOT.version 3.3.4", boot_v == "3.3.4", str(boot_v))
    # popup static check (popup runs only inside the extension)
    popup = open(os.path.join(ROOT, "extension", "popup.html"),
                 encoding="utf-8").read()
    pg.set_content(popup)
    check("popup select renders",
          pg.locator("#selPrinter").count() == 1 and
          pg.locator("#bRefreshPrinters").count() == 1)
    check("popup legacy ids present",
          pg.locator("#swShareTxRow").count() == 1 and
          pg.locator("#bShot").count() == 1)
    b.close()

# uncaught exceptions are fatal; 401 resource noise from early polls
# (before the boot token reaches api()) is expected on a fresh hub
fatal = [e for e in errors
         if "401" not in e and "favicon" not in e]
check("no uncaught JS exceptions", not fatal, "; ".join(fatal[:3]))
n401 = sum(1 for e in errors if "401" in e)
check("only 401 resource noise otherwise", len(errors) - len(fatal) == n401,
      "%d x 401" % n401)
print()
print("UI " + ("PASS" if ok_all else "FAIL"))
sys.exit(0 if ok_all else 1)
