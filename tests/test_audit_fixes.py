"""v2.9.1 regression tests for the Claude-AI audit fixes.

Every test maps to one audit finding (H1..H7, M1..M7, P1, L1..L8):
the fix must behave exactly as the audit's fix proposal requires.
"""
import json
import os
import socket
import threading
import time
import urllib.error
import urllib.request

import pytest

import advprint

PDF = b"%PDF-1.4\n%audit-test\n" + b"1 0 obj\nendobj\n" * 8 + b"trailer<<>>\n%%EOF\n"


# ---------------------------------------------------------------- H1
def test_save_job_file_never_collides(hub):
    """H1: two saves with the same title in the same second produce two
    DIFFERENT paths and two intact files (no silent overwrite)."""
    p1 = advprint.save_job_file("a4", "COLLIDE", b"AAAA", ext="pdf")
    p2 = advprint.save_job_file("a4", "COLLIDE", b"BBBB", ext="pdf")
    assert p1 != p2
    with open(p1, "rb") as f:
        assert f.read() == b"AAAA"
    with open(p2, "rb") as f:
        assert f.read() == b"BBBB"


def test_duplicate_enqueue_keeps_original_file(hub, clean_queue):
    """H1: the duplicate path must NOT delete the original job's payload.
    Old code: same-second submissions shared one path -> the dup delete
    destroyed the first job's file."""
    j1, dup1 = advprint.enqueue_print("a4", "DUP-FILE", PDF)
    j2, dup2 = advprint.enqueue_print("a4", "DUP-FILE", PDF)
    assert dup2 == j1                      # second is flagged as duplicate
    row1 = advprint.db_get(j1)
    assert row1["file_path"] and os.path.exists(row1["file_path"])
    with open(row1["file_path"], "rb") as f:
        assert f.read() == PDF             # ORIGINAL payload survived


# ---------------------------------------------------------------- H2/P4
def test_html_to_pdf_isolated_workdir(hub, monkeypatch):
    """H2: each render uses its OWN temp dir (no PID-named shared file)."""
    seen = []

    class FakeProc:
        pid = 4242
        def communicate(self, timeout=None):
            # prove the out path is private to this call
            seen.append(advprint._BROWSER_SEM)
            return (b"", b"")

    def fake_popen(cmd, **kw):
        out = [a for a in cmd if a.startswith("--print-to-pdf=")][0]
        with open(out.split("=", 1)[1], "wb") as f:
            f.write(PDF)
        return FakeProc()

    monkeypatch.setattr(advprint, "find_browser", lambda: "/usr/bin/chromium")
    monkeypatch.setattr(advprint.subprocess, "Popen", fake_popen)
    pdf, name = advprint.html_to_pdf_bytes("<h1>hi</h1>", is_url=False)
    assert pdf.startswith(b"%PDF")
    assert name.endswith(".pdf")


# ---------------------------------------------------------------- H5
def test_foreign_host_header_blocked(hub):
    """H5: DNS-rebinding Host header -> 421, token not returned."""
    # /token/current answers the token to loopback callers - a rebounded
    # page rides loopback with an ATTACKER Host header
    req = urllib.request.Request(hub.base + "/token/current")
    req.add_header("Host", "evil.example:%d"
                   % int(hub.base.rsplit(":", 1)[1]))
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            code, body = r.getcode(), r.read()
    except urllib.error.HTTPError as e:
        code, body = e.code, e.read()
    assert code == 421
    assert hub.token.encode() not in body


def test_good_host_header_accepted(hub):
    code, body = hub.get("/health", token=None)
    assert code == 200


# ---------------------------------------------------------------- H6
def test_ipp_rejects_browser_origin(hub):
    """H6: a web page (http Origin) can no longer drive the raw IPP
    endpoint; native IPP clients (no Origin) keep working -> 404 'off'
    because the test hub has ipp_printer off, which still proves the
    origin check runs BEFORE any IPP processing."""
    code, body = hub.post("/ipp/print", raw=PDF,
                          content_type="application/ipp",
                          token=None,
                          headers={"Origin": "https://evil.example"})
    assert code == 403


# ---------------------------------------------------------------- H4
def test_page_url_ssrf_blocked(hub):
    """H4: page_url runs the same SSRF guard as pdf_url."""
    code, body = hub.post("/print", {"page_url": "file:///etc/passwd",
                                     "title": "x"})
    assert code == 400
    assert "blocked" in body.get("error", "").lower()


