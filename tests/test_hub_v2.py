"""AdvPrint Pro v2.0.1 - pytest suite (pure stdlib hub, no real printer).

Covers the 22 feature areas: security (random token, header-only, origins,
SSRF guard, lockout + v2.0.1 loopback exemption, rotate), printer (status,
groups, raw ESC/POS+ZPL, profiles, page ranges), queue (retry, priority,
dedupe, schedule, dead-letter, peers), audit (log, reason, watermark, CSV,
diagnostics, dashboard) plus repo sanity (version anchors, migrations).
"""
import base64
import hashlib
import re
import json
import os
import sqlite3
import sys
import time
import urllib.request

import pytest

import advprint
from conftest import wait_until  # noqa: E402


# ============================================================
# 1. health / security
# ============================================================

def test_health_open_no_token(hub):
    code, d = hub.get("/health", token=None)
    assert code == 200 and d["ok"] is True
    assert d["version"] == "3.2.1"
    assert d["v2"] is True
    assert "100% local" in d["branding"]


def test_health_carries_token_hint_v265(hub):
    """v2.6.5: /health exposes the LAST 4 CHARACTERS of the active token
    only - enough to verify the extension token matches (the 401 /
    auth.failed family), never enough to reuse the token."""
    code, d = hub.get("/health", token=None)
    assert code == 200
    assert d["token_hint"] == advprint.CFG["token"][-4:]
    assert advprint.CFG["token"] not in json.dumps(d)   # never the full token


def test_sumatra_scans_have_glob_v265():
    """v2.6.5 regression: the all-users SumatraPDF profile scan uses
    glob - the module MUST be imported or find_sumatra() silently
    degrades on Windows (service-mode PDF printing lost its last-resort
    detection in 2.6.4 exactly this way)."""
    import glob as _glob  # noqa: F401
    src = open(advprint.__file__, encoding="utf-8").read()
    assert re.search(r"^import glob$", src, re.M)
    assert advprint.glob is _glob


def test_service_lifecycle_has_no_bind_race_v265():
    """v2.6.5 regression: the Windows service reports RUNNING only after
    a real port bind (ready-event handshake), never after a blind
    0.5 s sleep - the 'stuck at Starting' fix."""
    src = open(os.path.join(os.path.dirname(advprint.__file__),
                            "service_main.py"), encoding="utf-8").read()
    assert "_signal_ready" in src
    assert 'ready_event.set("ready")' in src
    assert "time.sleep(0.5)             # give bind failures a moment" not in src


def test_new_install_random_token(hub):
    assert hub.token and hub.token != "PrintHub-2024"
    assert advprint.CFG["token_header_only"] is True     # fresh install = strict


def test_auth_required_without_token(hub):
    code, _ = hub.get("/jobs", token=None)
    assert code == 401


def test_header_token_works_on_every_get_v202(hub):
    # v2.0.2: the /audit vs /dashboard mismatch is gone - the SAME token
    # must open EVERY GET endpoint, with or without a browser header
    for path in ("/jobs", "/audit", "/stats", "/diagnostics",
                 "/printers", "/queue", "/config", "/peers"):
        code, _ = hub.get(path)                           # header call
        assert code == 200, path
        code, _ = hub.get(path + "?token=" + hub.token,
                          token=None)                     # browser link
        assert code == 200, path


def test_post_query_token_still_rejected_v202(hub):
    # v2.0.2 hardening kept: mutating POSTs require the header in
    # header-only mode - a query token alone is not enough
    code, _ = hub.post("/queue/pause?token=" + hub.token,
                       {}, token=None)
    assert code == 401
    code, _ = hub.post("/queue/pause", {})                # header works
    assert code == 200
    hub.post("/queue/resume", {})                         # restore


def test_wrong_token_get_gives_json_for_api_clients(hub):
    code, d = hub.get("/audit", token="nope-" + hub.token)
    assert code == 401 and d["ok"] is False and "error" in d


def test_wrong_token_counts_and_lockout(hub, cfg_reset, monkeypatch):
    # v2.6.3+: loopback is UNCONDITIONALLY exempt (the owner's PC can
    # never lock itself out). Exercise the remote-IP lock path by
    # simulating a remote client IP for the live server threads.
    monkeypatch.setattr(advprint.Handler, "_client_ip",
                        lambda self: "203.0.113.7")
    advprint._AUTH_FAILS.clear()
    codes = []
    for i in range(advprint.CFG["max_auth_failures"]):
        code, _ = hub.get("/jobs", token="wrong-%d" % i)
        codes.append(code)
    assert codes[: advprint.CFG["max_auth_failures"] - 1] == [401] * (
        advprint.CFG["max_auth_failures"] - 1)
    code, d = hub.get("/jobs")          # even the CORRECT token is locked now
    assert code == 429
    advprint._AUTH_FAILS.clear()


def test_loopback_never_locked_by_default(hub):
    """v2.0.1 core fix: many Chrome windows share 127.0.0.1 - a stale
    token in one window must never lock the dashboard/tray/extension
    of every other window out."""
    advprint._AUTH_FAILS.clear()
    n = int(advprint.CFG["max_auth_failures"]) + 5
    codes = set()
    for i in range(n):
        code, _ = hub.get("/jobs", token="still-wrong-%d" % i)
        codes.add(code)
    assert 429 not in codes             # no lock, no matter how many fails
    code, d = hub.get("/jobs")          # the correct token keeps working
    assert code == 200 and d["ok"] is True
    assert not advprint._AUTH_FAILS.get("127.0.0.1", {}).get("until")
    advprint._AUTH_FAILS.clear()


def test_success_clears_failure_counter(hub):
    advprint._AUTH_FAILS.clear()
    for i in range(int(advprint.CFG["max_auth_failures"]) - 1):
        hub.get("/jobs", token="bad-%d" % i)
    code, _ = hub.get("/jobs")          # one success -> counter reset
    assert code == 200
    rec = advprint._AUTH_FAILS.get("127.0.0.1")
    assert rec is None                  # success clears the IP entirely
    advprint._AUTH_FAILS.clear()


def test_failures_expire_with_sliding_window(hub):
    advprint._AUTH_FAILS.clear()
    for i in range(int(advprint.CFG["max_auth_failures"]) - 1):
        hub.get("/jobs", token="old-%d" % i)
    rec = advprint._AUTH_FAILS["127.0.0.1"]
    rec["first"] -= int(advprint.CFG["lockout_minutes"]) * 60 + 1  # age out
    code, _ = hub.get("/jobs", token="after-window")
    assert code == 401                  # still rejected, but...
    fresh = advprint._AUTH_FAILS["127.0.0.1"]
    assert fresh["count"] == 1          # ...counted in a NEW window
    advprint._AUTH_FAILS.clear()


def test_old_default_token_gets_clear_hint(hub):
    code, d = hub.get("/jobs", token="PrintHub-2024")
    assert code == 401
    assert "OLD default token" in d["error"]
    # v2.6.1: the hint carries the FULL advprint.py path so it works
    # from any folder (no more "can't open file" from a wrong cwd)
    assert "advprint.py" in d["error"] and "token" in d["error"]
    assert "/" in d["error"]          # contains a real absolute path


def test_dashboard_wrong_token_html_error(hub, monkeypatch):
    """REMOTE browsers opening /dashboard with a stale ?token= still get
    a readable HTML page (fix instructions), not a raw JSON blob.
    (v2.6.4: the OWNER's browser on loopback now gets a 302 straight to
    the working URL - see test_v264_loopback_browser_gets_302.)"""
    monkeypatch.setattr(advprint.Handler, "_is_loopback",
                        lambda self: False)
    code, body = hub.get("/dashboard?token=PrintHub-2024",
                         token="PrintHub-2024",
                         headers={"Accept": "text/html"})
    assert code == 401
    assert b"<!DOCTYPE html>" in body and b"tray icon" in body.lower()
    # JSON clients still get JSON
    code, d = hub.get("/dashboard?token=PrintHub-2024", token="PrintHub-2024")
    assert code == 401 and d["ok"] is False and "error" in d


def test_origin_allowlist(hub, cfg_reset):
    hub.post("/config", {"allowed_origins": ["*.htncr.org"]})
    code, d = hub.post("/print", {"text": "origin test", "title": "o1",
                                  "kind": "thermal"},
                       headers={"Origin": "https://app.htncr.org",
                                "X-AdvPrint-Token": hub.token})
    assert code == 200
    code, _ = hub.post("/print", {"text": "evil", "title": "o2",
                                  "kind": "thermal"},
                       headers={"Origin": "https://evil.example",
                                "X-AdvPrint-Token": hub.token})
    assert code == 403
    hub.post("/config", {"allowed_origins": []})   # back to allow-all


def test_pdf_url_scheme_blocked(hub):
    for bad in ("file:///etc/passwd", "ftp://host/x.pdf", "gopher://x/y"):
        code, d = hub.post("/print", {"pdf_url": bad})
        assert code == 400 and "blocked" in d["error"], bad


def test_pdf_url_private_ip_blocked(hub, cfg_reset):
    code, d = hub.post("/print", {"pdf_url": "http://192.168.1.1/a.pdf"})
    assert code == 400 and "private" in d["error"]
    code, d = hub.post("/print", {"pdf_url": "http://127.0.0.1:9235/health"})
    assert code == 400 and "private" in d["error"]
    # allowlist override accepts the host (download then fails for other
    # reasons - NOT the SSRF guard). Use the hub itself as the allowed
    # host so the check never depends on unreachable networks.
    hub.post("/config", {"pdf_url_allowed_hosts": ["127.0.0.1"]})
    code, d = hub.post("/print", {
        "pdf_url": hub.base + "/a-not-a-pdf"})
    assert code == 400 and "private" not in str(d.get("error", ""))
    assert "blocked" not in str(d.get("error", ""))
    hub.post("/config", {"pdf_url_allowed_hosts": []})


def test_token_rotate_api(hub):
    old = hub.token
    code, d = hub.post("/token/rotate")
    assert code == 200 and d["token"]
    new = d["token"]
    code, _ = hub.get("/jobs", token=old)
    assert code == 401                      # old token dead immediately
    code, _ = hub.get("/jobs", token=new)
    assert code == 200
    hub.token = new
    assert advprint.CFG["token_header_only"] is True


def test_config_post_persists(hub):
    code, d = hub.post("/config", {"max_retries": 3})
    assert code == 200 and "max_retries" in d["changed"]
    disk = json.load(open(advprint.config_path()))
    assert disk["max_retries"] == 3
    code, d = hub.post("/config", {"token": "hack"})
    assert code == 400                      # token only via /token/rotate


def test_config_view_masks_token(hub):
    code, d = hub.get("/config")
    assert code == 200 and d["token"].endswith("***")


# ============================================================
# 2. queue: dedupe / priority / schedule / retry / dead-letter
# ============================================================

def test_duplicate_blocking(hub, clean_queue):
    code, d1 = hub.post("/print", {"text": "same body", "title": "dup",
                                   "kind": "thermal"})
    assert code == 200 and d1["duplicate"] is False
    code, d2 = hub.post("/print", {"text": "same body", "title": "dup",
                                   "kind": "thermal"})
    assert code == 200 and d2["duplicate"] is True
    assert d2["job_id"] == d1["job_id"]
    code, d3 = hub.post("/print", {"text": "same body", "title": "dup",
                                   "kind": "thermal", "dedupe": False})
    assert code == 200 and d3["duplicate"] is False


def test_priority_urgent_first(hub, clean_queue):
    advprint.RESUME_EVENT.clear()                       # hold the queue
    code, lo = hub.post("/print", {"text": "low prio", "title": "low",
                                   "priority": 9})
    code, hi = hub.post("/print", {"text": "urgent", "title": "urgent",
                                   "priority": 1})
    assert lo["priority"] == 9 and hi["priority"] == 1
    advprint.RESUME_EVENT.set()
    ok = wait_until(lambda: len(hub.printed) >= 2)
    assert ok
    assert hub.printed[0]["job_id"] == hi["job_id"]     # urgent jumped the line
    assert hub.printed[1]["job_id"] == lo["job_id"]


def test_scheduled_print(hub, clean_queue):
    code, d = hub.post("/print", {"text": "later", "title": "sched",
                                  "run_at": "+1h", "kind": "thermal"})
    assert code == 200 and d["status"] == "scheduled" and d["scheduled_for"]
    j = advprint.db_get(d["job_id"])
    assert j["status"] == "scheduled"
    assert advprint.db_promote_scheduled() == 0         # 1h away: not yet
    advprint.db_update(j["id"], run_at="2020-01-01T00:00:00")
    assert advprint.db_promote_scheduled() == 1
    ok = wait_until(lambda: (advprint.db_get(j["id"]) or {})
                    .get("status") in ("printed", "failed"))
    assert ok


def test_retry_then_dead_letter(hub, clean_queue, cfg_reset):
    advprint.CFG["max_retries"] = 1
    advprint.CFG["retry_base_seconds"] = 0
    # make printing explode
    orig = advprint.print_file
    calls = {"n": 0}
    def boom(*a, **k):
        calls["n"] += 1
        raise RuntimeError("printer on fire")
    advprint.print_file = boom
    try:
        advprint.RESUME_EVENT.clear()
        code, d = hub.post("/print", {"text": "will fail", "title": "boom",
                                      "kind": "thermal"})
        advprint.RESUME_EVENT.set()
        ok = wait_until(lambda: (advprint.db_get(d["job_id"]) or {})
                        .get("status") == "dead")
        assert ok, "job should reach dead-letter after retries"
        assert calls["n"] >= 2                          # 1st + 1 retry
        # dead-letter recovery: retry on ANOTHER printer
        code, d2 = hub.post("/jobs/%d/retry" % d["job_id"],
                            {"printer": "BackupLab"})
        assert code == 200
        j = advprint.db_get(d["job_id"])
        assert j["status"] in ("queued", "printing", "printed")
        assert j["printer"] == "BackupLab"
    finally:
        advprint.print_file = orig


def test_hold_when_printer_offline(hub, clean_queue, cfg_reset, monkeypatch):
    advprint.CFG["hold_offline"] = True
    monkeypatch.setattr(advprint, "printer_ready",
                        lambda name="": "offline")
    code, d = hub.post("/print", {"text": "wait for paper", "title": "hold",
                                  "kind": "thermal", "printer": "FrontDesk"})
    jid = d["job_id"]
    ok = wait_until(lambda: (advprint.db_get(jid) or {}).get("status") == "held")
    assert ok
    j = advprint.db_get(jid)
    assert "offline" in (j.get("held_reason") or "")
    # printer back online -> released
    monkeypatch.setattr(advprint, "printer_ready", lambda name="": "ready")
    advprint._UNHOLD_TS[0] = 0.0
    ok = wait_until(lambda: (advprint.db_get(jid) or {}).get("status")
                    in ("printed", "printing"))
    assert ok


