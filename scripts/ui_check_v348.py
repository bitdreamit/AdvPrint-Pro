#!/usr/bin/env python3
"""v3.4.8 UI check - the rules table must never overflow the card.

Boots the real hub with the patched console, injects rules with the
exact user scenario (Paper + Page-content extras, long strings), and
measures at 1280px (must FIT, no scroll) and 800px (may scroll INSIDE
the .tbl-wrap but must never cross the card border).  Also re-checks
that the reverted rule-editor is the untouched v3.4.7 one.
"""
import json
import os
import socket
import sys
import tempfile
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tool", "windows", "portable", "hub"))
os.environ["ADVPRINT_DATA"] = tempfile.mkdtemp(prefix="ap348-ui-")

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
    {"id": 3, "name": "Patient reports", "pattern": "(any page)",
     "match": "content",
     "content": "Patient Report (a long content line that used to stretch "
                "the row beyond the card border)",
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

from playwright.sync_api import sync_playwright  # noqa: E402

MEASURE = """() => {
  const card = document.querySelector('#p-rules .card:last-of-type');
  const tbl  = document.querySelector('#p-rules table.tbl');
  const wrap = tbl.closest('.tbl-wrap');
  const host = card;
  const firstDataRow = tbl.querySelectorAll('tr')[1];
  const last = firstDataRow.querySelectorAll('td');
  const edit = last[last.length - 1].querySelector('button');
  const er = edit.getBoundingClientRect(), hr = host.getBoundingClientRect();
  const ths = [...tbl.querySelectorAll('tr')[0].querySelectorAll('th')]
    .map(t => t.textContent.trim()).filter(Boolean);
  // the CONTENT rule's Page-content cell (td[3] chip says CONTENT)
  let contentClamped = null;
  [...tbl.querySelectorAll('tr')].forEach(tr => {
    const tds = tr.querySelectorAll('td');
    if (tds.length > 4 && tds[3].textContent.indexOf('CONTENT') >= 0)
      contentClamped = tds[4].className.indexOf('doc') >= 0;
  });
  return {
    boot: BOOT.version,
    tableW: tbl.scrollWidth, cardW: host.clientWidth,
    overflow: Math.max(0, tbl.scrollWidth - host.clientWidth),
    editRight: Math.round(er.right), cardRight: Math.round(hr.right),
    editInside: er.right <= hr.right + 1,
    wrapScrolls: wrap ? (wrap.scrollWidth > wrap.clientWidth) : null,
    pageOverflowX: document.documentElement.scrollWidth - window.innerWidth,
    headers: ths,
    contentClamped: contentClamped,
    docCount: document.querySelectorAll('#p-rules .tbl-wrap').length
  };
}"""

fails = []
with sync_playwright() as pw:
    b = pw.chromium.launch()
    pg = b.new_page(viewport={"width": 1280, "height": 800})
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto(base + "/ui", wait_until="domcontentloaded", timeout=20000)
    pg.wait_for_function("typeof BOOT === 'object' && BOOT.version",
                         timeout=15000)
    pg.wait_for_function(
        "cfgCache && cfgCache.rules_mirror && cfgCache.rules_mirror.length",
        timeout=15000)
    pg.evaluate("typeof showTab === 'function' && showTab('rules')")
    pg.wait_for_selector("#p-rules table.tbl tr td", timeout=10000)
    time.sleep(1.2)

    m = pg.evaluate(MEASURE)
    print("WIDE 1280:", json.dumps(m, indent=2))
    ok = (m["boot"] == "3.4.8" and m["overflow"] == 0 and m["editInside"]
          and m["contentClamped"] is True
          and m["headers"][:12] == ["#", "Rule", "URL / address filter",
                                    "Match by", "Page content", "URL type",
                                    "Printer", "What to print", "Cpl",
                                    "Paper", "On", "Auto"]
          and m["docCount"] >= 1)
    (fails if not ok else []).append("wide-1280") if not ok else None
    pg.evaluate(
        "document.querySelector('#p-rules .tbl-wrap')"
        ".scrollIntoView({block:'center'})")
    time.sleep(0.4)
    pg.screenshot(path=os.path.join(ROOT, "scripts", "ui348-rules-table.png"))

    # narrow window: the wrap scrolls INSIDE the card; after scrolling the
    # wrap fully right the Edit button must sit INSIDE the card rect, and
    # the page itself must never grow a horizontal scrollbar
    pg.set_viewport_size({"width": 800, "height": 700})
    time.sleep(0.6)
    m2 = pg.evaluate(MEASURE)
    pg.evaluate(
        "const w = document.querySelector('#p-rules .tbl-wrap'); "
        "w.scrollLeft = w.scrollWidth;")
    time.sleep(0.3)
    m3 = pg.evaluate(MEASURE)
    print("NARROW 800:", json.dumps(m2, indent=2))
    print("NARROW scrolled to end:", json.dumps(
        {k: m3[k] for k in ("editRight", "cardRight", "editInside")}))
    ok2 = (m2["pageOverflowX"] <= 0          # page never scrolls sideways
           and m2["wrapScrolls"] is True     # the wrap does the scrolling
           and m3["editInside"]              # button reachable INSIDE card
           and m2["headers"][:12] == m["headers"][:12])
    (fails if not ok2 else []).append("narrow-800") if not ok2 else None
    pg.screenshot(path=os.path.join(ROOT, "scripts", "ui348-rules-narrow.png"))

    # reverted rule editor must be the untouched v3.4.7 one (no explicit
    # value attributes on the options - option.value alone falls back to
    # the text content, which is normal DOM behaviour)
    rev = pg.evaluate("""() => {
      const sel = document.querySelector('#re-type');
      const opts = [...sel.options].map(o => o.textContent.trim());
      const withValueAttr = [...sel.options].filter(o => o.hasAttribute('value')).length;
      return {opts, withValueAttr};
    }""")
    print("EDITOR:", json.dumps(rev))
    ok3 = (rev["opts"] == ["PDF link", "Web page", "Plain text / stream", "Any"]
           and rev["withValueAttr"] == 0)
    if not ok3:
        fails.append("reverted-editor")
    if errors:
        fails.append("js-errors: " + "; ".join(errors[:3]))
    b.close()

print("UI CHECK:", "PASS" if not fails else "FAIL " + ", ".join(fails))
sys.exit(0 if not fails else 1)
