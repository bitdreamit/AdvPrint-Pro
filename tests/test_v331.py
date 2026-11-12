"""v3.3.1 - THE LAN PC + WINDOWS IPP CONNECTION RELEASE.

Locks the four user-reported bugs end to end:

BUG 1 - Windows "couldn't connect to the printer" on ipp://ip:9235/ipp/print
  AND ipp://ip:9235/ipp/print/<printer>. RFC 8011 requires
  printer-uri-supported / uri-authentication-supported /
  uri-security-supported to be three PARALLEL 1setOf attributes with the
  same value count. v3.3.0 emitted two fixed auth values and NO
  uri-security-supported at all, so echoing the LAN client's own URI
  (4 URIs / 2 auth values / no security list) failed the Microsoft IPP
  Class Driver validation. v3.3.1 builds the full parallel triple.

BUG 2 - per-printer IPP queues 404 right after hub start: the queue
  resolver only read the ASYNC printer cache (empty until the background
  enumeration landed). v3.3.1 enumerates synchronously when the cache is
  empty (rate-limited), so ipp://ip:9235/ipp/print/<printer> works the
  second the hub is up.

BUG 3 - the "Another PC (LAN PC)" card was a demo mockup: Connect read
  the SELF PC URL (input[0]) and toasted, Clear toasted "(demo value)",
  the CONNECTED chip was hardcoded and every refresh overwrote the URL
  input with this hub's own address ("share send mode auto-redirects to
  my own ip"). v3.3.1: real Connect (probe + save peer_hubs), real Clear,
  live chip, and a REAL Share Send Mode switch.

BUG 4 - Share Send Mode did not exist: peer_forwarding only forwarded
  jobs when the printer was REALLY down. v3.3.1 adds share_send_all -
  every printable job goes to the LAN PC; when that PC is unreachable the
  job is HELD (nothing prints locally behind the user's back; Print now
  overrides). Virtual PDF printers + raw/receipt jobs stay local.

Also locked: /peer-probe endpoint (server-side probe with token),
health keys (peer_forwarding / share_send_all / peer_hubs_count) and
byte-identical hub copies.
"""
import json
import os
import re
import socket
import struct
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import advprint
from conftest import ROOT

HUB_DIR = os.path.join(ROOT, "tool", "windows", "portable", "hub")
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

# ---- IPP wire helpers (same encoding as tests/test_ipp.py) ----
T_OP, T_END, T_PRINTER = 0x01, 0x03, 0x04
V_INT, V_BOOL, V_ENUM = 0x21, 0x22, 0x23
V_DATE, V_RANGE = 0x31, 0x33
V_TEXT, V_NAME, V_KEYWORD = 0x41, 0x42, 0x44
V_URI, V_CHARSET, V_LANG, V_MIME = 0x45, 0x47, 0x48, 0x49


def _attr(tag, name, value):
    if isinstance(value, int):
        value = struct.pack(">i", value)
    nb = name.encode()
    vb = value if isinstance(value, bytes) else str(value).encode()
    return (bytes([tag]) + len(nb).to_bytes(2, "big") + nb +
            len(vb).to_bytes(2, "big") + vb)


def _req(op, uri_path="/ipp/print", port=None, doc=b"", rid=7, ver=(1, 1),
         requested=None):
    out = bytearray()
    out += bytes(ver) + op.to_bytes(2, "big") + rid.to_bytes(4, "big")
    out += bytes([T_OP])
    out += _attr(V_CHARSET, "attributes-charset", "utf-8")
    out += _attr(V_LANG, "attributes-natural-language", "en")
    if port is not None:
        out += _attr(V_URI, "printer-uri",
                     "http://192.168.1.101:%d%s" % (port, uri_path))
        out += _attr(V_NAME, "requesting-user-name", "pytest")
    for r in (requested or []):
        out += _attr(V_KEYWORD, "requested-attributes", r)
    out += bytes([T_END])
    return bytes(out) + doc