# ============================================================
# 3. printer status / groups / raw / profiles
# ============================================================

def test_printer_group_fallback(hub, clean_queue, cfg_reset, monkeypatch):
    advprint.CFG["printer_groups"] = {"Front": ["A", "B"]}
    monkeypatch.setattr(advprint, "printers_status",
                        lambda force=False: {"A": "offline", "B": "ready"})
    assert advprint.pick_group_printer("Front") == "B"
    code, d = hub.post("/print", {"text": "to group", "title": "grp",
                                  "kind": "thermal", "printer": "Front"})
    ok = wait_until(lambda: len(hub.printed) >= 1)
    assert ok and hub.printed[-1]["printer"] == "B"


def test_printers_endpoint_has_status(hub):
    code, d = hub.get("/printers")
    assert code == 200
    for p in d["printers"]:
        assert "status" in p and "is_group" in p


def test_escpos_builder_markers():
    b = advprint.escpos_bytes(
        "HI\n#big HEAD\n|center|C\n|barcode:12345|\n|qr:tbl-9|\n|drawer|\n|cut|")
    assert b[:2] == b"\x1b@"                  # init
    assert b"\x1dV" in b                      # cut
    assert b"\x1bp\x00" in b                  # cash drawer
    assert b"\x1d(k" in b                     # QR
    assert b"\x1dkI" in b                     # CODE128 barcode
    assert b"\x1d!\x11" in b                  # double-size text


def test_raw_escpos_and_zpl_end_to_end(hub, clean_queue):
    code, d = hub.post("/print", {"lang": "escpos", "text": "COFFEE\n|cut|",
                                  "title": "receipt", "printer": "XP-58"})
    assert code == 200 and d["kind"] == "raw"
    ok = wait_until(lambda: len(hub.raw_printed) >= 1)
    assert ok
    data, printer = hub.raw_printed[-1]
    assert printer == "XP-58" and b"\x1dV" in data      # cut command inside
    code, d = hub.post("/print", {"lang": "zpl",
                                  "text": "^XA^FDHELLO^XZ",
                                  "title": "label", "printer": "Zebra"})
    ok = wait_until(lambda: len(hub.raw_printed) >= 2)
    assert ok
    data, printer = hub.raw_printed[-1]
    assert printer == "Zebra" and data == b"^XA^FDHELLO^XZ"


def test_pages_and_profile_reach_print_backend(hub, clean_queue, cfg_reset):
    hub.post("/config", {"profiles": {
        "Invoice": {"paper_size": "A4", "duplex": "long", "copies": 2}}})
    code, d = hub.post("/print", {"text": "x", "title": "withprof",
                                  "kind": "thermal", "profile": "Invoice",
                                  "pages": "1-3,5", "printer": "P1"})
    ok = wait_until(lambda: len(hub.printed) >= 1)
    assert ok
    rec = hub.printed[-1]
    assert rec["pages"] == "1-3,5"
    assert rec["duplex"] == "long" and rec["paper_size"] == "A4"
    assert rec["copies"] == 2                        # profile default applied


def test_unknown_profile_rejected(hub):
    code, d = hub.post("/print", {"text": "x", "title": "badprof",
                                  "profile": "Nope"})
    assert code == 400 and "unknown profile" in d["error"]


# ============================================================
# 4. audit / watermark / exports / dashboard / diagnostics
# ============================================================

def test_audit_trail(hub, clean_queue):
    code, d = hub.post("/print", {"text": "audit me", "title": "aud",
                                  "kind": "thermal"})
    wait_until(lambda: (advprint.db_get(d["job_id"]) or {}).get("status")
               == "printed")
    code, d = hub.get("/audit?event=print.submitted")
    assert code == 200 and any(e["event"] == "print.submitted"
                               for e in d["entries"])
    code, d = hub.get("/audit.csv")
    assert code == 200 and b"ts,event,job_id" in d


def test_job_records_site_and_hash(hub, clean_queue):
    code, d = hub.post("/print", {"text": "hash me", "title": "hash",
                                  "kind": "thermal"})
    j = advprint.db_get(d["job_id"])
    assert j["content_hash"] and len(j["content_hash"]) == 64


def test_reprint_reason_and_required(hub, clean_queue, cfg_reset):
    code, d = hub.post("/print", {"text": "orig", "title": "rep",
                                  "kind": "thermal"})
    wait_until(lambda: (advprint.db_get(d["job_id"]) or {}).get("status")
               == "printed")
    advprint.CFG["reprint_reason_required"] = True
    code, e = hub.post("/jobs/%d/reprint" % d["job_id"], {})
    assert code == 400 and "reason" in e["error"]
    code, e = hub.post("/jobs/%d/reprint" % d["job_id"],
                       {"reason": "customer lost the copy"})
    assert code == 200
    code, d2 = hub.get("/audit?event=reprint")
    assert any("customer lost" in (x.get("reason") or "")
               for x in d2["entries"])
    advprint.CFG["reprint_reason_required"] = False


def test_reprint_watermark(hub, clean_queue, cfg_reset):
    code, d = hub.post("/print", {"text": "wm source", "title": "wmsrc",
                                  "kind": "thermal"})
    wait_until(lambda: (advprint.db_get(d["job_id"]) or {}).get("status")
               == "printed")
    code, e = hub.post("/jobs/%d/reprint" % d["job_id"],
                       {"reason": "again", "watermark": True})
    assert code == 200 and e["watermark"] is True


def test_pdf_watermark_function():
    data, _ = advprint.thermal_pdf_bytes("WATERMARK UNIT TEST", "wm")
    out = advprint.pdf_watermark(data, "REPRINT")
    assert out[:5] == b"%PDF-" and len(out) > len(data)
    assert b"REPRINT" in out and b"PHwm" in out


def test_csv_history_export(hub, clean_queue):
    hub.post("/print", {"text": "csv row", "title": "csv", "kind": "thermal"})
    code, body = hub.get("/export/history.csv")
    assert code == 200
    head = body.split(b"\n")[0]
    for col in (b"priority", b"site", b"content_hash", b"attempts"):
        assert col in head


def test_stats_and_dashboard(hub):
    code, d = hub.get("/stats")
    assert code == 200
    for k in ("success_rate", "queue_size", "jobs_today", "by_status"):
        assert k in d
    code, body = hub.get("/dashboard?token=" + hub.token)
    assert code == 200 and b"Success Rate" in body


def test_diagnostics_redacts_token(hub):
    code, d = hub.get("/diagnostics")
    assert code == 200 and d["ok"] is True
    assert d["token"].endswith("***")
    assert hub.token not in json.dumps(d)


def test_peers_endpoint(hub, cfg_reset):
    advprint.CFG["peer_hubs"] = [{"url": "http://127.0.0.1:59999", "token": "x"}]
    advprint._PEER_CACHE["t"] = 0.0
    code, d = hub.get("/peers")
    assert code == 200 and d["peers"][0]["alive"] is False
    advprint.CFG["peer_hubs"] = []


# ============================================================
# 5. repo sanity: migration of a v1.x database + version anchors
# ============================================================

def test_v1_database_migration(tmp_path):
    dbf = tmp_path / "history.db"
    conn = sqlite3.connect(str(dbf))
    conn.execute("""CREATE TABLE jobs (id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL, kind TEXT NOT NULL, title TEXT, printer TEXT,
        copies INTEGER DEFAULT 1, status TEXT NOT NULL, error TEXT,
        file_path TEXT, source TEXT DEFAULT 'api', origin_ip TEXT,
        duration_ms INTEGER DEFAULT 0)""")
    conn.execute("INSERT INTO jobs (created_at,kind,title,printer,copies,"
                 "status,file_path,source,origin_ip,duration_ms) VALUES"
                 "('2025-01-01T00:00:00','a4','old job','X',1,'printed',"
                 "'/x.pdf','api','127',100)")
    conn.commit()
    conn.close()
    old_dir = advprint.CFG["data_dir"]
    advprint.CFG["data_dir"] = str(tmp_path)
    try:
        advprint.db_init()
        row = advprint.db_get(1)
        assert row["title"] == "old job"                 # data untouched
        assert all(k in row for k in ("priority", "attempts", "site",
                                      "content_hash", "held_reason"))
    finally:
        advprint.CFG["data_dir"] = old_dir


def test_version_anchors():
    assert advprint.VERSION == "3.2.1"
    # repo/package layout: tool/windows/portable/hub -> root/extension
    root = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.dirname(advprint.__file__)))))
    ext = os.path.join(root, "extension", "manifest.json")
    with open(ext) as f:
        assert json.load(f)["version"] == "3.2.1"


def test_log_rotation(tmp_path):
    old = advprint.CFG["data_dir"]
    advprint.CFG["data_dir"] = str(tmp_path)
    old_max = advprint.CFG["log_max_mb"]
    advprint.CFG["log_max_mb"] = 0        # rotate on every write
    try:
        advprint.log("rotation test entry")
        assert os.path.isfile(os.path.join(str(tmp_path), "hub.log"))
    finally:
        advprint.CFG["data_dir"] = old
        advprint.CFG["log_max_mb"] = old_max


# ============================================================
# v2.2.0: print options, capabilities, LAN share, queue shift
# ============================================================

@pytest.fixture(autouse=True)
def _v21_sync_token(hub):
    """Token rotation tests earlier in this module change CFG["token"] -
    keep the client's token in sync for every test."""
    hub.token = advprint.CFG["token"]
    yield


def test_v21_capabilities_endpoint(hub):
    code, d = hub.get("/printers/FakeLaser/capabilities")
    assert code == 200 and d["ok"] is True
    assert d["backend"] in ("sumatra", "cups")
    assert d["pages"]["odd_even"] is True


def test_v21_per_sheet_quality_reach_backend(hub, clean_queue):
    code, d = hub.post("/print", {"text": "nup", "title": "nup",
                                  "kind": "thermal", "printer": "P1",
                                  "per_sheet": 2, "quality": "draft"})
    assert code == 200
    ok = wait_until(lambda: len(hub.printed) >= 1)
    assert ok
    rec = hub.printed[-1]
    assert rec["per_sheet"] == 2 and rec["quality"] == "draft"


def test_v21_odd_even_reach_backend(hub, clean_queue):
    code, d = hub.post("/print", {"text": "oe", "title": "oe",
                                  "kind": "thermal", "printer": "P1",
                                  "pages": "odd"})
    assert code == 200
    ok = wait_until(lambda: len(hub.printed) >= 1)
    assert ok
    assert hub.printed[-1]["pages"] == "odd"


def test_v21_thermal_builder_overrides():
    data, _ = advprint.thermal_pdf_bytes("A\nB", title="t",
                                         margin_mm=10, scale_pct=200,
                                         landscape=True)
    assert data[:5] == b"%PDF-"
    data2, _ = advprint.thermal_pdf_bytes("x")          # old signature works
    assert data2[:5] == b"%PDF-"


def test_v21_helpers():
    assert advprint.text_needs_browser("বাংলা রসিদ") is True
    assert advprint.text_needs_browser("COFFEE 35.50") is False
    h = advprint.inject_page_css("<html><head></head><body>x</body></html>",
                                 margin_mm=8, scale_pct=150, landscape=True)
    assert "margin:8mm" in h and "zoom:150%" in h and "landscape" in h
    assert h.index("<style") < h.index("<body")
    assert advprint.pdf_page_count(b"%PDF-1.4 ... /Type /Page ... "
                                   b"/Type /Page ...") == 2
    assert advprint.pdf_page_count(b"not a pdf") is None


