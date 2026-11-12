#!/usr/bin/env python3
"""Live v3.3.1 smoke: boot the REAL hub (unix copy) on a random port and
verify the four release fixes over HTTP exactly like the user runs them:

  1. BUG 1 - the RFC 8011 uri triple: Get-Printer-Attributes on the
     generic queue AND a per-printer queue carries printer-uri-supported
     / uri-authentication-supported / uri-security-supported with EQUAL
     value counts and the client URI echoed (the exact validation the
     Microsoft IPP Class Driver runs during "Add Printer" - the missing
     triple was the "Windows couldn't connect to the printer" bug)
  2. BUG 2 - a per-printer queue resolves on a COLD printer cache (the
     resolver enumerates synchronously)
  3. BUG 4 - Share Send Mode: /config accepts share_send_all, /health
     exposes peer_forwarding / share_send_all / peer_hubs_count, and a
     queued job is forwarded to a fake LAN PC hub (or HELD when the peer
     is unreachable)
  4. the ONE UI console carries the REAL LAN PC card (ids present, the
     own-IP overwrite gone)
"""
import json
import os
import struct
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "tool", "unix", "hub"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import advprint  # noqa: E402

OK, BAD = [], []


def check(label, cond, detail=""):
    (OK if cond else BAD).append(label)
    print(("[OK]   " if cond else "[FAIL] ") + label +
          ("  " + detail if detail and not cond else ""))


# ---- IPP wire helpers ----
V_INT, V_ENUM, V_BOOL = 0x21, 0x23, 0x22
V_TEXT, V_NAME, V_KEYWORD = 0x41, 0x42, 0x44
V_URI, V_CHARSET, V_LANG = 0x45, 0x47, 0x48
T_OP, T_END, T_PRINTER = 0x01, 0x03, 0x04


def _attr(tag, name, value):
    nb = name.encode()
    vb = value if isinstance(value, bytes) else str(value).encode()
    return (bytes([tag]) + len(nb).to_bytes(2, "big") + nb +
            len(vb).to_bytes(2, "big") + vb)


def ipp_gpa(uri):
    b = bytes((1, 1)) + (0x000B).to_bytes(2, "big") + (7).to_bytes(4, "big")
    b += b"\x01" + _attr(V_CHARSET, "attributes-charset", "utf-8")
    b += _attr(V_LANG, "attributes-natural-language", "en")
    b += _attr(V_URI, "printer-uri", uri)
    b += b"\x03"
    return b


def parse_printer_group(raw):
    status = int.from_bytes(raw[2:4], "big")
    pr, i, n, last = None, 8, len(raw), ""
    while i < n:
        t = raw[i]
        if t == T_END:
            break
        if t in (T_OP, T_PRINTER, 0x02, 0x05):
            pr = [] if t == T_PRINTER else None
            i += 1
            continue
        nl = int.from_bytes(raw[i + 1:i + 3], "big"); i += 3
        nm = raw[i:i + nl].decode("utf-8", "replace"); i += nl
        vl = int.from_bytes(raw[i:i + 2], "big"); i += 2
        v = raw[i:i + vl]; i += vl
        if pr is None:
            continue
        if t == V_INT and len(v) == 4:
            v = str(struct.unpack(">i", v)[0])
        elif t in (V_TEXT, V_NAME, V_KEYWORD, V_URI, V_CHARSET, V_LANG):
            v = v.decode("utf-8", "replace")
        else:
            v = "<bin %d>" % len(v)
        if not nm:
            nm = last
        else:
            last = nm
        pr.append((nm, v))
    return status, pr


def vals(pr, name):
    return [v for (nm, v) in pr if nm == name]


