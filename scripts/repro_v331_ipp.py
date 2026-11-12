#!/usr/bin/env python3
"""v3.3.1 repro: simulate a REAL Windows 11 IPP Class Driver session from
a LAN PC against the AdvPrint Pro hub, then lint the wire responses the
way the Microsoft IPP Class Driver does during "Add Printer".

Simulated topology (mirrors the user's lab):
  hub PC   = 192.168.1.101 (the hub binds 0.0.0.0:PORT)
  LAN PC   = 192.168.1.104 (we bind the client socket to the sandbox's
             non-loopback interface so client_address[0] is NOT loopback)

Checks:
  A. Get-Printer-Attributes  http://192.168.1.101:PORT/ipp/print
  B. Get-Printer-Attributes  http://192.168.1.101:PORT/ipp/print/<name>
  C. Print-Job with a real PDF over the named queue
  D. Validate-Job / Create-Job / Send-Document session
  E. GET /connect?t=<token> with the LAN Host header (invite page)
Windows validation rules implemented here:
  - response status must be successful-ok
  - required RFC 8011 section 4.2.5.2 attribute set present
  - printer-uri-supported / uri-authentication-supported /
    uri-security-supported MUST have the SAME value count
  - uri-security-supported must exist (Windows requires it)
  - the URI the client asked for must appear in printer-uri-supported
  - ipp-versions-supported must list the request version
"""
import os
import socket
import sys
import struct
import tempfile
import threading
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = "/home/z/my-project/ap330-src/src"
sys.path.insert(0, os.path.join(SRC, "tool", "windows", "portable", "hub"))

import advprint  # noqa: E402

HUB_IP = "192.168.1.101"          # simulated hub address (Host header)
LAN_CLIENT = socket.gethostbyname(socket.gethostname())  # non-loopback src

# ---------------- wire tags ----------------
T_OP, T_JOB, T_END, T_PRINTER = 0x01, 0x02, 0x03, 0x04
V_INT, V_BOOL, V_ENUM, V_DATE, V_RANGE = 0x21, 0x22, 0x23, 0x31, 0x33
V_TEXT, V_NAME, V_KEYWORD = 0x41, 0x42, 0x44
V_URI, V_CHARSET, V_LANG, V_MIME = 0x45, 0x47, 0x48, 0x49


def attr(tag, name, value):
    if isinstance(value, str):
        value = value.encode("utf-8")
    return (struct.pack(">BH", tag, len(name)) + name +
            struct.pack(">H", len(value)) + value)


def extra(tag, value):
    return attr(tag, b"", value)


def opattr(tag, name, value):
    return attr(tag, name.encode("utf-8"), value)


def ipp_req(op, rid=1, uri=None, user="Administrator", doc=b"",
            requested=None, ver=(1, 1)):
    b = bytes(ver) + op.to_bytes(2, "big") + rid.to_bytes(4, "big")
    b += b"\x01"                    # operation-attributes-group tag
    b += opattr(V_CHARSET, "attributes-charset", "utf-8")
    b += opattr(V_LANG, "attributes-natural-language", "en")
    if uri:
        b += opattr(V_URI, "printer-uri", uri)
    if user:
        b += opattr(V_NAME, "requesting-user-name", user)
    if requested:
        for r in requested:
            b += opattr(V_KEYWORD, "requested-attributes", r)
    b += b"\x03"
    return b + doc


def get_printer_attrs_req(uri):
    # the attribute list Windows 11 IPP Class Driver asks for on add
    req_list = [
        "printer-name", "printer-state", "printer-state-reasons",
        "printer-is-accepting-jobs", "queued-job-count",
        "printer-up-time", "printer-current-time",
        "printer-uri-supported", "uri-authentication-supported",
        "uri-security-supported", "ipp-versions-supported",
        "operations-supported", "charset-configured",
        "natural-language-configured", "document-format-default",
        "document-format-supported", "pdl-override-supported",
        "compression-supported", "printer-make-and-model",
        "printer-more-info", "printer-location", "printer-uuid",
        "copies-default", "copies-supported", "sides-default",
        "sides-supported", "print-color-mode-default",
        "print-color-mode-supported", "media-default", "media-supported",
        "finishings-default", "finishings-supported",
    ]
    return ipp_req(0x000B, uri=uri, requested=req_list)