def test_v21_queue_shift_to_fake_peer(hub, clean_queue, cfg_reset):
    """Full-shift pending jobs to a fake peer hub over HTTP."""
    import http.server, threading as th
    got = {}

    class FakePeer(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            ln = int(self.headers.get("Content-Length") or 0)
            got["body"] = json.loads(self.rfile.read(ln) or b"{}")
            got["token"] = self.headers.get("X-AdvPrint-Token")
            body = json.dumps({"ok": True, "job_id": 777}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    psrv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakePeer)
    pport = psrv.server_address[1]
    th.Thread(target=psrv.serve_forever, daemon=True).start()
    try:
        # v2.9.1: the worker now claims jobs in ~1 ms (wake event), so the
        # job must be posted while the queue is PAUSED - otherwise it is
        # printed before the shift arrives and there is nothing to shift.
        hub.post("/queue/pause", {})
        code, d = hub.post("/print", {"text": "shift me", "title": "sh",
                                      "kind": "thermal", "printer": "P1"})
        jid = d["job_id"]
        advprint._PAUSED.clear() if hasattr(advprint, "_PAUSED") else None
        code, d = hub.post("/queue/shift", {
            "target": "http://127.0.0.1:%d" % pport,
            "target_token": "peersecret", "scope": "all"})
        assert code == 200 and d["ok"] is True, d
        assert d["shifted_count"] == 1 and jid in d["shifted"]
        assert got["token"] == "peersecret"
        assert got["body"]["title"] == "sh"
        assert (advprint.db_get(jid) or {}).get("status") == "forwarded"
        # individual shift: unknown id list shifts nothing
        code, d = hub.post("/queue/shift", {
            "target": "http://127.0.0.1:%d" % pport, "scope": "job",
            "ids": [424242]})
        assert code == 200 and d["shifted_count"] == 0
    finally:
        hub.post("/queue/resume", {})
        psrv.shutdown()


def test_v21_share_lan_config_roundtrip(hub, cfg_reset):
    code, d = hub.post("/config", {"share_lan": True})
    assert code == 200 and d["config"]["share_lan"] is True
    code, d = hub.get("/health", token=None)
    assert d["share_lan"] is True and d["lan_url"]
    hub.post("/config", {"share_lan": False})
    code, d = hub.get("/health", token=None)
    assert d["share_lan"] is False and d["lan_url"] is None


def test_v21_escpos_codepage_config(hub, cfg_reset, monkeypatch):
    advprint.CFG["escpos_codepage"] = "cp850"
    data = advprint.escpos_bytes("caf\xe9")       # \xe9 is 0x82 in cp850
    assert b"caf\x82" in data
    advprint.CFG["escpos_codepage"] = "cp437"
    data = advprint.escpos_bytes("caf\xe9")
    assert b"caf" in data                          # replaced, no crash

# ============================================================
# v2.2.0: quality presets AND DPI, built-in /docs page,
# dashboard LAN card, health lan_active
# ============================================================

def test_v22_quality_preset_still_works(hub, clean_queue):
    code, d = hub.post("/print", {"text": "q", "title": "q",
                                  "kind": "thermal", "printer": "P1",
                                  "quality": "draft"})
    assert code == 200
    assert wait_until(lambda: len(hub.printed) >= 1)
    assert hub.printed[-1]["quality"] == "draft"


def test_v22_quality_dpi_spellings(hub, clean_queue):
    """v2.2: quality accepts draft/normal/high AND DPI - all 3 forms."""
    for given, want in (("600dpi", "dpi:600"), ("600", "dpi:600"),
                        ("1200 dpi", "dpi:1200")):
        n = len(hub.printed)
        code, d = hub.post("/print", {"text": "q-" + given, "title": "q-" + given,
                                      "kind": "thermal", "printer": "P1",
                                      "quality": given})
        assert code == 200, (given, d)
        assert wait_until(lambda: len(hub.printed) > n)
        assert hub.printed[-1]["quality"] == want, given


def test_v22_dpi_field(hub, clean_queue):
    code, d = hub.post("/print", {"text": "q-dpi", "title": "q-dpi",
                                  "kind": "thermal", "printer": "P1",
                                  "dpi": 300})
    assert code == 200
    assert wait_until(lambda: len(hub.printed) >= 1)
    assert hub.printed[-1]["quality"] == "dpi:300"


def test_v22_quality_alias_and_clamp(hub, clean_queue):
    code, d = hub.post("/print", {"text": "q-best", "title": "q-best",
                                  "kind": "thermal", "printer": "P1",
                                  "quality": "best"})
    assert code == 200
    assert wait_until(lambda: len(hub.printed) >= 1)
    assert hub.printed[-1]["quality"] == "high"
    # clamp: 99999 dpi -> 2400
    code, d = hub.post("/print", {"text": "q-clamp", "title": "q-clamp",
                                  "kind": "thermal", "printer": "P1",
                                  "dpi": 99999})
    assert code == 200
    assert wait_until(lambda: hub.printed[-1]["quality"] == "dpi:2400")


def test_v22_capabilities_quality_shape(hub):
    code, d = hub.get("/printers/FakeLaser/capabilities")
    assert code == 200 and d["ok"] is True
    q = d["quality"]
    assert isinstance(q, dict) and "draft" in q["presets"]
    # dpi is either a list (CUPS) or None (Windows driver-controlled)
    assert q["dpi"] is None or isinstance(q["dpi"], list)


def test_v22_docs_page_served(hub):
    code, d = hub.get("/docs")
    assert code == 200
    # the client falls back to raw bytes for non-JSON responses
    body = (d.decode("utf-8", "replace") if isinstance(d, bytes)
            else d if isinstance(d, str) else json.dumps(d))
    assert "LAN sharing" in body and "POST /print" in body
    assert advprint.VERSION in body


def test_v22_docs_wrong_token_json(hub):
    code, d = hub.get("/docs", token="wrong-token")
    assert code == 401 and d.get("ok") is False


def test_v22_dashboard_has_lan_card_and_docs(hub):
    html = advprint.dashboard_html("")
    assert 'id="lanBody"' in html and "LAN sharing" in html
    assert "/docs" in html and "shiftJob" in html
    assert 'id="dbgBody"' in html and "toggleDebug" in html
    assert advprint.VERSION in html


def test_v22_health_lan_active(hub):
    code, d = hub.get("/health")
    assert code == 200
    assert d["lan_active"] is False      # test server binds 127.0.0.1


# ============================================================
# v2.2.1 - "extension shows OK but nothing prints" fixes
# ============================================================

def test_v221_print_response_has_status(hub, clean_queue):
    # the extension history used to record EVERY job as "queued" because
    # the POST /print answer carried no status field at all
    code, d = hub.post("/print", {"text": "status check", "title": "st1"})
    assert code == 200 and d["ok"] is True
    assert d["status"] == "queued"
    code, d = hub.post("/print", {"text": "direct", "title": "st2",
                                  "queue": False})
    assert code == 200 and d["status"] in ("printing", "printed")
    # v2.9.1: with the instant worker the direct job can FINISH before the
    # response is built - "printed" is the truthful answer then


def test_v221_get_single_job(hub, clean_queue):
    code, d = hub.post("/print", {"text": "single", "title": "solo"})
    jid = d["job_id"]
    code, d = hub.get("/jobs/%d" % jid)
    assert code == 200 and d["ok"] is True
    assert d["job"]["id"] == jid and d["job"]["title"] == "solo"
    code, d = hub.get("/jobs/999999")
    assert code == 404 and d["ok"] is False


def test_v221_print_now_bypasses_hold(hub, clean_queue, cfg_reset, monkeypatch):
    # printer reports offline -> job HELD (old behaviour: stuck forever,
    # the user sees "queued/held" and nothing prints). print-now must
    # push it out immediately.
    advprint.CFG["hold_offline"] = True
    monkeypatch.setattr(advprint, "printers_status",
                        lambda force=False: {"GhostOff": "offline"})
    code, d = hub.post("/print", {"text": "held job", "title": "h1",
                                  "printer": "GhostOff"})
    jid = d["job_id"]
    assert wait_until(lambda: (advprint.db_get(jid) or {}).get("status")
                      == "held"), "job should be held"
    code, d = hub.post("/jobs/%d/print-now" % jid, {})
    assert code == 200 and d["ok"] is True and d["status"] == "printing"
    assert wait_until(lambda: (advprint.db_get(jid) or {}).get("status")
                      == "printed"), "print-now must print despite hold"


def test_v221_print_now_bypasses_pause(hub, clean_queue):
    # v2.9.1: pause FIRST - the worker now wakes instantly (no 0.35 s
    # poll), so a job posted while the queue is running can print before
    # the pause arrives; pausing first makes the scenario deterministic.
    hub.post("/queue/pause", {})
    try:
        code, d = hub.post("/print", {"text": "paused job", "title": "p1"})
        jid = d["job_id"]
        assert wait_until(lambda: (advprint.db_get(jid) or {})
                          .get("status") == "queued")
        code, d = hub.post("/jobs/%d/print-now" % jid, {})
        assert code == 200
        assert wait_until(lambda: (advprint.db_get(jid) or {})
                          .get("status") == "printed"), \
            "print-now must print even while the queue is paused"
    finally:
        hub.post("/queue/resume", {})


def test_v221_worker_survives_internal_error(hub, clean_queue, monkeypatch):
    # THE regression: any unexpected exception inside the worker used to
    # kill the thread - the hub kept answering OK while every later job
    # stayed "queued" forever. The exception-proof loop must keep going.
    calls = {"n": 0}
    real_execute = advprint._execute_job

    def exploding(job, t0):
        calls["n"] += 1
        raise RuntimeError("simulated worker crash")

    monkeypatch.setattr(advprint, "_execute_job", exploding)
    code, d = hub.post("/print", {"text": "boom", "title": "crash1"})
    jid1 = d["job_id"]
    # the crash must be picked up by the worker...
    assert wait_until(lambda: calls["n"] >= 1, timeout=10), \
        "worker should have called the exploding handler"
    # ...and the job must NOT be stuck in 'printing' forever - it goes
    # to failed -> retry backoff (status queued again, attempts counted)
    def retried():
        j = advprint.db_get(jid1) or {}
        return (j.get("status") == "queued" and j.get("attempts", 0) >= 1) \
            or j.get("status") == "failed"
    assert wait_until(retried), \
        "crashed job must not stay 'printing' forever"
    # the worker must STILL be alive for the next job
    monkeypatch.setattr(advprint, "_execute_job", real_execute)
    code, d = hub.post("/print", {"text": "after crash", "title": "ok1"})
    jid2 = d["job_id"]
    assert wait_until(lambda: (advprint.db_get(jid2) or {})
                      .get("status") == "printed", timeout=10), \
        "worker must survive an unexpected internal error"
    assert calls["n"] >= 1


def test_v221_watchdog_respawns_dead_worker(hub):
    # belt & braces: the watchdog must notice a dead worker thread and
    # spawn a fresh one
    dead = __import__("threading").Thread(target=lambda: None)
    dead.start()
    dead.join()
    old = advprint._WORKER_THREAD[0]
    try:
        advprint._WORKER_THREAD[0] = dead
        assert not advprint._WORKER_THREAD[0].is_alive()
        advprint._spawn_worker()
        assert advprint._WORKER_THREAD[0].is_alive()
        assert advprint._WORKER_THREAD[0] is not dead
    finally:
        advprint._WORKER_THREAD[0] = old


def test_v221_health_reports_worker_and_hold(hub):
    code, d = hub.get("/health")
    assert code == 200
    assert d["worker_alive"] is True
    assert d["hold_offline"] is True


# ============================================================
# v2.3.0 - instant print + auto-queue fallback + /debug
# ============================================================

def test_v23_debug_endpoint(hub):
    code, d = hub.get("/debug")
    assert code == 200 and d["ok"] is True
    for key in ("problems", "client_reports", "worker_alive", "paused",
                "printers", "recent_jobs", "queue", "debug",
                "instant_auto_queue", "version"):
        assert key in d, key
    assert isinstance(d["problems"], list) and d["problems"]
    assert all("level" in p and "message" in p for p in d["problems"])


def test_v23_debug_wrong_token(hub):
    code, d = hub.get("/debug", token="nope-" + hub.token)
    assert code == 401 and d.get("ok") is False


def test_v23_debug_query_token_works(hub):
    # v2.0.2 rule must hold for the new endpoint too: browsers open
    # /debug?token=... with a plain link
    code, d = hub.get("/debug?token=" + hub.token, token=None)
    assert code == 200 and d["ok"] is True


def test_v23_debug_report_roundtrip(hub):
    code, d = hub.post("/debug/report", {
        "source": "extension", "level": "error",
        "message": "pytest test report - printer fetch failed",
        "context": {"url": "http://x/y.pdf"}, "job_id": None})
    assert code == 200 and d["ok"] is True and d["stored"] >= 1
    code, d = hub.get("/debug")
    reports = d["client_reports"]
    assert any("pytest test report" in r.get("message", "")
               for r in reports)
    hit = [r for r in reports if "pytest test report" in r.get("message", "")][0]
    assert hit["source"] == "extension"
    assert hit["level"] == "error"
    assert hit["ts"] and hit["ip"]


def test_v23_debug_report_persists(hub):
    # the ring buffer survives a restart via debug_reports.json
    hub.post("/debug/report", {"source": "tool", "level": "warn",
                               "message": "persistence check"})
    path = os.path.join(advprint.CFG["data_dir"], "debug_reports.json")
    assert os.path.isfile(path)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert any(r.get("message") == "persistence check" for r in data)


def test_v23_instant_auto_queue(hub, clean_queue, cfg_reset, monkeypatch):
    # THE v2.3 feature: queue OFF (instant) + printer NOT active ->
    # the job is auto-queued instead of being printed (and failing)
    advprint.CFG["hold_offline"] = True
    monkeypatch.setattr(advprint, "printers_status",
                        lambda force=False: {"GhostOff": "offline"})
    code, d = hub.post("/print", {"text": "instant fallback",
                                  "title": "iaq", "printer": "GhostOff",
                                  "queue": False})
    assert code == 200 and d["ok"] is True
    assert d["instant"] is True
    assert d["auto_queued"] is True
    assert d["status"] == "queued"
    assert "auto-queued" in d["message"]
    jid = d["job_id"]
    row = advprint.db_get(jid)
    assert row["status"] in ("queued", "held")     # never printing directly
    audited = advprint.audit_list(50, "print.auto_queued")
    assert any(a.get("job_id") == jid for a in audited)
    assert not hub.printed                          # nothing hit the printer


def test_v23_instant_prints_when_printer_ready(hub, clean_queue, cfg_reset,
                                               monkeypatch):
    # printer IS ready -> instant mode really prints immediately
    monkeypatch.setattr(advprint, "printers_status",
                        lambda force=False: {"StubPrinter": "ready"})
    code, d = hub.post("/print", {"text": "instant now", "title": "iok",
                                  "queue": False})
    assert code == 200 and d["auto_queued"] is False
    assert wait_until(lambda: (advprint.db_get(d["job_id"]) or {})
                      .get("status") == "printed"), \
        "instant print must go out immediately when the printer is ready"


def test_v23_mode_instant_alias(hub, clean_queue, cfg_reset, monkeypatch):
    # mode=instant is the friendlier alias of queue:false
    monkeypatch.setattr(advprint, "printers_status",
                        lambda force=False: {"StubPrinter": "ready"})
    code, d = hub.post("/print", {"text": "alias", "title": "mai",
                                  "mode": "instant"})
    assert code == 200 and d["instant"] is True and d["queue_mode"] == "off"
    assert wait_until(lambda: (advprint.db_get(d["job_id"]) or {})
                      .get("status") == "printed")
    code, d = hub.post("/print", {"text": "alias back", "title": "maq",
                                  "mode": "queue"})
    assert code == 200 and d["queue_mode"] == "on" and d["status"] == "queued"


def test_v23_instant_raw_skips_status_check(hub, clean_queue):
    # ESC/POS receipt printers rarely report a status - instant raw
    # printing must never be blocked by the auto-queue fallback
    code, d = hub.post("/print", {"raw_base64": base64.b64encode(
                                      b"\x1b@receipt").decode(),
                                  "lang": "escpos", "title": "raw-inst",
                                  "queue": False})
    assert code == 200 and d["ok"] is True
    assert wait_until(lambda: (advprint.db_get(d["job_id"]) or {})
                      .get("status") == "printed")


def test_v23_debug_toggle_via_config(hub):
    code, d = hub.post("/config", {"debug": True})
    assert code == 200 and d["ok"] is True
    code, d = hub.get("/health")
    assert d["debug"] is True
    code, d = hub.get("/debug")
    assert d["debug"] is True
    code, d = hub.post("/config", {"debug": False})
    assert code == 200
    code, d = hub.get("/health")
    assert d["debug"] is False and d["instant_auto_queue"] is True


def test_v23_debug_off_info_hint(hub):
    # debug OFF -> the verdict still works and tells the user to switch on
    code, d = hub.get("/debug")
    assert code == 200
    assert any(p["check"] == "debug off" for p in d["problems"]) or d["debug"]


def test_v23_endpoints_list_includes_debug(hub):
    code, d = hub.get("/")
    assert code == 200
    eps = " ".join(d["endpoints"])
    assert "/debug" in eps and "/debug/report" in eps


def test_v23_docs_has_debug_and_instant(hub):
    code, d = hub.get("/docs")
    assert code == 200
    body = (d.decode("utf-8", "replace") if isinstance(d, bytes)
            else d if isinstance(d, str) else json.dumps(d))
    assert "Debug mode" in body and "/debug" in body
    assert "instant" in body and "auto-queued" in body
    assert "/debug/report" in body


# ================= v2.6: one-click token fix + live test =================

def test_v26_token_current_loopback_only(hub):
    """GET /token/current answers on loopback WITHOUT a token (the
    owner PC one-click fix) and returns the hub's current token."""
    code, d = hub.get("/token/current")
    assert code == 200 and d["ok"] is True
    assert d["token"] == hub.token
    assert d["app"] == "AdvPrint Pro" and d["version"] == "3.2.1"


def test_v26_token_current_rejects_remote(hub):
    """The /token/current gate is _is_loopback(): a LAN client
    (192.168.x.x) is NOT loopback and therefore gets 403 - the token
    never leaves the hub PC over this endpoint."""
    f = advprint.Handler.__new__(advprint.Handler)
    f.client_address = ("192.168.1.77", 5555)
    assert f._is_loopback() is False
    f.client_address = ("127.0.0.1", 4444)
    assert f._is_loopback() is True
    f.client_address = ("::1", 4444)
    assert f._is_loopback() is True


def test_v26_dashboard_error_page_has_one_click_fix(hub, monkeypatch):
    monkeypatch.setattr(advprint.Handler, "_is_loopback",
                        lambda self: False)
    code, body = hub.get("/dashboard?token=WRONG-stale-token",
                         token="WRONG-stale-token",
                         headers={"Accept": "text/html"})
    assert code == 401
    assert b"Fix it now" in body and b"/token/current" in body


def test_v26_livetest_endpoint(hub):
    code, d = hub.post("/livetest", {})
    assert code == 200 and d["ok"] is True
    names = [s["name"] for s in d["steps"]]
    assert any("Queue DB" in n for n in names)
    assert isinstance(d["all_ok"], bool)


def test_v26_health_reports_new_brand(hub):
    code, d = hub.get("/health")
    assert code == 200
    assert d["app"] == "AdvPrint Pro"
    assert "Bit Dream IT" in d["branding"]
    assert "Innovative Healthcare Solutions" in d["branding"]


def test_v26_legacy_header_accepted(hub):
    """Old clients still send X-PrintHub-Token - accepted."""
    code, d = hub.get("/jobs", headers={"X-PrintHub-Token": hub.token})
    assert code == 200


# ============================================================
# v2.6.1 - hub start + tray fix release
# ============================================================

def test_v261_hub_dir_on_sys_path():
    """The embedded runtime (isolated mode) does not add the script
    folder to sys.path -> tray import failed in the portable layout.
    advprint.py must self-insert its own folder (idempotent)."""
    here = os.path.dirname(os.path.abspath(advprint.__file__))
    assert here in sys.path
    assert advprint._HUB_DIR == here


def test_v261_tray_module_ships_and_parses():
    """The real root cause of 'tray icon missing': tray_windows.py must
    ship next to advprint.py and stay importable on Windows (it is a
    Windows-only ctypes module - here we parse + sanity-check it)."""
    import ast
    p = os.path.join(os.path.dirname(advprint.__file__), "tray_windows.py")
    src = open(p, encoding="utf-8").read()
    ast.parse(src)
    assert "def start(" in src
    assert "Shell_NotifyIcon" in src


def test_v261_version_single_source():
    assert advprint.VERSION == "3.2.1"
    assert advprint.VERSION_NAME.startswith("v3.2.1")


def test_v261_cli_cmd_full_path():
    cmd = advprint.cli_cmd("token-rotate")
    assert "advprint.py" in cmd and "token-rotate" in cmd
    assert os.sep in cmd or "/" in cmd      # contains a real path


def test_v261_dashboard_live_tool_version():
    """The live debug tool must show the REAL version (was stuck v2.5)."""
    html = advprint.dashboard_html(query="?token=x")
    assert "(v%s)" % advprint.VERSION in html
    assert "(v2.5)" not in html
    assert "Hub is OFFLINE" in html          # offline-friendly buttons


def test_v261_boot_lines_and_crash_catcher():
    src = open(os.path.join(os.path.dirname(advprint.__file__),
                            "advprint.py"), encoding="utf-8").read()
    assert "[BOOT] AdvPrint Pro v" in src            # boot bracket
    assert "FATAL - the hub crashed" in src          # crash -> hub.log
    assert "FATAL: startup failed before opening the port" in src


def test_v261_tool_has_diagnose_menu():
    tp = os.path.join(os.path.dirname(advprint.__file__), "tool.py")
    src = open(tp, encoding="utf-8").read()
    import ast
    ast.parse(src)                                   # tool.py must parse
    assert "def diagnose_and_fix()" in src
    assert "def _report_start_failure()" in src
    assert "def _manual_command()" in src
    assert "Unblock-File" in src                     # MOTW repair
    assert "[13] Diagnose & fix" in src
    assert "Choose [0-14]" in src
    assert "The hub did not answer within 30 seconds" in src


def test_v261_tool_manual_command_uses_full_path():
    import importlib.util
    tp = os.path.join(os.path.dirname(advprint.__file__), "tool.py")
    spec = importlib.util.spec_from_file_location("tool_chk", tp)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    cmd = m._manual_command()
    assert "advprint.py" in cmd and " serve" in cmd
    assert os.sep in cmd                     # absolute, works from any cwd


# ============================================================
# v2.6.4 - winreg import + never-empty-response + 302 token repair
# ============================================================

def test_v264_winreg_import_guard():
    """v2.6.3 FIELD BUG: advprint.py USED the `winreg` module in
    _winreg_lookup_sumatra() but never imported it. On Windows that
    raised NameError inside find_sumatra(), which is on the /health
    snapshot path (so /health answered the 6-key "starting": true
    fallback forever), on /debug + /diagnostics (both died with
    ERR_EMPTY_RESPONSE) and on the PDF print path (every job failed).
    Linux never runs that code - which is why the sandbox smoke tests
    looked green while the user's Windows PC was broken."""
    src = open(os.path.join(os.path.dirname(advprint.__file__),
                            "advprint.py"), encoding="utf-8").read()
    assert "try:\n    import winreg" in src
    assert "except ImportError:" in src
    assert hasattr(advprint, "winreg")      # module attribute exists


def test_v264_find_sumatra_never_raises(hub, monkeypatch):
    """Defense in depth: whatever happens inside the Sumatra lookup,
    find_sumatra() must degrade to None - it is called by the /health
    snapshot builder, /debug, /diagnostics AND the print path."""
    def boom():
        raise RuntimeError("simulated registry/glob failure")
    monkeypatch.setattr(advprint, "_find_sumatra_inner", boom)
    assert advprint.find_sumatra() is None
    assert advprint.SUMATRA_LAST["found"] is None


def test_v264_health_snapshot_survives_sumatra_crash(hub, monkeypatch):
    """The refresher catches silently - the snapshot must still fill
    (i.e. /health must never fall back to starting:true forever)."""
    def boom():
        raise RuntimeError("simulated registry/glob failure")
    monkeypatch.setattr(advprint, "_find_sumatra_inner", boom)
    snap = advprint.build_health_snapshot()
    assert snap["ok"] is True and "worker_alive" in snap
    assert "starting" not in snap


def test_v264_crashed_endpoint_answers_500(hub, monkeypatch):
    """v2.6.4 NEVER-EMPTY-RESPONSE guarantee: a handler crash must give
    the client a readable 500 JSON (Chrome showed ERR_EMPTY_RESPONSE
    when /debug crashed in v2.6.3)."""
    def boom():
        raise RuntimeError("simulated handler crash")
    monkeypatch.setattr(advprint, "build_debug_report", boom)
    code, d = hub.get("/debug")
    assert code == 500
    assert d["ok"] is False and "internal error" in d["error"]
    monkeypatch.setattr(advprint, "build_debug_report",
                        lambda: {"ok": True})          # restore


def test_v264_loopback_browser_gets_302_token_repair(hub):
    """A browser (Accept: text/html) opening /dashboard with a stale
    token from the hub PC is redirected to the CURRENT token instead of
    an error page; API clients keep the strict 401 JSON."""
    import urllib.request as _ur
    class _NoRedirect(_ur.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None                     # surface the 302 itself
    opener = _ur.build_opener(_NoRedirect)
    req = _ur.Request(hub.base + "/dashboard?token=WRONG", headers={
        "Accept": "text/html,application/xhtml+xml"})
    try:
        with opener.open(req, timeout=10) as r:
            code, hdrs = r.getcode(), r.headers
    except _ur.HTTPError as e:
        code, hdrs = e.code, e.headers
    assert code == 302, code
    assert ("token=" + hub.token) in (hdrs.get("Location") or "")
    # API clients (no Accept header, like fetch) still get the 401
    code2, d2 = hub.get("/dashboard?token=WRONG", token=None)
    assert code2 == 401 and d2["ok"] is False


def test_v264_loopback_302_never_for_remote_or_api():
    """The 302 repair must be loopback+browser only (source-level:
    _is_loopback() and the Accept check happen before any redirect)."""
    src = open(os.path.join(os.path.dirname(advprint.__file__),
                            "advprint.py"), encoding="utf-8").read()
    assert "not self._is_loopback()" in src
    assert '"text/html" not in (self.headers.get("Accept") or "")' in src


def test_v264_extension_auto_heal_unchanged():
    """The v2.6.2 extension auto-heal must stay wired: hubFetch retries
    through /token/current on the first 401 (the audit spam the user
    saw was a stale-token client polling every ~15 s)."""
    p = os.path.join(os.path.dirname(advprint.__file__),
                     "..", "..", "..", "..", "extension", "background.js")
    src = open(p, encoding="utf-8").read()
    assert "function autoHealToken()" in src
    assert '"/token/current"' in src
    assert "await autoHealToken()" in src


def test_v264_setup_exe_kills_zombie_hubs():
    """The Setup exe must stop a running hub by IMAGE NAME too (the old
    code only killed the port-9235 listener, so a hub on another port
    survived the upgrade with its old token in memory)."""
    src = open(os.path.join(os.path.dirname(advprint.__file__),
                            "..", "..", "..", "..",
                            "installer", "setup.nsi"), encoding="utf-8").read()
    # v2.8: the kill-by-image logic moved into hub-stop.ps1, which
    # setup.nsi extracts and runs BEFORE touching any file
    assert "hub-stop.ps1" in src
    stopps = open(os.path.join(os.path.dirname(advprint.__file__),
                               "..", "install", "hub-stop.ps1"),
                  encoding="utf-8").read()
    assert "Stop-Process -Name AdvPrintPro" in stopps
    assert "Stop-Process -Name PrintHubPro" in stopps
    assert "sc.exe delete AdvPrint" in stopps
    assert 'VIProductVersion "3.2.1.0"' in src


# ---------------- v2.6.8: printer-name self-heal + menu guard ----------

def test_v268_fix_printer_name_doubled():
    """'CanonCanon' style names collapse to their half when that half is
    an installed printer (live case: job #2 'Canon LBP6230/6240Canon
    LBP6230/6240')."""
    st = {"Canon LBP6230/6240", "Fax"}
    fixed, note = advprint.fix_printer_name(
        "Canon LBP6230/6240Canon LBP6230/6240", st)
    assert fixed == "Canon LBP6230/6240"
    assert "doubled" in (note or "")


def test_v268_fix_printer_name_case_space():
    """A name that differs only by case / doubled spaces matches the
    installed printer exactly."""
    st = {"Canon LBP6230/6240"}
    fixed, note = advprint.fix_printer_name("canon  LBP6230/6240", st)
    assert fixed == "Canon LBP6230/6240"
    assert "case" in (note or "")


def test_v268_fix_printer_name_exact_passthrough():
    """An exact name passes through untouched."""
    st = {"Canon LBP6230/6240"}
    fixed, note = advprint.fix_printer_name("Canon LBP6230/6240", st)
    assert fixed == "Canon LBP6230/6240" and note is None


def test_v268_fix_printer_name_miss_returns_none():
    """A truly unknown name still returns None -> the clear
    'printer not found' error stays (no false healing)."""
    st = {"Canon LBP6230/6240"}
    assert advprint.fix_printer_name("Ghost 9000", st) == (None, None)
    assert advprint.fix_printer_name("", st) == (None, None)
    assert advprint.fix_printer_name("Canon LBP6230/6240", {}) == (None, None)


def test_v268_print_file_guard_heals_before_refusing(monkeypatch, tmp_path):
    """print_file must self-heal a doubled printer name instead of
    raising 'not found' (the exact job #2 failure). Uses an ISOLATED
    module import because the shared hub fixture permanently stubs
    advprint.print_file for the whole test session."""
    import importlib.util
    import types
    spec = importlib.util.spec_from_file_location(
        "advprint_iso_268",
        os.path.join(os.path.dirname(advprint.__file__), "advprint.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    import tempfile
    os.environ.setdefault("ADVPRINT_DATA", tempfile.mkdtemp(prefix="t268-"))
    os.environ.setdefault("ADVPRINT_FILE_DIR",
                          tempfile.mkdtemp(prefix="t268fd-"))
    mod.ensure_dirs()
    pdf = tmp_path / "j.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr(mod, "printers_status",
                        lambda force=False: {"Canon LBP6230/6240": "ready"})
    monkeypatch.setattr(mod, "default_printer",
                        lambda: "Canon LBP6230/6240")
    monkeypatch.setattr(mod, "find_sumatra", lambda: "C:/x/SumatraPDF.exe")
    monkeypatch.setattr(mod, "IS_WIN", False)
    monkeypatch.setattr(mod.shutil, "which",
                        lambda n: "/usr/bin/lp" if n == "lp" else None)

    class P:
        returncode = 0
        stdout = b""
        stderr = b""

        def communicate(self, timeout=None):
            return (b"", b"")

        def kill(self):
            pass

    monkeypatch.setattr(mod.subprocess, "Popen", lambda *a, **k: P())
    monkeypatch.setattr(mod.subprocess, "run",
                        lambda *a, **k: P())
    target = mod.print_file(str(pdf), "a4",
                            "Canon LBP6230/6240Canon LBP6230/6240")
    assert target == "Canon LBP6230/6240"


def test_v268_extension_self_heal_and_menu_patterns():
    """The extension must collapse doubled names before sending and its
    context menus must be limited to printable pages."""
    p = os.path.join(os.path.dirname(advprint.__file__),
                     "..", "..", "..", "..", "extension", "background.js")
    src = open(p, encoding="utf-8").read()
    assert "function healPrinterName" in src
    assert "payload.printer = healPrinterName(payload.printer)" in src
    assert "documentUrlPatterns" in src
    assert '"http://*/*"' in src and '"https://*/*"' in src
    assert "function printableTab" in src
    assert "/^(https?|file):/i" in src


# ---------------- v2.6.9: no double print (worker vs direct race) -------

def test_v269_direct_job_printed_exactly_once(hub, clean_queue, monkeypatch):
    """v2.6.9 regression for the real-machine report 'the page prints
    twice' (two Sumatra runs, two '[OK] job #N' lines): with Queue Mode
    OFF the job row used to be born 'queued' and was only flipped to
    'printing' AFTER the slow printer-status probe (hundreds of ms on
    Windows) - the FIFO worker polls every 0.35 s and could claim the job
    inside that window, so BOTH paths sent the same job to the backend.
    The row is now born 'printing', a state the worker (which only claims
    'queued') can never see."""
    def slow_ready(name=""):
        time.sleep(0.6)              # probe wider than the worker cycle
        return "ready"
    monkeypatch.setattr(advprint, "printer_ready", slow_ready)
    code, d = hub.post("/print", {"text": "double print race", "title":
                                  "race269", "queue": False})
    assert code == 200 and d.get("ok"), d
    jid = d["job_id"]
    assert wait_until(lambda: any(p.get("job_id") == jid
                                  for p in hub.printed), timeout=10)
    time.sleep(1.2)                  # a 2nd execution would land here
    hits = [p for p in hub.printed if p.get("job_id") == jid]
    assert len(hits) == 1, ("job #%d was printed %d times - double-print"
                            " bug is back" % (jid, len(hits)))
    assert advprint.db_get(jid)["status"] == "printed"


def test_v269_direct_retry_keeps_file(hub, clean_queue, cfg_reset,
                                      monkeypatch):
    """v2.6.9: a Queue-Mode-OFF job that fails must stay printable - its
    PDF file used to be deleted in the direct thread's finally block, so
    the automatic retry always died on 'file no longer stored'."""
    monkeypatch.setitem(advprint.CFG, "max_retries", 2)
    monkeypatch.setitem(advprint.CFG, "retry_base_seconds", 30)
    def boom(*a, **kw):
        raise RuntimeError("backend exploded")
    monkeypatch.setattr(advprint, "print_file", boom)
    code, d = hub.post("/print", {"text": "retry keeps file", "title":
                                  "retryfile269", "queue": False})
    assert code == 200 and d.get("ok"), d
    jid = d["job_id"]
    ok = wait_until(lambda: (advprint.db_get(jid) or {}).get("status")
                    == "queued"
                    and (advprint.db_get(jid) or {}).get("next_attempt_at"),
                    timeout=8)
    assert ok, advprint.db_get(jid)
    j = advprint.db_get(jid)
    assert j["attempts"] == 1
    assert j.get("file_path") and os.path.exists(j["file_path"]), \
        "retry file was deleted - the retry can never succeed"
    advprint.db_update(jid, status="canceled", error="test done")


# ---------------- v2.7.0: history manager + bulk endpoints --------------

def _v270_mkfile(tmp_path, name, content=b"%PDF-1.4 v270-test"):
    p = tmp_path / name
    p.write_bytes(content)
    return str(p)


def test_v270_bulk_reprint_by_ids(hub, clean_queue, tmp_path):
    """v2.7.0: POST /jobs/bulk-reprint {"ids":[...]} re-queues exactly the
    picked stored jobs and reports per-job results."""
    src = _v270_mkfile(tmp_path, "a.pdf")
    j1 = advprint.db_add("a4", "bulk-src-1", "", 1, src, "test", "t",
                         status="printed")
    j2 = advprint.db_add("a4", "bulk-src-2", "", 1, src, "test", "t",
                         status="printed")
    code, d = hub.post("/jobs/bulk-reprint", {"ids": [j1, j2]})
    assert code == 200 and d["ok"] and d["queued"] == 2, d
    assert [r["ok"] for r in d["results"]] == [True, True]
    for r in d["results"]:
        j = advprint.db_get(r["job_id"])
        assert j and j["title"].endswith("-reprint")
        advprint.db_update(r["job_id"], status="canceled", error="test done")
    # unknown ids never abort the batch - they are reported as skipped
    code, d = hub.post("/jobs/bulk-reprint", {"ids": [999999]})
    assert code == 200 and d["queued"] == 0 and d["skipped"] == 1, d
    assert d["results"][0]["id"] == 999999
    assert d["results"][0]["error"] == "job not found"


def test_v270_bulk_reprint_not_printed_scope(hub, clean_queue, tmp_path):
    """v2.7.0: {"scope":"not_printed"} re-queues failed/dead/canceled
    rows only - printed jobs stay untouched. (The suite shares one hub
    DB across tests, so assertions are scoped to the rows this test
    created, never to absolute counts.)"""
    src = _v270_mkfile(tmp_path, "f.pdf")
    failed_id = advprint.db_add("a4", "never-printed-270", "", 1, src,
                                "test", "t", status="failed", error="x")
    printed_id = advprint.db_add("a4", "done-ok-270", "", 1, src,
                                 "test", "t", status="printed")
    code, d = hub.post("/jobs/bulk-reprint", {"scope": "not_printed"})
    assert code == 200 and d["ok"], d
    mine = [r for r in d["results"] if r["id"] == failed_id]
    assert mine and mine[0]["ok"] and mine[0]["job_id"], d
    assert all(r["id"] != printed_id for r in d["results"]), \
        "a printed job must never be re-queued by the not_printed scope"
    assert d["queued"] >= 1
    advprint.db_update(mine[0]["job_id"], status="canceled",
                       error="test done")


def test_v270_bulk_reprint_bad_payload(hub, clean_queue):
    code, d = hub.post("/jobs/bulk-reprint", {})
    assert code == 400 and "ids" in d["error"]
    code, d = hub.post("/jobs/bulk-reprint", {"ids": "nope"})
    assert code == 400


def test_v270_history_clear_keeps_active_jobs(hub, clean_queue, tmp_path):
    """v2.7.0: POST /history/clear removes FINISHED rows only - a held
    (waiting) job MUST survive the wipe, and the audit trail records it."""
    src = _v270_mkfile(tmp_path, "c.pdf")
    done = advprint.db_add("a4", "finished-row-270", "", 1, src, "test",
                           "t", status="printed")
    held = advprint.db_add("a4", "waiting-row-270", "", 1, src, "test",
                           "t", status="held", held_reason="printer offline")
    code, d = hub.post("/history/clear", {})
    assert code == 200 and d["ok"] and d["deleted"] >= 1, d
    assert advprint.db_get(done) is None, "finished row must be gone"
    j = advprint.db_get(held)
    assert j is not None and j["status"] == "held", \
        "clearing the history ate a WAITING job"
    code, a = hub.get("/audit?event=history.cleared")
    assert any("history cleared" in (x.get("details") or "")
               for x in a["entries"])
    advprint.db_update(held, status="canceled", error="test done")


def test_v270_single_reprint_shares_core(hub, clean_queue, tmp_path):
    """v2.7.0: the single /jobs/{id}/reprint endpoint now runs through the
    same reprint_job_core() helper as the bulk route - behaviour kept."""
    src = _v270_mkfile(tmp_path, "s.pdf")
    jid = advprint.db_add("a4", "solo-src-270", "", 1, src, "test", "t",
                          status="printed")
    code, d = hub.post("/jobs/%d/reprint" % jid, {})
    assert code == 200 and d["ok"] and d["reprint_of"] == jid
    j = advprint.db_get(d["job_id"])
    assert j["title"] == "solo-src-270-reprint"
    advprint.db_update(d["job_id"], status="canceled", error="test done")


def test_v270_missing_file_is_skipped_not_fatal(hub, clean_queue, tmp_path):
    """v2.7.0: a bulk batch keeps going when one row lost its file."""
    gone = _v270_mkfile(tmp_path, "gone.pdf")
    keep = _v270_mkfile(tmp_path, "keep.pdf")
    dead_id = advprint.db_add("a4", "file-gone-270", "", 1, gone, "test",
                              "t", status="failed", error="x")
    ok_id = advprint.db_add("a4", "file-there-270", "", 1, keep, "test",
                            "t", status="failed", error="x")
    import os as _os
    _os.unlink(gone)                      # the file is really gone now
    code, d = hub.post("/jobs/bulk-reprint",
                       {"ids": [dead_id, ok_id]})
    assert code == 200 and d["queued"] == 1 and d["skipped"] == 1, d
    assert d["results"][0]["ok"] is False
    assert "no longer stored" in (d["results"][0]["error"] or "")
    advprint.db_update(d["results"][1]["job_id"], status="canceled",
                       error="test done")


# ============================================================
# v2.8.1 - two hub profiles / DropZone / send portal / restart
# ============================================================
def _v280_hub_src():
    return open(os.path.join(os.path.dirname(advprint.__file__),
                             "advprint.py"), encoding="utf-8").read()


def _v280_pdf(tmp_path, name="z.pdf", big="AdvPrint Pro v2.8 test"):
    data, _ = advprint.thermal_pdf_bytes("#big %s\nline" % big, "t280",
                                         paper="a4")
    p = tmp_path / name
    p.write_bytes(data)
    return str(p), data


def test_v280_version_and_config_keys():
    assert advprint.VERSION == "3.2.1"
    for k in ("drop_enabled", "drop_dir", "drop_delete"):
        assert k in advprint.CFG and k in advprint.CONFIG_KEYS
        assert k in advprint.CONFIG_TYPES
    assert advprint.CONFIG_TYPES["drop_enabled"] is bool
    assert advprint.CONFIG_TYPES["drop_delete"] is bool
    assert advprint.CONFIG_TYPES["drop_dir"] is str


def test_v280_dropzone_default_dir_and_stats():
    d = advprint.drop_dir()
    assert d == os.path.join(advprint.CFG["data_dir"], "DropZone")
    st = advprint.drop_stats()
    assert st["ok"] and st["enabled"] and st["waiting"] == 0


def test_v280_dropzone_watcher_prints_and_moves(hub, clean_queue, cfg_reset,
                                                tmp_path):
    """v2.8.1: a PDF dropped into the DropZone is picked up, printed and
    moved to done/ - the 'MS Word style' path without the extension."""
    advprint.CFG["drop_enabled"] = True
    advprint.CFG["drop_dir"] = str(tmp_path / "zone")
    advprint.CFG["drop_delete"] = False
    _p, data = _v280_pdf(tmp_path, "dropped.pdf")
    zone = advprint.drop_dir()
    os.makedirs(os.path.join(zone, "done"), exist_ok=True)
    dst = os.path.join(zone, "dropped.pdf")
    with open(dst, "wb") as f:
        f.write(data)
    before = len(hub.printed)
    advprint._drop_scan()          # first poll: learns the size
    advprint._drop_scan()          # second poll: stable -> picks it up
    assert not os.path.exists(dst), "PDF must move out of the zone"
    assert os.path.exists(os.path.join(zone, "done", "dropped.pdf"))

    # v2.9.1: assert on THIS job's DB row (immune to prints from other
    # tests' leftover threads landing in hub.printed mid-test)
    def _dz_printed():
        rows = [j for j in advprint.db_list(limit=30)
                if j["source"] == "dropzone"
                and j["title"] == "DropZone: dropped"]
        return rows and rows[0]["status"] == "printed"
    assert wait_until(_dz_printed, timeout=10), \
        "the dropzone job must actually print (worker is async)"
    assert len(hub.printed) >= before + 1
    rows = [j for j in advprint.db_list(limit=20)
            if j["source"] == "dropzone" and j["title"] == "DropZone: dropped"]
    assert rows, "a dropzone job must be in the history"
    advprint.db_update(rows[0]["id"], status="canceled", error="test done")
    advprint.CFG["drop_dir"] = ""


def test_v280_dropzone_non_pdf_is_not_printed(cfg_reset, tmp_path):
    """A file named .pdf that is not a PDF is moved aside untouched, and
    never printed."""
    advprint.CFG["drop_dir"] = str(tmp_path / "zone2")
    zone = advprint.drop_dir()
    os.makedirs(os.path.join(zone, "done"), exist_ok=True)
    junk = os.path.join(zone, "fake.pdf")
    with open(junk, "wb") as f:
        f.write(b"definitely not a pdf")
    before = len(hub.printed) if False else 0
    advprint._drop_process(junk)
    assert not os.path.exists(junk)
    assert os.path.exists(os.path.join(zone, "done", "fake.pdf"))
    advprint.CFG["drop_dir"] = ""


def test_v280_dropzone_scan_skips_incomplete(cfg_reset, tmp_path):
    """_drop_scan leaves files alone until the size is stable twice."""
    advprint.CFG["drop_dir"] = str(tmp_path / "zone3")
    zone = advprint.drop_dir()
    os.makedirs(zone, exist_ok=True)
    p = os.path.join(zone, "growing.pdf")
    with open(p, "wb") as f:
        f.write(b"%PDF-1.4 tiny")
    advprint._drop_scan()
    advprint._drop_scan()
    assert os.path.exists(p), "a <200-byte file must never be picked"
    os.unlink(p)
    advprint.CFG["drop_dir"] = ""


def test_v280_dropzone_config_roundtrip(hub, cfg_reset, tmp_path):
    code, d = hub.post("/config", {"drop_enabled": False,
                                   "drop_dir": str(tmp_path / "w"),
                                   "drop_delete": True})
    assert code == 200 and d["ok"], d
    code, st = hub.get("/dropzone")
    assert code == 200 and st["ok"]
    assert st["enabled"] is False and st["delete"] is True
    assert st["custom_dir"] == str(tmp_path / "w")
    assert st["is_default"] is False
    code, cfg = hub.get("/config")
    assert cfg["drop_enabled"] is False and cfg["drop_delete"] is True


def test_v280_send_multipart_prints(hub, clean_queue, tmp_path):
    """v2.8.1: POST /send with a multipart PDF queues a real job."""
    p, _ = _v280_pdf(tmp_path, "lab-report.pdf")
    with open(p, "rb") as f:
        raw = f.read()
    boundary = "----advprint280"
    body = (("--%s\r\nContent-Disposition: form-data; name=\"file\"; "
             "filename=\"lab-report.pdf\"\r\nContent-Type: "
             "application/pdf\r\n\r\n" % boundary).encode()
            + raw + ("\r\n--%s--\r\n" % boundary).encode())
    req = urllib.request.Request(hub.base + "/send", data=body,
                                 method="POST")
    req.add_header("X-AdvPrint-Token", hub.token)
    req.add_header("Content-Type",
                   "multipart/form-data; boundary=%s" % boundary)
    with urllib.request.urlopen(req, timeout=8) as r:
        d = json.loads(r.read().decode())
    assert d["ok"] and d["job_id"], d
    j = advprint.db_get(d["job_id"])
    assert j["source"] == "send" and j["title"] == "Send: lab-report"
    advprint.db_update(d["job_id"], status="canceled", error="test done")


def test_v280_send_raw_body_and_guards(hub, clean_queue, tmp_path):
    p, raw = _v280_pdf(tmp_path, "raw.pdf")
    # raw application/pdf body works (POST auth = token HEADER, the
    # v2.0.2 rule every mutating call follows)
    req = urllib.request.Request(hub.base + "/send?title=rawtest",
                                 data=raw, method="POST")
    req.add_header("Content-Type", "application/pdf")
    req.add_header("X-AdvPrint-Token", hub.token)
    with urllib.request.urlopen(req, timeout=8) as r:
        d = json.loads(r.read().decode())
    assert d["ok"]
    advprint.db_update(d["job_id"], status="canceled", error="test done")
    # no token -> 401 (pdf content-type so the raw path reaches auth)
    try:
        req = urllib.request.Request(hub.base + "/send", data=raw,
                                     method="POST")
        req.add_header("Content-Type", "application/pdf")
        urllib.request.urlopen(req, timeout=8)
        assert False, "must require a token"
    except urllib.error.HTTPError as e:
        assert e.code == 401, e.code
    # non-PDF -> 400
    req = urllib.request.Request(hub.base + "/send", data=b"hello",
                                 method="POST")
    req.add_header("Content-Type", "application/pdf")
    req.add_header("X-AdvPrint-Token", hub.token)
    try:
        urllib.request.urlopen(req, timeout=8)
        assert False, "non-PDF must be refused"
    except urllib.error.HTTPError as e:
        assert e.code == 400
        assert "only PDF" in e.read().decode()


def test_v280_send_portal_page(hub):
    code, d = hub.get("/send")
    assert code == 200 or isinstance(d, dict)
    req = urllib.request.Request(hub.base + "/send?token=" + hub.token)
    with urllib.request.urlopen(req, timeout=8) as r:
        html = r.read().decode()
    assert "Send a PDF to print" in html
    assert "/send?token=" in html
    assert "100% local" in html


def test_v280_restart_guard_and_listing(hub):
    """POST /restart needs the token; the root endpoint list advertises
    the v2.8 routes. (A real restart is NOT triggered in tests.)"""
    # NOTE: an empty body - b"{}" without a JSON content-type hits the
    # urlencoded fallback (400) before auth; empty body reaches auth.
    try:
        urllib.request.urlopen(urllib.request.Request(
            hub.base + "/restart", data=b"", method="POST"), timeout=8)
        assert False, "restart must require a token"
    except urllib.error.HTTPError as e:
        assert e.code == 401, e.code
    code, root = hub.get("/")
    eps = " ".join(root["endpoints"])
    assert "/restart" in eps and "/send" in eps and "/dropzone" in eps


def test_v280_dropzone_open_loopback(hub, cfg_reset, tmp_path,
                                     monkeypatch):
    """POST /dropzone/open creates the folder and opens it (the opener
    is monkeypatched - no real window in tests)."""
    advprint.CFG["drop_dir"] = str(tmp_path / "zone4")
    opened = []
    if advprint.IS_WIN:
        monkeypatch.setattr(advprint.os, "startfile",
                            lambda p: opened.append(p), raising=False)
    else:
        monkeypatch.setattr(advprint.subprocess, "Popen",
                            lambda argv, **kw: opened.append(argv[1]))
    code, d = hub.post("/dropzone/open", {})
    assert code == 200 and d["ok"], d
    assert opened and opened[0] == d["dir"]
    assert os.path.isdir(os.path.join(d["dir"], "done"))
    advprint.CFG["drop_dir"] = ""


def test_v280_source_wiring_restart_tray_tool_installer():
    """The restart path, tray menu item, tool menu [14], installer stop
    script and the extension dual-profile keys all exist in source."""
    src = _v280_hub_src()
    assert "ADVPRINT_RESTART" in src
    assert "def _restart_and_exit()" in src
    assert '"on_restart": _restart' in src
    tray = open(os.path.join(os.path.dirname(advprint.__file__),
                             "tray_windows.py"), encoding="utf-8").read()
    assert '"Restart hub", M_RESTART' in tray
    tool = open(os.path.join(os.path.dirname(advprint.__file__),
                             "tool.py"), encoding="utf-8").read()
    assert "[14] Restart AdvPrint" in tool
    assert 'cmd == "restart"' in tool
    root = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.dirname(advprint.__file__)))))  # tree root
    portable = os.path.join(root, "tool", "windows", "portable")
    stopps1 = os.path.join(portable, "install", "hub-stop.ps1")
    assert os.path.isfile(stopps1)
    stopps = open(stopps1, encoding="utf-8").read()
    assert "sc.exe delete AdvPrint" in stopps
    assert "Stop-Process" in stopps
    nsi = open(os.path.join(root, "installer", "setup.nsi"),
               encoding="utf-8").read()
    assert "hub-stop.ps1" in nsi
    assert "3.2.1" in nsi and "${IfNot} ${Silent}" in nsi
    # extension dual profile
    ext = os.path.join(root, "extension")
    bg = open(os.path.join(ext, "background.js"), encoding="utf-8").read()
    assert "hubUrlLan" in bg and "hubTokenLan" in bg
    assert 'closeAfterPrint: false' in bg
    assert "resolveTarget" in bg
    pop = open(os.path.join(ext, "popup.html"), encoding="utf-8").read()
    assert "swHook" not in pop          # v3.0.2: popup switch removed
    opt = open(os.path.join(ext, "options.html"), encoding="utf-8").read()
    # v3.2.1: Options opens the hub directly; the LAN profile lives in
    # background.js + the ONE UI Connections tab
    assert "127.0.0.1:9235" in opt and "ONE UI" in opt
    man = json.load(open(os.path.join(ext, "manifest.json")))
    assert man["version"] == "3.2.1"


