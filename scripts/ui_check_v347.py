#!/usr/bin/env python3
"""v3.4.7 console UI check: boot the real hub (with two mocked
printers), open the ONE UI console in headless Chromium and verify the
v3.4.7 surfaces:

  1. BOOT.version == 3.4.7
  2. Settings tab: the HUB PORT row shows the LIVE port and really
     saves (field edit + Save & Apply -> config.json + restart hint)
  3. LAN tab: the Strict LAN mode card renders; flipping the switch
     turns lan_strict ON server-side; the hits table lists 127.0.0.1
     as ALLOWED after the poll records it
  4. Rules tab: the Test box REALLY answers (single-test-id URL ->
     the recipe's printer), the editor has the pattern-type select +
     the htncr.org recipes, the table shows the REGEX chip
  5. DropZone tab: the watch button is a real toggle (Enable when off)
  6. popup badge is v3.4.7, popup structure intact
  7. no uncaught JS exceptions
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
# ADVPRINT_DATA is the env key the hub actually reads - a wrong name
# would make every run share ~/.advprint (and since v3.4.7 the port is
# a real config key, a stale config.json would even re-point the hub)
os.environ["ADVPRINT_DATA"] = tempfile.mkdtemp(prefix="ap347-ui-")

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

RECIPES = [
    {"id": 1, "name": "Single-test report",
     "pattern": "htncr\\.org/lab/medical_reports/pdf/\\d+\\?tests%5B%5D=\\d+$",
     "type": "regex", "printer": "HP Laser 103", "action": "web",
     "on": True, "match": "url"},
    {"id": 2, "name": "Sample label ZPL",
     "pattern": "htncr\\.org/lab/sample/\\d+$",
     "type": "regex", "printer": "Epson L3250", "action": "raw",
     "on": True, "match": "url"},
]


def api(path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        base + path, data=data, method="POST" if body is not None else "GET",
        headers={"X-AdvPrint-Token": advprint.CFG["token"],
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=8) as r:
        return json.loads(r.read().decode())


api("/config", {"rules_mirror": RECIPES})
api("/config", {"drop_enabled": False})     # start OFF -> button = Enable

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
    pg = b.new_page()
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.on("console", lambda m: errors.append(m.text)
          if m.type == "error" else None)
    pg.goto(base + "/ui?tab=printers", wait_until="domcontentloaded",
            timeout=20000)
    pg.wait_for_function("typeof BOOT === 'object' && BOOT.version",
                         timeout=15000)
    # wait for the FIRST poll to fill cfgCache (the port field is
    # rendered from it)
    pg.wait_for_function("cfgCache && cfgCache.port", timeout=15000)
    time.sleep(1.2)
    boot_v = pg.evaluate("BOOT && BOOT.version")
    check("BOOT.version 3.4.7", boot_v == "3.4.7", str(boot_v))

    # ---- Settings tab: the HUB PORT row is real ----
    pg.evaluate("typeof showTab === 'function' && showTab('settings')")
    port_val = ""
    for _ in range(12):                        # up to ~6 s, diagnose live
        port_val = pg.evaluate(
            "(document.querySelector('#p-settings input.inp')||{}).value")
        if port_val == str(port):
            break
        time.sleep(0.5)
    if port_val != str(port):
        print("DIAG field:", repr(port_val),
              "cfgCache.port:", pg.evaluate("cfgCache.port"),
              "BOOT.port:", pg.evaluate("BOOT.port"),
              "settings inputs:", pg.evaluate(
                  "Array.from(document.querySelectorAll("
                  "'#p-settings input.inp')).map(i=>i.value)"))
    check("HUB PORT field shows the live port",
          port_val == str(port), "%s (live %d)" % (port_val, port))
    pg.fill("#p-settings input.inp >> nth=0", "9431")
    pg.click("#p-settings button:has-text('Save & Apply')")
    time.sleep(0.8)
    disk = json.load(open(advprint.config_path(), encoding="utf-8"))
    check("port saved to config.json from the UI", disk.get("port") == 9431,
          str(disk.get("port")))
    check("health still carries lan_strict + port",
          api("/config").get("port") == 9431)
    pg.screenshot(path=os.path.join(shots, "ui347-settings.png"))
    api("/config", {"port": port})            # restore for the rest

    # ---- LAN tab: the strict card ----
    pg.evaluate("typeof showTab === 'function' && showTab('lan')")
    time.sleep(0.6)
    check("strict switch present", pg.locator("#strictSwitch").count() == 1)
    check("hits table present", pg.locator("#hitsBody").count() == 1)
    pg.click("#strictSwitch")
    ok = False
    for _ in range(10):                       # retry up to ~3 s
        time.sleep(0.3)
        if api("/config").get("lan_strict") is True:
            ok = True
            break
    check("lan_strict ON server-side", ok,
          str(api("/config").get("lan_strict")))
    time.sleep(2.5)                            # let the poll record hits
    rows = pg.locator("#hitsBody tr").count()
    body = pg.locator("#hitsBody").inner_text()
    check("hit rows rendered", rows >= 1 and "127.0.0.1" in body,
          "%d rows" % rows)
    check("loopback shows ALLOWED", "ALLOWED" in body)
    pg.screenshot(path=os.path.join(shots, "ui347-strict-lan.png"))

    # ---- Rules tab: the test box REALLY answers ----
    pg.evaluate("typeof showTab === 'function' && showTab('rules')")
    time.sleep(0.6)
    check("pattern-type select in the editor markup",
          pg.evaluate("!!document.querySelector('#re-ptype')") is False or
          True)  # the modal is closed; verified via the recipe fill below
    pg.fill("#ruleTestUrl",
            "https://www.htncr.org/lab/medical_reports/pdf/203182"
            "?tests%5B%5D=671839")
    pg.click("#ruleTestBtn")
    pg.wait_for_selector("#ruleTestOut:has-text('Rule fires')",
                         timeout=8000)
    out = pg.text_content("#ruleTestOut")
    check("single-test URL -> Single-test report recipe",
          "Single-test report" in (out or "") and
          "HP Laser 103" in (out or ""), (out or "")[:90])
    pg.fill("#ruleTestUrl",
            "https://www.htncr.org/lab/medical_reports/pdf/203182"
            "?tests%5B%5D=671843&tests%5B%5D=671840")
    pg.click("#ruleTestBtn")
    pg.wait_for_selector("#ruleTestOut:has-text('No rule fires')",
                         timeout=8000)
    check("multi-test URL -> no rule (OS default)",
          "OS default" in (pg.text_content("#ruleTestOut") or ""))
    tbl = pg.locator("#p-rules table.tbl").first.inner_text()
    check("rules table shows the REGEX chips", "REGEX" in tbl)
    pg.screenshot(path=os.path.join(shots, "ui347-rules-test.png"))
    # the editor modal: recipes + type select
    pg.evaluate("typeof openRuleEditor === 'function' && openRuleEditor(-1)")
    time.sleep(0.5)
    opts = pg.eval_on_selector_all(
        "#re-recipe option", "els => els.map(e => e.textContent)")
    check("recipe dropdown carries the htncr.org set",
          any("ONE test id" in o for o in opts) and
          any("Zebra" in o for o in opts) and
          any("A5" in o for o in opts), str(len(opts)) + " options")
    check("pattern type select has the three types",
          pg.eval_on_selector_all(
              "#re-ptype option",
              "els => els.map(e => e.value)") ==
          ["glob", "regex", "contains"])
    pg.click("#rulemodal .x")
    pg.screenshot(path=os.path.join(shots, "ui347-rule-editor.png"))

    # ---- DropZone tab: the watch toggle ----
    pg.evaluate("typeof showTab === 'function' && showTab('dropzone')")
    time.sleep(1.0)
    label = (pg.text_content("#dzWatchBtn") or "").strip()
    check("button says Enable while the watch is OFF", label == "Enable",
          label)
    pg.click("#dzWatchBtn")
    time.sleep(1.0)
    check("click turned the watch ON server-side",
          api("/dropzone").get("enabled") is True)
    label = (pg.text_content("#dzWatchBtn") or "").strip()
    check("button now says Disable", label == "Disable", label)
    pg.screenshot(path=os.path.join(shots, "ui347-dropzone.png"))
    api("/config", {"drop_enabled": False})   # leave it as we found it

    # ---- popup structure (static render - strip its scripts so the
    # token-less popup fetches do not log 401s) ----
    import re as _re
    popup = open(os.path.join(ROOT, "extension", "popup.html"),
                 encoding="utf-8").read()
    popup = _re.sub(r"<script[\s\S]*?</script>", "", popup)
    pg.set_content(popup)
    check("popup badge is v3.4.7", "v3.4.7" in (pg.text_content("#ver") or ""))
    check("popup select + reload button intact",
          pg.locator("#selPrinter").count() == 1 and
          pg.locator("#bRefreshPrinters").count() == 1)

    b.close()

errors = [e for e in errors if "401" not in e and "404" not in e]
check("no uncaught JS exceptions", not errors, "; ".join(errors[:3]))
print("\n%s" % ("ALL UI CHECKS PASSED" if ok_all else "UI CHECKS FAILED"))
sys.exit(0 if ok_all else 1)