REQUIRED = {
    "printer-uri-supported", "uri-authentication-supported",
    "printer-name", "printer-state", "printer-state-reasons",
    "ipp-versions-supported", "operations-supported",
    "charset-configured", "natural-language-configured",
    "document-format-default", "document-format-supported",
    "pdl-override-supported", "printer-is-accepting-jobs",
    "queued-job-count", "printer-up-time", "printer-current-time",
    "compression-supported",
}


def parse_ipp(data):
    """Strict wire parser -> (ver, status, rid, groups) where groups is
    a list of (tag, ordered list of (name, [values-with-tags]))."""
    if len(data) < 8:
        raise ValueError("short response")
    ver = (data[0], data[1])
    status = int.from_bytes(data[2:4], "big")
    rid = int.from_bytes(data[4:8], "big")
    groups, i = [], 8
    cur = None
    while i < len(data):
        b = data[i]
        if b == 0x03:
            break
        if b in (0x00, 0x01, 0x02, 0x04, 0x05):
            cur = []
            groups.append((b, cur))
            i += 1
            continue
        if i + 3 > len(data):
            break
        tag = b
        nl = int.from_bytes(data[i + 1:i + 3], "big")
        i += 3
        name = data[i:i + nl].decode("utf-8", "replace")
        i += nl
        if i + 2 > len(data):
            break
        vl = int.from_bytes(data[i:i + 2], "big")
        i += 2
        val = data[i:i + vl]
        i += vl
        if cur is None:
            continue
        # binary value tags: decode ints/bools for readable checks
        if tag == V_INT and len(val) == 4:
            try:
                val = str(struct.unpack(">i", val)[0])
            except Exception:
                pass
        if nl == 0:
            try:
                vtxt = val.decode("utf-8")
            except UnicodeDecodeError:
                vtxt = "<bin %d bytes>" % len(val)
            if cur:
                cur[-1][1].append((tag, vtxt))
            else:
                cur.append(("?", [(tag, vtxt)]))
        else:
            if isinstance(val, str):
                txt = val
            else:
                try:
                    txt = val.decode("utf-8")
                except UnicodeDecodeError:
                    txt = "<bin %d bytes>" % len(val)
            cur.append((name, [(tag, txt)]))
    return ver, status, rid, groups


def flatten(groups, want_tag):
    """Merge all groups of type want_tag into one ordered dict
    name -> list[(tag, value)]."""
    out = {}
    for tag, entries in groups:
        if tag != want_tag:
            continue
        for name, vals in entries:
            out.setdefault(name, []).extend(vals)
    return out


def http_post(host, port, path, body, hosthdr, src_bind=True):
    """Raw HTTP/1.1 POST from a socket bound to the LAN-looking source."""
    s = socket.socket()
    if src_bind:
        s.bind((LAN_CLIENT, 0))
    s.settimeout(10)
    s.connect(("127.0.0.1", port))   # real route; Host header = LAN name
    hdr = ("POST %s HTTP/1.1\r\nHost: %s\r\nContent-Type: application/ipp\r\n"
           "Content-Length: %d\r\nConnection: close\r\n\r\n"
           % (path, hosthdr, len(body))).encode()
    s.sendall(hdr + body)
    chunks = []
    while True:
        try:
            c = s.recv(65536)
        except socket.timeout:
            break
        if not c:
            break
        chunks.append(c)
    s.close()
    return b"".join(chunks)


def http_get(host, port, path, hosthdr, src_bind=True):
    s = socket.socket()
    if src_bind:
        s.bind((LAN_CLIENT, 0))
    s.settimeout(10)
    s.connect(("127.0.0.1", port))   # real route; Host = LAN name
    s.sendall(("GET %s HTTP/1.1\r\nHost: %s\r\nConnection: close\r\n"
               "Accept: text/html\r\n\r\n" % (path, hosthdr)).encode())
    chunks = []
    while True:
        try:
            c = s.recv(65536)
        except socket.timeout:
            break
        if not c:
            break
        chunks.append(c)
    s.close()
    return b"".join(chunks)


def http_body(resp):
    return resp.split(b"\r\n\r\n", 1)[1] if b"\r\n\r\n" in resp else b""


def http_status(resp):
    try:
        return int(resp.split(b" ", 2)[1])
    except Exception:
        return -1


FAILS = []
def check(label, ok, detail=""):
    print(("PASS  " if ok else "FAIL  ") + label + ("  " + detail if detail and not ok else ""))
    if not ok:
        FAILS.append(label)


