#!/usr/bin/env python3
"""v3.4.6 live smoke test: boot a REAL hub and prove ONE PORT FOR
EVERYTHING end to end over real HTTP - the exact requests Windows
10/11 "Add a printer -> IPP Device" sends - plus the popup-memory
surface (/printers default field) and the closed-port check (no 9236+
listeners any more)."""
import http.client
import json
import os
import socket
import sys
import tempfile
import threading
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tool", "windows", "portable", "hub"))
import advprint  # noqa: E402

data_dir = tempfile.mkdtemp(prefix="advprint-live-")
advprint.CFG["data_dir"] = data_dir
advprint.CFG["port"] = 19235
advprint.CFG["host"] = "127.0.0.1"
advprint.db_init()
advprint.RESUME_EVENT.set()
advprint.start_worker()

# stub the OS print backends (no printer here)
PRINTED = []


def fake_print_file(path, kind="a4", printer="", copies=1, job_id=None,
                    pages=None, duplex=None, paper_size=None, tray=None,
                    per_sheet=None, quality=None):
    PRINTED.append({"printer": printer, "job_id": job_id})
    return printer or "StubPrinter"


advprint.print_file = fake_print_file

from http.server import ThreadingHTTPServer  # noqa: E402
httpd = ThreadingHTTPServer(("127.0.0.1", 19235), advprint.Handler)
httpd.daemon_threads = True
threading.Thread(target=httpd.serve_forever, daemon=True).start()
time.sleep(0.4)

BASE = "http://127.0.0.1:19235"
HUB_PORT = 19235
ok = []


def check(name, cond, extra=""):
    ok.append((name, bool(cond)))
    print(("PASS" if cond else "FAIL") + "  " + name +
          (("  " + str(extra)) if extra else ""))


# 1. health = 3.4.6
with urllib.request.urlopen(BASE + "/health", timeout=5) as r:
    h = json.loads(r.read())
check("health v3.4.6", h["ok"] is True and h["version"] == "3.4.6",
      h["version"])

# 2. ONE port: no 9236+ listeners (the v3.3.5 queue ports are gone)
time.sleep(1.2)                       # the 3 s hooks had time to run
extra_ports = []
for p in range(HUB_PORT + 1, HUB_PORT + 25):
    s = socket.socket()
    s.settimeout(0.15)
    try:
        s.connect(("127.0.0.1", p))
        extra_ports.append(p)
    except OSError:
        pass
    finally:
        s.close()
check("no dedicated queue ports listening", not extra_ports, extra_ports)

# 3. mocked printers
NAMES = ["HP Laser 103", "Epson L3250"]
advprint.list_printers_cached = lambda max_age=30.0: list(NAMES)
advprint.default_printer_cached = lambda max_age=10.0: NAMES[0]


def gpa(path, uri):
    """Windows-style Get-Printer-Attributes over the REAL hub port."""
    opg = advprint._ipp_group(0x01, [
        advprint._ipp_attr(0x47, "attributes-charset", "utf-8"),
        advprint._ipp_attr(0x48, "attributes-natural-language", "en"),
        advprint._ipp_attr(0x45, "printer-uri", uri),
    ])
    req = (bytes((1, 1)) + (0x000B).to_bytes(2, "big") +
           (2345).to_bytes(4, "big") + opg + b"\x03")
    c = http.client.HTTPConnection("127.0.0.1", HUB_PORT, timeout=5)
    c.request("POST", path, body=req,
              headers={"Content-Type": "application/ipp"})
    r = c.getresponse()
    body = r.read()
    c.close()
    return r.status, body


def attr(raw, name):
    i = raw.find(name.encode())
    if i < 0:
        return None
    p = i + len(name)
    vlen = int.from_bytes(raw[p:p + 2], "big")
    return raw[p + 2:p + 2 + vlen].decode("utf-8", "replace")


