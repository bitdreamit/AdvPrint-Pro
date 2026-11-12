#!/usr/bin/env python3
"""Live v3.3.0 smoke: boot the REAL hub (unix copy) on a random port,
then verify the three fixes over HTTP exactly like the user runs them:

  1. BUG 1 - the invite page /connect?t=... : the peer URL follows the
     address the VISITOR used (Host header), a loopback visitor gets the
     self-invite explainer, POST /peer-connect refuses a self-invite,
     and a wrong token explains the DIFFERENT-PC case
  2. BUG 2 - the LAN listener + RAW port answer on IPv4 AND IPv6 (the
     [::] socket accepts ::1 connections), /health reports raw_addrs /
     lan_bind_addrs / lan_ips6
  3. BUG 3 - per-printer queues: /printers lists ipp:// URLs, an unknown
     queue 404s WITH the live queue list, unicode slugs stay distinct
"""
import json
import os
import socket
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
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


tmp = tempfile.mkdtemp(prefix="ap330-smoke-")
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
advprint.list_lan_ips = lambda *a, **k: ["192.168.1.101", "10.26.94.206"]
advprint.list_lan_ips6 = lambda *a, **k: ["2001:db8::10"]
advprint.list_printers_cached = lambda *a, **k: [
    "HP Laser 103", "প্রিন্টার ১"]

httpd = ThreadingHTTPServer(("127.0.0.1", 0), advprint.Handler)
httpd.daemon_threads = True
port = httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()
base = "http://127.0.0.1:%d" % port
advprint.CFG["port"] = port           # URLs + binds follow the REAL port
time.sleep(0.2)


def get(path, host=None, token=True):
    req = urllib.request.Request(base + path)
    if host:
        req.add_header("Host", host)
    if token:
        req.add_header("X-AdvPrint-Token", advprint.CFG["token"])
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.getcode(), r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def post_raw(path, data, content_type):
    req = urllib.request.Request(base + path, data=data, method="POST",
                                 headers={"Content-Type": content_type})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.getcode(), r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


# ---------- 1. BUG 1: the invite connects the RIGHT PC ----------
tok = urllib.parse.quote(advprint.CFG["token"])

# 1a. the LAN-visitor FORM page (peer URL = the address the visitor typed).
# The sandbox can only connect from loopback, so the page is checked via
# the same builder the route calls (the route wiring is locked in tests).
form = advprint.connect_page_html(advprint.CFG["token"], "AI-Lab",
                                  req_host="192.168.1.104", req_port=port)
check("peer URL follows the VISITOR address (192.168.1.104)",
      'id="peerUrl">http://192.168.1.104:%d<' % port in form)
check("peer URL is NOT the hub's own lan_ip guess",
      'id="peerUrl">http://192.168.1.101' not in form)
check("the form still posts to the visitor's own loopback hub",
      "127.0.0.1:%d/peer-connect" % advprint.DEFAULT_PEER_PORT in form)
check("the page probes the visitor's own hub first",
      "127.0.0.1" in form and "/health" in form)
check("other hub addresses offered as chips (v4 + v6)",
      "use this" in form and "http://[2001:db8::10]:%d" % port in form)

# 1b. a loopback visitor over HTTP gets the self-invite explainer

code, page = get("/connect?t=%s&n=AI-Lab" % tok)
html = page.decode("utf-8", "replace")
check("loopback visitor gets the self-invite explainer",
      code == 200 and "OTHER PC" in html)
check("the explainer offers NO add-to-self form",
      "/peer-connect" not in html)
check("the explainer shows the invite link to carry over",
      "/connect?t=" in html)

# 1c. POST /peer-connect with the hub's OWN url is REFUSED
body = urllib.parse.urlencode({
    "url": "http://192.168.1.101:%d" % port, "token": "x",
    "name": "SelfPC", "confirm": "1"}).encode()
code, page = post_raw("/peer-connect", body,
                      "application/x-www-form-urlencoded")
check("self-invite POST is refused (400)",
      code == 400 and "own invite" in page.decode("utf-8", "replace"))
check("no self peer entry was written",
      not (advprint.CFG.get("peer_hubs") or []))

