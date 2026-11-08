#!/usr/bin/env python3
"""v3.0.8 live smoke test: boot a real hub, then verify the professional
IPP printer end to end (Windows-style GPA, chunked Print-Job, jobs ops)
plus mDNS announce/answer packet checks - the exact requests Windows
10/11 "Add a printer -> IPP Device" sends."""
import http.client
import json
import os
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                    "AdvPrint-Pro")
sys.path.insert(0, os.path.join(ROOT, "tool", "windows", "portable", "hub"))
import advprint  # noqa: E402

data_dir = tempfile.mkdtemp(prefix="advprint-live-")
advprint.CFG["data_dir"] = data_dir
advprint.CFG["port"] = 19235
advprint.CFG["host"] = "127.0.0.1"
advprint.db_init()
advprint.RESUME_EVENT.set()
advprint.start_worker()

from http.server import ThreadingHTTPServer  # noqa: E402
httpd = ThreadingHTTPServer(("127.0.0.1", 19235), advprint.Handler)
httpd.daemon_threads = True
import threading
threading.Thread(target=httpd.serve_forever, daemon=True).start()
time.sleep(0.4)

BASE = "http://127.0.0.1:19235"
ok = []

# 1. health
with urllib.request.urlopen(BASE + "/health", timeout=5) as r:
    h = json.loads(r.read())
ok.append(("health", h["ok"] is True and h["version"] == "3.0.7"))

# 2. IPP info page (what a browser sees)
with urllib.request.urlopen(BASE + "/ipp/print", timeout=5) as r:
    page = r.read().decode()
ok.append(("info-page", "IPP Device" in page and "AdvPrint Pro" in page))

# 3. Windows-style Get-Printer-Attributes (exact MS Class Driver shape)
V_INT, V_BOOL, V_ENUM, V_DATE, V_RANGE = 0x21, 0x22, 0x23, 0x31, 0x33
V_TEXT, V_NAME, V_KEYWORD = 0x41, 0x42, 0x44
V_URI, V_CHARSET, V_LANG, V_MIME = 0x45, 0x47, 0x48, 0x49


def attr(tag, name, value):
    nb = name.encode()
    vb = value if isinstance(value, bytes) else value.encode()
    return bytes([tag]) + len(nb).to_bytes(2, "big") + nb + \
        len(vb).to_bytes(2, "big") + vb


def add(tag, value):
    return attr(tag, "", value)


def parse_resp(raw):
    """(status, groups) with a strict walk."""
    status = int.from_bytes(raw[2:4], "big")
    i = 8
    groups = []
    cur = None
    while i < len(raw):
        b = raw[i]
        if b == 0x03:
            break
        if b in (0x01, 0x02, 0x04, 0x05):
            cur = {}
            groups.append(cur)
            i += 1
            continue
        tag = b
        nl = int.from_bytes(raw[i + 1:i + 3], "big")
        name = raw[i + 3:i + 3 + nl].decode()
        i += 3 + nl
        vl = int.from_bytes(raw[i:i + 2], "big")
        val = raw[i + 2:i + 2 + vl]
        i += 2 + vl
        if nl == 0 and cur:
            key = list(cur)[-1] if cur else None
            if key:
                cur[key].append((tag, val))
            continue
        cur.setdefault(name, []).append((tag, val))
    return status, groups


req = bytearray()
req += bytes([1, 1]) + (0x000B).to_bytes(2, "big") + (42).to_bytes(4, "big")
req += bytes([0x01])
req += attr(V_CHARSET, "attributes-charset", "utf-8")
req += attr(V_LANG, "attributes-natural-language", "en")
req += attr(V_URI, "printer-uri", "http://127.0.0.1:19235/ipp/print")
req += attr(V_NAME, "requesting-user-name", "windows")
req += attr(V_KEYWORD, "requested-attributes", "all")
req += bytes([0x03])
conn = http.client.HTTPConnection("127.0.0.1", 19235, timeout=5)
conn.request("POST", "/ipp/print", body=bytes(req),
             headers={"Content-Type": "application/ipp"})
resp = conn.getresponse()
raw = resp.read()
conn.close()
status, groups = parse_resp(raw)
g = groups[1]
required = ("printer-uri-supported", "uri-authentication-supported",
            "printer-state", "printer-state-reasons",
            "ipp-versions-supported", "operations-supported",
            "charset-configured", "natural-language-configured",
            "document-format-default", "document-format-supported",
            "pdl-override-supported", "printer-is-accepting-jobs",
            "queued-job-count", "printer-up-time", "printer-current-time",
            "printer-name", "printer-make-and-model", "printer-uuid",
            "copies-supported", "media-default")
missing = [k for k in required if k not in g]
ok.append(("windows-GPA", status == 0 and resp.getheader("Content-Type")
           == "application/ipp" and not missing
           and g["printer-state"][0][0] == V_ENUM
           and len(g["printer-state"][0][1]) == 4
           and g["printer-is-accepting-jobs"][0][0] == V_BOOL
           and len(g["printer-is-accepting-jobs"][0][1]) == 1
           and g["queued-job-count"][0][0] == V_INT
           and g["copies-supported"][0][0] == V_RANGE
           and len(g["copies-supported"][0][1]) == 8
           and ("ipp://127.0.0.1:19235/ipp/print".encode()
                in [v for _t, v in g["printer-uri-supported"]])))