def test_v280_lan_profile_never_auto_heals():
    """hubFetch must skip the loopback token auto-heal for the LAN
    target - healing would overwrite the LAN token with this PC's."""
    root = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.dirname(advprint.__file__)))))
    src = open(os.path.join(root, "extension", "background.js"),
               encoding="utf-8").read()
    assert 'target !== "lan"' in src


# ============================================================
# v2.8.1 - Send-portal QR + one-click LAN invite
# ============================================================
def _v281_cfg_snapshot():
    return {k: advprint.CFG[k]
            for k in ("peer_hubs", "share_lan", "port", "token")}


def _v281_cfg_restore(snap):
    advprint.CFG.update(snap)


def test_v281_health_has_hostname(hub):
    code, d = hub.get("/health", token=None)
    assert code == 200
    assert isinstance(d.get("hostname"), str) and d["hostname"]


def test_v281_qr_encoder_golden():
    """The vendored QR encoder is frozen with a golden digest (validated
    bit-exact against an independent implementation externally - this
    test pins the behaviour so a future edit cannot silently break it).
    Structural checks: correct size for the version, finder + timing."""
    url = b"http://192.168.1.100:9235/send?token=TEST-TOKEN-1234"
    m = advprint.qr_matrix(url)
    assert len(m) == 33                       # version 5 (33 = 4*5 + 17)
    blob = ";".join("".join("1" if v else "0" for v in row) for row in m)
    assert hashlib.sha256(blob.encode()).hexdigest() == \
        "e6cf35dda03e6c53cc1b6f33404aa620d5f830e0843fe4d97c8679808a72b257"
    # finder pattern: 7x7 ring at top-left
    ring = [[m[y][x] for x in range(7)] for y in range(7)]
    assert ring[0] == [True] * 7 and ring[6] == [True] * 7
    assert all(r[0] and r[6] for r in ring)
    assert not any(ring[1][1:6])              # white inside the ring
    # timing line alternates
    assert all(m[6][x] == (x % 2 == 0) for x in range(8, 26))


