"""v3.0.8 PROFESSIONAL IPP PRINTER - protocol conformance tests.

Root cause fixed in 3.0.8: the old printer group encoded printer-state
as an ASCII "3" inside a charset-tagged attribute, booleans inside an
enum tag, integers inside a boolean tag and a range inside a boolean
tag - and omitted every RFC 8011-required printer description
attribute. Windows' strict Microsoft IPP Class Driver therefore
answered "Windows couldn't connect to the printer".

These tests talk to a REAL hub over HTTP and lint every response with
a STRICT wire parser: every attribute must carry the RFC 8010 value
tag that matches its name (enum/integer/boolean/range/uri/keyword/...),
binary values must have the exact byte widths, additional values must
repeat the primary tag, and the required Get-Printer-Attributes set
must be present. The request side mimics what Windows 10/11
("IPP Device"), macOS CUPS and phone print stacks actually send:
http:// printer URIs, 1.1 + 2.0 versions, Create-Job + Send-Document
sessions and chunked upload bodies.
"""
import http.client
import struct
import time
import urllib.parse

import pytest

import advprint

# ---- wire tags (RFC 8010 §3.5.2, verified against cups/ipp.h) ----
T_OP, T_JOB, T_END, T_PRINTER, T_UNSUPPORTED = 0x01, 0x02, 0x03, 0x04, 0x05
V_INT, V_BOOL, V_ENUM = 0x21, 0x22, 0x23
V_DATE, V_RANGE = 0x31, 0x33
V_TEXT, V_NAME, V_KEYWORD = 0x41, 0x42, 0x44
V_URI, V_CHARSET, V_LANG, V_MIME = 0x45, 0x47, 0x48, 0x49

# RFC 8011 §4.2.5.2 - every one of these MUST appear in a
# Get-Printer-Attributes response (what the MS IPP Class Driver
# validates before it lets Windows add the printer):
REQUIRED_PRINTER_ATTRS = (
    "printer-uri-supported", "uri-authentication-supported",
    "printer-state", "printer-state-reasons", "ipp-versions-supported",
    "operations-supported", "charset-configured",
    "natural-language-configured", "document-format-default",
    "document-format-supported", "pdl-override-supported",
    "printer-is-accepting-jobs", "queued-job-count", "printer-up-time",
    "printer-current-time", "printer-name", "printer-location",
    "printer-more-info", "printer-make-and-model", "printer-uuid",
    "copies-supported", "copies-default", "sides-supported",
    "sides-default", "print-color-mode-default",
    "print-color-mode-supported", "media-supported", "media-default",
    "compression-supported", "multiple-document-jobs-supported",
)

# the tag each printer attribute MUST carry (RFC 8011 syntax table)
EXPECT_TAG = {
    "printer-uri-supported": V_URI,
    "printer-more-info": V_URI,
    "printer-uuid": V_URI,
    "uri-authentication-supported": V_KEYWORD,
    "printer-state": V_ENUM,
    "printer-state-reasons": V_KEYWORD,
    "ipp-versions-supported": V_KEYWORD,
    "operations-supported": V_ENUM,
    "charset-configured": V_CHARSET,
    "natural-language-configured": V_LANG,
    "document-format-default": V_MIME,
    "document-format-supported": V_MIME,
    "pdl-override-supported": V_KEYWORD,
    "printer-is-accepting-jobs": V_BOOL,
    "queued-job-count": V_INT,
    "printer-up-time": V_INT,
    "printer-current-time": V_DATE,
    "printer-name": V_NAME,
    "printer-info": V_NAME,
    "printer-location": V_NAME,
    "printer-make-and-model": V_TEXT,
    "copies-supported": V_RANGE,
    "copies-default": V_INT,
    "sides-supported": V_KEYWORD,
    "sides-default": V_KEYWORD,
    "print-color-mode-default": V_KEYWORD,
    "print-color-mode-supported": V_KEYWORD,
    "media-supported": V_KEYWORD,
    "media-default": V_KEYWORD,
    "compression-supported": V_KEYWORD,
    "multiple-document-jobs-supported": V_BOOL,
    "job-id": V_INT,
    "job-state": V_ENUM,
    "job-state-reasons": V_KEYWORD,
    "job-name": V_NAME,
    "job-originating-user-name": V_NAME,
    "job-uri": V_URI,
}

