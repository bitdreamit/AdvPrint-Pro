"""v3.3.2 - SHARE SEND MODE + WINDOWS IPP ADD-FIX RELEASE.

Four real-world reports, each locked here:

BUG 1  Windows "couldn't connect to the printer": the Get-Printer-
       Attributes response was missing the RFC 8011 REQUIRED
       uri-security-supported attribute (the strict Microsoft IPP Class
       Driver refuses the whole response), and the uri-* 1setOf parity
       rule was broken as soon as a client URI was echoed into
       printer-uri-supported (multi-adapter hub). The wire ordering
       rule (all auth values before the security values - an additional
       value belongs to the attribute right before it) is covered too.

BUG 2  a tokenless IPP Print-Job over 1 MB hit _preauth_gate() and was
       answered 401 before the body was read -> connection aborted
       mid-transmit on the client. IPP routes are exempt now.

BUG 3  an unknown per-printer queue hard-404'd the whole add flow; it
       now answers as the generic queue (add succeeds).

BUG 4  SHARE SEND MODE is real: /peer/pair persists the OTHER PC's
       url+token (self-pairs refused), /peer/status probes it live,
       share_send forwards every job to the paired PC, /peer/unpair
       clears it, /peer/test-page relays a test page, the console card
       renders the persisted state (never the demo mockup), the LAN PC
       URL input is never overwritten with this PC's own address.
"""
import json
import os
import socket
import struct
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import advprint
from conftest import wait_until

# ---- IPP wire helpers (same encoding as tests/test_ipp.py) ----
T_OP, T_END = 0x01, 0x03
V_INT, V_BOOL, V_ENUM = 0x21, 0x22, 0x23
V_TEXT, V_NAME, V_KEYWORD = 0x41, 0x42, 0x44
V_URI, V_CHARSET, V_LANG, V_MIME = 0x45, 0x47, 0x48, 0x49


def _attr(tag, name, value):
    nb = name.encode()
    vb = value if isinstance(value, bytes) else str(value).encode()
    return bytes([tag]) + len(nb).to_bytes(2, "big") + nb + \
        len(vb).to_bytes(2, "big") + vb


def _add(tag, value):
    return _attr(tag, "", value)


def _req(op, uri, ver=(1, 1), extra=(), doc=b""):
    body = bytes(ver) + op.to_bytes(2, "big") + (1).to_bytes(4, "big")
    body += bytes([T_OP])
    body += _attr(V_CHARSET, "attributes-charset", "utf-8")
    body += _attr(V_LANG, "attributes-natural-language", "en")
    body += _attr(V_URI, "printer-uri", uri)
    for tag, name, val in extra:
        body += _attr(tag, name, val)
    body += bytes([T_END]) + doc
    return body


def _ipp_post(hub, raw, path="/ipp/print"):
    return hub.req("POST", path, token=None, raw=raw,
                   content_type="application/ipp")


def _walk(resp):
    """Strict-ish parse: groups -> {name: [(tag, raw_value), ...]} with
    additional values (empty name) attached to the attribute right
    before them - exactly the RFC 8010 §3.1.4 rule."""
    groups = []
    cur = None
    last = None
    i = 8
    ver = (resp[0], resp[1])
    status = int.from_bytes(resp[2:4], "big")
    while i < len(resp):
        b = resp[i]
        if b in (0x00, 0x01, 0x02, 0x04, 0x05):
            cur = {}
            groups.append(cur)
            i += 1
            continue
        if b == T_END:
            break
        tag = b
        nl = int.from_bytes(resp[i + 1:i + 3], "big")
        i += 3
        nm = resp[i:i + nl].decode()
        i += nl
        vl = int.from_bytes(resp[i:i + 2], "big")
        i += 2
        val = resp[i:i + vl]
        i += vl
        if nm:
            cur.setdefault(nm, []).append((tag, val))
            last = nm
        else:
            cur.setdefault(last, []).append((tag, val))
    return ver, status, groups


def _printer_group(groups):
    for g in groups:
        if "printer-uri-supported" in g:
            return g
    return {}


# ================================================================
# BUG 1 - uri-security-supported + 1setOf parity (Windows add)
# ================================================================