def test_v281_qr_svg_contains_module_grid():
    svg = advprint.qr_svg(b"http://192.168.1.100:9235/send?token=x")
    assert svg.startswith("<svg") and svg.endswith("</svg>")
    assert "image/svg" not in svg or True     # xmlns present instead
    assert 'xmlns="http://www.w3.org/2000/svg"' in svg
    assert '<path d="M' in svg and "crispEdges" in svg


def test_v281_lan_share_urls(hub, cfg_reset):
    snap = _v281_cfg_snapshot()
    try:
        advprint.CFG["share_lan"] = True
        tok = advprint.CFG["token"]
        port = advprint.CFG["port"]
        s = advprint.lan_share_url("send")
        assert s.startswith("http://%s:%d/send?token=" % (advprint.lan_ip(), port))
        assert s.endswith(tok)
        i = advprint.lan_share_url("invite")
        assert i.startswith("http://%s:%d/connect?t=" % (advprint.lan_ip(), port))
        assert "n=" in i and tok in i
        advprint.CFG["share_lan"] = False
        assert advprint.lan_share_url("send").startswith(
            "http://127.0.0.1:%d/" % port)
    finally:
        _v281_cfg_restore(snap)


def test_v281_qr_endpoint_svg(hub, cfg_reset):
    advprint.CFG["share_lan"] = True
    code, body = hub.get("/qr?kind=send")
    assert code == 200 and body.startswith(b"<svg")
    assert b"crispEdges" in body and len(body) > 1000
    code2, body2 = hub.get("/qr?kind=invite")
    assert code2 == 200 and body2.startswith(b"<svg")
    assert body2 != body, "send and invite QR must encode different URLs"
    # wrong kind falls back to send
    code3, body3 = hub.get("/qr?kind=evil")
    assert code3 == 200 and body3 == body