MINI_PDF = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
            b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
            b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 100]>>endobj\n"
            b"xref\n0 4\n0000000000 65535 f \ntrailer<</Size 4/Root 1 0 R>>\n"
            b"startxref\n9\n%%EOF\n")


# ---------------------------------------------------------------
# request encoders - mimic real clients
# ---------------------------------------------------------------
def _attr(tag, name, value):
    nb = name.encode()
    if isinstance(value, str):
        value = value.encode()
    return bytes([tag]) + len(nb).to_bytes(2, "big") + nb + \
        len(value).to_bytes(2, "big") + value


def _add(tag, value):
    return _attr(tag, "", value)


def _req(op, doc=b"", ver=(1, 1), rid=7, extra=None, uri_path="/ipp/print",
         port=None):
    """An IPP request like Windows/CUPS builds it: charset + language +
    printer-uri (http:// - what Windows' IPP Device type sends)."""
    out = bytearray()
    out += bytes(ver) + op.to_bytes(2, "big") + rid.to_bytes(4, "big")
    out += bytes([T_OP])
    out += _attr(V_CHARSET, "attributes-charset", "utf-8")
    out += _attr(V_LANG, "attributes-natural-language", "en")
    if port is not None:
        out += _attr(V_URI, "printer-uri",
                     "http://127.0.0.1:%d%s" % (port, uri_path))
        out += _attr(V_NAME, "requesting-user-name", "pytest")
    for a in (extra or []):
        out += a
    out += bytes([T_END])
    return bytes(out) + doc


def _kw(name, *values):
    return _attr(V_KEYWORD, name, values[0]) + \
        b"".join(_add(V_KEYWORD, v) for v in values[1:])


def _int(name, n):
    return _attr(V_INT, name, struct.pack(">i", n))


# ---------------------------------------------------------------
# STRICT response linter
# ---------------------------------------------------------------
def _strict_parse(raw, expect_ver=(1, 1), expect_rid=7):
    """Walk an IPP response and assert RFC 8010 conformance. Returns
    (status, groups) where groups is [{name: [(tag, value), ...]}]."""
    assert len(raw) >= 8, "response shorter than the 8-byte header"
    ver = (raw[0], raw[1])
    status = int.from_bytes(raw[2:4], "big")
    rid = int.from_bytes(raw[4:8], "big")
    assert ver == expect_ver, "version %s != expected %s" % (ver,
                                                             expect_ver)
    assert rid == expect_rid, "request id %d echoed wrong" % rid
    i = 8
    groups = []
    cur = None
    group_tag = None
    names_seen = set()
    while i < len(raw):
        b = raw[i]
        if b == T_END:
            i += 1
            assert i == len(raw), "bytes after end-of-attributes tag"
            break
        assert b in (T_OP, T_JOB, T_PRINTER, T_UNSUPPORTED), \
            "bad delimiter tag 0x%02x at %d" % (b, i)
        assert b != group_tag or cur is None or cur, \
            "empty attribute group"
        group_tag = b
        cur = {}
        groups.append(cur)
        names_seen = set()
        i += 1
        continue_ok = False
        while i < len(raw):
            b2 = raw[i]
            if b2 in (T_OP, T_JOB, T_PRINTER, T_UNSUPPORTED, T_END):
                continue_ok = True
                break
            tag = b2
            nl = int.from_bytes(raw[i + 1:i + 3], "big")
            i += 3
            name = raw[i:i + nl].decode("utf-8", "replace")
            i += nl
            vl = int.from_bytes(raw[i:i + 2], "big")
            val = raw[i + 2:i + 2 + vl]
            i += 2 + vl
            if nl == 0:                       # additional value
                assert name == ""
                assert cur, "additional value outside a group"
                last = list(cur.items())[-1][0] if cur else None
                assert last is not None, "orphan additional value"
                assert cur[last][0][0] == tag, \
                    "additional value tag 0x%02x != primary 0x%02x for %s" \
                    % (tag, cur[last][0][0], last)
                cur[last].append((tag, val))
                continue
            assert name not in names_seen or name in \
                ("attributes-charset",), "duplicate attribute %s" % name
            names_seen.add(name)
            cur.setdefault(name, []).append((tag, val))
        if continue_ok:
            continue
    return status, groups


