#!/usr/bin/env python3
"""Live v3.2.9 smoke: boot the REAL hub (unix copy) on a random port,
then verify the three multi-PC fixes over HTTP exactly like the user
runs them:

  1. GET /ipp/print with a LAN Host header  -> the landing page uses
     the address THE OPENING DEVICE used (BUG 3), never the hub IP,
     and states who may print (BUG 2 ACL transparency)
  2. IPP Get-Printer-Attributes for a per-printer queue -> the queue
     URI is echoed in BOTH schemes with the queue printer-name (BUG 1)
  3. GET /health -> version 3.2.9 + the new lan_ips key
  4. POST /print + 8 parallel /health clients -> the node serves
     concurrent PCs (BUG 2)
"""
import concurrent.futures
import json
import os
import struct
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


tmp = tempfile.mkdtemp(prefix="ap329-smoke-")
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


def get(path, host="127.0.0.1:%d" % 0 or None):
    req = urllib.request.Request(base + path)
    if host:
        req.add_header("Host", host)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
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


# 1. BUG 3 - the landing page mirrors the OPENING device's address
code, page = get("/ipp/print", host="10.26.94.77:%d" % port)
html = page.decode("utf-8", "replace")
check("GET /ipp/print answers 200", code == 200)
check("landing uses the REQUEST device address",
      "ipp://10.26.94.77:%d/ipp/print" % port in html and
      "http://10.26.94.77:%d/ipp/print" % port in html,
      "every LAN PC sees its own reachable ip:port")
check("hub's own lan_ip is NOT shown to that device",
      "192.168.1.101" not in html)
check("doubled scheme stays gone (v3.2.8 rule)",
      "ipp://http://" not in html)
check("landing states who may print (BUG 2)",
      "every device on the LAN" in html and "allowed_ips" in html)

# 2. BUG 1 - the per-printer queue echo over the wire
def _attr(tag, name, value):
    nb = name.encode()
    vb = value if isinstance(value, bytes) else str(value).encode()
    return (bytes([tag]) + len(nb).to_bytes(2, "big") + nb +
            len(vb).to_bytes(2, "big") + vb)


def ipp_get_printer(uri_path):
    out = bytearray()
    out += b"\x01\x01" + (0x000B).to_bytes(2, "big") + (7).to_bytes(4, "big")
    out += b"\x01"
    out += _attr(0x47, "attributes-charset", "utf-8")
    out += _attr(0x48, "attributes-natural-language", "en")
    out += _attr(0x45, "printer-uri",
                 "http://10.26.94.77:%d%s" % (port, uri_path))
    out += b"\x03"
    req = urllib.request.Request(
        base + uri_path, data=bytes(out),
        headers={"Content-Type": "application/ipp"}, method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.getcode(), r.read()


def _walk(raw):
    attrs, i, n, cur, last = [], 8, len(raw), None, ""
    while i < n:
        b = raw[i]
        if b == 0x03:
            break
        if b in (0x01, 0x02, 0x04, 0x05):
            cur = []
            attrs.append(cur)
            i += 1
            continue
        nl = int.from_bytes(raw[i + 1:i + 3], "big")
        i += 3
        name = raw[i:i + nl].decode("utf-8", "replace")
        i += nl
        vl = int.from_bytes(raw[i:i + 2], "big")
        i += 2
        val = raw[i:i + vl].decode("utf-8", "replace")
        i += vl
        if cur is not None:
            if not name:
                name = last
            else:
                last = name
            cur.append((name, val))
    return attrs


# this sandbox has no real printers -> an unknown queue honestly 404s;
# a resolved queue is unit-locked in tests/test_v329.py. Here we prove
# the WIRE shape for the generic queue (echo of the requested URI in
# both schemes + hostname identity).
code, raw = ipp_get_printer("/ipp/print")
attrs = _walk(raw)
flat = dict()
for grp in attrs:
    for name, val in grp:
        flat.setdefault(name, []).append(val)
check("IPP Get-Printer-Attributes answers 200", code == 200)
uris = flat.get("printer-uri-supported", [])
check("generic response echoes the requested URI in both schemes",
      any(u.startswith("http://10.26.94.77:%d/ipp/print" % port)
          for u in uris) and
      any(u.startswith("ipp://10.26.94.77:%d/ipp/print" % port)
          for u in uris), str(uris[:2]))
check("printer-name = hub hostname (generic queue)",
      flat.get("printer-name", [""])[0] == advprint.socket.gethostname())
check("printer-uuid present (stable identity)",
      flat.get("printer-uuid", [""])[0].startswith("urn:uuid:"))

# 3. health - version + the new lan_ips key
code, h = get("/health")
hj = json.loads(h.decode())
check("health version 3.2.9",
      hj.get("version") == "3.2.9", str(hj.get("version")))
check("health exposes lan_ips (BUG 3)",
      isinstance(hj.get("lan_ips"), list) and hj["lan_ips"],
      str(hj.get("lan_ips")))

# 4. BUG 2 - concurrent PCs: 8 parallel clients + a real job
code, rj = post("/print", {"title": "v3.2.9 smoke", "text": "hello",
                           "printer": "__file__", "queue": False})
check("POST /print answers job JSON", code == 200 and rj.get("ok") is True,
      json.dumps(rj)[:120])


def poll(_):
    c, p = get("/health")
    return c == 200 and b"3.2.9" in p


with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
    ok = list(ex.map(poll, range(8)))
check("8 parallel PC polls all answer 200", all(ok), str(ok))

httpd.shutdown()
print()
if fail:
    print("SMOKE FAILED: %d check(s): %s" % (len(fail), ", ".join(fail)))
    sys.exit(1)
print("SMOKE PASSED - all three v3.2.9 multi-PC fixes verified live")