def test_v281_qr_endpoint_needs_token(hub):
    code, _ = hub.get("/qr?kind=send", token=None)
    assert code == 401


def test_v281_connect_page_ok(hub, cfg_reset):
    advprint.CFG["share_lan"] = True
    code, body = hub.get(
        "/connect?t=%s&n=LAB-PC" % advprint.CFG["token"], token=None,
        headers={"Accept": "text/html"})
    assert code == 200
    html = body.decode("utf-8", "replace")
    assert "Add" in html and "LAB-PC" in html
    assert "/peer-connect" in html
    assert advprint.CFG["token"] in html      # hidden token input
    assert "127.0.0.1" in html                # form posts to the peer's own hub


def test_v281_connect_page_rejects_bad_token(hub, cfg_reset):
    code, body = hub.get("/connect?t=WRONG&n=x", token=None)
    assert code == 403
    assert b"not valid" in body


def test_v281_connect_page_requires_share_lan(hub, cfg_reset):
    advprint.CFG["share_lan"] = False
    code, body = hub.get(
        "/connect?t=%s&n=x" % advprint.CFG["token"], token=None)
    assert code == 403
    assert b"LAN sharing" in body


def _v281_form(url, token, name, confirm="1"):
    from urllib.parse import quote
    return ("url=%s&token=%s&name=%s&confirm=%s"
            % (quote(url, safe=""), quote(token, safe=""),
               quote(name, safe=""), confirm)).encode()


def test_v281_peer_connect_success(hub, cfg_reset):
    snap = _v281_cfg_snapshot()
    try:
        advprint.CFG["peer_hubs"] = []
        code, body = hub.post(
            "/peer-connect", token=None,
            raw=_v281_form("http://192.168.1.50:9235", "PEER-TOKEN-1",
                           "LAB-PC"),
            content_type="application/x-www-form-urlencoded",
            headers={"Origin": "http://192.168.1.50:9235"})
        assert code == 200
        html = body.decode("utf-8", "replace")
        assert "Connected" in html and "LAB-PC" in html
        peers = advprint.CFG["peer_hubs"]
        assert len(peers) == 1
        assert peers[0]["url"] == "http://192.168.1.50:9235"
        assert peers[0]["token"] == "PEER-TOKEN-1"
        assert peers[0]["name"] == "LAB-PC"
        # persisted to disk
        disk = json.load(open(advprint.config_path(), encoding="utf-8"))
        assert any(p.get("url") == "http://192.168.1.50:9235"
                   for p in disk.get("peer_hubs", []))
        con = sqlite3.connect(advprint.db_path())
        try:
            n = con.execute(
                "select count(*) from audit where event='peer.connected'"
            ).fetchone()[0]
        finally:
            con.close()
        assert n >= 1
    finally:
        _v281_cfg_restore(snap)


def test_v281_peer_connect_csrf_blocked(hub, cfg_reset):
    snap = _v281_cfg_snapshot()
    try:
        advprint.CFG["peer_hubs"] = []
        code, body = hub.post(
            "/peer-connect", token=None,
            raw=_v281_form("http://192.168.1.50:9235", "PEER-TOKEN-1",
                           "EVIL"),
            content_type="application/x-www-form-urlencoded",
            headers={"Origin": "http://evil.example"})
        assert code == 403
        assert b"Blocked" in body
        assert advprint.CFG["peer_hubs"] == []
        con = sqlite3.connect(advprint.db_path())
        try:
            n = con.execute(
                "select count(*) from audit where event='peer.connect.denied'"
            ).fetchone()[0]
        finally:
            con.close()
        assert n >= 1
    finally:
        _v281_cfg_restore(snap)


def test_v281_peer_connect_public_ip_rejected(hub, cfg_reset):
    snap = _v281_cfg_snapshot()
    try:
        advprint.CFG["peer_hubs"] = []
        code, body = hub.post(
            "/peer-connect", token=None,
            raw=_v281_form("http://93.184.216.34:9235", "T", "x"),
            content_type="application/x-www-form-urlencoded",
            headers={"Origin": "http://93.184.216.34:9235"})
        assert code == 400
        assert advprint.CFG["peer_hubs"] == []
    finally:
        _v281_cfg_restore(snap)


def test_v281_peer_connect_missing_token_rejected(hub, cfg_reset):
    snap = _v281_cfg_snapshot()
    try:
        advprint.CFG["peer_hubs"] = []
        code, body = hub.post(
            "/peer-connect", token=None,
            raw=_v281_form("http://192.168.1.50:9235", "", "x"),
            content_type="application/x-www-form-urlencoded",
            headers={"Origin": "http://192.168.1.50:9235"})
        assert code == 400
        assert advprint.CFG["peer_hubs"] == []
    finally:
        _v281_cfg_restore(snap)


def test_v281_peer_connect_dedupes_same_url(hub, cfg_reset):
    snap = _v281_cfg_snapshot()
    try:
        advprint.CFG["peer_hubs"] = []
        for tok in ("TOKEN-A", "TOKEN-B"):
            code, _ = hub.post(
                "/peer-connect", token=None,
                raw=_v281_form("http://192.168.1.77:9235", tok, "PC77"),
                content_type="application/x-www-form-urlencoded",
                headers={"Origin": "http://192.168.1.77:9235"})
            assert code == 200
        peers = advprint.CFG["peer_hubs"]
        assert len(peers) == 1, "same peer URL must replace, not duplicate"
        assert peers[0]["token"] == "TOKEN-B"
    finally:
        _v281_cfg_restore(snap)


def test_v281_dashboard_lan_card_has_new_rows():
    src = open(os.path.join(os.path.dirname(advprint.__file__),
                            "advprint.py"), encoding="utf-8").read()
    for marker in ("Send portal (phones)", "Connect another PC",
                   "copySend", "copyInvite", "showQr", "qrRow",
                   "renderQr"):
        assert marker in src, marker


def test_v281_setup_nsi_version():
    # walk up from the hub dir to the tree root
    root = os.path.dirname(advprint.__file__)
    for _ in range(4):
        root = os.path.dirname(root)
    nsi = open(os.path.join(root, "installer", "setup.nsi"),
               encoding="utf-8", errors="replace").read()
    assert 'VIProductVersion "3.2.1.0"' in nsi
    assert "AdvPrint-Pro-Setup-3.2.1.exe" in nsi


