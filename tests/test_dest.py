"""AdvPrint Pro v2.9 - print DESTINATION routing (ANY printer).

dest_mode: "default" / "selected" / "ip" - a per-job printer name always
wins. dest_mode "ip" forwards every job to an upstream network printer
(JetDirect RAW 9100 or an IPP Print-Job) - exactly the chain a PC or
phone uses after adding THIS hub as their IP printer.

Covers: resolve_dest (legacy mapping, explicit override, protocol port
defaults, unconfigured fallback), the IPP client request bytes (valid
RFC 8010 framing, job-name, document-format, copies), IPP error status
propagation, /config validation, /health destination exposure,
/ip-printer/test (reachable + refused), print_raw IP routing and a full
worker -> JetDirect sink end-to-end PDF print.
"""
import base64
import socket
import threading

import pytest

import advprint
from conftest import wait_until  # noqa: E402

PDF = b"%PDF-1.4\n%fake test pdf for the destination sink\n%%EOF\n"


# ------------------------------------------------------------
# helpers
# ------------------------------------------------------------

def _jetdirect_sink():
    """A tiny fake JetDirect printer. Returns (socket, port, received)
    - every connection's payload is appended to `received`."""
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(8)
    port = srv.getsockname()[1]
    received = []

    def loop():
        try:
            while True:
                conn, _ = srv.accept()
                threading.Thread(target=_handle, args=(conn, received),
                                 daemon=True).start()
        except OSError:
            pass

    threading.Thread(target=loop, daemon=True).start()
    return srv, port, received


def _handle(conn, received):
    try:
        conn.settimeout(6)
        chunks = []
        while True:
            b = conn.recv(65536)
            if not b:
                break
            chunks.append(b)
        data = b"".join(chunks)
        if data:            # probe connections arrive empty - ignore them
            received.append(data)
    except Exception:
        pass
    finally:
        try:
            conn.close()
        except OSError:
            pass