# 1d. a REAL peer still saves end to end
body = urllib.parse.urlencode({
    "url": "http://192.168.1.200:%d" % 9235, "token": "peer-token",
    "name": "Shop-PC", "confirm": "1"}).encode()
code, page = post_raw("/peer-connect", body,
                      "application/x-www-form-urlencoded")
peers = advprint.CFG.get("peer_hubs") or []
check("a real LAN peer saves via the invite",
      code == 200 and any(p.get("name") == "Shop-PC" for p in peers))
advprint.CFG["peer_hubs"] = []          # clean up for the next section
advprint._PEER_CACHE["t"] = 0.0

# 1e. a token from a DIFFERENT PC's hub is explained
code, page = get("/connect?t=WRONG-TOKEN&n=x")
html = page.decode("utf-8", "replace")
check("token mismatch explains the DIFFERENT-PC case",
      code == 403 and "DIFFERENT PC" in html)

# ---------- 2. BUG 2: dual-stack, every-interface listeners ----------
lan_err = advprint.lan_listen_start()
check("LAN listener started cleanly", lan_err is None, str(lan_err))
check("LAN listener binds at least one socket", advprint.lan_listen_active())
check("health carries the bound-socket list",
      advprint.build_health_snapshot()["lan_bind_addrs"] ==
      list(advprint._LAN_BINDS))
v6_socks = [s for s in advprint._LAN_HTTPDS
            if s.socket.family == socket.AF_INET6] if advprint._LAN_HTTPDS \
    else []
if socket.has_dualstack_ipv6():
    check("a [::] (IPv6) listener is up (V6ONLY)",
          any(s.socket.getsockname()[0] == "::" for s in v6_socks))
    # ::1 must really answer on the hub port
    try:
        probe = socket.create_connection(("::1", port), timeout=5)
        probe.sendall(b"GET /health HTTP/1.0\r\nHost: [::1]\r\n\r\n")
        data = probe.recv(200)
        probe.close()
        check("IPv6 ::1 answers HTTP on the hub port",
              b"200" in data.split(b"\r\n")[0])
    except OSError as e:
        check("IPv6 ::1 answers HTTP on the hub port", False, str(e))

raw_err = advprint.raw_listen_start()
check("RAW 9100-style listener started on a free config port",
      raw_err is None, str(raw_err))
snap = advprint.build_health_snapshot()
check("health reports raw_addrs with the bound sockets",
      snap["raw_active"] is True and len(snap["raw_addrs"]) >= 1)
check("health carries lan_ips6",
      snap["lan_ips6"] == ["2001:db8::10"])
advprint.raw_listen_stop()
advprint.lan_listen_stop()
time.sleep(0.4)

# ---------- 3. BUG 3: per-printer queues for ANY printer ----------
code, data = get("/printers", host="192.168.1.104:%d" % port)
d = json.loads(data.decode("utf-8"))
q = {p["name"]: p.get("ipp_queue") for p in d.get("printers", [])}
check("/printers lists every printer with its own ipp:// queue",
      "ipp://192.168.1.104:%d/ipp/print/hp-laser-103" % port
      in (q.get("HP Laser 103") or ""))
check("unicode printer names get a distinct, percent-encoded queue",
      "ipp://192.168.1.104:%d/ipp/print/" % port in (q.get("প্রিন্টার ১") or "")
      and urllib.parse.quote(advprint._ipp_queue_slug("প্রিন্টার ১"),
                             safe="") in (q.get("প্রিন্টার ১") or ""))
code, data = get("/ipp/print/totally-unknown-queue")
d = json.loads(data.decode("utf-8"))
check("unknown queue 404s WITH the live queue list",
      code == 404 and "hp-laser-103" in str(d.get("error", ""))
      and "Active queues" in str(d.get("error", "")))

code, page = get("/health")
d = json.loads(page.decode("utf-8"))
check("health reports version 3.3.0", d.get("version") == "3.3.0")

print()
if fail:
    print("SMOKE FAILED: %d checks:" % len(fail))
    for f in fail:
        print("  -", f)
    sys.exit(1)
print("v3.3.0 smoke: ALL CHECKS PASSED")