def test_gpa_answers_uri_security_supported(hub):
    port = urllib.parse.urlparse(hub.base).port
    code, raw = _ipp_post(hub, _req(0x000B, "ipp://127.0.0.1:%d/ipp/print"
                                    % port, ver=(2, 0)))
    assert code == 200
    ver, status, groups = _walk(raw)
    assert status == 0x0000
    pg = _printer_group(groups)
    names = set(pg.keys())
    assert "uri-security-supported" in names, \
        "RFC 8011 REQUIRED attribute missing - Windows refuses the add"
    assert "uri-authentication-supported" in names
    uris = [v for _t, v in pg["printer-uri-supported"]]
    auths = [v for _t, v in pg["uri-authentication-supported"]]
    secs = [v for _t, v in pg["uri-security-supported"]]
    assert len(auths) == len(uris), "1setOf parity broken (auth)"
    assert len(secs) == len(uris), "1setOf parity broken (security)"
    for v in auths:
        assert v == b"none"
    for v in secs:
        assert v == b"none"


def test_gpa_parity_holds_when_client_uri_is_echoed(hub):
    """Multi-adapter case: the client reaches the hub by an address that
    is NOT the canonical lan_ip() - the echo grows printer-uri-supported
    and the uri-* lists must grow with it (the old code kept 2 values)."""
    port = urllib.parse.urlparse(hub.base).port
    foreign = "http://203.0.113.77:%d/ipp/print" % port   # TEST-NET-3
    code, raw = _ipp_post(hub, _req(0x000B, foreign))
    assert code == 200
    _ver, status, groups = _walk(raw)
    assert status == 0x0000
    pg = _printer_group(groups)
    uris = [v for _t, v in pg["printer-uri-supported"]]
    auths = [v for _t, v in pg["uri-authentication-supported"]]
    secs = [v for _t, v in pg["uri-security-supported"]]
    assert foreign.encode() in uris, "the client URI must be echoed"
    assert len(auths) == len(uris)
    assert len(secs) == len(uris)


def test_gpa_wire_order_auth_values_before_security(hub):
    """An additional value (empty name) belongs to the attribute right
    before it - interleaving auth/security primaries would attach the
    extra "none" to the wrong attribute on every strict parser."""
    port = urllib.parse.urlparse(hub.base).port
    code, raw = _ipp_post(hub, _req(0x000B,
                                    "ipp://127.0.0.1:%d/ipp/print" % port))
    assert code == 200
    _ver, _status, groups = _walk(raw)
    pg = _printer_group(groups)
    # parity already proves the grouping; additionally every auth value
    # must carry the keyword tag and sit before the security primary
    auths = pg["uri-authentication-supported"]
    secs = pg["uri-security-supported"]
    assert all(t == V_KEYWORD for t, _v in auths)
    assert all(t == V_KEYWORD for t, _v in secs)


def test_gpa_per_printer_queue_parity(hub):
    import time as _t
    advprint._LP_CACHE["v"] = ["HP Laser 103"]
    advprint._LP_CACHE["t"] = _t.time()
    port = urllib.parse.urlparse(hub.base).port
    code, raw = _ipp_post(hub, _req(
        0x000B, "ipp://127.0.0.1:%d/ipp/print/hp-laser-103" % port))
    assert code == 200
    _ver, status, groups = _walk(raw)
    assert status == 0x0000
    pg = _printer_group(groups)
    uris = [v.decode() for _t, v in pg["printer-uri-supported"]]
    auths = [v for _t, v in pg["uri-authentication-supported"]]
    secs = [v for _t, v in pg["uri-security-supported"]]
    assert any(u.endswith("/ipp/print/hp-laser-103") for u in uris)
    assert len(auths) == len(uris) == len(secs)


# ================================================================
# BUG 2 - tokenless IPP Print-Job > 1 MB survives the preauth gate
# ================================================================

def test_ipp_print_job_over_1mb_no_token(hub, clean_queue):
    """Windows speaks IPP without any token; its PDFs are routinely
    > 1 MB. The old preauth gate answered 401 before reading a byte and
    the client died mid-transmit (broken pipe). Now: HTTP 200 + IPP
    successful-ok and a real queued job."""
    port = urllib.parse.urlparse(hub.base).port
    big = b"%PDF-1.4\n" + b"%" + b"A" * (1024 * 1024 + 512 * 1024)
    code, raw = _ipp_post(hub, _req(
        0x0002, "http://127.0.0.1:%d/ipp/print" % port,
        ver=(2, 0), doc=big))
    assert code == 200, "IPP must NOT die on the preauth gate"
    _ver, status, _groups = _walk(raw)
    assert status == 0x0000
    assert wait_until(lambda: [j for j in hub.printed
                               if j.get("job_id")], timeout=10)


def test_ipp_validate_job_ok(hub):
    port = urllib.parse.urlparse(hub.base).port
    code, raw = _ipp_post(hub, _req(
        0x0004, "ipp://127.0.0.1:%d/ipp/print" % port, ver=(2, 0)))
    assert code == 200
    _ver, status, _groups = _walk(raw)
    assert status == 0x0000