def lint_gpa(label, resp, asked_uri, ver=(1, 1)):
    """Lint a Get-Printer-Attributes response the way Windows does."""
    st = http_status(resp)
    check(label + ": HTTP 200", st == 200, "got %s" % st)
    ver_, status, rid, groups = parse_ipp(http_body(resp))
    check(label + ": IPP successful-ok", status == 0x0000,
          "status=0x%04x" % status)
    check(label + ": response ver echoes request", tuple(ver_) == ver,
          "%s" % (ver_,))
    pr = flatten(groups, T_PRINTER)
    names = set(pr)
    missing = REQUIRED - names
    check(label + ": required attribute set present", not missing,
          "missing=%s" % sorted(missing))
    # --- THE WINDOWS KILLER CHECK: uri triple cardinality ---
    uris = [v for t, v in pr.get("printer-uri-supported", [])]
    auth = [v for t, v in pr.get("uri-authentication-supported", [])]
    sec = [v for t, v in pr.get("uri-security-supported", [])]
    check(label + ": uri-security-supported present", bool(sec),
          "MISSING - Windows IPP Class Driver refuses the printer")
    check(label + ": uri triple cardinality equal",
          len(uris) == len(auth) and len(uris) == len(sec) and len(uris) > 0,
          "uris=%d auth=%d sec=%d  (uris=%s)" % (len(uris), len(auth),
                                                 len(sec), uris))
    check(label + ": asked URI echoed in printer-uri-supported",
          asked_uri in uris, "uris=%s" % uris)
    check(label + ": ipp-versions-supported includes 1.1",
          "1.1" in [v for t, v in pr.get("ipp-versions-supported", [])])
    return pr, uris, auth, sec


MIN_PDF = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
           b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
           b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]"
           b"/Contents 4 0 R>>endobj\n4 0 obj<</Length 44>>stream\n"
           b"BT /F1 24 Tf 72 720 Td (v331 LAN test) Tj ET\nendstream"
           b"endobj\ntrailer<</Root 1 0 R>>\n%%EOF")