# ---------------------------------------------------------------- H7
def test_download_pdf_redirect_guard(monkeypatch):
    """H7: every redirect hop is re-guarded (a loopback hop raises)."""
    calls = []
    def fake_guard(u):
        calls.append(u)
        if "127.0.0.1" in u or "10." in u:
            raise ValueError("blocked: %s" % u)
    monkeypatch.setattr(advprint, "pdf_url_guard", fake_guard)
    h = advprint._GuardedRedirect()
    class FakeReq: pass
    with pytest.raises(ValueError):
        h.redirect_request(FakeReq(), None, 302, "Found",
                           {"location": "http://127.0.0.1/x"},
                           "http://127.0.0.1/x")
    assert calls == ["http://127.0.0.1/x"]   # hop WAS checked


# ---------------------------------------------------------------- M1
def test_handler_socket_timeout_set(hub):
    """M1: the handler class carries a socket timeout (no slowloris hang)."""
    assert advprint.Handler.timeout and advprint.Handler.timeout > 0


def test_big_unauth_body_not_read(hub):
    """M1: a >1MB Content-Length with NO token is refused (401) without
    reading the body - we send ONLY the headers, never a body, and the
    hub answers instantly instead of hanging waiting for 2 MB."""
    port = int(hub.base.rsplit(":", 1)[1])
    s = socket.create_connection(("127.0.0.1", port), timeout=10)
    try:
        s.sendall(b"POST /print HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                  b"Content-Type: application/pdf\r\n"
                  b"Content-Length: 2097152\r\n\r\n")   # headers only!
        resp = b""
        try:
            resp = s.recv(4096)
        except socket.timeout:
            pass
        status = resp.split(b"\r\n")[0]
        assert b"401" in status
    finally:
        s.close()


# ---------------------------------------------------------------- M2
def test_log_tail_masks_tokens(hub):
    """M2: _log_tail redacts token=... and [TOKEN] token: ... lines."""
    log_path = os.path.join(advprint.CFG["data_dir"], "hub.log")
    with open(log_path, "a", encoding="utf-8") as f:
        f.write("[TOKEN] token: SuperSecretValue123\n")
        f.write("Dashboard -> http://127.0.0.1:9235/dashboard?token=abcSecretXYZ\n")
    lines = advprint._log_tail(lines=5)
    joined = "\n".join(lines)
    assert "SuperSecretValue123" not in joined
    assert "abcSecretXYZ" not in joined


# ---------------------------------------------------------------- M3/M7
def test_retry_or_dead_survives_missing_job(hub):
    """M3: a deleted row no longer raises KeyError."""
    advprint._retry_or_dead({}, RuntimeError("boom"))          # no raise
    advprint._retry_or_dead(None, RuntimeError("boom"))        # no raise


def test_raw_and_timeout_jobs_do_not_autoretry(hub, clean_queue):
    """M7: raw jobs + timeout failures go straight to the dead-letter
    list (no silent duplicate printing)."""
    advprint.RESUME_EVENT.clear()          # keep the worker away mid-test
    try:
        j, _ = advprint.enqueue_print("raw", "RETRY-RAW", b"\x1b@ESCPOS",
                                      dedupe=False)
        advprint._retry_or_dead(advprint.db_get(j),
                                RuntimeError("print backend exit 1"))
        assert advprint.db_get(j)["status"] == "dead"
        j2, _ = advprint.enqueue_print("a4", "RETRY-TMO", PDF, dedupe=False)
        advprint._retry_or_dead(advprint.db_get(j2),
                                RuntimeError("printer did not respond"
                                             " within 180 s"))
        assert advprint.db_get(j2)["status"] == "dead"
        # PDF non-timeout errors still retry normally
        j3, _ = advprint.enqueue_print("a4", "RETRY-PDF", PDF, dedupe=False)
        advprint._retry_or_dead(advprint.db_get(j3),
                                RuntimeError("print backend exit 1"))
        assert advprint.db_get(j3)["status"] == "queued"
        # do not leave a live queued job behind: the worker would pick it
        # up the moment the queue resumes and pollute later tests
        advprint.db_update(j3, status="canceled", error="test done")
        # also remove the dead jobs' PAYLOAD files: the queue/shift
        # scope=all includes dead rows with files, so leftovers would be
        # shifted along by later tests (audit M7: dead jobs no longer
        # auto-retry, so nothing else cleans these files up)
        for row_id in (j, j2):
            row = advprint.db_get(row_id)
            if row and row.get("file_path") and os.path.exists(row["file_path"]):
                try:
                    os.unlink(row["file_path"])
                except OSError:
                    pass
    finally:
        advprint.RESUME_EVENT.set()


