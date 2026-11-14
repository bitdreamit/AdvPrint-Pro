"""v3.2.9 - THE MULTI-PC IPP RELEASE.

Locks the three user-reported multi-PC bugs end to end:

BUG 1 - a per-printer queue (ipp://ip:9235/ipp/print/<printer-name>)
  refused to connect from OTHER PCs while the generic /ipp/print kept
  working: Get-Printer-Attributes answered with only the generic
  printer-uri-supported pair, so the client never saw the queue URI it
  asked for. v3.2.9 echoes the queue end to end - queue URIs first
  (http:// + ipp://), queue printer-name/info/uuid, queue job-uri -
  and honours a queue name that arrives ONLY in the printer-uri
  operation attribute.

BUG 2 - one hub serving MANY PCs is now professional and optimized:
  accept backlog 128 on every listener, session-lock around all
  _IPP_JOBS mutations, memoized queue-name resolution, unique
  _write_atomic temp names + serialized virtual-PDF saves (two jobs in
  the same second used to kill each other's .part file), and the ACL
  403 echoes the ACTIVE allowed_ips rules.

BUG 3 - every LAN PC saw the SAME hub URL (the hub's default-route
  address, possibly a VPN adapter the client cannot reach). Pages now
  build URLs from the address THE OPENING DEVICE used (sanitized Host
  header) first, the boot JSON carries self_host/self_port/client_ip/
  lan_ips, and the LAN panel lists every hub interface IP as chips.

Also locked: version coherence 3.3.0 everywhere, byte-identical hub
copies, the fixed scripts/embed_console.py close sequence, and the new
release docs.
"""
import json
import os
import re
import struct
import threading

import pytest

import advprint
from conftest import ROOT

HUB_DIR = os.path.join(ROOT, "tool", "windows", "portable", "hub")
UNIX_HUB = os.path.join(ROOT, "tool", "unix", "hub")
EXT = os.path.join(ROOT, "extension")

CONSOLE = open(os.path.join(HUB_DIR, "console.html"),
               encoding="utf-8").read()
ADVPRINT_SRC = open(os.path.join(HUB_DIR, "advprint.py"),
                    encoding="utf-8").read()
VERSION_TXT = open(os.path.join(ROOT, "VERSION.txt"),
                   encoding="utf-8").read()
MANIFEST = json.load(open(os.path.join(EXT, "manifest.json"),
                          encoding="utf-8"))
CHANGELOG = open(os.path.join(ROOT, "CHANGELOG.md"),
                 encoding="utf-8").read()
NSI = open(os.path.join(ROOT, "installer", "setup.nsi"),
           encoding="utf-8").read()

# ---- minimal IPP wire helpers (same encoding as tests/test_ipp.py) ----
T_OP, T_END = 0x01, 0x03
V_INT, V_BOOL, V_ENUM = 0x21, 0x22, 0x23
V_TEXT, V_NAME, V_KEYWORD = 0x41, 0x42, 0x44
V_URI, V_CHARSET, V_LANG, V_MIME = 0x45, 0x47, 0x48, 0x49


def _attr(tag, name, value):
    if isinstance(value, int):
        value = struct.pack(">i", value)
    nb = name.encode()
    vb = value if isinstance(value, bytes) else str(value).encode()
    return (bytes([tag]) + len(nb).to_bytes(2, "big") + nb +
            len(vb).to_bytes(2, "big") + vb)


def _req(op, uri_path="/ipp/print", port=None, doc=b"", rid=7, ver=(1, 1)):
    out = bytearray()
    out += bytes(ver) + op.to_bytes(2, "big") + rid.to_bytes(4, "big")
    out += bytes([T_OP])
    out += _attr(V_CHARSET, "attributes-charset", "utf-8")
    out += _attr(V_LANG, "attributes-natural-language", "en")
    if port is not None:
        out += _attr(V_URI, "printer-uri",
                     "http://10.26.94.55:%d%s" % (port, uri_path))
        out += _attr(V_NAME, "requesting-user-name", "pytest")
    out += bytes([T_END])
    return bytes(out) + doc