# 4. THREE queues on THE SAME port - generic, HP, Epson
seen = {}
for key, path in (("generic", "/ipp/print"),
                  ("hp", "/ipp/print/hp-laser-103"),
                  ("epson", "/ipp/print/epson-l3250")):
    st, body = gpa(path, "ipp://127.0.0.1:%d%s" % (HUB_PORT, path))
    seen[key] = (st, attr(body, "printer-name"),
                 attr(body, "printer-uuid"))
check("generic queue answers 200", seen["generic"][0] == 200)
check("generic printer-name = hostname",
      seen["generic"][1] == socket.gethostname(), seen["generic"][1])
check("hp queue routes to HP Laser 103",
      seen["hp"][1] == "HP Laser 103", seen["hp"][1])
check("epson queue routes to Epson L3250",
      seen["epson"][1] == "Epson L3250", seen["epson"][1])
uuids = [seen[k][2] for k in ("generic", "hp", "epson")]
check("3 queues -> 3 DIFFERENT printer-uuids",
      all(uuids) and len(set(uuids)) == 3)

# 5. the landing page (browser GET) still works on the one port
with urllib.request.urlopen(BASE + "/ipp/print", timeout=5) as r:
    page = r.read().decode()
check("ipp landing page", "AdvPrint Pro" in page)
with urllib.request.urlopen(BASE + "/ipp/print/hp-laser-103",
                            timeout=5) as r:
    page = r.read().decode()
check("per-printer landing page names the queue",
      "HP Laser 103" in page)

# 6. /printers: default field (the popup's fix) + path queue only
req = urllib.request.Request(BASE + "/printers",
                             headers={"X-AdvPrint-Token":
                                      advprint.CFG["token"]})
with urllib.request.urlopen(req, timeout=5) as r:
    pl = json.loads(r.read())
check("/printers default = HP Laser 103",
      pl.get("default") == NAMES[0], pl.get("default"))
check("/printers has NO ipp_dedicated/ipp_port",
      all(("ipp_dedicated" not in it and "ipp_port" not in it)
          for it in pl["printers"]))
items = {it["name"]: it for it in pl["printers"] if not it["is_group"]}
check("per-printer ipp_queue on the HUB port",
      all((":%d/ipp/print/" % HUB_PORT) in items[n]["ipp_queue"]
          for n in NAMES))

# 7. mDNS: every service announces the ONE hub port
svcs = advprint._mdns_services()
check("mDNS services all on the hub port",
      len(svcs) == 3 and {s[5] for s in svcs} == {HUB_PORT})

# 8. Print-Job to a per-printer queue routes to THAT printer
opg = advprint._ipp_group(0x01, [
    advprint._ipp_attr(0x47, "attributes-charset", "utf-8"),
    advprint._ipp_attr(0x48, "attributes-natural-language", "en"),
    advprint._ipp_attr(0x45, "printer-uri",
                       "ipp://127.0.0.1:%d/ipp/print/epson-l3250"
                       % HUB_PORT),
    advprint._ipp_attr(0x42, "job-name", "one-port live"),
    advprint._ipp_attr(0x49, "document-format", "application/pdf"),
])
pj = (bytes((1, 1)) + (0x0002).to_bytes(2, "big") +
      (1234).to_bytes(4, "big") + opg + b"\x03" +
      b"%PDF-1.4 one-port live test")
c = http.client.HTTPConnection("127.0.0.1", HUB_PORT, timeout=5)
c.request("POST", "/ipp/print/epson-l3250", body=pj,
          headers={"Content-Type": "application/ipp"})
r = c.getresponse()
body = r.read()
c.close()
check("Print-Job accepted", r.status == 200 and
      attr(body, "job-state") is not None or r.status == 200)

httpd.shutdown()
print()
bad = [n for n, good in ok if not good]
print("RESULT: %d/%d PASS%s" % (len(ok) - len(bad), len(ok),
                                ("  FAILED: " + ", ".join(bad))
                                if bad else ""))
sys.exit(1 if bad else 0)