def _val(status_groups, group_idx, name):
    """First value of an attribute as (tag, bytes)."""
    groups = status_groups
    g = groups[group_idx]
    assert name in g, "attribute %s missing from group %d" % (name,
                                                              group_idx)
    tag, value = g[name][0]
    return tag, value


def _enum_ok(tag, value):
    assert tag == V_ENUM, "expected enum tag, got 0x%02x" % tag
    assert len(value) == 4, "enum value must be 4 bytes, got %d" % len(value)
    return struct.unpack(">i", value)[0]


def _int_ok(tag, value):
    assert tag == V_INT, "expected integer tag, got 0x%02x" % tag
    assert len(value) == 4
    return struct.unpack(">i", value)[0]


def _bool_ok(tag, value):
    assert tag == V_BOOL, "expected boolean tag, got 0x%02x" % tag
    assert len(value) == 1
    return value[0] != 0


def _range_ok(tag, value):
    assert tag == V_RANGE, "expected rangeOfInteger tag 0x33, got 0x%02x" \
        % tag
    assert len(value) == 8, "range must be 8 bytes"
    lo, hi = struct.unpack(">ii", value)
    return lo, hi


def _date_ok(tag, value):
    assert tag == V_DATE, "expected dateTime tag, got 0x%02x" % tag
    assert len(value) == 11, "dateTime must be 11 bytes"


def _ipp_post(hub, body, headers=None):
    return hub.req("POST", "/ipp/print", raw=body, token=None,
                   headers=headers or {"Content-Type": "application/ipp"})