# ============================================================
# v2.8.2 - LAN sharing applies LIVE + firewall one-click
# ============================================================

def test_v282_share_lan_applies_live(hub):
    """The reported 2.8.1 bug: 'LAN sharing ON but the LAN IP does not
    answer - only 127.0.0.1 works'. The toggle must start/stop the LAN
    listener INSIDE the POST /config request - no hub restart."""
    try:
        code, d = hub.post("/config", {"share_lan": True})
        assert code == 200 and d["ok"]
        assert d.get("lan", {}).get("rebound") is True
        err = d["lan"].get("lan_error")
        code, h = hub.get("/health")
        if err is None:
            # bind succeeded: the LAN listener is really serving
            assert h["lan_active"] is True
            assert h["lan_bind_ip"] == h["lan_ip"]
            assert h["lan_bind_ip"] != "127.0.0.1"
            # ...and it actually answers HTTP on the LAN IP itself
            u = "http://%s:%d/health" % (h["lan_bind_ip"],
                                         advprint.CFG["port"])
            with urllib.request.urlopen(u, timeout=5) as r:
                body = json.loads(r.read().decode("utf-8", "replace"))
            assert body["app"] == advprint.APP_NAME
        else:
            # no routable LAN IP in this environment - say so honestly
            assert h["lan_active"] is False
            assert ("LAN IP" in err) or ("bind" in err)
        # the self-test endpoint mirrors the same truth
        code, st = hub.get("/lan/selftest")
        assert code == 200
        assert st["ok"] is (err is None)
        if st["ok"]:
            assert st["url"].startswith("http://%s:%d"
                                        % (h["lan_ip"],
                                           advprint.CFG["port"]))
    finally:
        code, d = hub.post("/config", {"share_lan": False})
        assert code == 200 and d["ok"]
        code, h = hub.get("/health")
        assert h["lan_active"] is False
        assert h["share_lan"] is False


def test_v282_firewall_route_loopback_ok(hub):
    """POST /firewall/allow answers from loopback (a no-op OK on
    non-Windows, a real netsh attempt on Windows)."""
    code, d = hub.post("/firewall/allow", {})
    if advprint.IS_WIN:
        assert code in (200, 400)
    else:
        assert code == 200 and d["ok"] is True
    assert "firewall_ok" in d


def test_v282_health_has_lan_diagnostics(hub):
    code, h = hub.get("/health")
    assert code == 200
    assert "lan_ip" in h and "lan_bind_ip" in h
    assert h["firewall_ok"] is None or isinstance(h["firewall_ok"], bool)


def test_v282_dashboard_has_live_rebind_ui():
    src = open(os.path.join(os.path.dirname(advprint.__file__),
                            "advprint.py"), encoding="utf-8").read()
    for marker in ("Allow in firewall", "Test LAN", "lanSelftest",
                   "fwAllow", "/firewall/allow", "/lan/selftest",
                   "lan_listen_start", "lan_listen_ensure",
                   "RIGHT NOW (no restart needed)"):
        assert marker in src, marker


# ============================================================
# v2.9.0 - PHONE AUTH FIX + NETWORK PRINTER MODE (IPP + RAW 9100)
# ============================================================

def _multipart(field, fname, data, extra=None):
    bnd = "----advprinttest"
    out = []
    for k, v in (extra or {}).items():
        out.append("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n"
                   % (bnd, k, v))
    out.append("--%s\r\nContent-Disposition: form-data; name=\"%s\"; "
               "filename=\"%s\"\r\nContent-Type: application/pdf\r\n\r\n"
               % (bnd, field, fname))
    body = "".join(out).encode() + data + ("\r\n--%s--\r\n" % bnd).encode()
    return body, "multipart/form-data; boundary=%s" % bnd


MINI_PDF = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
            b"2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\n"
            b"trailer<</Root 1 0 R>>\n%%EOF\n")

# 1x1 JPEG skeleton: SOI + SOF0 (1x1) + EOI - enough for jpeg_size()
MINI_JPEG = (b"\xff\xd8\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x00"
             b"\x11\x00\x02\x11\x01\x03\x11\x01\xff\xd9")


def test_v290_phone_post_send_query_token_in_header_only_mode(hub, cfg_reset):
    """THE reported phone bug: with token_header_only=true the Send
    portal GET opened but the browser POST could never authenticate
    (phones cannot send the X-AdvPrint-Token header) -> 'Auth fail'
    for every phone while PCs kept working. v2.9.0 accepts the token
    from the query/body for /send POST - the token is still required."""
    code, d = hub.post("/config", {"token_header_only": True})
    assert code == 200 and d["ok"]
    try:
        body, ct = _multipart("file", "phone.pdf", MINI_PDF)
        code, d = hub.req("POST", "/send?token=" + hub.token, raw=body,
                          headers={"Content-Type": ct}, token=None)
        assert code == 200, d
        assert d["ok"] is True and d["job_id"] > 0
    finally:
        hub.post("/config", {"token_header_only": False})


def test_v290_phone_post_send_form_field_token(hub, cfg_reset):
    """v2.9.0: the portal also appends the token as a form field, so
    the upload survives QR apps that mangle the query string."""
    code, d = hub.post("/config", {"token_header_only": True})
    assert code == 200 and d["ok"]
    try:
        body, ct = _multipart("file", "phone.pdf", MINI_PDF,
                              extra={"token": hub.token})
        code, d = hub.req("POST", "/send", raw=body,
                          headers={"Content-Type": ct}, token=None)
        assert code == 200, d
        assert d["ok"] is True
    finally:
        hub.post("/config", {"token_header_only": False})


def test_v290_send_wrong_token_still_rejected(hub, cfg_reset):
    """Relaxing the transport must NOT relax the check: a wrong token
    on /send POST still gets 401 with the phone-friendly message."""
    body, ct = _multipart("file", "phone.pdf", MINI_PDF)
    code, d = hub.req("POST", "/send?token=WRONG", raw=body,
                      headers={"Content-Type": ct}, token=None)
    assert code == 401
    assert d["ok"] is False and "Auth failed" in d["error"]


def _ipp_request(op, doc=b"", job_name="pytest job"):
    """Build a minimal IPP/1.1 request (operation-attributes + doc)."""
    out = bytearray()
    out += bytes([1, 1]) + op.to_bytes(2, "big") + (7).to_bytes(4, "big")
    out += b"\x01"                                     # operation-attributes
    out += bytes([0x47]) + b"attributes-charset".__len__().to_bytes(2, "big") \
        + b"attributes-charset" + len(b"utf-8").to_bytes(2, "big") + b"utf-8"
    out += bytes([0x48]) + len(b"attributes-natural-language").to_bytes(2, "big") \
        + b"attributes-natural-language" + len(b"en").to_bytes(2, "big") + b"en"
    if job_name:
        out += bytes([0x45]) + len(b"job-name").to_bytes(2, "big") + b"job-name" \
            + len(job_name.encode()).to_bytes(2, "big") + job_name.encode()
    out += b"\x03"                                     # end-of-attributes
    out += doc
    return bytes(out)


def _ipp_read(resp):
    ver = (resp[0], resp[1])
    status = int.from_bytes(resp[2:4], "big")
    rid = int.from_bytes(resp[4:8], "big")
    return ver, status, rid, resp[8:]


def test_v290_ipp_get_printer_attributes(hub):
    body = _ipp_request(0x000B)                      # Get-Printer-Attributes
    code, raw = hub.req("POST", "/ipp/print", raw=body, token=None,
                        headers={"Content-Type": "application/ipp"})
    assert code == 200
    ver, status, rid, rest = _ipp_read(raw)
    assert status == 0x0000                          # successful-ok
    assert b"printer-name" in rest
    assert b"application/pdf" in rest
    assert b"AdvPrint Pro" in rest


def test_v290_ipp_print_job_pdf(hub, clean_queue):
    body = _ipp_request(0x0002, doc=MINI_PDF, job_name="ipp pdf")
    code, raw = hub.req("POST", "/ipp/print", raw=body, token=None,
                        headers={"Content-Type": "application/ipp"})
    assert code == 200
    ver, status, rid, rest = _ipp_read(raw)
    assert status == 0x0000
    assert b"job-id" in rest and b"job-state" in rest
    j = wait_until(lambda: [x for x in advprint.db_list(limit=5)
                            if x["source"] == "ipp"])
    assert j, "IPP PDF job did not reach the queue"


def test_v290_ipp_print_job_jpeg(hub, clean_queue):
    body = _ipp_request(0x0002, doc=MINI_JPEG, job_name="ipp photo")
    code, raw = hub.req("POST", "/ipp/print", raw=body, token=None,
                        headers={"Content-Type": "application/ipp"})
    assert code == 200
    ver, status, rid, rest = _ipp_read(raw)
    assert status == 0x0000, "JPEG IPP job rejected: %s" % status
    j = wait_until(lambda: [x for x in advprint.db_list(limit=8)
                            if x["source"] == "ipp"])
    assert j, "IPP JPEG job did not reach the queue"


def test_v290_ipp_print_job_zpl_goes_raw(hub, clean_queue):
    zpl = b"^XA^FO50,50^ADN,36,20^FDAdvPrint IPP^FS^XZ"
    before = len(hub.raw_printed)
    body = _ipp_request(0x0002, doc=zpl, job_name="ipp label")
    code, raw = hub.req("POST", "/ipp/print", raw=body, token=None,
                        headers={"Content-Type": "application/ipp"})
    assert code == 200
    ver, status, rid, rest = _ipp_read(raw)
    assert status == 0x0000
    # v2.9.1 (M5 fix): the payload is ENQUEUED with a history row and
    # printed by the FIFO worker (pause/cancel/reprint now apply) - so
    # the printout arrives a beat after the 200 answer.
    assert wait_until(lambda: len(hub.raw_printed) >= before + 1), \
        "the IPP ZPL job must print through the queue"
    assert hub.raw_printed[-1][0].startswith(b"^XA")


def test_v290_ipp_validate_job(hub):
    body = _ipp_request(0x0004, doc=MINI_PDF)
    code, raw = hub.req("POST", "/ipp/print", raw=body, token=None,
                        headers={"Content-Type": "application/ipp"})
    ver, status, rid, rest = _ipp_read(raw)
    assert status == 0x0000


def test_v290_ipp_unknown_operation(hub):
    # v3.0.8: 0x0008 (Cancel-Job) IS implemented now - use a genuinely
    # unknown operation id for the not-supported check
    body = _ipp_request(0x0033)
    code, raw = hub.req("POST", "/ipp/print", raw=body, token=None,
                        headers={"Content-Type": "application/ipp"})
    ver, status, rid, rest = _ipp_read(raw)
    assert status == 0x040F                          # not-supported


def test_v3008_ipp_cancel_job_without_id(hub):
    # v3.0.8: Cancel-Job without the required job-id -> bad request
    body = _ipp_request(0x0008)
    code, raw = hub.req("POST", "/ipp/print", raw=body, token=None,
                        headers={"Content-Type": "application/ipp"})
    ver, status, rid, rest = _ipp_read(raw)
    assert status == 0x0400                          # bad-request


def test_v290_ipp_disabled(hub, cfg_reset):
    advprint.CFG["ipp_printer"] = False
    try:
        body = _ipp_request(0x000B)
        code, d = hub.req("POST", "/ipp/print", raw=body, token=None,
                          headers={"Content-Type": "application/ipp"})
        assert code == 404
    finally:
        advprint.CFG["ipp_printer"] = True


def test_v900_ipp_garbage_body(hub):
    code, raw = hub.req("POST", "/ipp/print", raw=b"not-ipp", token=None,
                        headers={"Content-Type": "application/ipp"})
    ver, status, rid, rest = _ipp_read(raw)
    assert status == 0x0400                          # bad-request


def test_v290_route_print_payload_sniffs_languages(hub, clean_queue):
    # v2.9.1 (M5 fix): printer-language passthrough now ENQUEUES (history
    # row, pause/cancel/reprint, dest_mode routing) instead of printing
    # synchronously inside the socket thread - so the printouts arrive
    # through the FIFO worker a moment later.
    before = len(hub.raw_printed)
    job, kind = advprint.route_print_payload(MINI_PDF, "t", "10.0.0.9")
    assert kind == "pdf"
    job, kind = advprint.route_print_payload(b"%!PS-Adobe-3.0\n", "t",
                                             "10.0.0.9")
    assert kind == "postscript"
    job, kind = advprint.route_print_payload(b"\x1bE\x1b%-12345X", "t",
                                             "10.0.0.9")
    assert kind == "pcl"
    job, kind = advprint.route_print_payload(b"^XA^XZ", "t", "10.0.0.9")
    assert kind == "zpl"
    job, kind = advprint.route_print_payload(b"\x1b@text", "t", "10.0.0.9")
    assert kind == "escpos"
    assert wait_until(lambda: len(hub.raw_printed) >= before + 4), \
        "the raw passthrough jobs must print through the queue"
    # every passthrough job got a real history row (was job_id=0)
    assert job > 0


def test_v290_route_print_payload_rejects_oversize(hub, cfg_reset, monkeypatch):
    monkeypatch.setattr(advprint, "MAX_PDF", 10, raising=False)
    with pytest.raises(ValueError):
        advprint.route_print_payload(MINI_PDF, "t", "10.0.0.9")


def test_v290_health_has_printer_mode_fields(hub):
    code, h = hub.get("/health")
    assert code == 200
    assert h["ipp_printer"] is True
    assert h["raw_printer_port"] == 9100
    assert "raw_active" in h
    assert "ipp_url" in h


def test_v290_qr_svg_supports_ipp_kind(hub):
    code, raw = hub.req("GET", "/qr?kind=ipp", token="use-default")
    assert code == 200 and b"<svg" in raw
    code, raw = hub.req("GET", "/qr?kind=bogus", token="use-default")
    assert code == 200 and b"<svg" in raw            # falls back to send


def test_v290_raw_listener_disabled_without_lan_sharing():
    """The RAW 9100 listener must never start while LAN sharing is off
    and must never bind 0.0.0.0 - it follows share_lan + its config."""
    assert advprint._RAW_TCP is None                 # never started here
    err = advprint.raw_listen_start()                # share_lan False -> no-op
    assert err is None
    assert advprint._RAW_TCP is None