class PeerHub(BaseHTTPRequestHandler):
    jobs = []

    def log_message(self, *a):
        pass

    def do_GET(self):
        body = json.dumps({"ok": True, "version": advprint.VERSION,
                           "share_lan": True,
                           "hostname": "SMOKE-PEER"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        data = self.rfile.read(n)
        PeerHub.jobs.append(json.loads(data))
        body = json.dumps({"ok": True, "job_id": "smoke-peer-1"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def http_post_ipp(port, path, body):
    import urllib.request
    req = urllib.request.Request(
        "http://127.0.0.1:%d%s" % (port, path), data=body,
        headers={"Content-Type": "application/ipp"})
    return urllib.request.urlopen(req, timeout=8).read()


def main():
    advprint.CFG["data_dir"] = tempfile.mkdtemp(prefix="ap-smoke-")
    advprint.CFG["port"] = 0
    advprint.CFG["host"] = "127.0.0.1"
    advprint.CFG["share_lan"] = True
    advprint.db_init()
    advprint.RESUME_EVENT.set()
    advprint.start_worker()
    advprint.print_file = lambda *a, **k: (k.get("printer") or "Stub")
    advprint.print_raw = lambda *a, **k: "Stub"
    advprint.list_printers = lambda: ["HP-Laser-103", "AI-Lab"]

    from http.server import ThreadingHTTPServer
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), advprint.Handler)
    httpd.daemon_threads = True
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    token = advprint.CFG["token"]
    base = "http://127.0.0.1:%d" % port
    print("smoke hub on %s (v%s)" % (base, advprint.VERSION))

    hdr = {"X-AdvPrint-Token": token, "Content-Type": "application/json"}

    # ---- 1. the RFC 8011 uri triple ----
    import urllib.request
    for path in ("/ipp/print", "/ipp/print/HP-Laser-103"):
        uri = "http://192.168.1.101:%d%s" % (port, path)
        raw = http_post_ipp(port, path, ipp_gpa(uri))
        status, pr = parse_printer_group(raw)
        uris = vals(pr, "printer-uri-supported")
        auths = vals(pr, "uri-authentication-supported")
        secs = vals(pr, "uri-security-supported")
        check("IPP %s: successful-ok" % path, status == 0)
        check("IPP %s: uri triple parallel (%d/%d/%d)"
              % (path, len(uris), len(auths), len(secs)),
              len(uris) == len(auths) == len(secs) > 0)
        check("IPP %s: uri-security-supported all 'none'" % path,
              bool(secs) and all(v == "none" for v in secs))
        check("IPP %s: client URI echoed" % path, uri in uris)
    # per-printer queue name
    raw = http_post_ipp(port, "/ipp/print/HP-Laser-103",
                        ipp_gpa("http://192.168.1.101:%d/ipp/print/"
                                "HP-Laser-103" % port))
    _, pr = parse_printer_group(raw)
    check("per-printer queue printer-name", "HP-Laser-103" in vals(pr,
          "printer-name"))

    # ---- 2. cold-cache queue resolution ----
    advprint._LP_CACHE["t"] = 0.0
    advprint._LP_CACHE["v"] = []
    advprint._QMATCH_CACHE.clear()
    advprint._LP_SYNC_TS[0] = 0.0
    check("cold cache resolves per-printer queue",
          advprint._ipp_queue_match("AI-Lab") == "AI-Lab")

    # ---- 3. Share Send Mode ----
    psrv = ThreadingHTTPServer(("127.0.0.1", 0), PeerHub)
    threading.Thread(target=psrv.serve_forever, daemon=True).start()
    peer = "http://127.0.0.1:%d" % psrv.server_address[1]
    req = urllib.request.Request(base + "/peer-probe", data=json.dumps(
        {"url": peer, "token": "smoke"}).encode(),
        headers=dict(hdr, **{"Content-Type": "application/json"}))
    probe = json.loads(urllib.request.urlopen(req, timeout=8).read())
    check("/peer-probe sees the fake LAN PC",
          probe.get("ok") and probe.get("up") and
          probe.get("hostname") == "SMOKE-PEER")

    req = urllib.request.Request(base + "/config", data=json.dumps(
        {"peer_hubs": [{"url": peer, "token": "smoke",
                        "name": "SMOKE-PEER"}],
         "peer_forwarding": True, "share_send_all": True}).encode(),
        headers=hdr)
    urllib.request.urlopen(req, timeout=8).read()
    h = advprint.health_snapshot()
    check("health carries share-send keys",
          h.get("peer_forwarding") is True and
          h.get("share_send_all") is True and
          h.get("peer_hubs_count") == 1)

    pdf = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
           b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
           b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]>>endobj"
           b"\ntrailer<</Root 1 0 R>>\n%%EOF")
    jid = advprint.enqueue_print("pdf", "smoke-share-send", pdf,
                                 source="smoke")[0]
    end = time.time() + 8
    st = None
    while time.time() < end:
        st = advprint.db_get(jid).get("status")
        if st in ("forwarded", "held", "failed", "printed"):
            break
        time.sleep(0.05)
    check("Share Send Mode forwards the job", st == "forwarded",
          "status=%s" % st)
    check("the LAN PC hub received the document", len(PeerHub.jobs) >= 1)
    req = urllib.request.Request(base + "/config", data=json.dumps(
        {"peer_hubs": [], "peer_forwarding": False,
         "share_send_all": False}).encode(), headers=hdr)
    urllib.request.urlopen(req, timeout=8).read()

    # ---- 4. the REAL LAN PC card in the console ----
    con = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "tool", "unix", "hub",
        "console.html"), encoding="utf-8").read()
    for frag in ('id="lanPcCard"', 'id="lanPcConnect"', 'id="lanPcClear"',
                 'id="lanPcSendSw"', 'api("/peer-probe"',
                 'share_send_all: want'):
        check("console carries %s" % frag, frag in con)
    check("console no longer overwrites the LAN PC URL with own IP",
          "pcUrl.value = lanBase()" not in con)
    check("console boot version current",
          'BOOT.version || "%s"' % advprint.VERSION in con)

    psrv.shutdown()
    print()
    if BAD:
        print("SMOKE FAILED: %d checks:" % len(BAD))
        for b in BAD:
            print("  - " + b)
        return 1
    print("v3.3.1 smoke: ALL %d CHECKS PASSED" % len(OK))
    return 0


if __name__ == "__main__":
    sys.exit(main())