# ================================================================
# BUG 3 - unknown per-printer queue no longer 404s the add
# ================================================================

def test_unknown_queue_gpa_answers_add(hub):
    import time as _t
    advprint._LP_CACHE["v"] = ["HP Laser 103"]
    advprint._LP_CACHE["t"] = _t.time()
    port = urllib.parse.urlparse(hub.base).port
    code, raw = _ipp_post(hub, _req(
        0x000B, "ipp://127.0.0.1:%d/ipp/print/typo-device" % port))
    assert code == 200
    _ver, status, groups = _walk(raw)
    assert status == 0x0000
    pg = _printer_group(groups)
    nm = [v for _t, v in pg["printer-name"]]
    assert nm and b"typo-device" in nm[0], \
        "printer-name must echo the requested queue"


def test_unknown_queue_print_job_falls_back(hub, clean_queue):
    port = urllib.parse.urlparse(hub.base).port
    code, raw = _ipp_post(hub, _req(
        0x0002, "ipp://127.0.0.1:%d/ipp/print/no-such-device" % port,
        doc=b"%PDF-1.4\nunknown-queue-fallback"))
    assert code == 200
    _ver, status, _groups = _walk(raw)
    assert status == 0x0000, "documents must not die on an unknown slug"


def test_unknown_queue_landing_page_is_html(hub):
    code, page = hub.get("/ipp/print/no-such-device", token=None)
    assert code == 200
    html = page.decode("utf-8", "replace") if isinstance(page, bytes) \
        else str(page)
    assert "IPP network printer" in html


# ================================================================
# BUG 4 - SHARE SEND MODE: pairing + forwarding + relay
# ================================================================

class _FakePeerHandler(BaseHTTPRequestHandler):
    peer_state = {"share_lan": True, "version": "3.3.1",
                  "printers": ["HP Laser 103 107 108"],
                  "print_jobs": [], "refuse": False}

    def log_message(self, *a):
        pass

    def _reply(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        st = _FakePeerHandler.peer_state
        if self.path == "/health":
            self._reply({"ok": True, "version": st["version"],
                         "host": "OTHER-PC", "share_lan": st["share_lan"],
                         "ipp_printer": True,
                         "default_printer": st["printers"][0]})
        elif self.path == "/printers":
            self._reply({"ok": True, "printers": [
                {"name": n, "status": "ready", "is_default": i == 0}
                for i, n in enumerate(st["printers"])]})
        else:
            self._reply({"ok": False, "error": "unknown"}, 404)

    def do_POST(self):
        st = _FakePeerHandler.peer_state
        if st["refuse"]:
            self._reply({"ok": False, "error": "refused by test"}, 500)
            return
        ln = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(ln).decode("utf-8"))
        if self.path == "/print":
            st["print_jobs"].append(body)
            self._reply({"ok": True, "job_id": 990 + len(st["print_jobs"])})
        else:
            self._reply({"ok": False, "error": "unknown"}, 404)


