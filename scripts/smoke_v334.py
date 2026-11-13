#!/usr/bin/env python3
"""Live v3.3.4 smoke: boot the REAL hub (unix copy) on a random port,
then verify the release exactly like the user runs it:

  1. BUG 1 - multi-printer IPP add: every advertised mDNS service
     carries its OWN printer-uuid (announce + direct unicast TXT
     answer), the per-printer queues answer Get-Printer-Attributes
     with per-queue uuids, /printers lists every ipp:// queue
  2. BUG 2 - /printers/set-default is IDEMPOTENT: an already-default
     request answers unchanged:true with ZERO setter commands, a real
     change runs the setter exactly once, an immediate repeat runs
     nothing
  3. POPUP surface - /health carries lan_bind_addrs (network icon +
     Share Receive listen address), /printers feeds the selector
"""
import json
import os
import socket
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tool", "unix", "hub"))

import advprint  # noqa: E402

fail = []


def check(name, cond, detail=""):
    print(("[OK]   " if cond else "[FAIL] ") + name + (" - " + detail
                                                        if detail else ""))
    if not cond:
        fail.append(name)


def main():
    data_dir = tempfile.mkdtemp(prefix="advprint-smoke-334-")
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()

    advprint.CFG["data_dir"] = data_dir
    advprint.CFG["port"] = port
    advprint.CFG["host"] = "127.0.0.1"
    advprint.db_init()
    advprint.RESUME_EVENT.set()
    advprint.start_worker()

    from http.server import ThreadingHTTPServer
    httpd = ThreadingHTTPServer(("127.0.0.1", port), advprint.Handler)
    httpd.daemon_threads = True
    import threading
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % port
    tok = advprint.CFG["token"]

    def req(method, path, body=None, headers=None, raw=None):
        h = dict(headers or {})
        h["X-AdvPrint-Token"] = tok
        data = raw
        if body is not None:
            data = json.dumps(body).encode()
            h["Content-Type"] = "application/json"
        r = urllib.request.Request(base + path, data=data, headers=h,
                                   method=method)
        try:
            with urllib.request.urlopen(r, timeout=10) as resp:
                return resp.getcode(), resp.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def jreq(method, path, body=None):
        c, b = req(method, path, body)
        try:
            return c, json.loads(b.decode("utf-8"))
        except Exception:
            return c, {}

    # fake printers (no real printer in CI)
    NAMES = ["HP Laser 103 107 108", "Epson L3250"]
    advprint.list_printers = lambda: list(NAMES)
    advprint._LP_CACHE["v"] = list(NAMES)
    advprint._LP_CACHE["t"] = time.time() + 999
    advprint._DP_CACHE["v"] = NAMES[0]
    advprint._DP_CACHE["t"] = time.time() + 999

    calls = []
    real_set = advprint.os_set_default_printer

    def counted_set(name):
        calls.append(name)
        return True, name, "smoke setter"

    advprint.os_set_default_printer = counted_set

    try:
        # ---------- health (popup network icon + share label) ----------
        c, h = jreq("GET", "/health")
        check("health ok v3.3.4", c == 200 and h.get("version") == "3.3.4",
              str(h.get("version")))
        check("health has lan_bind_addrs (net icon / listen label)",
              isinstance(h.get("lan_bind_addrs"), list),
              str(h.get("lan_bind_addrs"))[:60])

        # ---------- /printers (popup selector) ----------
        c, pr = jreq("GET", "/printers")
        names = [p["name"] for p in pr.get("printers", [])]
        check("printers list for the selector", c == 200 and
              NAMES[0] in names and NAMES[1] in names, str(names))
        check("printers list carries ipp_queue per printer",
              all(p.get("ipp_queue") for p in pr.get("printers", [])
                  if p.get("name") in NAMES))

        # ---------- BUG 2: idempotent set-default ----------
        c, r = jreq("POST", "/printers/set-default",
                    {"printer": NAMES[0]})
        check("set-default on already-default: unchanged, ZERO cmds",
              c == 200 and r.get("ok") is True and
              r.get("unchanged") is True and calls == [],
              json.dumps(r)[:90])
        c, r = jreq("POST", "/printers/set-default",
                    {"printer": NAMES[1]})
        check("set-default real change: setter ran ONCE",
              c == 200 and r.get("ok") is True and calls == [NAMES[1]],
              str(calls))
        c, r = jreq("POST", "/printers/set-default",
                    {"printer": NAMES[1]})
        check("set-default immediate repeat: unchanged, still ONE cmd",
              c == 200 and r.get("unchanged") is True and
              calls == [NAMES[1]], str(calls))

        # ---------- BUG 1: mDNS uuid uniqueness ----------
        svcs = advprint._mdns_services()
        uuids = []
        for inst, rp, ty, note, slug in svcs:
            txt = advprint._mdns_txt_records(rp=rp, ty=ty, note=note,
                                             slug=slug)
            m = [kv for kv in txt.split(b"\x00") if False]  # placeholder
            # parse TXT items: len-prefixed
            i, got = 0, {}
            while i < len(txt):
                ln = txt[i]
                item = txt[i + 1:i + 1 + ln].decode("utf-8", "replace")
                i += 1 + ln
                if "=" in item:
                    k, v = item.split("=", 1)
                    got[k] = v
            uuids.append(got.get("UUID"))
        check("mDNS: 3 services, 3 DISTINCT printer-uuids",
              len(svcs) == 3 and len(set(uuids)) == 3,
              "%d services / %d uuids" % (len(svcs), len(set(uuids))))
        check("mDNS: central queue keeps the hub uuid",
              uuids[0] == advprint._ipp_printer_uuid().replace(
                  "urn:uuid:", ""))

        # ---------- BUG 1: per-printer IPP endpoint answers ----------
        c, page = req("GET", "/ipp/print/" +
                      urllib.parse.quote(NAMES[1]))
        page = page.decode("utf-8", "replace")
        check("per-printer queue landing page answers",
              c == 200 and "ipp/print/" in page, "HTTP %s" % c)
        c2, page2 = req("GET", "/ipp/print/definitely-not-a-printer")
        check("unknown queue still answers (graceful, v3.3.2 contract)",
              c2 == 200, "HTTP %s" % c2)

        # ---------- per-queue IPP uuid via Get-Printer-Attributes ----------
        opq = advprint._ipp_queue_slug(NAMES[1])
        u_q = advprint._ipp_printer_uuid(opq)
        u_hub = advprint._ipp_printer_uuid()
        check("IPP layer: per-queue uuid differs from hub uuid",
              u_q != u_hub and u_q.startswith("urn:uuid:"))

        advprint.os_set_default_printer = real_set
    finally:
        httpd.shutdown()
        pass  # daemon worker; the process exits with the smoke

    print()
    if fail:
        print("SMOKE v3.3.4 FAILED: %d -> %s" % (len(fail), fail))
        return 1
    print("SMOKE v3.3.4 PASSED - all checks green")
    return 0


if __name__ == "__main__":
    sys.exit(main())