def _resp_groups(raw):
    """Walk an IPP response into [(name, [(tag, value_str), ...]), ...]."""
    assert raw[:2] in (b"\x01\x01", b"\x01\x00", b"\x02\x00", b"\x02\x01")
    status = int.from_bytes(raw[2:4], "big")
    rid = int.from_bytes(raw[4:8], "big")
    attrs = []
    i, n = 8, len(raw)
    cur = None
    last = ("",)
    while i < n:
        b = raw[i]
        if b == T_END:
            break
        if b in (T_OP, 0x02, 0x04, 0x05):
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
        val = raw[i:i + vl]
        i += vl
        if cur is not None:
            if not name:
                # RFC 8010 additional value: empty name continues the
                # previous attribute - fold it so _vals() sees every uri
                name = last[0] if last else ""
            else:
                last = (name,)
            cur.append((name, (b, val.decode("utf-8", "replace"))))
    return status, rid, attrs


def _vals(group, name):
    return [v for (n, v) in group if n == name]


# ---------------------------------------------------------------
# 1. version coherence 3.3.0
# ---------------------------------------------------------------

def test_version_329_everywhere():
    assert advprint.VERSION == "3.4.6"
    assert advprint.VERSION_NAME.startswith("v3.4.6")
    assert "ONE PORT FOR EVERYTHING" in advprint.VERSION_NAME
    assert "3.4.6" in VERSION_TXT
    assert MANIFEST["version"] == "3.4.6"
    assert 'var _apVerFallback = "3.4.6";' in open(
        os.path.join(EXT, "content", "api.js"), encoding="utf-8").read()
    assert 'BOOT.version || "3.4.6"' in CONSOLE
    assert "## v3.2.9 - THE MULTI-PC IPP RELEASE" in CHANGELOG
    assert 'VIProductVersion "3.4.6.0"' in NSI
    assert "AdvPrint-Pro-Setup-3.4.6.exe" in NSI


def test_release_docs_329_exist():
    notes = open(os.path.join(ROOT, "docs", "RELEASE-NOTES-v3.2.9.md"),
                 encoding="utf-8").read()
    assert "ipp/print/<printer-name>" in notes
    assert "MULTI-PC" in notes
    guide = open(os.path.join(ROOT,
                 "docs", "AdvPrint-Pro-v3.2.9-A-to-Z-DEV-GUIDE.md"),
                 encoding="utf-8").read()
    assert "_ipp_queue_match_cached" in guide
    assert "list_lan_ips" in guide
    assert "scripts/embed_console.py" in guide


def test_embed_console_close_sequence_fixed():
    """v3.2.9 regression: the old embed wrote the closing quotes WITHOUT
    the leading newline, so the next embed's CLOSE search overshot into
    DOCS_HTML and silently deleted docs_html()/DOCS_HTML/
    console_page_bytes()/dashboard_html() from the hub."""
    esrc = open(os.path.join(ROOT, "scripts", "embed_console.py"),
                encoding="utf-8").read()
    assert "OPEN + html + CLOSE" in esrc
    # and the hub file still carries every constant the old run ate
    for name in ("CONSOLE_HTML", "DOCS_HTML", "DASHBOARD_AUTH_ERROR_TMPL"):
        assert re.search(r"^%s = " % name, ADVPRINT_SRC, re.M), name


def test_hub_copies_byte_identical():
    for name in ("advprint.py", "console.html"):
        a = open(os.path.join(UNIX_HUB, name), "rb").read()
        b = open(os.path.join(HUB_DIR, name), "rb").read()
        assert a == b, "%s copies drifted" % name


# ---------------------------------------------------------------
# 2. BUG 1 - the per-printer queue ECHO
# ---------------------------------------------------------------

def test_queue_uris_both_schemes():
    uris = advprint._ipp_queue_uris("hp-laser")
    assert len(uris) == 2
    assert all(u.endswith("/ipp/print/hp-laser") for u in uris)
    assert any(u.startswith("ipp://") for u in uris)
    assert any(u.startswith("http://") for u in uris)


