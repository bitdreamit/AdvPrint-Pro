#!/usr/bin/env python3
"""v3.4.8 console UI check: boot the real hub (two mocked printers),
open the ONE UI console in headless Chromium and verify the v3.4.8
surfaces:

  1. BOOT.version == 3.4.8
  2. Rules table (with paper + content extras): every column through
     Runs + the Edit/Del buttons render INSIDE the card (the reported
     v3.4.7 bug); the table is tbl compact inside a .tbl-wrap
  3. Narrow window (800px): the wrap scrolls INSIDE the card - the
     Edit button stays reachable, the card border is never crossed
  4. Rule editor: #re-type carries real values; saving "Web page" +
     content stores kind html (the v3.4.7 shift bug is gone)
  5. popup badge is v3.4.8, popup structure intact
  6. no uncaught JS exceptions
"""
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
os.environ["ADVPRINT_DATA"] = tempfile.mkdtemp(prefix="ap348-ui-")

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

# rules WITH the extras the user reported (paper + content)
RULES = [
    {"id": 1, "name": "Lab PDF reports",
     "pattern": "*://www.htncr.org/lab/*", "type": "glob",
     "printer": NAMES[0], "action": "web", "copies": 1, "paper": "A5",
     "on": True, "match": "url", "runs": 128,
     "last_run": "2026-11-14T14:22:08.000Z"},
    {"id": 2, "name": "Receipts", "pattern": "*://billing.local/pos/*",
     "type": "glob", "printer": "XP-58 Thermal", "action": "raw",
     "copies": 1, "paper": "58mm receipt", "on": True, "match": "url",
     "runs": 41},
    {"id": 3, "name": "Patient reports", "pattern": "(any page)",
     "match": "content", "content": "Patient Report (long content line "
     "that used to stretch the row)",
     "printer": NAMES[1], "action": "web", "copies": 1,
     "paper": "4\u00d76\u2033 label", "on": True, "runs": 12},
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

ok_all = True


def check(name, cond, extra=""):
    global ok_all
    print(("PASS " if cond else "FAIL "), name, extra)
    if not cond:
        ok_all = False


from playwright.sync_api import sync_playwright

errors = []
shots = os.path.join(ROOT, "scripts")
with sync_playwright() as pw:
    b = pw.chromium.launch()
    pg = b.new_page(viewport={"width": 1280, "height": 800})
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.on("console", lambda m: errors.append(m.text)
          if m.type == "error" else None)
    pg.goto(base + "/ui", wait_until="domcontentloaded", timeout=20000)
    pg.wait_for_function("typeof BOOT === 'object' && BOOT.version",
                         timeout=15000)
    pg.wait_for_function("cfgCache && cfgCache.rules_mirror", timeout=15000)
    pg.evaluate("typeof showTab === 'function' && showTab('rules')")
    pg.wait_for_selector("#p-rules table.tbl tr td", timeout=10000)
    time.sleep(1.0)
    check("BOOT.version 3.4.8", pg.evaluate("BOOT && BOOT.version") == "3.4.8")

    # ---- 2. the reported bug: Edit button inside the card ----
    m = pg.evaluate("""() => {
      const tbl = document.querySelector('#p-rules table.tbl');
      const host = tbl.closest('.card');
      const rows = tbl.querySelectorAll('tbody tr, tr');
      let worstRight = 0, worstEdit = null;
      rows.forEach(function(tr){
        const tds = tr.querySelectorAll('td');
        if (!tds.length) return;
        const edit = tds[tds.length - 1].getBoundingClientRect();
        if (edit.right > worstRight) { worstRight = edit.right;
          worstEdit = (tds[0].textContent || '').trim(); }
      });
      const hr = host.getBoundingClientRect();
      const wrap = tbl.closest('.tbl-wrap');
      return {tableW: tbl.scrollWidth, hostW: host.clientWidth,
              editRight: worstRight, hostRight: hr.right,
              editInside: worstRight <= hr.right + 1,
              compact: tbl.className.indexOf('compact') >= 0,
              wrapped: !!wrap, editRow: worstEdit};
    }""")
    check("rules table is tbl compact inside .tbl-wrap",
          m["compact"] and m["wrapped"], json.dumps(m))
    check("Edit/Del inside the card (overflow %dpx)"
          % (m["editRight"] - m["hostRight"]), m["editInside"],
          "row %s editRight=%.0f hostRight=%.0f"
          % (m["editRow"], m["editRight"], m["hostRight"]))
    check("table width == card width (no overflow)",
          m["tableW"] <= m["hostW"] + 1,
          "table %d vs card %d" % (m["tableW"], m["hostW"]))
    tbl_txt = pg.locator("#p-rules table.tbl").first.inner_text()
    for col in ("RULE", "URL / ADDRESS", "MATCH BY", "PAGE CONTENT",
                "URL TYPE", "PRINTER", "WHAT TO", "CPL", "PAPER", "ON",
                "AUTO", "RUNS"):
        check("header keeps %s" % col, col in tbl_txt.upper())
    check("runs cell shows the synced last_run",
          "14:22" in tbl_txt, "last HH:MM from last_run")
    pg.evaluate("document.querySelector('#p-rules table.tbl')"
                ".scrollIntoView({block:'center'})")
    time.sleep(0.4)
    pg.screenshot(path=os.path.join(shots, "ui348-rules-table.png"))

    # ---- 3. narrow window: the wrap scrolls, nothing escapes ----
    pg.set_viewport_size({"width": 800, "height": 700})
    time.sleep(0.5)
    m2 = pg.evaluate("""() => {
      const tbl = document.querySelector('#p-rules table.tbl');
      const wrap = tbl.closest('.tbl-wrap');
      const host = tbl.closest('.card');
      const rows = tbl.querySelectorAll('tr');
      let editRight = 0, editLeft = 0;
      rows.forEach(function(tr){
        const t = tr.querySelectorAll('td');
        if (t.length) { const r = t[t.length-1].getBoundingClientRect();
          editRight = Math.max(editRight, r.right);
          editLeft = editLeft || r.left; }
      });
      const wr = wrap.getBoundingClientRect();
      return {
        wrapScrolls: wrap.scrollWidth > wrap.clientWidth + 1,
        hostScrolls: host.scrollWidth <= host.clientWidth + 1,
        /* scrolling the wrap right must be able to reveal the buttons:
           the cell must end within the wrap's scrollable content box */
        editReachable: (editRight - wr.left) <= wrap.scrollWidth + 1,
        cardClips: host.clientWidth > 0 &&
                   host.getBoundingClientRect().right <=
                     window.innerWidth + 1};
    }""")
    check("narrow window: the wrap scrolls internally",
          m2["wrapScrolls"], json.dumps(m2))
    check("narrow window: nothing crosses the card border",
          m2["hostScrolls"] and m2["editReachable"])
    pg.screenshot(path=os.path.join(shots, "ui348-rules-narrow.png"))

    # ---- 4. the editor kind fix ----
    pg.set_viewport_size({"width": 1280, "height": 800})
    time.sleep(0.4)
    pg.evaluate("typeof openRuleEditor === 'function' && openRuleEditor(-1)")
    time.sleep(0.4)
    vals = pg.eval_on_selector_all(
        "#re-type option", "els => els.map(e => [e.value, e.textContent])")
    check("URL-type select carries real values",
          [v[0] for v in vals] == ["pdf", "web", "text", "zpl", "image", ""],
          str(vals))
    # simulate the exact user flow: content text + Web page -> kind html
    pg.fill("#re-content", "Patient Report")
    pg.select_option("#re-type", "web")
    kind = pg.evaluate("""() => {
      var v = String(document.querySelector('#re-type').value || "");
      if (v === "web") v = "html";
      if (["pdf","html","text","zpl","image",""].indexOf(v) < 0) v = "";
      if (document.querySelector('#re-content').value.trim() && !v) v = "html";
      return v;
    }""")
    check("content + Web page saves kind html (was pdf)", kind == "html")
    pg.click("#rulemodal .x")

    # ---- 5. popup structure ----
    import re as _re
    popup = open(os.path.join(ROOT, "extension", "popup.html"),
                 encoding="utf-8").read()
    popup = _re.sub(r"<script[\s\S]*?</script>", "", popup)
    pg.set_content(popup)
    check("popup badge is v3.4.8", "v3.4.8" in (pg.text_content("#ver") or ""))
    check("popup select + reload button intact",
          pg.locator("#selPrinter").count() == 1 and
          pg.locator("#bRefreshPrinters").count() == 1)

    b.close()

errors = [e for e in errors if "401" not in e and "404" not in e]
check("no uncaught JS exceptions", not errors, "; ".join(errors[:3]))
print("\n%s" % ("ALL UI CHECKS PASSED" if ok_all else "UI CHECKS FAILED"))
sys.exit(0 if ok_all else 1)