ok.append(("windows-GPA-missing", not missing))

# 4. chunked Print-Job (phone style)
MINI = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n"
pj = bytearray()
pj += bytes([1, 1]) + (0x0002).to_bytes(2, "big") + (43).to_bytes(4, "big")
pj += bytes([0x01])
pj += attr(V_CHARSET, "attributes-charset", "utf-8")
pj += attr(V_LANG, "attributes-natural-language", "en")
pj += attr(V_URI, "printer-uri", "http://127.0.0.1:19235/ipp/print")
pj += attr(V_NAME, "job-name", "live smoke pdf")
pj += attr(V_MIME, "document-format", "application/pdf")
pj += bytes([0x03]) + MINI
conn = http.client.HTTPConnection("127.0.0.1", 19235, timeout=5)
conn.putrequest("POST", "/ipp/print")
conn.putheader("Content-Type", "application/ipp")
conn.putheader("Transfer-Encoding", "chunked")
conn.endheaders()
half = len(pj) // 2
conn.send(b"%x\r\n" % half + bytes(pj[:half]) + b"\r\n")
conn.send(b"%x\r\n" % (len(pj) - half) + bytes(pj[half:]) + b"\r\n")
conn.send(b"0\r\n\r\n")
r2 = conn.getresponse()
raw2 = r2.read()
conn.close()
st2, gr2 = parse_resp(raw2)
jid = int.from_bytes(gr2[1]["job-id"][0][1], "big", signed=True)
ok.append(("chunked-print", st2 == 0 and jid >= 1
           and r2.getheader("Content-Type") == "application/ipp"))

# 5. Get-Jobs sees the job
qj = bytearray()
qj += bytes([1, 1]) + (0x000A).to_bytes(2, "big") + (44).to_bytes(4, "big")
qj += bytes([0x01])
qj += attr(V_CHARSET, "attributes-charset", "utf-8")
qj += attr(V_LANG, "attributes-natural-language", "en")
qj += attr(V_URI, "printer-uri", "http://127.0.0.1:19235/ipp/print")
qj += bytes([0x03])
conn = http.client.HTTPConnection("127.0.0.1", 19235, timeout=5)
conn.request("POST", "/ipp/print", body=bytes(qj),
             headers={"Content-Type": "application/ipp"})
r3 = conn.getresponse()
raw3 = r3.read()
conn.close()
st3, gr3 = parse_resp(raw3)
ids = [int.from_bytes(v, "big", signed=True)
       for gg in gr3[1:] for k in gg if k == "job-id"
       for _t, v in gg[k]]
ok.append(("get-jobs", st3 == 0 and jid in ids))

# 6. mDNS announce packet builds + query answering
ip = advprint.lan_ip()
pkt = advprint._mdns_packet(advprint._mdns_rrset(ip))
ok.append(("mdns-announce-len", 40 < len(pkt) < 1500))
# craft an iOS-style PTR query for _ipp._tcp.local and answer it
qname = advprint._mdns_encode_name("_ipp._tcp.local")
query = ((0).to_bytes(2, "big") +          # transaction id
         (0).to_bytes(2, "big") +          # flags
         (1).to_bytes(2, "big") +          # QDCOUNT (offset 4)
         (0).to_bytes(2, "big") +          # ANCOUNT
         (0).to_bytes(2, "big") +          # NSCOUNT
         (0).to_bytes(2, "big") +          # ARCOUNT
         qname + (12).to_bytes(2, "big") + (1).to_bytes(2, "big"))
qs = advprint._mdns_parse_questions(query)
ok.append(("mdns-query-parse", len(qs) == 1
           and qs[0][0] == "_ipp._tcp.local" and qs[0][1] == 12))
advprint._mdns_state["sock"] = "fake"
try:
    import io
    sent = {}

    class FakeSock:
        def sendto(self, data, addr):
            sent["data"] = data
            sent["addr"] = addr

    advprint._mdns_state["sock"] = FakeSock()
    advprint._mdns_answer_query(query, ("192.168.1.55", 5353), ip)
    ans = sent["data"]
    flags = int.from_bytes(ans[2:4], "big")
    ancount = int.from_bytes(ans[6:8], "big")
    ok.append(("mdns-answer", flags == 0x8400 and ancount >= 4
               and b"AdvPrint Pro" in ans and b"ipp/print" in ans))
finally:
    advprint._mdns_state["sock"] = None

# 7. audit trail has the IPP job
with urllib.request.urlopen(
        BASE + "/audit?token=" + advprint.CFG["token"], timeout=5) as r:
    audit = json.loads(r.read())
entries = audit.get("entries", []) if isinstance(audit, dict) else []
events = [a.get("event", "") for a in entries][:20]
ok.append(("audit", any(e.startswith("print") for e in events)))

httpd.shutdown()
advprint._WORK_STOP = True

print("\n=== LIVE SMOKE RESULTS ===")
allok = True
for name, val in ok:
    print("  %-24s %s" % (name, "PASS" if val is True else
                          ("FAIL %s" % val) if val is not True else val))
    if val is not True:
        allok = False
print("=== %s ===" % ("ALL PASS" if allok else "SOME FAILED"))
sys.exit(0 if allok else 1)
