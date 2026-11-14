#!/usr/bin/env python3
"""Reproduce the v3.4.8 rules-table overflow: rules with paper / content
extras make the row wider than the card, pushing the Edit button outside
the visible area. Boot the hub, inject 4 rules, measure + screenshot."""
import os
import sys
import tempfile
import threading
import time
import json
import socket
import urllib.request
from http.server import ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tool", "windows", "portable", "hub"))
os.environ["ADVPRINT_DATA"] = tempfile.mkdtemp(prefix="ap348-repro-")

import advprint  # noqa: E402

NAMES = ["HP Laser 103 107 108", "AdvPrint Pro @ AI-Lab (IPP virtual)"]
advprint.list_printers_cached = lambda max_age=30.0: list(NAMES)
advprint.default_printer_cached = lambda max_age=10.0: NAMES[0]
advprint.printers_status_cached = lambda max_age=30.0: {n: "ready" for n in NAMES}

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

RULES = [
    {"id": 1, "name": "Lab PDF reports", "pattern": "*://www.htncr.org/lab/*",
     "type": "glob", "printer": NAMES[0], "action": "web", "copies": 1,
     "paper": "A5", "on": True, "match": "url", "runs": 128},
    {"id": 2, "name": "Receipts", "pattern": "*://billing.local/pos/*",
     "type": "glob", "printer": "XP-58 Thermal", "action": "raw", "copies": 1,
     "paper": "58mm receipt", "color": "Black & white", "duplex": "",
     "on": True, "match": "url", "runs": 41},
    {"id": 3, "name": "Patient reports",
     "pattern": "(any page)", "match": "content",
     "content": "Patient Report (long content line to test wrapping)",
     "printer": NAMES[1], "action": "web", "copies": 1,
     "paper": "4\u00d76\u2033 label", "on": True, "runs": 12},
    {"id": 4, "name": "Night reports",
     "pattern": "*://intranet/night-reports/very/long/path/*",
     "type": "glob", "printer": NAMES[0], "action": "web", "copies": 2,
     "paper": "Legal", "on": True, "match": "url", "runs": 3},
]


def api(path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        base + path, data=data, method="POST" if body is not None else "GET",
        headers={"X-AdvPrint-Token": advprint.CFG["token"],
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=8) as r:
        return json.loads(r.read().decode())


api("/config", {"rules_mirror": RULES})

from playwright.sync_api import sync_playwright

with sync_playwright() as pw:
    b = pw.chromium.launch()
    pg = b.new_page(viewport={"width": 1280, "height": 800})
    pg.goto(base + "/ui", wait_until="domcontentloaded", timeout=20000)
    pg.wait_for_function("typeof BOOT === 'object' && BOOT.version", timeout=15000)
    pg.wait_for_function("cfgCache && cfgCache.rules_mirror && cfgCache.rules_mirror.length",
                         timeout=15000)
    pg.evaluate("typeof showTab === 'function' && showTab('rules')")
    pg.wait_for_selector("#p-rules table.tbl tr td", timeout=10000)
    time.sleep(1.2)
    m = pg.evaluate("""() => {
      const card = document.querySelector('#p-rules .card:last-of-type');
      const tbl  = document.querySelector('#p-rules table.tbl');
      const host = tbl.closest('.card') || tbl.parentElement;
      const last = tbl.querySelectorAll('tr')[1].querySelectorAll('td');
      const edit = last[last.length - 1];
      const er = edit.getBoundingClientRect(), hr = host.getBoundingClientRect();
      return {tableW: tbl.scrollWidth, hostW: host.clientWidth,
              overflow: tbl.scrollWidth - host.clientWidth,
              editRight: er.right, hostRight: hr.right,
              editOutside: er.right > hr.right + 1};
    }""")
    print(json.dumps(m, indent=2))
    # scroll the rules table into view and shoot
    pg.evaluate("document.querySelector('#p-rules table.tbl').scrollIntoView({block:'center'})")
    time.sleep(0.4)
    pg.screenshot(path=os.path.join(ROOT, "scripts", "repro348-rules-table.png"))
    # crop on the table region
    el = pg.locator("#p-rules table.tbl").first
    el.screenshot(path=os.path.join(ROOT, "scripts", "repro348-table-only.png"))
    b.close()
print("done")