def _gpa_groups(raw):
    """Parse an IPP response into the printer-attributes group as an
    ordered list of (name, [(tag, value), ...]) - additional values are
    kept so the RFC 8011 1setOf cardinality can be linted exactly the
    way the Microsoft IPP Class Driver does during Add Printer."""
    assert raw[0] in (1, 2)
    status = int.from_bytes(raw[2:4], "big")
    i, n = 8, len(raw)
    cur_pr = None
    last = ""
    while i < n:
        b = raw[i]
        if b == T_END:
            break
        if b in (T_OP, T_PRINTER, 0x02, 0x05):
            cur_pr = [] if b == T_PRINTER else None
            i += 1
            continue
        if i + 3 > n:
            break
        tag = b
        nl = int.from_bytes(raw[i + 1:i + 3], "big")
        i += 3
        name = raw[i:i + nl].decode("utf-8", "replace")
        i += nl
        if i + 2 > n:
            break
        vl = int.from_bytes(raw[i:i + 2], "big")
        i += 2
        val = raw[i:i + vl]
        i += vl
        if cur_pr is None:
            continue
        if tag == V_INT and len(val) == 4:
            val = str(struct.unpack(">i", val)[0])
        elif tag == V_ENUM and len(val) == 4:
            val = "enum:%d" % struct.unpack(">i", val)[0]
        elif tag == V_BOOL and len(val) == 1:
            val = "true" if val == b"\x01" else "false"
        elif tag in (V_TEXT, V_NAME, V_KEYWORD, V_URI, V_CHARSET,
                     V_LANG, V_MIME):
            val = val.decode("utf-8", "replace")
        else:
            val = "<bin %d>" % len(val)
        if not name:
            name = last
        else:
            last = name
        cur_pr.append((name, (tag, val)))
    return status, cur_pr


def _vals(group, name):
    return [val for (n, (_tag, val)) in group if n == name]


REQUIRED_PRINTER_ATTRS = (
    "printer-uri-supported", "uri-authentication-supported",
    "uri-security-supported",
    "printer-name", "printer-state", "printer-state-reasons",
    "ipp-versions-supported", "operations-supported",
    "charset-configured", "natural-language-configured",
    "document-format-default", "document-format-supported",
    "pdl-override-supported", "printer-is-accepting-jobs",
    "queued-job-count", "printer-up-time", "printer-current-time",
    "compression-supported",
)


def _windows_lint(hub, path, asked_uri):
    """The exact validation the Microsoft IPP Class Driver runs when
    'Add a printer using an IPP Device' is used from a LAN PC."""
    port = int(hub.base.rsplit(":", 1)[1])
    r = hub.req("POST", path, token=None, raw=_req(
        0x000B, uri_path=path, port=port,
        requested=["printer-name", "printer-state"]),
        content_type="application/ipp")
    assert isinstance(r, tuple) and r[0] == 200, r
    status, pr = _gpa_groups(r[1])
    assert status == 0x0000, hex(status)
    missing = [a for a in REQUIRED_PRINTER_ATTRS
               if not _vals(pr, a)]
    assert not missing, "missing %s" % missing
    uris = _vals(pr, "printer-uri-supported")
    auths = _vals(pr, "uri-authentication-supported")
    secs = _vals(pr, "uri-security-supported")
    # THE WINDOWS KILLER CHECKS:
    assert len(uris) == len(auths) == len(secs) and len(uris) > 0, \
        "uri triple cardinality: %d/%d/%d (%s)" % (
            len(uris), len(auths), len(secs), uris)
    assert all(v == "none" for v in secs), \
        "plain-http hub must answer security 'none'"
    assert asked_uri in uris, \
        "the URI the client asked for must be echoed: %s not in %s" % (
            asked_uri, uris)
    assert "1.1" in _vals(pr, "ipp-versions-supported")
    return pr, uris, auths, secs


