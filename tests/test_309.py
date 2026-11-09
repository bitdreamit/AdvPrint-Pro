"""v3.0.9 BUG-FIX RELEASE - regression tests.

Two fixes ship in 3.0.9 (on the v3.0.8 professional IPP printer base):

(1) DEFAULT-PRINTER DROPDOWN DOUBLING: the extension showed every
    printer name twice ("HP Laser 103 107 108HP Laser 103 107 108",
    "AdvPrint Pro @ AI-LabAdvPrint Pro @ AI-Lab", ...). v3.0.9 heals
    the names at the SOURCE in the hub (list_printers /
    default_printer / status maps collapse a name that is the same
    text twice in a row) and the options page heals + dedupes
    defensively for older hubs.

(2) PER-PRINTER IPP MIDDLEWARE: every local printer also gets its own
    ipp://host:9235/ipp/print/<printer> queue + its own mDNS/Bonjour
    announcement (rp=ipp/print/<printer>, per-queue stable UUID).
    The hub becomes the central IPP middleware for ALL PC printers.
"""
import time

import pytest

import advprint

# reuse the strict wire parser + packet builders from the 3.0.8 suite
from test_ipp import (_attr, _kw, _req, _strict_parse, _val,
                      V_CHARSET, V_INT, V_LANG, V_NAME, V_URI)

# ---------------------------------------------------------------
# (1) doubled-name healing - the exact names from the bug report
# ---------------------------------------------------------------
BUG_NAMES = [
    ("AdvPrint Pro @ AI-LabAdvPrint Pro @ AI-Lab", "AdvPrint Pro @ AI-Lab"),
    ("OneNote (Desktop)OneNote (Desktop)", "OneNote (Desktop)"),
    ("Microsoft Print to PDFMicrosoft Print to PDF",
     "Microsoft Print to PDF"),
    ("HP Laser 103 107 108HP Laser 103 107 108", "HP Laser 103 107 108"),
]


@pytest.mark.parametrize("bad,good", BUG_NAMES)
def test_heal_doubled_name_bug_report(bad, good):
    assert advprint._heal_doubled_name(bad) == good


def test_heal_doubled_name_never_mangles():
    # healthy names pass through untouched (odd length, no doubling)
    for ok in ("HP Laser 103 107 108", "OKI", "", None, "ab", "abcabcabc"):
        assert advprint._heal_doubled_name(ok) == (ok or "")
    # quad-doubled collapses all the way down
    assert advprint._heal_doubled_name("HPHPHPHP") == "HP"


def test_list_printers_heals_and_dedupes(monkeypatch):
    class FakeOut:
        stdout = ("HP Laser 103 107 108HP Laser 103 107 108\n"
                  "OneNote (Desktop)OneNote (Desktop)\n"
                  "HP Laser 103 107 108\n")     # dup (different case-free)
        stderr = ""

    def fake_run(*a, **kw):
        return FakeOut()

    monkeypatch.setattr(advprint.subprocess, "run", fake_run)
    names = advprint.list_printers()
    assert names == ["HP Laser 103 107 108", "OneNote (Desktop)"]


# ---------------------------------------------------------------
# (2) per-printer IPP queues
# ---------------------------------------------------------------
def test_ipp_queue_target_parsing():
    assert advprint._ipp_queue_target("/ipp/print") == ""
    assert advprint._ipp_queue_target("/ipp") == ""
    assert advprint._ipp_queue_target("/ipp/print/HP%20Laser%20103") == \
        "HP Laser 103"
    # %2F survives -> names with slashes work
    assert advprint._ipp_queue_target("/ipp/print/Canon%20LBP6230%2F6240") \
        == "Canon LBP6230/6240"
    # a doubled queue name heals to the real printer
    assert advprint._ipp_queue_target(
        "/ipp/print/HP%20LaserHP%20Laser") == "HP Laser"