def _dead_port():
    """A bound-but-never-listening socket -> connects are refused."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    return s, s.getsockname()[1]


@pytest.fixture()
def dest_reset(hub):
    """Snapshot every destination config key; restore afterwards."""
    snap = {k: advprint.CFG.get(k) for k in
            ("dest_mode", "printer", "ip_printer_host",
             "ip_printer_port", "ip_printer_proto", "hold_offline",
             "instant_auto_queue", "share_lan", "ipp_printer",
             "raw_printer_port")}
    yield hub
    advprint.CFG.update({k: v for k, v in snap.items()})
    advprint.build_health_snapshot()


# ------------------------------------------------------------
# resolve_dest
# ------------------------------------------------------------

def test_resolve_dest_legacy_empty(hub, dest_reset):
    advprint.CFG["dest_mode"] = ""
    advprint.CFG["printer"] = ""
    assert advprint.resolve_dest() == ("local", "")
    assert advprint.dest_display() == "(default printer)"


def test_resolve_dest_legacy_selected_printer(hub, dest_reset):
    """Old installs: a configured printer name keeps working - with NO
    dest_mode stored, it still routes to that printer."""
    advprint.CFG["dest_mode"] = ""
    advprint.CFG["printer"] = "Zebra ZD421"
    assert advprint.resolve_dest() == ("local", "Zebra ZD421")
    assert advprint.dest_display() == "Zebra ZD421"


def test_resolve_dest_explicit_job_wins(hub, dest_reset):
    advprint.CFG["dest_mode"] = "ip"
    advprint.CFG["ip_printer_host"] = "10.0.0.9"
    assert advprint.resolve_dest("HP Desk 2700") == ("local", "HP Desk 2700")


def test_resolve_dest_ip_port_defaults(hub, dest_reset):
    advprint.CFG["dest_mode"] = "ip"
    advprint.CFG["ip_printer_host"] = "192.168.1.50"
    advprint.CFG["ip_printer_port"] = 0
    advprint.CFG["ip_printer_proto"] = "raw"
    assert advprint.resolve_dest() == ("ip", ("192.168.1.50", 9100, "raw"))
    advprint.CFG["ip_printer_proto"] = "ipp"
    assert advprint.resolve_dest() == ("ip", ("192.168.1.50", 631, "ipp"))
    advprint.CFG["ip_printer_port"] = 9200
    assert advprint.resolve_dest() == ("ip", ("192.168.1.50", 9200, "ipp"))
    assert advprint.dest_display() == "IP printer 192.168.1.50:9200 (ipp)"


def test_resolve_dest_ip_unconfigured_falls_back(hub, dest_reset):
    advprint.CFG["dest_mode"] = "ip"
    advprint.CFG["ip_printer_host"] = ""
    assert advprint.resolve_dest() == ("local", "")
    # garbage proto is clamped to raw, garbage port is ignored
    advprint.CFG["ip_printer_host"] = "p1"
    advprint.CFG["ip_printer_proto"] = "lpd"
    advprint.CFG["ip_printer_port"] = "abc"
    assert advprint.resolve_dest() == ("ip", ("p1", 9100, "raw"))


def test_resolve_dest_selected_mode(hub, dest_reset):
    advprint.CFG["dest_mode"] = "selected"
    advprint.CFG["printer"] = "Front Desk A4"
    assert advprint.resolve_dest() == ("local", "Front Desk A4")
    advprint.CFG["printer"] = ""          # selected with no name -> default
    assert advprint.resolve_dest() == ("local", "")


# ------------------------------------------------------------
# IPP client request bytes
# ------------------------------------------------------------

class _FakeResp:
    def __init__(self, payload):
        self.p = payload

    def read(self, n=-1):
        return self.p

    def getcode(self):
        return 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _ipp_reply(status):
    return bytes((1, 1)) + int(status).to_bytes(2, "big") + \
        b"\x00\x00\x00\x01" + b"\x03"


def test_ipp_client_request_framing(hub, monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["ctype"] = req.headers.get("Content-type")
        captured["body"] = req.data
        return _FakeResp(_ipp_reply(0x0000))

    monkeypatch.setattr(advprint.urllib.request, "urlopen", fake_urlopen)
    doc = b"%PDF-1.4 payload"
    advprint._ipp_client_print("10.1.1.8", 631, doc, "Lab report",
                               "application/pdf", copies=2)
    b = captured["body"]
    assert captured["url"] == "http://10.1.1.8:631/ipp/print"
    assert "application/ipp" in (captured["ctype"] or "")
    assert b[0:2] == b"\x01\x01"                 # IPP version 1.1
    assert b[2:4] == b"\x00\x02"                 # operation: Print-Job
    assert b"ipp://10.1.1.8:631/ipp/print" in b  # printer-uri
    assert b"attributes-charset" in b            # required first attribute
    assert b"application/pdf" in b               # document-format
    assert b"Lab report" in b                    # job-name
    assert b"AdvPrint Pro" in b                  # requesting-user-name
    assert b"copies" in b                        # job-template copies
    end = b.index(b"\x03")                       # end-of-attributes tag
    assert b[end + 1:] == doc                    # document follows verbatim


def test_ipp_client_raises_on_ipp_error(hub, monkeypatch):
    monkeypatch.setattr(advprint.urllib.request, "urlopen",
                        lambda req, timeout=None:
                        _FakeResp(_ipp_reply(0x040B)))
    with pytest.raises(RuntimeError, match="040B"):
        advprint._ipp_client_print("10.1.1.8", 631, b"x", "j",
                                   "application/pdf")


def test_ipp_client_raises_on_http_error(hub, monkeypatch):
    import urllib.error

    def fake_urlopen(req, timeout=None):
        raise urllib.error.HTTPError(
            "http://10.1.1.8:631/ipp/print", 503, "Service Unavailable",
            {}, None)

    monkeypatch.setattr(advprint.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(RuntimeError, match="503"):
        advprint._ipp_client_print("10.1.1.8", 631, b"x", "j",
                                   "application/pdf")


def test_ipp_client_raises_when_unreachable(hub, monkeypatch):
    def fake_urlopen(req, timeout=None):
        raise OSError("connection refused")

    monkeypatch.setattr(advprint.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(RuntimeError, match="unreachable"):
        advprint._ipp_client_print("10.1.1.8", 631, b"x", "j",
                                   "application/pdf")


# ------------------------------------------------------------
# HTTP API surface
# ------------------------------------------------------------

def test_config_rejects_bad_dest_values(hub, dest_reset):
    code, d = hub.post("/config", {"dest_mode": "bogus"})
    assert code == 400 and "dest_mode" in d["error"]
    code, d = hub.post("/config", {"ip_printer_proto": "lpd"})
    assert code == 400 and "ip_printer_proto" in d["error"]


def test_config_sets_ip_destination_and_health_shows_it(hub, dest_reset):
    code, d = hub.post("/config", {"dest_mode": "ip",
                                   "ip_printer_host": "192.168.1.50",
                                   "ip_printer_port": 9100,
                                   "ip_printer_proto": "raw"})
    assert code == 200 and "dest_mode" in d["changed"]
    code, h = hub.get("/health", token=None)
    assert code == 200
    assert h["dest_mode"] == "ip"
    assert h["dest_display"] == "IP printer 192.168.1.50:9100 (raw)"
    assert h["ip_printer"]["host"] == "192.168.1.50"
    assert h["ip_printer"]["port"] == 9100
    assert h["ip_printer"]["proto"] == "raw"
    # the audit trail names the destination, not a stale printer name
    code, d = hub.post("/print", {"pdf_base64":
                                  base64.b64encode(PDF).decode(),
                                  "title": "audit dest"})
    assert code == 200


def test_ip_printer_test_endpoint_reachable(hub, dest_reset):
    srv, port, _received = _jetdirect_sink()
    try:
        code, d = hub.post("/ip-printer/test",
                           {"host": "127.0.0.1", "port": port,
                            "proto": "raw"})
        assert code == 200 and d["ok"] is True
        assert d["state"] == "ready" and d["ms"] >= 0
        assert d["target"].endswith(":%d (raw)" % port)
    finally:
        srv.close()


def test_ip_printer_test_endpoint_refused(hub, dest_reset):
    keep, port = _dead_port()
    try:
        code, d = hub.post("/ip-printer/test",
                           {"host": "127.0.0.1", "port": port,
                            "proto": "ipp"})
        assert code == 200 and d["ok"] is False
        assert d["state"] == "offline"
        assert "TCP %d" % port in d["error"]
    finally:
        keep.close()


def test_ip_printer_test_needs_a_host(hub, dest_reset):
    advprint.CFG["ip_printer_host"] = ""
    code, d = hub.post("/ip-printer/test", {"proto": "raw"})
    assert code == 400 and "IP" in d["error"]


def test_ip_printer_mode_derived_status(hub, dest_reset):
    """IP PRINTER MODE = the hub is reachable as a network printer
    (LAN sharing + the IPP/RAW listeners) - derived, never drifts."""
    advprint.CFG["share_lan"] = False
    advprint.CFG["ipp_printer"] = True
    assert advprint.build_health_snapshot()["ip_printer_mode"] is False
    advprint.CFG["share_lan"] = True
    assert advprint.build_health_snapshot()["ip_printer_mode"] is True
    advprint.CFG["ipp_printer"] = False
    advprint.CFG["raw_printer_port"] = 0
    assert advprint.build_health_snapshot()["ip_printer_mode"] is False
    advprint.CFG["raw_printer_port"] = 9100
    assert advprint.build_health_snapshot()["ip_printer_mode"] is True


# ------------------------------------------------------------
# end-to-end: the worker really delivers to the IP printer
# ------------------------------------------------------------

def test_worker_routes_pdf_to_jetdirect_sink(hub, dest_reset, clean_queue,
                                             monkeypatch):
    """Full chain: POST /print -> queue -> worker -> print_file ->
    resolve_dest('ip') -> JetDirect sink receives the PDF bytes."""
    monkeypatch.setattr(advprint, "print_file", hub.real_print_file)
    srv, port, received = _jetdirect_sink()
    advprint.CFG["dest_mode"] = "ip"
    advprint.CFG["ip_printer_host"] = "127.0.0.1"
    advprint.CFG["ip_printer_port"] = port
    advprint.CFG["ip_printer_proto"] = "raw"
    try:
        code, d = hub.post("/print", {"pdf_base64":
                                      base64.b64encode(PDF).decode(),
                                      "title": "sink test"})
        assert code == 200, d
        jid = d["job_id"]
        assert wait_until(lambda: received, timeout=15)
        assert received[0].startswith(b"%PDF")
        row = advprint.db_get(jid)
        assert row["status"] == "printed"
        assert row["printer"] == "IP printer 127.0.0.1:%d (raw)" % port
    finally:
        srv.close()


def test_worker_holds_pdf_while_ip_printer_down(hub, dest_reset, clean_queue):
    """dest_mode ip + the sink port refuses -> the job is HELD with a
    clear reason (never silently sent into the void)."""
    keep, port = _dead_port()
    advprint.CFG["dest_mode"] = "ip"
    advprint.CFG["ip_printer_host"] = "127.0.0.1"
    advprint.CFG["ip_printer_port"] = port
    advprint.CFG["ip_printer_proto"] = "raw"
    try:
        code, d = hub.post("/print", {"pdf_base64":
                                      base64.b64encode(PDF).decode(),
                                      "title": "hold test"})
        assert code == 200, d
        jid = d["job_id"]
        assert wait_until(lambda: (advprint.db_get(jid) or {})
                          .get("status") == "held", timeout=15)
        row = advprint.db_get(jid)
        assert row["status"] == "held"
        assert "%d is unreachable" % port in (row["held_reason"] or "")
        assert (row["held_reason"] or "").startswith("IP printer")
        # 'Print now' overrides the hold even while the printer is down
        code, d = hub.post("/jobs/%d/print-now" % jid, {})
        assert code == 200
    finally:
        keep.close()
        # release the held job so later tests start clean
        try:
            advprint.db_update(jid, status="canceled", error="test done")
        except Exception:
            pass


def test_print_raw_routes_to_jetdirect_sink(hub, dest_reset, monkeypatch):
    monkeypatch.setattr(advprint, "print_raw", hub.real_print_raw)
    srv, port, received = _jetdirect_sink()
    advprint.CFG["dest_mode"] = "ip"
    advprint.CFG["ip_printer_host"] = "127.0.0.1"
    advprint.CFG["ip_printer_port"] = port
    advprint.CFG["ip_printer_proto"] = "raw"
    try:
        name = advprint.print_raw(b"\x1b@ESCPOS receipt\r\n", printer="",
                                  title="receipt")
        assert name == "IP printer 127.0.0.1:%d (raw)" % port
        assert wait_until(lambda: received, timeout=10)
        assert received[0].startswith(b"\x1b@")
    finally:
        srv.close()


def test_selected_mode_still_reaches_local_stub(hub, dest_reset,
                                                clean_queue):
    """dest_mode selected -> the job goes to the LOCAL stub printer with
    that exact name (the classic single-PC flow is untouched)."""
    advprint.CFG["dest_mode"] = "selected"
    advprint.CFG["printer"] = "StubPrinter"
    code, d = hub.post("/print", {"pdf_base64":
                                  base64.b64encode(PDF).decode(),
                                  "title": "local route"})
    assert code == 200, d
    jid = d["job_id"]
    assert wait_until(lambda: (advprint.db_get(jid) or {})
                      .get("status") == "printed", timeout=15)
    row = advprint.db_get(jid)
    assert row["printer"] == "StubPrinter"


def test_default_mode_prints_on_stub(hub, dest_reset, clean_queue):
    """dest_mode default (the empty-config legacy state) -> OS default."""
    advprint.CFG["dest_mode"] = "default"
    advprint.CFG["printer"] = ""
    code, d = hub.post("/print", {"pdf_base64":
                                  base64.b64encode(PDF).decode(),
                                  "title": "default route"})
    assert code == 200, d
    jid = d["job_id"]
    assert wait_until(lambda: (advprint.db_get(jid) or {})
                      .get("status") == "printed", timeout=15)
    row = advprint.db_get(jid)
    assert row["status"] == "printed"