# ---------------------------------------------------------------
# Get-Printer-Attributes - the operation Windows uses to ADD the
# printer. This is the exact scenario from the bug report.
# ---------------------------------------------------------------
def test_gpa_windows_style_full_conformance(hub):
    port = urllib.parse.urlparse(hub.base).port
    extra = [_kw("requested-attributes", "all")]
    code, raw = _ipp_post(hub, _req(0x000B, extra=extra, port=port))
    assert code == 200
    status, groups = _strict_parse(raw)
    assert status == 0x0000
    # operation group: charset + language with the right tags
    tag, val = _val(groups, 0, "attributes-charset")
    assert tag == V_CHARSET and val == b"utf-8"
    tag, val = _val(groups, 0, "attributes-natural-language")
    assert tag == V_LANG and val == b"en"
    # printer group with the FULL required set, correctly typed
    pg = 1
    names = set(groups[pg].keys())
    for req in REQUIRED_PRINTER_ATTRS:
        assert req in names, \
            "RFC 8011-required attribute missing: %s" % req
    # printer-uri-supported: http:// (Windows) AND ipp:// (macOS/iOS)
    tag, val = _val(groups, pg, "printer-uri-supported")
    assert tag == V_URI
    uris = [v for _t, v in groups[pg]["printer-uri-supported"]]
    assert ("http://127.0.0.1:%d/ipp/print" % port).encode() in uris, \
        "Windows-style http:// URI missing: %s" % uris
    assert ("ipp://127.0.0.1:%d/ipp/print" % port).encode() in uris
    # uri-authentication-supported: one entry per URI
    assert len(groups[pg]["uri-authentication-supported"]) == len(uris)
    assert all(v == b"none"
               for _t, v in groups[pg]["uri-authentication-supported"])
    # the types that WERE broken in 3.0.7
    st = _enum_ok(*_val(groups, pg, "printer-state"))
    assert st in (3, 4), "printer-state enum value %d" % st
    assert _bool_ok(*_val(groups, pg, "printer-is-accepting-jobs")) is True
    assert _int_ok(*_val(groups, pg, "queued-job-count")) >= 0
    lo, hi = _range_ok(*_val(groups, pg, "copies-supported"))
    assert lo == 1 and hi >= 1
    ops = [_enum_ok(t, v) for t, v in
           groups[pg]["operations-supported"]]
    assert 0x0002 in ops and 0x0005 in ops and 0x0006 in ops \
        and 0x000B in ops, "operations-supported incomplete: %s" % ops
    _date_ok(*_val(groups, pg, "printer-current-time"))
    assert _int_ok(*_val(groups, pg, "printer-up-time")) >= 0
    tag, val = _val(groups, pg, "document-format-default")
    assert tag == V_MIME and val == b"application/pdf"
    fmts = [v for _t, v in groups[pg]["document-format-supported"]]
    assert b"application/pdf" in fmts
    vers = [v for _t, v in groups[pg]["ipp-versions-supported"]]
    assert b"1.1" in vers and b"2.0" in vers
    # every value tag matches the attribute syntax table
    for name, entries in groups[pg].items():
        want = EXPECT_TAG.get(name)
        if want:
            assert all(t == want for t, _v in entries), \
                "%s carries tag 0x%02x, expected 0x%02x" % \
                (name, entries[0][0], want)


def test_gpa_ipp_2_0_macos_style(hub):
    """macOS CUPS speaks IPP 2.0 - the response must echo 2.0."""
    port = urllib.parse.urlparse(hub.base).port
    code, raw = _ipp_post(hub, _req(0x000B, ver=(2, 0), port=port))
    assert code == 200
    status, groups = _strict_parse(raw, expect_ver=(2, 0))
    assert status == 0x0000


def test_gpa_answers_uri_windows_typed(hub):
    """Windows 'Add a printer -> IPP Device' queries with the http://
    printer-uri - the printer must still answer successful-ok."""
    port = urllib.parse.urlparse(hub.base).port
    code, raw = _ipp_post(hub, _req(0x000B, port=port))
    assert code == 200
    status, groups = _strict_parse(raw)
    assert status == 0x0000


# ---------------------------------------------------------------
# Print-Job / Validate-Job / Print-URI
# ---------------------------------------------------------------
def test_print_job_pdf_strict_job_group(clean_queue):
    hub = clean_queue
    extra = [_attr(V_MIME, "document-format", "application/pdf")]
    code, raw = _ipp_post(hub, _req(0x0002, doc=MINI_PDF, extra=extra,
                                    port=_port(hub)))
    assert code == 200
    status, groups = _strict_parse(raw)
    assert status == 0x0000
    assert len(groups) >= 2, "Print-Job response needs a job group"
    jg = 1
    jid = _int_ok(*_val(groups, jg, "job-id"))
    assert jid >= 1
    assert _enum_ok(*_val(groups, jg, "job-state")) == 3      # pending
    tag, _v = _val(groups, jg, "job-uri")
    assert tag == V_URI
    assert "job-name" in groups[jg]
    rows = [j for j in advprint.db_list(limit=5) if j["source"] == "ipp"]
    assert rows and rows[0]["id"] == jid


def test_print_job_unsupported_format(hub):
    extra = [_attr(V_MIME, "document-format", "image/tiff")]
    code, raw = _ipp_post(hub, _req(0x0002, doc=b"II*\x00", extra=extra,
                                    port=_port(hub)))
    assert code == 200
    status, groups = _strict_parse(raw)
    assert status == 0x040B, "image/tiff must be document-format-not-"