def test_ipp_queue_known_fail_open(monkeypatch):
    # empty enumeration -> never blocks a queue
    monkeypatch.setattr(advprint, "_LP_CACHE",
                        {"t": time.time(), "v": []})
    assert advprint._ipp_queue_known("Anything") is True
    # non-empty enumeration -> exact (case-insensitive) match required
    monkeypatch.setattr(advprint, "_LP_CACHE",
                        {"t": time.time(), "v": ["HP Laser 103 107 108"]})
    assert advprint._ipp_queue_known("HP Laser 103 107 108") is True
    assert advprint._ipp_queue_known("hp laser 103 107 108") is True
    assert advprint._ipp_queue_known("Nope") is False


def test_route_print_payload_passes_printer(monkeypatch):
    got = {}

    def fake_enqueue(kind, title, data, **kw):
        got.update(kind=kind, title=title, **kw)
        return (123, None)

    monkeypatch.setattr(advprint, "enqueue_print", fake_enqueue)
    pdf = b"%PDF-1.4 tiny"
    advprint.route_print_payload(pdf, "t", "1.2.3.4", source="ipp",
                                 printer="HP Laser")
    assert got["printer"] == "HP Laser"
    got.clear()
    advprint.route_print_payload(pdf, "t", "1.2.3.4", source="raw9100")
    assert got["printer"] == ""            # main queue: hub routing as before


def _ipp_post_queue(hub, path, body):
    return hub.req("POST", path, raw=body, token=None,
                   headers={"Content-Type": "application/ipp"})


def test_gpa_per_printer_queue(hub):
    # what Windows/CUPS send for ipp://host:9235/ipp/print/HP%20Laser
    pkt = _req(0x000B)                      # Get-Printer-Attributes
    code, raw = _ipp_post_queue(hub, "/ipp/print/HP%20Laser%20103", pkt)
    assert code == 200
    status, groups = _strict_parse(raw)
    assert status == 0x0000
    _tag, name = _val(groups, 1, "printer-name")
    assert name.decode() == "HP Laser 103"
    _tag, uuid = _val(groups, 1, "printer-uuid")
    main_pkt = _req(0x000B)
    _code, main_raw = _ipp_post_queue(hub, "/ipp/print", main_pkt)
    _st2, g2 = _strict_parse(main_raw)
    _t2, main_uuid = _val(g2, 1, "printer-uuid")
    assert uuid != main_uuid               # per-queue stable UUID
    _t3, uri = _val(groups, 1, "printer-uri-supported")
    assert b"/ipp/print/HP%20Laser%20103" in uri


def test_print_job_unknown_queue_rejected(hub, monkeypatch):
    monkeypatch.setattr(advprint, "_LP_CACHE",
                        {"t": time.time(), "v": ["StubPrinter"]})
    pkt = _req(0x0002, doc=b"%PDF-1.4 tiny")   # Print-Job
    code, raw = _ipp_post_queue(hub, "/ipp/print/NoSuchPrinter", pkt)
    status, _g = _strict_parse(raw)
    assert status == 0x0406                # client-error-not-found


def test_print_job_per_printer_targets_that_printer(hub, monkeypatch):
    monkeypatch.setattr(advprint, "_LP_CACHE",
                        {"t": time.time(), "v": ["StubPrinter"]})
    n_before = len(hub.printed)
    pkt = _req(0x0002, doc=b"%PDF-1.4 tiny")
    code, raw = _ipp_post_queue(hub, "/ipp/print/StubPrinter", pkt)
    status, groups = _strict_parse(raw)
    assert status == 0x0000
    # the FIFO worker prints it with the queue's printer
    end = time.time() + 8
    while len(hub.printed) == n_before and time.time() < end:
        time.sleep(0.05)
    assert len(hub.printed) > n_before
    assert hub.printed[-1]["printer"] == "StubPrinter"


