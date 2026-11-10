#!/usr/bin/env python3
"""Live v3.2.8 smoke: boot the REAL hub (unix copy) on a random port,
then verify the two fixes over HTTP exactly like the user runs them:

  1. GET http://127.0.0.1:<port>/ipp/print  -> landing page shows the
     clean ipp:// URL, never ipp://http://
  2. GET /health                            -> version 3.2.8
  3. POST /print (text job, queue:false)    -> answers job JSON
"""
import json
import os
import sys
import tempfile
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tool", "unix", "hub"))

import advprint  # noqa: E402

fail = []


def check(name, cond, detail=""):
    print(("[OK]   " if cond else "[FAIL] ") + name + (" - " + detail
                                                        if detail else ""))
    if not cond:
        fail.append(name)


tmp = tempfile.mkdtemp(prefix="ap328-smoke-")
advprint.CFG["data_dir"] = tmp
advprint.CFG["port"] = 0
advprint.CFG["host"] = "127.0.0.1"
advprint.CFG["share_lan"] = True
advprint.CFG["ipp_printer"] = True
advprint.db_init()
advprint.RESUME_EVENT.set()
advprint.start_worker()
advprint.CFG["port"] = 9235          # the real port for URL rendering
advprint.lan_ip = lambda: "192.168.1.101"   # deterministic LAN IP

httpd = ThreadingHTTPServer(("127.0.0.1", 0), advprint.Handler)
httpd.daemon_threads = True
port = httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()
base = "http://127.0.0.1:%d" % port
time.sleep(0.2)


def get(path):
    try:
        with urllib.request.urlopen(base + path, timeout=10) as r:
            return r.getcode(), r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def post(path, body):
    tok = advprint.CFG["token"]
    req = urllib.request.Request(
        base + path, data=json.dumps(body).encode(),
        headers={"X-AdvPrint-Token": tok,
                 "Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.getcode(), json.loads(r.read().decode())


# 1. the IPP landing page - BUG 1
code, page = get("/ipp/print")
html = page.decode("utf-8", "replace")
check("GET /ipp/print answers 200", code == 200)
check("landing shows clean ipp:// URL",
      "ipp://192.168.1.101:9235/ipp/print" in html,
      "the exact address Windows/macOS/iOS/CUPS accept")
check("landing shows the http:// twin too",
      "http://192.168.1.101:9235/ipp/print" in html)
check("doubled scheme is gone", "ipp://http://" not in html)

# per-printer landing (anonymous). This sandbox has NO real printer, so
# the hub's correct answer is 404 "unknown per-printer IPP queue" - a
# real install with printers serves the page (locked by unit tests).
code, page = get("/ipp/print/Test%20Printer")
html2 = page.decode("utf-8", "replace")
check("per-printer landing clean (200 or honest 404)",
      ("ipp://http://" not in html2) and
      (code == 404 or "ipp://" in html2))

# 2. health - version
code, h = get("/health")
hj = json.loads(h.decode())
check("health version 3.2.8",
      hj.get("version") == "3.2.8", str(hj.get("version")))

# 3. a real print job through /print (stubbed backend in CI? no - the
# backend here IS the real module; route to __file__ so nothing prints)
code, rj = post("/print", {"title": "v3.2.8 smoke", "text": "hello",
                           "printer": "__file__", "queue": False})
check("POST /print answers job JSON", code == 200 and rj.get("ok") is True,
      json.dumps(rj)[:120])

httpd.shutdown()
print()
if fail:
    print("SMOKE FAILED: %d check(s): %s" % (len(fail), ", ".join(fail)))
    sys.exit(1)
print("SMOKE PASSED - both v3.2.8 fixes verified live")