# ---------------------------------------------------------------
# 1. version coherence 3.3.1
# ---------------------------------------------------------------

def test_version_331_everywhere():
    assert advprint.VERSION == "3.3.1"
    assert advprint.VERSION_NAME.startswith("v3.3.1")
    assert "LAN PC" in advprint.VERSION_NAME
    assert "3.3.1" in VERSION_TXT
    assert MANIFEST["version"] == "3.3.1"
    assert CHANGELOG.startswith("# Changelog") or "3.3.1" in CHANGELOG
    assert "3.3.1" in NSI
    # the ONE UI header shows the version too
    assert "3.3.1" in CONSOLE


def test_hub_copies_byte_identical():
    a = open(os.path.join(ROOT, "tool", "unix", "hub", "advprint.py"),
             encoding="utf-8").read()
    b = ADVPRINT_SRC
    assert a == b
    c = open(os.path.join(ROOT, "tool", "windows", "portable", "hub",
                          "console.html"), encoding="utf-8").read()
    d = open(os.path.join(ROOT, "tool", "unix", "hub", "console.html"),
             encoding="utf-8").read()
    assert c == d


def test_release_docs_331_exist():
    for name in ("AdvPrint-Pro-v3.3.1-A-to-Z-DEV-GUIDE.md",):
        p = os.path.join(ROOT, "docs", name)
        assert os.path.exists(p), p


# ---------------------------------------------------------------
# 2. BUG 1 - the RFC 8011 uri triple (Windows connect fix)
# ---------------------------------------------------------------

def test_ipp_uri_triple_generic_queue(hub, cfg_reset):
    port = int(hub.base.rsplit(":", 1)[1])
    asked = "http://192.168.1.101:%d/ipp/print" % port
    pr, uris, auths, secs = _windows_lint(hub, "/ipp/print", asked)


def test_ipp_uri_triple_per_printer_queue(hub, cfg_reset, monkeypatch):
    monkeypatch.setattr(advprint, "list_printers",
                        lambda: ["HP-Laser-103", "AI-Lab"])
    # shared module globals - other tests leave stale entries behind
    advprint._LP_CACHE["t"] = 0.0
    advprint._LP_CACHE["v"] = []
    advprint._QMATCH_CACHE.clear()
    advprint._LP_SYNC_TS[0] = 0.0
    port = int(hub.base.rsplit(":", 1)[1])
    asked = "http://192.168.1.101:%d/ipp/print/HP-Laser-103" % port
    pr, uris, auths, secs = _windows_lint(hub, "/ipp/print/HP-Laser-103",
                                          asked)
    names = _vals(pr, "printer-name")
    assert names and names[0] == "HP-Laser-103"


def test_ipp_uri_triple_with_echoed_aliased_uri(hub, cfg_reset):
    """A LAN PC that reached the hub via an address the canonical URIs do
    not list (second NIC / hostname) gets its exact URI echoed - and the
    auth/security lists must grow to the same cardinality."""
    port = int(hub.base.rsplit(":", 1)[1])
    asked = "http://hub-alias.lab.local:%d/ipp/print" % port
    # direct unit-level check of the group builder with an extra URI
    grp = advprint._ipp_printer_group(
        queue_slug="hp-laser-103", queue_name="HP-Laser-103",
        extra_uris=[asked, "ipp://" + asked[7:]])
    status, pr = _gpa_groups(advprint._ipp_response((1, 1), 0, 1, [grp]))
    uris = _vals(pr, "printer-uri-supported")
    auths = _vals(pr, "uri-authentication-supported")
    secs = _vals(pr, "uri-security-supported")
    assert len(uris) == len(auths) == len(secs) > 2
    assert asked in uris
    assert "none" in secs