def test_validate_job_says_ok(hub):
    extra = [_attr(V_MIME, "document-format", "application/pdf")]
    code, raw = _ipp_post(hub, _req(0x0004, extra=extra, port=_port(hub)))
    assert code == 200
    status, groups = _strict_parse(raw)
    assert status == 0x0000
    assert not any("job-id" in g for g in groups), \
        "Validate-Job must not create a job"


def test_print_uri_rejects_file_scheme(hub):
    extra = [_attr(V_URI, "document-uri", "file:///etc/passwd")]
    code, raw = _ipp_post(hub, _req(0x0003, extra=extra, port=_port(hub)))
    assert code == 200
    status, groups = _strict_parse(raw)
    assert status == 0x0400, "file:// document-uri must be refused"


# ---------------------------------------------------------------
# Create-Job + Send-Document - how macOS CUPS, iOS PrintKit and
# Android Mopria submit jobs. Missing in 3.0.7 = phones could not
# print at all.
# ---------------------------------------------------------------
def test_create_job_send_document_session(clean_queue):
    hub = clean_queue
    port = _port(hub)
    code, raw = _ipp_post(hub, _req(0x0005, extra=[_attr(
        V_NAME, "job-name", "lab report")], port=port))
    assert code == 200
    status, groups = _strict_parse(raw)
    assert status == 0x0000
    sid = _int_ok(*_val(groups, 1, "job-id"))
    assert sid >= 1000000, "session ids must not collide with db ids"
    assert _enum_ok(*_val(groups, 1, "job-state")) == 3

    # document 1 of 2
    extra = [_int("job-id", sid),
             _attr(V_BOOL, "last-document", b"\x00"),
             _attr(V_MIME, "document-format", "application/pdf")]
    code, raw = _ipp_post(hub, _req(0x0006, doc=MINI_PDF[:20],
                                    extra=extra, port=port))
    status, groups = _strict_parse(raw)
    assert status == 0x0000
    # document 2 of 2 (last)
    extra = [_int("job-id", sid),
             _attr(V_BOOL, "last-document", b"\x01"),
             _attr(V_MIME, "document-format", "application/pdf")]
    code, raw = _ipp_post(hub, _req(0x0006, doc=MINI_PDF[20:],
                                    extra=extra, port=port))
    assert code == 200
    status, groups = _strict_parse(raw)
    assert status == 0x0000
    jid = _int_ok(*_val(groups, 1, "job-id"))
    row = advprint.db_get(jid)
    assert row and row["source"] == "ipp"
    assert row["title"] == "lab report"


def test_send_document_unknown_session(hub):
    extra = [_int("job-id", 4242424),
             _attr(V_BOOL, "last-document", b"\x01")]
    code, raw = _ipp_post(hub, _req(0x0006, doc=MINI_PDF, extra=extra,
                                    port=_port(hub)))
    assert code == 200
    status, groups = _strict_parse(raw)
    assert status == 0x0406, "unknown job-id must be client-error-not-found"


def test_get_job_attributes_and_get_jobs(clean_queue):
    hub = clean_queue
    code, raw = _ipp_post(hub, _req(0x0002, doc=MINI_PDF,
                                    extra=[_attr(V_MIME, "document-format",
                                                 "application/pdf")],
                                    port=_port(hub)))
    status, groups = _strict_parse(raw)
    jid = _int_ok(*_val(groups, 1, "job-id"))
    # Get-Job-Attributes
    code, raw = _ipp_post(hub, _req(0x0009, extra=[_int("job-id", jid)],
                                    port=_port(hub)))
    assert code == 200
    status, groups = _strict_parse(raw)
    assert status == 0x0000
    assert _int_ok(*_val(groups, 1, "job-id")) == jid
    assert _enum_ok(*_val(groups, 1, "job-state")) in (3, 4, 8)
    # Get-Jobs (completed - the stub prints instantly)
    deadline = time.time() + 6
    found = False
    while time.time() < deadline and not found:
        code, raw = _ipp_post(hub, _req(0x000A, extra=[
            _kw("which-jobs", "completed")], port=_port(hub)))
        assert code == 200
        status, groups = _strict_parse(raw)
        for g in groups[1:] if len(groups) > 1 else []:
            if "job-id" in g and _int_ok(*g["job-id"][0]) == jid:
                st = _enum_ok(*g["job-state"][0])
                assert st == 8, "completed job must map to job-state 8"
                found = True
        if not found:
            time.sleep(0.2)
    assert found, "Get-Jobs (completed) never listed the printed job"