def test_create_job_send_document_per_printer(hub, monkeypatch):
    monkeypatch.setattr(advprint, "_LP_CACHE",
                        {"t": time.time(), "v": ["StubPrinter"]})
    pkt = _req(0x0005, extra=[_kw("job-name", "ipp-session")])
    code, raw = _ipp_post_queue(hub, "/ipp/print/StubPrinter", pkt)
    status, groups = _strict_parse(raw)
    assert status == 0x0000
    _tag, jid_b = _val(groups, 1, "job-id")
    jid = struct_unpack_int(jid_b)
    doc = _req(0x0006, doc=b"%PDF-1.4 tiny",
               extra=[_kw("last-document", "true")])
    # Send-Document carries the job-id (integer attr) - build it here
    import struct as _s
    doc = bytearray(doc)
    # append job-id into the op group: rebuild instead - simpler:
    pkt2 = _req(0x0006, doc=b"%PDF-1.4 tiny",
                extra=[_attr(V_INT, "job-id", _s.pack(">i", jid)),
                       _kw("last-document", "true")])
    code2, raw2 = _ipp_post_queue(hub, "/ipp/print/StubPrinter", pkt2)
    status2, _g2 = _strict_parse(raw2)
    assert status2 == 0x0000


def struct_unpack_int(b):
    import struct as _s
    return _s.unpack(">i", b)[0]


def test_printers_endpoint_reports_ipp_urls(hub):
    code, body = hub.get("/printers")
    assert code == 200 and body.get("ok")
    real = [p for p in body["printers"] if not p.get("is_group")]
    for p in real:
        assert p["ipp_url"].startswith("ipp://")
        assert "/ipp/print/" + urllib_quote(p["name"]) == \
            p["ipp_url"].split(":", 3)[3]


def urllib_quote(s):
    import urllib.parse
    return urllib.parse.quote(s, safe="")


def test_ipp_info_page_per_printer(hub):
    code, body = hub.req("GET", "/ipp/print/HP%20Laser%20103", token=None)
    assert code == 200
    text = body.decode("utf-8", "replace")
    assert "HP Laser 103" in text
    assert "ipp/print/HP%20Laser%20103" in text


def test_mdns_one_service_per_printer(monkeypatch):
    names = ["HP Laser 103 107 108",
             "OneNote (Desktop)OneNote (Desktop)"]
    monkeypatch.setattr(advprint, "_LP_CACHE",
                        {"t": time.time(), "v": names})
    rr = advprint._mdns_rrset("192.168.1.7")
    # per-printer rp TXT records, with HEALED names
    assert any(b"rp=ipp/print/HP%20Laser%20103%20107%20108" in r
               for r in rr)
    assert any(b"rp=ipp/print/OneNote%20%28Desktop%29" in r for r in rr)
    # PTR browse list includes every instance (DNS wire = length-prefixed
    # labels: "\x11OneNote (Desktop)\x04_ipp\x04_tcp\x05local\x00")
    def dns_name(inst):
        out = b""
        for label in ("%s._ipp._tcp.local" % inst).split("."):
            lb = label.encode()[:63]
            out += bytes([len(lb)]) + lb
        return out + b"\x00"

    ptrs = b"".join(rr)
    assert dns_name("OneNote (Desktop)") in ptrs
    assert dns_name(advprint._mdns_instance_name()) in ptrs
    # no doubled name anywhere on the wire
    assert not any(b"OneNote (Desktop)OneNote" in r for r in rr)


def test_mdns_packet_size_stays_sane(monkeypatch):
    monkeypatch.setattr(advprint, "_LP_CACHE",
                        {"t": time.time(),
                         "v": ["Printer %d" % i for i in range(20)]})
    pkt = advprint._mdns_packet(advprint._mdns_rrset("192.168.1.7"))
    assert len(pkt) < 9000
    # cap respected: 12 queues max + the main hub queue
    assert len(advprint._mdns_printer_queues()) == 12
