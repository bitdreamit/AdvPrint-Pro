"""AdvPrint Pro v2.0.1 - pytest suite (pure stdlib hub, no real printer).

Covers the 22 feature areas: security (random token, header-only, origins,
SSRF guard, lockout + v2.0.1 loopback exemption, rotate), printer (status,
groups, raw ESC/POS+ZPL, profiles, page ranges), queue (retry, priority,
dedupe, schedule, dead-letter, peers), audit (log, reason, watermark, CSV,
diagnostics, dashboard) plus repo sanity (version anchors, migrations).
"""
import base64
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
    assert d["version"] == "2.6.8"
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
    assert code == 200 and b"success rate" in body


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
    assert advprint.VERSION == "2.6.8"
    # repo/package layout: tool/windows/portable/hub -> root/extension
    root = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.dirname(advprint.__file__)))))
    ext = os.path.join(root, "extension", "manifest.json")
    with open(ext) as f:
        assert json.load(f)["version"] == "2.6.8"


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
    assert code == 200 and d["status"] == "printing"


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
    code, d = hub.post("/print", {"text": "paused job", "title": "p1"})
    jid = d["job_id"]
    hub.post("/queue/pause", {})
    try:
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
    assert d["app"] == "AdvPrint Pro" and d["version"] == "2.6.8"


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
    assert advprint.VERSION == "2.6.8"
    assert advprint.VERSION_NAME.startswith("v2.6.8")


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
    assert "Choose [0-13]" in src
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
    assert "taskkill /F /IM AdvPrintPro.exe" in src
    assert "taskkill /F /IM PrintHubPro.exe" in src
    assert 'VIProductVersion "2.6.8.0"' in src


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