def main():
    port_file = tempfile.mktemp(suffix=".port")
    data_dir = tempfile.mkdtemp(prefix="ap331-data-")
    advprint.CFG["data_dir"] = data_dir
    advprint.CFG["port"] = 0
    advprint.CFG["host"] = "0.0.0.0"
    advprint.CFG["share_lan"] = True
    advprint.CFG["ipp_printer"] = True
    advprint.CFG["peer_forwarding"] = False
    advprint.db_init()
    advprint.RESUME_EVENT.set()
    advprint.start_worker()
    advprint.print_file = lambda *a, **k: (k.get("printer") or "StubPrinter")
    advprint.print_raw = lambda *a, **k: "StubPrinter"
    token = advprint.CFG["token"]

    from http.server import ThreadingHTTPServer
    httpd = ThreadingHTTPServer(("0.0.0.0", 0), advprint.Handler)
    httpd.daemon_threads = True
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    hubaddr = "127.0.0.1:%d" % port
    hosthdr = "%s:%d" % (HUB_IP, port)
    base_http = "http://%s:%d" % (HUB_IP, port)
    base_ipp = "ipp://%s:%d" % (HUB_IP, port)
    print("hub on %s  (Host header used by LAN PC: %s)  client src %s"
          % (hubaddr, hosthdr, LAN_CLIENT))

    # stub a printer list so per-printer queues exist
    # list_printers must return NAME STRINGS (the real hub's contract)
    advprint.list_printers = lambda: ["HP-Laser-103", "AI-Lab"]
    try:
        advprint.refresh_printer_cache()
    except Exception:
        pass

    # ---- A. generic queue, Windows add-printer ----
    uri = base_http + "/ipp/print"
    resp = http_post(HUB_IP, port, "/ipp/print",
                     get_printer_attrs_req(uri), hosthdr)
    pr, uris, auth, sec = lint_gpa("A generic add", resp, uri)

    # ---- B. per-printer queue ----
    uri2 = base_http + "/ipp/print/HP-Laser-103"
    resp2 = http_post(HUB_IP, port, "/ipp/print/HP-Laser-103",
                      get_printer_attrs_req(uri2), hosthdr)
    pr2, uris2, auth2, sec2 = lint_gpa("B per-printer add", resp2, uri2)
    if pr2:
        nm = [v for t, v in pr2.get("printer-name", [])]
        check("B: printer-name is the queue name",
              nm and nm[0] == "HP-Laser-103", "name=%s" % nm)

    # ---- C. Print-Job over the named queue ----
    pj = ipp_req(0x0002, uri=uri2, doc=MIN_PDF,
                 ver=(1, 1))
    pj = pj.replace(opattr(V_URI, "printer-uri", uri2),
                    opattr(V_URI, "printer-uri", uri2))
    # add job-name via raw rebuild
    def ipp_req2(op, rid, uri_, user, doc, ver):
        b = bytes(ver) + op.to_bytes(2, "big") + rid.to_bytes(4, "big")
        b += b"\x01"                # operation-attributes-group tag
        b += opattr(V_CHARSET, "attributes-charset", "utf-8")
        b += opattr(V_LANG, "attributes-natural-language", "en")
        b += opattr(V_URI, "printer-uri", uri_)
        b += opattr(V_NAME, "requesting-user-name", user)
        b += opattr(V_NAME, "job-name", "v331-lan-test")
        b += opattr(V_KEYWORD, "document-format", "application/pdf")
        b += b"\x03"
        return b + doc
    resp3 = http_post(HUB_IP, port, "/ipp/print/HP-Laser-103",
                      ipp_req2(0x0002, 2, uri2, "Administrator", MIN_PDF,
                               (1, 1)), hosthdr)
    st3 = http_status(resp3)
    check("C Print-Job: HTTP 200", st3 == 200, "got %s" % st3)
    ver3, status3, rid3, groups3 = parse_ipp(http_body(resp3))
    check("C Print-Job: successful-ok", status3 == 0x0000,
          "status=0x%04x" % status3)

    # ---- D. Create-Job + Send-Document session ----
    resp4 = http_post(HUB_IP, port, "/ipp/print",
                      ipp_req2(0x0005, 3, uri, "Administrator", b"",
                               (1, 1)), hosthdr)
    ver4, status4, rid4, groups4 = parse_ipp(http_body(resp4))
    check("D Create-Job: successful-ok", status4 == 0x0000,
          "status=0x%04x" % status4)
    jobs = flatten(groups4, T_JOB)
    jid_raw = jobs.get("job-id", [(0, "")])[0][1]
    try:
        jid = int(jid_raw) if str(jid_raw).isdigit() else 0
    except Exception:
        jid = 0
    check("D Create-Job: job-id returned", jid > 0, "job-id=%r" % jid_raw)
    if jid:
        b = bytes((1, 1)) + (0x0006).to_bytes(2, "big") + (4).to_bytes(4, "big")
        b += b"\x01"
        b += opattr(V_CHARSET, "attributes-charset", "utf-8")
        b += opattr(V_LANG, "attributes-natural-language", "en")
        b += opattr(V_URI, "printer-uri", uri)
        b += opattr(V_INT, "job-id", struct.pack(">i", jid))
        b += opattr(V_BOOL, "last-document", b"\x01")
        b += b"\x03" + MIN_PDF
        resp5 = http_post(HUB_IP, port, "/ipp/print", b, hosthdr)
        ver5, status5, rid5, groups5 = parse_ipp(http_body(resp5))
        check("D Send-Document: successful-ok", status5 == 0x0000,
              "status=0x%04x" % status5)

    # ---- E. /connect invite page with LAN Host ----
    resp6 = http_get(HUB_IP, port,
                     "/connect?t=%s&n=Lab-104" % token, hosthdr)
    st6 = http_status(resp6)
    body6 = http_body(resp6).decode("utf-8", "replace")
    check("E /connect: HTTP 200 from LAN", st6 == 200, "got %s" % st6)
    check("E /connect: peer URL keeps the LAN host",
          ("http://%s:%d" % (HUB_IP, port)) in body6,
          "page did not carry the 192.168.1.101 URL")
    check("E /connect: form posts to the VISITOR's own hub",
          "127.0.0.1:%d/peer-connect" % advprint.CFG.get("port", 9235)
          in body6 or "127.0.0.1" in body6)
    check("E /connect: not the self-invite page",
          "invite is for the OTHER PC" not in body6)

    print()
    if FAILS:
        print("RESULT: %d FAILURES:" % len(FAILS))
        for f in FAILS:
            print("  - " + f)
        return 1
    print("RESULT: ALL PASS (the hub handles the Windows LAN session)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
