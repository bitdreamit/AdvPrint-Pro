"""v3.0.9 PER-PRINTER IPP QUEUES - the hub as central IPP middleware.

Every local printer gets its own queue on the hub:
    ipp://<lan-ip>:9235/ipp/print/<printer>
so child PCs / phones print to ONE exact printer of the center PC
without installing anything there.

These tests talk to a REAL hub over HTTP (the conftest fixture) and
check the full chain: queue-name matching (raw / URL-encoded / slug),
IPP Print-Job routed to the queue's printer, unknown queues rejected,
the per-queue landing page, /printers queue metadata and the mDNS
service list (one service per printer)."""
import re

import pytest

import advprint

# ------------------------------------------------------------ unit:
# queue name <-> slug matching
PRINTERS = ["HP Laser 103 107 108", "Microsoft Print to PDF",
            "OneNote (Desktop)", "AdvPrint Pro @ AI-Lab"]


@pytest.fixture
def printers(monkeypatch):
    monkeypatch.setattr(advprint, "list_printers_cached",
                        lambda max_age=60.0: list(PRINTERS))
    return PRINTERS


def test_slug_is_url_safe(printers):
    assert advprint._ipp_queue_slug("HP Laser 103 107 108") == \
        "hp-laser-103-107-108"
    assert advprint._ipp_queue_slug("OneNote (Desktop)") == "onenote-desktop"
    assert advprint._ipp_queue_slug("Microsoft Print to PDF") == \
        "microsoft-print-to-pdf"


def test_match_accepts_raw_encoded_and_slug(printers):
    # raw Windows name (as typed in Add Printer)
    assert advprint._ipp_queue_match("HP Laser 103 107 108") == \
        "HP Laser 103 107 108"
    # URL-encoded raw name (what Windows puts on the wire)
    assert advprint._ipp_queue_match("HP%20Laser%20103%20107%20108") == \
        "HP Laser 103 107 108"
    # slug form
    assert advprint._ipp_queue_match("onenote-desktop") == "OneNote (Desktop)"
    # case-insensitive + punctuation-insensitive
    assert advprint._ipp_queue_match("MICROSOFT-PRINT-TO-PDF") == \
        "Microsoft Print to PDF"
    # unknown / empty -> no match
    assert advprint._ipp_queue_match("no-such-printer") == ""
    assert advprint._ipp_queue_match("") == ""
    assert advprint._ipp_queue_match(None) == ""


def test_mdns_announces_one_service_per_printer(printers):
    svc = advprint._mdns_services()
    assert svc[0][1] == "ipp/print"          # classic central queue first
    rps = [s[1] for s in svc[1:]]
    assert "ipp/print/hp-laser-103-107-108" in rps
    assert "ipp/print/microsoft-print-to-pdf" in rps
    assert "ipp/print/onenote-desktop" in rps
    # every instance is unique
    insts = [s[0] for s in svc]
    assert len(insts) == len(set(insts))


def test_mdns_rrset_carries_per_printer_rp(monkeypatch, printers):
    monkeypatch.setattr(advprint, "_ipp_printer_uuid",
                        lambda: "urn:uuid:test-uuid")
    rr = advprint._mdns_rrset("192.168.1.50")
    blob = b"".join(r for r in rr)
    assert b"hp-laser-103-107-108" in blob
    # 4 printers + central = 5 services -> 2 PTR + 2 unique + 1 A each
    assert len(rr) == 5 * 4 + 1


# ------------------------------------------------------------ HTTP:
# real hub end-to-end (IPP Print-Job -> job row of THAT printer)
def _print_job_bytes(title="per-queue test"):
    opg = advprint._ipp_group(0x01, [
        advprint._ipp_attr(0x47, "attributes-charset", "utf-8"),
        advprint._ipp_attr(0x48, "attributes-natural-language", "en"),
        advprint._ipp_attr(0x45, "printer-uri",
                           "ipp://hub:9235/ipp/print/test"),
        advprint._ipp_attr(0x42, "job-name", title),
        advprint._ipp_attr(0x49, "document-format", "application/pdf"),
    ])
    return (bytes((1, 1)) + (0x0002).to_bytes(2, "big") +
            (1234).to_bytes(4, "big") + opg + b"\x03" +
            b"%PDF-1.4 tiny per-printer test")