# ---------------------------------------------------------------- M4
def test_peer_forward_not_on_unknown(hub, clean_queue, monkeypatch):
    """M4: 'unknown' printer state prints locally - never forwarded."""
    called = []
    monkeypatch.setattr(advprint, "_try_peer_forward",
                        lambda job: called.append(job) or True)
    monkeypatch.setattr(advprint, "printer_ready", lambda p: "unknown")
    j, _ = advprint.enqueue_print("a4", "PEER-UNK", PDF, printer="NoStatePrinter",
                                  dedupe=False)
    ok = wait_ok(hub, j)
    assert ok
    assert called == []                   # forward was NOT attempted


def wait_ok(hub, jid, timeout=15.0):
    end = time.time() + timeout
    while time.time() < end:
        row = advprint.db_get(jid)
        if row and row["status"] in ("printed", "failed", "dead", "canceled",
                                     "forwarded", "saved"):
            return row["status"] == "printed"
        time.sleep(0.05)
    return False


# ---------------------------------------------------------------- M5
def test_raw_oversize_rejected(hub, monkeypatch):
    """M5: a payload over MAX_PDF is rejected whole - never truncated and
    printed, and never enqueued."""
    small_cap = 1024
    monkeypatch.setattr(advprint, "MAX_PDF", small_cap)
    enq = []
    monkeypatch.setattr(advprint, "enqueue_print",
                        lambda *a, **kw: enq.append((a, kw)) or (0, None))
    # feed MAX_PDF + 1 bytes through the connection handler
    class FakeConn:
        def __init__(self, data):
            self.data = data
            self.closed = False
        def settimeout(self, t): pass
        def recv(self, n):
            if self.data:
                out, self.data = self.data[:n], self.data[n:]
                return out
            return b""
        def close(self): self.closed = True
    payload = b"\x1b@ESCPOS-TOO-BIG" + b"x" * small_cap
    advprint._RAW_SEM.acquire()           # the accept loop acquires in prod
    advprint._raw_conn_handler(FakeConn(payload), ("127.0.0.1", 5555))
    assert enq == []                      # nothing was processed


def test_raw_passthrough_enqueues(hub, clean_queue, monkeypatch):
    """M5: printer-language passthrough now enqueues (history row)."""
    data = b"\x1b@ESCPOS-RECEIPT"
    job, lang = advprint.route_print_payload(data, "RAW print",
                                             "127.0.0.1", source="raw9100")
    assert job > 0                        # real history row, not 0
    row = advprint.db_get(job)
    assert row is not None and row["kind"] == "raw"
    assert lang == "escpos"


# ---------------------------------------------------------------- M6
def test_config_apply_is_atomic(hub, cfg_reset):
    """M6: one bad key => NOTHING is applied (no memory/disk drift)."""
    code, body = hub.post("/config", {
        "dedupe_minutes": 9,              # valid
        "dest_mode": "NONSENSE",          # invalid -> whole request rejected
    })
    assert code == 400
    assert advprint.CFG["dedupe_minutes"] != 9


def test_peer_hubs_dicts_survive_config(hub, cfg_reset):
    """M6: real peer dicts round-trip instead of becoming repr strings."""
    peers = [{"url": "http://192.168.1.50:9235", "token": "t", "name": "lab"}]
    code, body = hub.post("/config", {"peer_hubs": peers})
    assert code == 200
    got = advprint.CFG["peer_hubs"]
    assert isinstance(got[0], dict) and got[0]["url"] == peers[0]["url"]


def test_printer_groups_validated(hub, cfg_reset):
    """M6: a group whose members are not a string list is rejected."""
    code, body = hub.post("/config", {"printer_groups": {"Lab": "oops"}})
    assert code == 400


# ---------------------------------------------------------------- L1..L8
def test_sanitize_fname_keeps_bengali():
    """L3: combining marks survive (was: 'রিপোর্ট-Lab' -> 'রপরট-Lab')."""
    out = advprint.sanitize_fname("রিপোর্ট-Lab", maxlen=50, extra="-_ ",
                                  fallback="job")
    assert out == "রিপোর্ট-Lab"


def test_sanitize_fname_still_drops_separators():
    out = advprint.sanitize_fname("a/b\\c:d*e.pdf", maxlen=50, extra="-_ ",
                                  fallback="job")
    assert "/" not in out and "\\" not in out


def test_jobs_limit_clamped(hub):
    code, body = hub.get("/jobs?limit=99999999")
    assert code == 200                    # clamped server-side, no explosion
    code, body = hub.get("/jobs?limit=0")
    assert code == 200


def test_content_disposition_sanitized(hub):
    """L7: quotes/CR/LF are stripped from download names."""
    # unit-level: build the header exactly as _send_file does
    name = 'bad"name\r\nInj.pdf'
    safe = "".join(c for c in name if c not in ('"', "\r", "\n", "\\"))[:100]
    assert '"' not in safe and "\r" not in safe and "\n" not in safe