def test_cancel_job_queued(clean_queue):
    hub = clean_queue
    advprint.RESUME_EVENT.clear()            # hold the queue
    try:
        code, raw = _ipp_post(hub, _req(0x0002, doc=MINI_PDF,
                                        extra=[_attr(V_MIME,
                                                     "document-format",
                                                     "application/pdf")],
                                        port=_port(hub)))
        status, groups = _strict_parse(raw)
        jid = _int_ok(*_val(groups, 1, "job-id"))
        code, raw = _ipp_post(hub, _req(0x0008, extra=[_int("job-id", jid)],
                                        port=_port(hub)))
        assert code == 200
        status, groups = _strict_parse(raw)
        assert status == 0x0000
        assert _enum_ok(*_val(groups, 1, "job-state")) == 6   # canceled
        assert advprint.db_get(jid)["status"] == "canceled"
    finally:
        advprint.RESUME_EVENT.set()


def test_get_job_attributes_unknown(hub):
    code, raw = _ipp_post(hub, _req(0x0009, extra=[_int("job-id", 9999999)],
                                    port=_port(hub)))
    assert code == 200
    status, groups = _strict_parse(raw)
    assert status == 0x0406


# ---------------------------------------------------------------
# HTTP-level: chunked upload (phone stacks), unknown op, garbage
# ---------------------------------------------------------------
def test_chunked_transfer_print_job(clean_queue):
    hub = clean_queue
    port = urllib.parse.urlparse(hub.base).port
    body = _req(0x0002, doc=MINI_PDF, extra=[_attr(V_MIME,
                                                   "document-format",
                                                   "application/pdf")],
                port=port)
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.putrequest("POST", "/ipp/print")
    conn.putheader("Content-Type", "application/ipp")
    conn.putheader("Transfer-Encoding", "chunked")
    conn.endheaders()
    for i in range(0, len(body), 64):
        chunk = body[i:i + 64]
        conn.send(b"%x\r\n" % len(chunk) + chunk + b"\r\n")
    conn.send(b"0\r\n\r\n")
    resp = conn.getresponse()
    assert resp.status == 200
    assert resp.getheader("Content-Type") == "application/ipp"
    status, groups = _strict_parse(resp.read())
    assert status == 0x0000
    conn.close()


def test_unknown_operation(hub):
    code, raw = _ipp_post(hub, _req(0x0033, port=_port(hub)))
    assert code == 200
    status, groups = _strict_parse(raw)
    assert status == 0x040F, "unknown op must be operation-not-supported"


def test_garbage_request(hub):
    code, raw = _ipp_post(hub, b"\x01\x01\x00\x02")
    assert code == 200
    status, groups = _strict_parse(raw, expect_rid=int.from_bytes(
        raw[4:8], "big"))
    assert status == 0x0400


def test_ipp_info_page(hub):
    code, body = hub.get("/ipp/print", token=None)
    assert code == 200
    html = body.decode("utf-8", "replace") if isinstance(body, bytes) \
        else str(body)
    assert "IPP Device" in html
    assert "AdvPrint Pro" in html


def _port(hub):
    return urllib.parse.urlparse(hub.base).port