@pytest.fixture
def ipp_on(monkeypatch):
    monkeypatch.setitem(advprint.CFG, "ipp_printer", True)
    monkeypatch.setitem(advprint.CFG, "share_lan", True)
    monkeypatch.setattr(advprint, "lan_ip", lambda: "192.168.1.50")


def test_print_job_per_printe_queue(hub, printers, ipp_on, clean_queue):
    code, payload = hub.req(
        "POST", "/ipp/print/hp-laser-103-107-108",
        token=None, raw=_print_job_bytes(),
        content_type="application/ipp")
    assert code == 200
    st = int.from_bytes(payload[2:4], "big")
    assert st < 0x0400                       # successful-ok band
    # job is enqueued FOR the queue's printer (db row carries it)
    code, jobs = hub.get("/jobs?limit=5")
    assert code == 200
    row = next(j for j in jobs["jobs"]
               if j["title"] == "per-queue test")
    assert row["printer"] == "HP Laser 103 107 108"


def test_print_job_encoded_raw_name_queue(hub, printers, ipp_on,
                                          clean_queue):
    # "@" + spaces - the raw Windows name must survive URL-encoding
    code, payload = hub.req(
        "POST", "/ipp/print/AdvPrint%20Pro%20%40%20AI-Lab",
        token=None, raw=_print_job_bytes("encoded queue"),
        content_type="application/ipp")
    assert code == 200
    code, jobs = hub.get("/jobs?limit=5")
    row = next(j for j in jobs["jobs"] if j["title"] == "encoded queue")
    assert row["printer"] == "AdvPrint Pro @ AI-Lab"


def test_virtual_pdf_printer_queue_saves_file(hub, printers, ipp_on,
                                              clean_queue):
    # v2.6.7 behavior kept intact (v3.0.9): "Microsoft Print to PDF" is
    # a VIRTUAL printer - the hub saves the file instead of popping a
    # Save-As dialog on the center PC, even when addressed per queue.
    code, payload = hub.req(
        "POST", "/ipp/print/Microsoft%20Print%20to%20PDF",
        token=None, raw=_print_job_bytes("virtual pdf queue"),
        content_type="application/ipp")
    assert code == 200
    code, jobs = hub.get("/jobs?limit=5")
    row = next(j for j in jobs["jobs"] if j["title"] == "virtual pdf queue")
    assert row["printer"] == "File (PDF)"
    assert row["status"] == "saved"


def test_unknown_queue_404(hub, printers, ipp_on):
    code, payload = hub.req(
        "POST", "/ipp/print/no-such-printer",
        token=None, raw=_print_job_bytes(),
        content_type="application/ipp")
    assert code == 404
    assert "unknown per-printer IPP queue" in str(payload)


def test_per_queue_landing_page(hub, printers, ipp_on):
    code, page = hub.get("/ipp/print/onenote-desktop", token=None)
    assert code == 200
    html = page.decode("utf-8") if isinstance(page, bytes) else str(page)
    assert "OneNote (Desktop)" in html
    assert ("ipp://192.168.1.50:%d/ipp/print/onenote-desktop"
            % advprint.CFG["port"]) in html
    code, _ = hub.get("/ipp/print/no-such-printer", token=None)
    assert code == 404


def test_printers_answers_queue_metadata(hub, printers, ipp_on):
    code, data = hub.get("/printers")
    assert code == 200
    assert data["ipp_per_printer"] is True
    assert data["ipp_central_url"].endswith("/ipp/print")
    by_name = {p["name"]: p for p in data["printers"]
               if not p.get("is_group")}
    assert by_name["HP Laser 103 107 108"]["ipp_queue"] == \
        "ipp://192.168.1.50:%d/ipp/print/hp-laser-103-107-108" \
        % advprint.CFG["port"]
    # v3.2.6 BUG FIX 2: ipp_path is the BARE slug (the console
    # joins "/ipp/print/" + slug itself - no doubled path any more)
    assert by_name["OneNote (Desktop)"]["ipp_path"] == "onenote-desktop"


def test_classic_central_queue_still_works(hub, printers, ipp_on,
                                           clean_queue):
    # the v2.9/v3.0.8 behavior must keep working unchanged
    code, payload = hub.req(
        "POST", "/ipp/print", token=None, raw=_print_job_bytes("central"),
        content_type="application/ipp")
    assert code == 200
    code, jobs = hub.get("/jobs?limit=5")
    assert any(j["title"] == "central" for j in jobs["jobs"])