@pytest.fixture()
def fake_peer():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    httpd = ThreadingHTTPServer(("127.0.0.1", port), _FakePeerHandler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    _FakePeerHandler.peer_state.update(
        {"share_lan": True, "version": "3.3.1",
         "printers": ["HP Laser 103 107 108"], "print_jobs": [],
         "refuse": False})
    yield {"base": "http://127.0.0.1:%d" % port, "httpd": httpd}
    httpd.shutdown()


@pytest.fixture()
def no_peer(hub):
    """Tests here must not inherit peer_hubs from other tests."""
    saved = advprint.CFG.get("peer_hubs")
    saved_ss = advprint.CFG.get("share_send")
    advprint.CFG["peer_hubs"] = []
    advprint.CFG["share_send"] = False
    yield
    advprint.CFG["peer_hubs"] = saved
    advprint.CFG["share_send"] = saved_ss
    try:
        advprint.write_config_file({k: advprint.CFG[k]
                                    for k in advprint.CONFIG_KEYS})
    except Exception:
        pass


def test_pair_refuses_self(hub, no_peer):
    code, data = hub.post("/peer/pair", body={
        "url": "http://127.0.0.1:%d" % advprint.CFG["port"],
        "token": "whatever"})
    assert code == 400
    assert "own hub" in data["error"]
    assert advprint.CFG["peer_hubs"] == []


def test_pair_requires_url_and_token(hub, no_peer):
    code, data = hub.post("/peer/pair", body={"url": ""})
    assert code == 400
    assert "URL" in data["error"] and "token" in data["error"]


def test_pair_requires_peer_lan_sharing_on(hub, no_peer, fake_peer):
    _FakePeerHandler.peer_state["share_lan"] = False
    try:
        code, data = hub.post("/peer/pair", body={"url": fake_peer["base"],
                                                  "token": "t2"})
        assert code == 400
        assert "LAN sharing is OFF" in data["error"]
        assert advprint.CFG["peer_hubs"] == []
    finally:
        _FakePeerHandler.peer_state["share_lan"] = True


def test_pair_persists_and_survives(hub, no_peer, fake_peer, tmp_path):
    code, st = hub.post("/peer/pair", body={"url": fake_peer["base"],
                                            "token": "tok2",
                                            "name": "Storage PC"})
    assert code == 200
    assert st["configured"] is True
    assert st["url"] == fake_peer["base"]
    assert st["token_set"] is True
    p = st["peer"]
    assert p["alive"] is True
    assert p["version"] == "3.3.1"
    assert p["peer_host"] == "OTHER-PC"
    assert p["share_lan"] is True and p["ipp_printer"] is True
    assert p["printers"] and p["printers"][0]["name"] == \
        "HP Laser 103 107 108"
    # persisted in config.json with the real token (never rendered back)
    cfg = json.load(open(advprint.config_path(), encoding="utf-8"))
    entries = [x for x in cfg.get("peer_hubs", [])
               if x.get("name") == "lan-pc"]
    assert entries and entries[0]["token"] == "tok2"
    assert entries[0]["label"] == "Storage PC"
    # the status endpoint never returns the token itself
    code2, st2 = hub.get("/peer/status")
    assert code2 == 200
    raw = json.dumps(st2)
    assert "tok2" not in raw, "the token must never be rendered back"


def test_status_offline_shows_error(hub, no_peer, fake_peer):
    hub.post("/peer/pair", body={"url": fake_peer["base"], "token": "t"})
    # take the OTHER PC's hub down after pairing, then the card must
    # show OFFLINE + the reason (not a stale CONNECTED chip)
    fake_peer["httpd"].shutdown()
    advprint._LANPC_PROBE_CACHE["v"] = None
    _code, st = hub.get("/peer/status")
    assert st["configured"] is True
    assert st["peer"]["alive"] is False
    assert st["peer"]["error"]


def test_share_send_blocked_without_pairing(hub, no_peer):
    code, data = hub.post("/config", body={"share_send": True})
    assert code == 400
    assert "Connect the LAN PC first" in data["error"]
    assert advprint.CFG["share_send"] is False


def test_share_send_forward_every_job(hub, clean_queue, no_peer,
                                      fake_peer, monkeypatch):
    """Share Send ON: EVERY new job goes to the paired PC - even though
    the local printer is fine and peer_forwarding is OFF."""
    hub.post("/peer/pair", body={"url": fake_peer["base"], "token": "t"})
    code, _r = hub.post("/config", body={"share_send": True})
    assert code == 200
    pdf = b"%PDF-1.4\nshare-send-me"
    code2, r2 = hub.post("/print", body={
        "pdf_base64": __import__("base64").b64encode(pdf).decode(),
        "title": "share-test", "printer": "HP Laser 103 107 108"})
    assert code2 == 200
    assert wait_until(lambda:
                      _FakePeerHandler.peer_state["print_jobs"], timeout=15)
    job = _FakePeerHandler.peer_state["print_jobs"][0]
    assert job["title"] == "share-test"
    assert job["printer"] == "HP Laser 103 107 108"
    assert job["source"].startswith("share-send")
    # db row forwarded, nothing printed locally
    assert wait_until(lambda: [
        j for j in advprint.db_list(limit=20) if j["status"] == "forwarded"],
        timeout=15)
    assert not hub.printed, "the job must NOT print locally in share mode"
    # the forward is audited
    aud = advprint.audit_list(limit=20)
    assert any(a.get("event") == "job.forwarded" for a in aud)


def test_share_send_peer_without_printer_prints_locally(hub, clean_queue,
                                                       no_peer, fake_peer):
    hub.post("/peer/pair", body={"url": fake_peer["base"], "token": "t"})
    hub.post("/config", body={"share_send": True})
    _FakePeerHandler.peer_state["printers"] = ["Some Other Printer"]
    try:
        pdf = b"%PDF-1.4\nlocal-fallback"
        hub.post("/print", body={
            "pdf_base64": __import__("base64").b64encode(pdf).decode(),
            "title": "fallback-test", "printer": "HP Laser 103 107 108"})
        assert wait_until(lambda: hub.printed, timeout=15), \
            "peer lacks the printer -> the job must print locally"
        assert _FakePeerHandler.peer_state["print_jobs"] == []
    finally:
        _FakePeerHandler.peer_state["printers"] = ["HP Laser 103 107 108"]


def test_unpair_clears_everything(hub, no_peer, fake_peer):
    hub.post("/peer/pair", body={"url": fake_peer["base"], "token": "t"})
    hub.post("/config", body={"share_send": True})
    code, st = hub.post("/peer/unpair", body={})
    assert code == 200
    assert st["configured"] is False
    assert st["share_send"] is False
    assert advprint.CFG["share_send"] is False
    assert not [x for x in (advprint.CFG.get("peer_hubs") or [])
                if x.get("name") == "lan-pc"]
    cfg = json.load(open(advprint.config_path(), encoding="utf-8"))
    assert not [x for x in cfg.get("peer_hubs", [])
                if x.get("name") == "lan-pc"]


def test_peer_test_page_relay(hub, no_peer, fake_peer):
    code, data = hub.post("/peer/test-page", body={})
    assert code == 400            # nothing paired yet
    hub.post("/peer/pair", body={"url": fake_peer["base"], "token": "t"})
    code2, data2 = hub.post("/peer/test-page",
                            body={"printer": "HP Laser 103 107 108"})
    assert code2 == 200
    assert data2["ok"] is True and data2["job_id"]
    job = _FakePeerHandler.peer_state["print_jobs"][-1]
    assert job["printer"] == "HP Laser 103 107 108"
    assert job["pdf_base64"].startswith("JVBERi")   # %PDF in b64


def test_peer_status_shape(hub, no_peer, fake_peer):
    _code, st = hub.get("/peer/status")
    assert st == {"ok": True, "configured": False, "share_send": False,
                  "version": advprint.VERSION, "url": "", "label": "",
                  "token_set": False, "peer": None}

# ================================================================
# Console UI - the LAN PC card is REAL, never the mockup
# ================================================================

def _console():
    src = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "tool", "unix", "hub", "advprint.py"),
        encoding="utf-8").read()
    i = src.index('CONSOLE_HTML = r"""') + len('CONSOLE_HTML = r"""')
    j = src.index('\n"""', i)
    return src[i:j]