def test_ipp_printer_group_unit_triple_always_parallel():
    """Even with NO extra URIs the security list must exist (v3.3.0
    omitted it entirely)."""
    grp = advprint._ipp_printer_group()
    status, pr = _gpa_groups(advprint._ipp_response((1, 1), 0, 1, [grp]))
    uris = _vals(pr, "printer-uri-supported")
    auths = _vals(pr, "uri-authentication-supported")
    secs = _vals(pr, "uri-security-supported")
    assert len(uris) >= 2
    assert len(uris) == len(auths) == len(secs)


# ---------------------------------------------------------------
# 3. BUG 2 - per-printer queue cold start (no 404)
# ---------------------------------------------------------------

def test_perprinter_queue_cold_start_resolves(monkeypatch):
    monkeypatch.setattr(advprint, "list_printers",
                        lambda: ["Cold-Printer-9", "Other"])
    advprint._LP_CACHE["t"] = 0.0
    advprint._LP_CACHE["v"] = []
    advprint._QMATCH_CACHE.clear()
    advprint._LP_SYNC_TS[0] = 0.0
    # first answer must already resolve - no waiting for async refreshes
    assert advprint._ipp_queue_match("Cold-Printer-9") == "Cold-Printer-9"
    assert advprint._ipp_queue_match("cold-printer-9") == "Cold-Printer-9"


def test_perprinter_queue_match_cached_negative_retries_sync(monkeypatch):
    """A slug that is unknown NOW must not be memoized forever when the
    printer appears seconds later (the forced refresh is synchronous)."""
    state = {"names": ["A-Printer"]}

    def fake_list():
        return list(state["names"])

    monkeypatch.setattr(advprint, "list_printers", fake_list)
    advprint._LP_CACHE["t"] = 0.0
    advprint._LP_CACHE["v"] = []
    advprint._QMATCH_CACHE.clear()
    advprint._QMATCH_LAST_FORCE["t"] = 0.0
    assert advprint._ipp_queue_match_cached("B-Printer") == ""
    state["names"].append("B-Printer")
    # 3 s forced-refresh window passed (real hubs have seconds between
    # the events) + the 2 s sync rate-limit reset - then the cached
    # negative answer is replaced by a fresh SYNCHRONOUS lookup
    import time as _time
    advprint._QMATCH_LAST_FORCE["t"] = _time.time() - 10.0
    advprint._LP_SYNC_TS[0] = _time.time() - 10.0
    advprint._QMATCH_CACHE.clear()
    assert advprint._ipp_queue_match_cached("B-Printer") == "B-Printer"


# ---------------------------------------------------------------
# 4. BUG 3+4 - Share Send Mode / LAN PC card (config + health)
# ---------------------------------------------------------------

def test_share_send_all_config_key_round_trip(hub, cfg_reset):
    r = hub.post("/config", body={"share_send_all": True})
    assert r[0] == 200 and r[1].get("ok")
    assert advprint.CFG["share_send_all"] is True
    snap = advprint.health_snapshot()
    assert snap["share_send_all"] is True
    assert snap["peer_forwarding"] is False
    assert snap["peer_hubs_count"] == 0
    hub.post("/config", body={"share_send_all": False})
    assert advprint.CFG["share_send_all"] is False