def test_get_printer_attributes_echoes_queue(monkeypatch):
    """Windows sends Get-Printer-Attributes for the queue URI - the
    response must lead with BOTH queue URIs and name the queue."""
    monkeypatch.setattr(advprint, "_ipp_queue_match_cached",
                        lambda name: "HP Laser 103" if name else "")
    monkeypatch.setattr(advprint, "list_printers_cached",
                        lambda *a, **k: ["HP Laser 103"])
    monkeypatch.setattr(advprint, "lan_ip", lambda: "10.26.94.206")
    monkeypatch.setitem(advprint.CFG, "share_lan", True)
    port = advprint.CFG["port"]
    raw = advprint.ipp_handle(
        _req(0x000B, uri_path="/ipp/print/HP-Laser-103", port=port),
        "10.26.94.55", printer="HP Laser 103")
    status, rid, groups = _resp_groups(raw)
    assert status == 0 and rid == 7
    printer = groups[1]
    uris = [v[1] for v in _vals(printer, "printer-uri-supported")]
    # the canonical slug pair leads
    assert uris[0] == "http://10.26.94.206:%d/ipp/print/hp-laser-103" % port
    assert uris[1] == "ipp://10.26.94.206:%d/ipp/print/hp-laser-103" % port
    # and the EXACT URI the client asked for is echoed (both schemes)
    assert "http://10.26.94.55:%d/ipp/print/HP-Laser-103" % port in uris
    assert "ipp://10.26.94.55:%d/ipp/print/HP-Laser-103" % port in uris
    # generic URIs still present behind the queue ones
    assert any(u.endswith("/ipp/print") for u in uris)
    names = [v[1] for v in _vals(printer, "printer-name")]
    assert names and names[0] == "HP Laser 103"
    info = _vals(printer, "printer-info")[0][1]
    assert "queue HP Laser 103" in info
    # per-queue uuid differs from the generic hub uuid
    q_uuid = _vals(printer, "printer-uuid")[0][1]
    g_uuid = advprint._ipp_printer_uuid()
    assert q_uuid != g_uuid
    assert advprint._ipp_printer_uuid("hp-laser-103") == q_uuid  # stable
    assert advprint._ipp_printer_uuid("other") != q_uuid


def test_generic_printer_group_unchanged():
    """Without a queue the response keeps the classic hostname identity."""
    raw = advprint.ipp_handle(_req(0x000B), "127.0.0.1")
    status, rid, groups = _resp_groups(raw)
    printer = groups[1]
    names = [v[1] for v in _vals(printer, "printer-name")]
    assert names and names[0] == advprint.socket.gethostname()
    uris = [v[1] for v in _vals(printer, "printer-uri-supported")]
    assert all(u.endswith("/ipp/print") for u in uris)


def test_queue_name_inside_printer_uri_is_honoured(monkeypatch):
    """Some clients put the queue ONLY in the printer-uri attribute of a
    GENERIC path request - the job must still reach that printer."""
    seen = {}
    monkeypatch.setattr(advprint, "_ipp_queue_match_cached",
                        lambda name: "HP Laser 103" if name else "")

    def fake_route(data, title, ip, source="ipp", printer=""):
        seen["printer"] = printer
        return 4242, "pdf"

    monkeypatch.setattr(advprint, "route_print_payload", fake_route)
    port = advprint.CFG["port"]
    monkeypatch.setattr(advprint, "lan_ip", lambda: "10.26.94.206")
    raw = advprint.ipp_handle(
        _req(0x0002, uri_path="/ipp/print/HP-Laser-103", port=port,
             doc=b"%PDF-1.4 tiny"), "10.26.94.55")
    status, rid, groups = _resp_groups(raw)
    assert status == 0
    assert seen["printer"] == "HP Laser 103"
    job = groups[1]
    juri = _vals(job, "job-uri")[0][1]
    assert "/ipp/print/hp-laser-103/job/4242" in juri


def test_job_uri_echoes_queue(monkeypatch):
    monkeypatch.setattr(advprint, "route_print_payload",
                        lambda data, title, ip, source="ipp", printer="":
                            (4243, "pdf"))
    monkeypatch.setattr(advprint, "lan_ip", lambda: "10.26.94.206")
    monkeypatch.setitem(advprint.CFG, "share_lan", True)
    raw = advprint.ipp_handle(
        _req(0x0002, doc=b"%PDF-1.4 tiny"), "127.0.0.1",
        printer="HP Laser 103")
    status, rid, groups = _resp_groups(raw)
    assert status == 0
    juri = _vals(groups[1], "job-uri")[0][1]
    assert "/ipp/print/hp-laser-103/job/4243" in juri


# ---------------------------------------------------------------
# 3. BUG 2 - many PCs at once: the optimized IPP node
# ---------------------------------------------------------------