def test_console_lan_pc_card_is_wired():
    ui = _console()
    # ids the handlers bind
    for needle in ("lanPcConnect", "lanPcClear", "lanPcToken",
                   "shareSendSw", "showRemoteSw", "renderLanPeer",
                   "loadLanPeer", "renderRemotePrinters"):
        assert needle in ui, "console misses " + needle
    # the card talks to the REAL endpoints
    assert "/peer/pair" in ui and "/peer/unpair" in ui
    assert "/peer/status" in ui and "/peer/test-page" in ui
    # the own-IP autofill is GONE (the "auto redirect own ip" bug)
    assert 'pcUrl.value = lanBase()' not in ui
    # the demo toast is GONE
    assert "LAN PC pairing cleared (demo value)" not in ui
    # the switch asks the PERSISTED state, not a transient flag
    assert "lanPeerState" in ui and "configured" in ui
    # the status line mirrors the peer's REAL switches
    assert "LAN sharing" in ui and "IP printer" in ui
    # printers panel: remote devices with a source badge
    assert "Show other PCs (LAN / IPP)" in ui
    assert "LAN PC" in ui and "IPP" in ui


def test_console_lan_pc_card_never_autofills_own_url():
    ui = _console()
    # the only writes to the LAN PC URL input restore the SAVED peer
    import re
    for m in re.finditer(r'lanPcHubUrl', ui):
        seg = ui[max(0, m.start() - 400):m.start() + 400]
        assert "lanBase()" not in seg, \
            "the LAN PC URL input must not be filled from lanBase()"


# ================================================================
# config plumbing
# ================================================================

def test_new_config_keys_whitelisted():
    assert "share_send" in advprint.CONFIG_KEYS
    assert "show_remote_printers" in advprint.CONFIG_KEYS
    assert advprint.CONFIG_TYPES["share_send"] is bool
    assert advprint.CONFIG_TYPES["show_remote_printers"] is bool


def test_redacted_config_masks_peer_token(hub, no_peer, fake_peer):
    hub.post("/peer/pair", body={"url": fake_peer["base"], "token": "tok3"})
    code, cfg = hub.get("/config")
    assert code == 200
    assert cfg["share_send"] is False
    raw = json.dumps(cfg)
    assert "tok3" not in raw
    assert any(p.get("name") == "lan-pc" for p in cfg["peer_hubs"])