def test_peer_probe_live_peer(hub, cfg_reset):
    """Probe a REAL fake peer hub served in-process."""
    seen = {}

    class Peer(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            seen["path"] = self.path
            seen["token"] = self.headers.get("X-AdvPrint-Token")
            body = json.dumps({
                "ok": True, "version": "3.3.1",
                "hostname": "LAB-PC-2", "share_lan": True,
                "token_hint": "abcd"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    psrv = ThreadingHTTPServer(("127.0.0.1", 0), Peer)
    threading.Thread(target=psrv.serve_forever, daemon=True).start()
    try:
        purl = "http://127.0.0.1:%d" % psrv.server_address[1]
        code, data = hub.post("/peer-probe",
                              body={"url": purl, "token": "tok-abcd"})
        assert code == 200 and data["ok"]
        assert data["up"] is True
        assert data["version"] == "3.3.1"
        assert data["hostname"] == "LAB-PC-2"
        assert data["share_lan"] is True
        assert data["token_ok"] is True
        assert seen["token"] == "tok-abcd"
    finally:
        psrv.shutdown()


def test_peer_probe_dead_peer_and_bad_url(hub, cfg_reset):
    # dead peer -> up:false with a readable error, still HTTP 200
    code, data = hub.post("/peer-probe", body={
        "url": "http://127.0.0.1:9", "token": "x"})
    assert code == 200 and data["ok"] and data["up"] is False
    assert "no answer" in data.get("error", "")
    # non-LAN public host -> 400
    code, data = hub.post("/peer-probe", body={
        "url": "http://8.8.8.8:9235", "token": "x"})
    assert code == 400
    # malformed url -> 400
    code, data = hub.post("/peer-probe", body={"url": "ftp://x", "token": "x"})
    assert code == 400


def test_peer_probe_requires_token(hub):
    code, data = hub.req("POST", "/peer-probe", token=None,
                         body={"url": "http://127.0.0.1:9"})
    assert code == 401


# ---------------------------------------------------------------
# 5. BUG 4 - worker Share Send Mode end to end
# ---------------------------------------------------------------

MIN_PDF = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
           b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
           b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]>>endobj"
           b"\ntrailer<</Root 1 0 R>>\n%%EOF")


class PeerHub(BaseHTTPRequestHandler):
    """Fake LAN PC hub: /health 200, /print records + accepts."""
    jobs = []
    alive = True

    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/health":
            body = json.dumps({"ok": True, "version": "3.3.1",
                               "share_lan": True}).encode()
            self.send_response(200)
        else:
            body = b"{}"
            self.send_response(404)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path == "/print":
            n = int(self.headers.get("Content-Length") or 0)
            data = self.rfile.read(n)
            PeerHub.jobs.append({"token": self.headers.get("X-AdvPrint-Token"),
                                 "len": n, "body": json.loads(data)})
            body = json.dumps({"ok": True, "job_id": "remote-77"}).encode()
            self.send_response(200)
        else:
            body = b'{"ok": false}'
            self.send_response(404)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture()
def fake_peer(hub):
    PeerHub.jobs = []
    PeerHub.alive = True
    srv = ThreadingHTTPServer(("127.0.0.1", 0), PeerHub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield "http://127.0.0.1:%d" % srv.server_address[1]
    srv.shutdown()


def _wait_job_status(job_id, statuses, timeout=8.0):
    end = time.time() + timeout
    while time.time() < end:
        j = advprint.db_get(job_id)
        if j and j.get("status") in statuses:
            return j
        time.sleep(0.05)
    return advprint.db_get(job_id)


def test_share_send_mode_forwards_every_job(hub, cfg_reset, fake_peer):
    PeerHub.jobs = []
    hub.post("/config", body={
        "peer_hubs": [{"url": fake_peer, "token": "tok-peer",
                       "name": "LAB-PC-2"}],
        "peer_forwarding": True, "share_send_all": True})
    job_id = advprint.enqueue_print(
        "pdf", "share-send-every", MIN_PDF, source="pytest")[0]
    j = _wait_job_status(job_id, ("forwarded", "printed", "failed",
                                  "held"))
    assert j["status"] == "forwarded", j
    assert (j.get("peer") or "") == fake_peer
    assert PeerHub.jobs, "the peer hub never received the document"
    p = PeerHub.jobs[0]
    assert p["token"] == "tok-peer"
    assert p["body"]["title"] == "share-send-every"
    assert p["body"]["source"].startswith("share-send:")
    hub.post("/config", body={"peer_hubs": [], "peer_forwarding": False,
                              "share_send_all": False})


def test_share_send_mode_holds_when_lan_pc_down(hub, cfg_reset):
    hub.post("/config", body={
        "peer_hubs": [{"url": "http://127.0.0.1:9", "token": "x",
                       "name": "dead"}],
        "peer_forwarding": True, "share_send_all": True})
    job_id = advprint.enqueue_print(
        "pdf", "share-send-hold", MIN_PDF, source="pytest")[0]
    j = _wait_job_status(job_id, ("held", "failed", "printed"))
    assert j["status"] == "held", j
    assert "LAN PC hub unreachable" in (j.get("held_reason") or "")
    # after the peer comes back the hold is released by the worker loop
    # (release pass) - covered by the live repro script; here the config
    # is restored for the following tests
    hub.post("/config", body={"peer_hubs": [], "peer_forwarding": False,
                              "share_send_all": False})


def test_legacy_peer_forwarding_offline_fallback_unchanged(hub, cfg_reset,
                                                           monkeypatch):
    """peer_forwarding WITHOUT share_send_all keeps the v2.9.1 M4
    behaviour: forward only when the printer is REALLY down."""
    monkeypatch.setattr(advprint, "printer_ready",
                        lambda name: "offline")
    hub.post("/config", body={
        "peer_hubs": [{"url": "http://127.0.0.1:9", "token": "x",
                       "name": "dead"}],
        "peer_forwarding": True, "share_send_all": False})
    job_id = advprint.enqueue_print(
        "pdf", "legacy-offline", MIN_PDF, source="pytest")[0]
    j = _wait_job_status(job_id, ("held", "forwarded", "failed", "printed"))
    assert j["status"] == "held"          # dead peer -> hold (unchanged)
    hub.post("/config", body={"peer_hubs": [], "peer_forwarding": False})


# ---------------------------------------------------------------
# 6. BUG 3 - the console LAN PC card is real
# ---------------------------------------------------------------

def test_console_lan_pc_card_no_own_ip_overwrite():
    assert 'id="lanPcCard"' in CONSOLE
    assert 'id="lanPcConnect"' in CONSOLE
    assert 'id="lanPcClear"' in CONSOLE
    assert 'id="lanPcChip"' in CONSOLE
    assert 'id="lanPcToken"' in CONSOLE
    assert 'id="lanPcSendSw"' in CONSOLE
    # the own-IP overwrite that broke Share Send Mode is GONE
    assert "pcUrl.value = lanBase()" not in CONSOLE
    # the demo toasts are gone
    assert 'toast("LAN PC pairing cleared (demo value)"' not in CONSOLE
    # hardcoded demo CONNECTED chip on the LAN PC card is gone
    card = CONSOLE.split('id="lanPcCard"')[1].split("</div>\n          </div>")[0]
    assert "CONNECTED" not in card.split("<p>")[0]
    assert "10.26.94.77" not in card
    # the switch promises the exact behaviour the user quoted
    assert "Share Send Mode" in CONSOLE


def test_console_connect_uses_peer_probe_then_config():
    # Connect probes server-side (no CORS pain) and saves peer_hubs
    assert 'api("/peer-probe"' in CONSOLE
    assert "peer_hubs: peers" in CONSOLE
    assert "peer_forwarding: true" in CONSOLE
    # Clear wipes both switches too
    assert "share_send_all: false" in CONSOLE
    # the switch saves BOTH keys instantly
    assert "share_send_all: want" in CONSOLE
    # guard: cannot flip ON without a connected peer
    assert "Connect the LAN PC first" in CONSOLE


def test_health_snapshot_share_send_keys():
    snap = advprint.health_snapshot()
    for k in ("peer_forwarding", "share_send_all", "peer_hubs_count"):
        assert k in snap


def test_version_bump_sync_copies():
    """The unix hub must carry the same release string as the portable
    hub (single source of truth for the version)."""
    unix = open(os.path.join(ROOT, "tool", "unix", "hub", "advprint.py"),
                encoding="utf-8").read()
    m = re.search(r'VERSION\s*=\s*"([^"]+)"', unix)
    assert m and m.group(1) == "3.3.1"
    assert 'VERSION_NAME = ("v3.3.1' in unix