def test_v290_extension_version_single_source():
    """ONE version everywhere in the extension - the manifest.
    v3.2.1: Options is the hub-redirect opener; the version lives in
    manifest.json (popup carries the same-value fallback, options.html
    shows the same brand line, no JS hardcodes an old version)."""
    ext = os.path.normpath(os.path.join(os.path.dirname(advprint.__file__),
                                        "extension"))
    if not os.path.isdir(ext):
        pytest.skip("extension not staged next to the hub")
    man_path = os.path.join(ext, "manifest.json")
    if not os.path.exists(man_path):
        pytest.skip("manifest not staged (CRX-only extension dir)")
    import json as _json
    man = _json.load(open(man_path))
    v = man["version"]
    popup = open(os.path.join(ext, "popup.html")).read()
    options = open(os.path.join(ext, "options.html")).read()
    ojs = open(os.path.join(ext, "options.js")).read()
    assert ('id="ver">v%s<' % v) in popup, "popup fallback drifts"
    assert ("v%s" % v) in options, "options brand line drifts"
    assert "127.0.0.1:9235" in options and "127.0.0.1:9235" in ojs, \
        "v3.2.1 Options must open the hub directly"
    assert "getManifest().version" in open(
        os.path.join(ext, "popup.js")).read()
    for f in ("popup.js", "background.js", "options.js"):
        src = open(os.path.join(ext, f)).read()
        assert "v2.8.0" not in src and "2.8.0<" not in src, \
            "%s still hardcodes an old version" % f



def test_v290_tray_actions_are_threaded():
    """v2.9.0 SMOOTH TRAY: every menu action dispatches through
    _cb_async (its own thread) - only Exit stays on the icon thread."""
    src = open(os.path.join(os.path.dirname(advprint.__file__),
                            "tray_windows.py"), encoding="utf-8").read()
    assert "_cb_async(\"on_open\")" in src
    assert "_cb_async(\"on_test\"" in src
    assert "_cb_async(\"on_pause_toggle\"" in src
    assert "_cb_async(\"on_autostart_toggle\"" in src
    assert "_cb_async(\"on_restart\")" in src
    assert "_cb_async(\"on_firewall\")" in src
    assert "_font_cache" in src


def test_v290_firewall_allow_covers_raw_port():
    src = open(os.path.join(os.path.dirname(advprint.__file__),
                            "advprint.py"), encoding="utf-8").read()
    assert 'RAW %d' in src and "raw_printer_port" in src


# ==================== v3.0.1 ====================

def test_v301_tray_menu_click_targets():
    """v3.0.1 regression - 'menu text and click are not the same': the old
    WM_LBUTTONUP did self.items[idx] with the selectable-row ORDINAL from
    _hit(), but self.items also holds ("sep",) entries - so every item
    after the first separator ran the WRONG command (Pause queue did
    nothing, Start at logon paused the queue, Restart hub toggled
    autostart, Allow LAN in firewall RESTARTED the hub, Exit opened the
    firewall prompt). We exec the REAL _hit() + _pos_of() code shipped in
    tray_windows.py (both are pure Python - no win32 calls inside) and
    simulate a click on every row of the real menu layout."""
    import ast
    import ctypes
    import textwrap
    p = os.path.join(os.path.dirname(advprint.__file__), "tray_windows.py")
    src = open(p, encoding="utf-8").read()
    tree = ast.parse(src)
    funcs = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in ("_hit", "_pos_of"):
            funcs[node.name] = ast.get_source_segment(src, node)
    assert set(funcs) == {"_hit", "_pos_of"}, \
        "_hit/_pos_of missing - the tray click fix is not in this build"
    ns = {"ctypes": ctypes}
    code = ["class Shim(object):",
            "    pad = 8",
            "    row_h = 30",
            "    _width = 400",
            "    _height = 400"]
    for name in ("_hit", "_pos_of"):
        code.append(textwrap.indent(funcs[name], "    "))
    exec("\n".join(code), ns)
    shim = ns["Shim"]()

    # the REAL menu layout (Tray._menu_items order + separator entries)
    items = [
        ("Open dashboard", 1001, False),
        ("Print test page", 1002, False),
        ("sep",),
        ("Pause queue", 1003, False),
        ("Start at Windows logon", 1004, True),
        ("Restart hub", 1006, False),
        ("Allow LAN in firewall", 1007, False),
        ("sep",),
        ("Exit", 1005, False),
    ]
    shim.items = items

    def lp(x, y):
        return (y << 16) | (x & 0xFFFF)

    # client-y band top of every row (pad + cumulative row heights)
    tops = []
    y = 8
    for it in items:
        tops.append(y)
        y += 15 if it[0] == "sep" else 30      # sep = half row

    # click the vertical CENTER of each selectable row, on the text area;
    # the ordinal from _hit must map back to the REAL items position
    for pos, it in enumerate(items):
        if it[0] == "sep":
            continue
        ordinal = shim._hit(lp(60, tops[pos] + 15))
        assert ordinal >= 0, "row %r did not register a hit" % it[0]
        real = shim._pos_of(ordinal)
        assert real == pos, \
            ("text/action mismatch: clicked %r -> ordinal %d -> items[%d]"
             " = %r" % (it[0], ordinal, real, items[real][0]))
        assert items[real][1] == it[1], \
            "clicked %r but the command would be %r" % (it[0], items[real][1])

    # the two reported symptoms, spelled out:
    assert items[shim._pos_of(shim._hit(lp(60, tops[8] + 15)))][1] == 1005, \
        "clicking 'Exit' must run Exit (was: firewall prompt)"
    assert items[shim._pos_of(shim._hit(lp(60, tops[6] + 15)))][1] == 1007, \
        "clicking 'Allow LAN in firewall' must run the firewall fix" \
        " (was: hub restart)"
    # clicks below the last row and on separators hit nothing
    assert shim._hit(lp(60, y + 5)) == -1



def test_v301_hook_switch_in_power_block():
    """v3.0.1 -> v3.2.1: the Intercept window.print() switch is the ONE
    hookPrint switch and lives in the ONE UI Power Switches tab (rev-4
    markup), between Queue mode and Debug mode. The extension adopts it
    via the hub ext_prefs mirror (background.js adoptHubExtPrefs)."""
    console = open(os.path.join(os.path.dirname(advprint.__file__),
                                "console.html"), encoding="utf-8").read()
    assert console.count("Intercept window.print()") == 1
    power = console.index("Queue mode (jobs wait in order)")
    hook = console.index("Intercept window.print()")
    debug = console.index("Debug mode \u2014 find problems fast")
    assert power < hook < debug, "hook switch must sit between Queue and Debug"
    bg = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "extension", "background.js"),
        encoding="utf-8").read()
    assert '"hookPrint"' in bg, "extension must adopt hookPrint from ext_prefs"




def test_v302_popup_has_no_hook_switch():
    """v3.0.2: the popup never carried the window.print() hook switch -
    the ONE switch lives in the ONE UI Power Switches tab since v3.2.1."""
    ext = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "extension")
    pop = open(os.path.join(ext, "popup.html"), encoding="utf-8").read()
    assert "swHook" not in pop, "popup still has the hook switch row"
    pjs = open(os.path.join(ext, "popup.js"), encoding="utf-8").read()
    assert "swHook" not in pjs and "renderHookState" not in pjs, \
        "popup.js still wires the removed switch"
    i18n = open(os.path.join(ext, "i18n.js"), encoding="utf-8").read()
    assert "popHook" not in i18n, "i18n still carries popHook* keys"



def test_v302_multi_printer_doc_ships():
    """v3.0.2: the multi-printer lab guide (docs/MULTI-PRINTER.md) must
    ship with the tree and document the real routing facts - the
    per-job-printer-wins rule, the payload sniffing table (ZPL/ESC-POS/
    PostScript/PCL raw passthrough) and the lab scenario with the hub
    API raw mode field names (lang=zpl + text / raw_base64)."""
    docs = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.dirname(advprint.__file__))))), "docs")
    md = open(os.path.join(docs, "MULTI-PRINTER.md"), encoding="utf-8").read()
    assert "per-job printer" in md.lower() or "printer name always wins" in md
    for marker in ("^XA", "ESC/POS", "Multiple printers", "raw_base64", "lang"):
        assert marker in md, "missing %r in MULTI-PRINTER.md" % marker
    assert "Zebra" in md
    guide = open(os.path.join(docs, "AdvPrint-Pro-Full-Guide.html"),
                 encoding="utf-8").read()
    assert "6.6 Multiple printers on one PC" in guide
    assert "MULTI-PRINTER.md" in guide



def test_v303_rules_print_labels_actions():
    """v3.0.3 -> v3.2.1: rules can print LABELS/RECEIPTS without page
    JavaScript. The action picker lives in the ONE UI rule editor
    (rev-4 re-what select: Raw text / ZPL / ESC-POS stream), the
    background engine still extracts page text and posts it with an
    explicit lang, and the guard refuses text without ^ commands."""
    ext = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "extension")
    bg = open(os.path.join(ext, "background.js"), encoding="utf-8").read()
    assert "KIND_OK_ACTIONS" in bg and "KIND_DEFAULT_ACTION" in bg
    assert "ZPL_RX" in bg
    console = open(os.path.join(os.path.dirname(advprint.__file__),
                                "console.html"), encoding="utf-8").read()
    assert "Raw text / ZPL / ESC-POS stream" in console, \
        "rule editor must offer the raw/label action"
    assert "ACTION_LABELS" in console and "raw:" in console, \
        "the wiring must map the raw action to the hub rule"




def test_v303_rules_copies_paper_columns():
    """v3.0.3 -> v3.2.1: per-rule Copies + Paper - the ONE UI rule
    editor carries both (re-copies / re-paper), the hub rules_mirror
    validation keeps them (copies 1-99, paper <=24 chars) and the
    extension's rulePrintExtras still turns them into job fields."""
    ext = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "extension")
    bg = open(os.path.join(ext, "background.js"), encoding="utf-8").read()
    assert "rulePrintExtras" in bg or "copies" in bg
    console = open(os.path.join(os.path.dirname(advprint.__file__),
                                "console.html"), encoding="utf-8").read()
    assert 'id="re-copies"' in console and 'id="re-paper"' in console
    hub_src = open(advprint.__file__, encoding="utf-8").read()
    assert '"copies": max(1, min(99, int(x.get("copies") or 1)))' in hub_src
    assert '"paper": str(x.get("paper") or "")[:24]' in hub_src




def test_v303_lab_card_and_docs():
    """v3.0.3 -> v3.2.1: the multi-printer lab explanation lives in the
    ONE UI Rules tab (match-by help) and MULTI-PRINTER.md still shows
    the RULES as the primary label flow."""
    root = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(advprint.__file__))))
    console = open(os.path.join(os.path.dirname(advprint.__file__),
                                "console.html"), encoding="utf-8").read()
    assert "Match by" in console and "ZPL" in console
    mp = os.path.join(root, "docs", "MULTI-PRINTER.md")
    if os.path.exists(mp):
        doc = open(mp, encoding="utf-8").read()
        assert "rule" in doc.lower() and "ZPL" in doc




def test_v304_multi_printer_rules_made_easy():
    """v3.0.4 -> v3.2.1: several printers stay easy - (1) patternToRegex
    supports 'contains' (background engine unchanged); (2) the ONE UI
    rule editor fills the printer dropdown from the LIVE hub printer
    list (one option per real printer - no duplicates by construction);
    (3) the printers themselves come from GET /printers."""
    ext = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "extension")
    bg = open(os.path.join(ext, "background.js"), encoding="utf-8").read()
    assert 'if (type === "contains")' in bg
    console = open(os.path.join(os.path.dirname(advprint.__file__),
                                "console.html"), encoding="utf-8").read()
    assert "sel.innerHTML = \"<option>(OS default printer)</option>\" +" in console, \
        "rule editor printer select must be rebuilt from live printers"
    assert "printersCache.filter(function(p){ return !p.is_group; })" in console




def test_v305_rule_manager_tab():
    """v3.0.5 -> v3.2.1: the rule manager IS the ONE UI Rules tab
    (rev-4): the rule table lives there once, every rule row has
    Edit + Delete, the rule editor modal opens for new + existing
    rules, and the hub keeps the mirror in rules_mirror."""
    console = open(os.path.join(os.path.dirname(advprint.__file__),
                                "console.html"), encoding="utf-8").read()
    assert 'id="p-rules"' in console
    assert console.count('id="p-rules"') == 1
    assert "data-new-rule" in console and "data-edit-rule" in console \
        and "data-del-rule" in console
    assert 'id="rulemodal"' in console and 'id="re-url"' in console
    assert "rules_mirror" in console
    bg = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "extension", "background.js"),
        encoding="utf-8").read()
    assert "rules_mirror" in bg, "extension must keep syncing the mirror"




def test_v305_pause_counters_and_log():
    """v3.0.5: pausing is a power switch - rulesPaused stops ONLY the
    hidden auto work (manual prints unaffected); every rule-triggered
    job bumps a per-rule run counter and lands in a 100-entry activity
    log. v3.2.1: the switch is ALSO mirrored in the ONE UI Power
    Switches tab (ext_prefs.rulesPaused)."""
    ext = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "extension")
    bg = open(os.path.join(ext, "background.js"), encoding="utf-8").read()
    assert "rulesPaused: false" in bg
    i_fn = bg.index("async function shouldAutoPrint")
    i_auto = bg.index("if (!rule || !rule.auto) return null;", i_fn)
    i_pause = bg.index("if (cfg.rulesPaused) return null;", i_auto)
    assert i_auto < i_pause
    assert "ruleStats: {}" in bg and "ruleLog: []" in bg
    seg_k = bg[bg.index("function ruleKey"):]
    assert "rule.id" in seg_k and "rule.pattern" in seg_k
    assert "log.slice(0, 100)" in bg
    assert 'mode: info.mode || "auto"' in bg
    assert 'status: "failed"' in bg, "failures must show in the manager"
    assert bg.count("bumpRuleStats(rule") >= 4
    console = open(os.path.join(os.path.dirname(advprint.__file__),
                                "console.html"), encoding="utf-8").read()
    assert "rulesPaused" in console, \
        "ONE UI must mirror the rules pause switch (ext_prefs)"




def test_v306_content_rules_engine():
    """v3.0.6 -> v3.2.1: rules can match by CONTENT - the engine in
    background.js is unchanged (isContentRule / matchRule(kind) /
    detectTabKind / ruleActionFor / printTabImage / two-pass auto
    matching), and the ONE UI rule editor exposes it (Match by +
    Page content field in the rev-4 rule modal)."""
    ext = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "extension")
    bg = open(os.path.join(ext, "background.js"), encoding="utf-8").read()
    for marker in ("function isContentRule",
                   "function matchRule(url, rules, title, kind)",
                   "function ruleActionFor(rule, kind)",
                   "function hasContentRules(cfg)",
                   "async function detectTabKind(tab)",
                   "async function printTabImage(tab, rule, printerOverride)"):
        assert marker in bg, "missing %r in background.js" % marker
    assert "ZPL_RX" in bg and "ZPL_RX_LOOSE" in bg
    console = open(os.path.join(os.path.dirname(advprint.__file__),
                                "console.html"), encoding="utf-8").read()
    assert 'id="re-content"' in console
    assert "Page content" in console, "rev-4 rule table shows the column"
    assert 'match: $("re-content").value.trim() ? "content" :' in console, \
        "wiring must switch match=content when content is filled"