def test_listener_backlog_and_timeouts():
    assert advprint.HubServer.request_queue_size == 128
    assert advprint._IPP631Server.request_queue_size == 128
    assert advprint.Handler.timeout == 30
    assert advprint.IPP631Handler.timeout == 30


def test_queue_match_memoized(monkeypatch):
    calls = {"n": 0}

    def slow_match(name):
        calls["n"] += 1
        return "HP Laser 103"

    monkeypatch.setattr(advprint, "_ipp_queue_match", slow_match)
    a = advprint._ipp_queue_match_cached("HP-Laser-103")
    b = advprint._ipp_queue_match_cached("hp laser 103")
    assert a == b == "HP Laser 103"
    assert calls["n"] == 1, "second call within the TTL must hit the memo"


def test_write_atomic_unique_temp_names(tmp_path):
    """Two writers to the SAME target in the same second must both
    succeed (the old path+pid temp name made one os.replace fail)."""
    target = str(tmp_path / "same-second.pdf")
    errs = []

    def writer(n):
        try:
            advprint._write_atomic(target, b"writer %d" % n)
        except Exception as e:                      # pragma: no cover
            errs.append(e)

    ts = [threading.Thread(target=writer, args=(i,)) for i in range(2)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errs
    assert open(target, "rb").read().startswith(b"writer ")
    leftovers = [p for p in os.listdir(tmp_path) if ".part" in p]
    assert leftovers == []


def test_virtual_pdf_same_second_two_jobs(tmp_path, hub, monkeypatch):
    """Two LAN PCs printing to the virtual PDF printer in the same
    second: the free-name check + write are serialized, both save."""
    monkeypatch.setattr(advprint, "default_file_dir",
                        lambda: str(tmp_path))
    src = tmp_path / "src.pdf"
    src.write_bytes(b"%PDF-1.4 source")
    jobs = [{"id": 771, "title": "same second", "file_path": str(src)},
            {"id": 772, "title": "same second", "file_path": str(src)}]
    errs = []

    def _save(job):
        try:
            advprint._save_virtual_pdf(job)
        except Exception as e:                      # pragma: no cover
            errs.append(e)

    ts = [threading.Thread(target=_save, args=(j,)) for j in jobs]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert errs == []
    outs = sorted(p for p in os.listdir(tmp_path)
                  if p.endswith(".pdf") and p.startswith("same_second"))
    assert len(outs) == 2, "both jobs must save (second one gets -2)"


def test_acl_403_echoes_rules_and_landing_says_who(monkeypatch):
    # the 403 payload source echoes the active rules
    assert '"allowed_ips"' in ADVPRINT_SRC
    # landing page states who may print
    advprint.CFG["allowed_ips"] = ["10.26.94.0/24", "10.26.95.*"]
    html = advprint.ipp_landing_html()
    assert "Allowed-IPs list" in html and "10.26.94.0/24" in html
    advprint.CFG["allowed_ips"] = ["*"]
    html = advprint.ipp_landing_html()
    assert "every device on the LAN" in html


# ---------------------------------------------------------------
# 4. BUG 3 - every device sees ITS OWN hub ip:port
# ---------------------------------------------------------------

def test_sanitize_host_hdr():
    f = advprint._sanitize_host_hdr
    assert f("10.26.94.77:9235") == ("10.26.94.77", "9235")
    assert f("192.168.1.101") == ("192.168.1.101", None)
    assert f("[::1]:9235") == ("::1", "9235")
    assert f("localhost:9235") == ("localhost", "9235")
    assert f("AI-Lab.corp.local:9235") == ("ai-lab.corp.local", "9235")
    assert f("") == ("", None)
    assert f("evil.com/path") == ("", None)          # path refused
    assert f("a" * 300) == ("", None)               # oversized refused
    assert f("bad host") == ("", None)              # space refused
    assert f("10.0.0.1:http") == ("10.0.0.1", None)  # non-numeric port


def test_landing_page_uses_request_host(monkeypatch):
    monkeypatch.setattr(advprint, "lan_ip", lambda: "192.168.1.101")
    advprint.CFG["share_lan"] = True
    port = advprint.CFG["port"]
    # a LAN PC that arrived via 10.26.94.77 sees THAT address
    html = advprint.ipp_landing_html(req_host="10.26.94.77", req_port=port)
    assert "ipp://10.26.94.77:%d/ipp/print" % port in html
    assert "http://10.26.94.77:%d/ipp/print" % port in html
    assert "192.168.1.101" not in html
    # the hub owner on loopback still gets the shareable LAN address
    html = advprint.ipp_landing_html(req_host="localhost", req_port=port)
    assert "ipp://192.168.1.101:%d/ipp/print" % port in html
    # a bad Host header falls back safely
    html = advprint.ipp_landing_html(req_host="", req_port=None)
    assert "ipp://192.168.1.101:%d/ipp/print" % port in html


def test_queue_url_per_host():
    u = advprint.ipp_queue_url("HP Laser 103", host="10.26.94.77")
    assert u == "ipp://10.26.94.77:%d/ipp/print/hp-laser-103" \
        % advprint.CFG["port"]
    # without a host the classic lan_ip() form is kept
    old = advprint.ipp_queue_url("HP Laser 103")
    assert old.startswith("ipp://")


def test_console_boot_json_per_device():
    page = advprint.console_page_bytes(
        "center", req_host="10.26.94.77", req_port=9235,
        client_ip="10.26.94.55").decode("utf-8")
    m = re.search(r'<script id="bootjson"[^>]*>(.*?)</script>',
                  page, re.S)
    boot = json.loads(m.group(1))
    assert boot["self_host"] == "10.26.94.77"
    assert boot["self_port"] == 9235
    assert boot["client_ip"] == "10.26.94.55"
    assert isinstance(boot["lan_ips"], list) and boot["lan_ips"]
    # on the hub itself (loopback) self_host stays empty - the UI falls
    # back to lan_ip so the owner copies a SHAREABLE url
    page = advprint.console_page_bytes("self").decode("utf-8")
    boot = json.loads(re.search(
        r'<script id="bootjson"[^>]*>(.*?)</script>', page, re.S).group(1))
    assert boot["self_host"] == ""


def test_list_lan_ips_returns_private_first():
    ips = advprint.list_lan_ips(max_age=0)
    assert isinstance(ips, list) and ips
    assert all(isinstance(x, str) for x in ips)
    assert len(ips) == len(set(ips))
    # no loopback junk
    assert all(not x.startswith("127.") for x in ips)


def test_console_ui_has_per_device_bits():
    # the smart lanBase() family replaces the old BOOT.lan_ip-first code
    assert "function hubIp()" in CONSOLE
    assert "function hubPort()" in CONSOLE
    assert "function isLoopHost(" in CONSOLE
    assert 'BOOT.self_host' in CONSOLE
    assert 'BOOT.lan_ips' in CONSOLE
    # the LAN panel ships the new rows/ids the JS fills
    assert 'id="hubIpList"' in CONSOLE
    assert 'id="row-hubips"' in CONSOLE
    assert 'id="lanPcHubUrl"' in CONSOLE
    # the /printers endpoint builds queue URLs per request
    assert "ipp_queue_url(n, host=_req_h)" in ADVPRINT_SRC


def test_live_landing_per_device(hub, cfg_reset, monkeypatch):
    """A LAN PC opening the printer page through 10.26.94.77:PORT sees
    exactly that address - never the hub's own lan_ip()."""
    monkeypatch.setattr(advprint, "lan_ip", lambda: "192.168.1.101")
    advprint.CFG["share_lan"] = True
    code, page = hub.get("/ipp/print", token=None,
                         headers={"Host": "10.26.94.77:%d"
                                  % advprint.CFG["port"]})
    assert code == 200
    html = page.decode("utf-8", "replace")
    assert "ipp://10.26.94.77:%d/ipp/print" % advprint.CFG["port"] in html
    assert "192.168.1.101" not in html


def test_live_acl_403_json_echoes_rules(hub, cfg_reset, monkeypatch):
    advprint.CFG["allowed_ips"] = ["10.26.94.0/24"]
    monkeypatch.setattr(advprint.Handler, "_client_ip",
                        lambda self: "10.77.77.77")
    code, page = hub.get("/health", token=None)
    assert code == 403
    d = page if isinstance(page, dict) else json.loads(page)
    assert d["ok"] is False
    assert d["allowed_ips"] == ["10.26.94.0/24"]
    advprint.CFG["allowed_ips"] = ["*"]
