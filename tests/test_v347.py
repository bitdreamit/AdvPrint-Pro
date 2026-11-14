"""v3.4.7 - CONFIGURABLE HUB PORT + DROPZONE WATCH FIX + STRICT LAN
SHARE + URL RULES THAT REALLY MATCH + CLEAN UI NOTES.

The user said "current work fine" and asked for the next version with
five items; every item is locked here:

 1. THE HUB PORT IS CONFIGURABLE - "port hub bu default 9235 but user
    can also change hub port to dynamic any port set ... needed if any
    pc has olready exist same port for diffrent software"
      - "port" is a real config key (CONFIG_KEYS / CONFIG_TYPES)
      - POST /config validates 1024-65535, refuses 631/5353/9100,
        answers restart:true + note on a real change
      - init_config: ADVPRINT_PORT env wins over config.json
      - the ONE UI Settings HUB PORT row really saves now
      - the boot bind-failure log names every way to move the hub

 2. DROPZONE WATCH FIX - "alwase disable dropzone watch off when click
    to open": the ONE UI p-head button was a static "Disable" that
    ALWAYS posted drop_enabled:false. Now it is a real Enable/Disable
    toggle bound by id that posts the OPPOSITE of the live state.

 3. STRICT LAN SHARE - "show which ip hit this printer all diffrent
    hited ip show here then hit add allow list": lan_strict records
    every distinct client IP (allowed or refused) while ON;
    GET /lan/hits lists them, POST /lan/allow moves one into
    allowed_ips (first add replaces "*" = lock-down), /lan/hits/clear
    resets. The gate itself denies exactly as before.

 4. URL RULES THAT REALLY MATCH - the hub KEEPS the rule "type" field
    (glob / regex / contains) it used to strip; a server-side mirror of
    the extension matcher powers POST|GET /rules/test; the ONE UI
    editor has a type select + the htncr.org recipes; the Test box is
    wired. The four lab recipes behave exactly as the user described:
    single tests[] id -> its printer, multi-id -> NO rule (OS default
    A4), /lab/sample/<id> -> Zebra, /lab/receipt-print/<id>/<role> ->
    the A5 printer.

 5. NO VERSION PREFIXES IN UI NOTES - "v2.8 ·", "v3.2.6 ·", "- v2.2:"
    etc. are gone from the ONE UI subs/notes and the dashboard titles.
"""
import json
import os

import pytest

import advprint

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CONSOLE = advprint.CONSOLE_HTML
DASHBOARD = advprint.DASHBOARD_HTML

U1 = "https://www.htncr.org/lab/medical_reports/pdf/203182?tests%5B%5D=671839"
U2 = ("https://www.htncr.org/lab/medical_reports/pdf/203182"
      "?tests%5B%5D=671843&tests%5B%5D=671840&tests%5B%5D=671841")
U3 = "https://www.htncr.org/lab/sample/203182"
U4 = "https://www.htncr.org/lab/receipt-print/203695/client"
U4B = "https://www.htncr.org/lab/receipt-print/203695/admin"

RECIPES = [
    {"id": 1, "name": "Single-test report",
     "pattern": r"htncr\.org/lab/medical_reports/pdf/\d+\?tests%5B%5D=\d+$",
     "type": "regex", "printer": "Report Printer", "action": "web",
     "on": True, "match": "url"},
    {"id": 2, "name": "Sample label ZPL",
     "pattern": r"htncr\.org/lab/sample/\d+$",
     "type": "regex", "printer": "Zebra ZPL", "action": "raw",
     "on": True, "match": "url"},
    {"id": 3, "name": "Receipt A5",
     "pattern": r"htncr\.org/lab/receipt-print/\d+/(client|all|lab|admin)$",
     "type": "regex", "printer": "Receipt A5", "action": "web",
     "on": True, "match": "url"},
]


@pytest.fixture
def clean_cfg():
    """Snapshot + restore the keys these tests mutate."""
    saved = {k: json.loads(json.dumps(advprint.CFG.get(k)))
             for k in ("allowed_ips", "lan_strict", "rules_mirror",
                       "drop_enabled", "drop_delete")}
    yield
    for k, v in saved.items():
        advprint.CFG[k] = v
    advprint.write_config_file({k: advprint.CFG[k]
                                for k in advprint.CONFIG_KEYS})


# ---------------------------------------------------------------
# 1. THE HUB PORT IS CONFIGURABLE
# ---------------------------------------------------------------

def test_port_is_a_real_config_key():
    assert "port" in advprint.CONFIG_KEYS
    assert advprint.CONFIG_TYPES.get("port") is int


def test_port_validation_and_save(hub, clean_cfg):
    # bad values are refused
    for bad in (80, 631, 5353, 9100, 65536, "abc", ""):
        code, r = hub.post("/config", body={"port": bad})
        assert code == 400, (bad, r)
        assert r.get("ok") is False
    # a valid change is saved + flagged for restart
    code, r = hub.post("/config", body={"port": 9431})
    assert code == 200 and r.get("ok") is True
    assert "port" in r.get("changed", [])
    assert r.get("restart") is True
    assert "9431" in r.get("note", "") and "Restart" in r.get("note", "")
    assert advprint.CFG["port"] == 9431
    disk = json.load(open(advprint.config_path(), encoding="utf-8"))
    assert disk.get("port") == 9431
    # the redacted /config view carries the port for the Settings panel
    code, r = hub.get("/config")
    assert code == 200 and r.get("port") == 9431


def test_init_config_env_port_wins_over_config_json(monkeypatch, tmp_path):
    saved = {k: advprint.CFG.get(k) for k in
             ("data_dir", "port", "token", "printer", "file_dir")}
    try:
        advprint.CFG["data_dir"] = str(tmp_path)
        disk = {"port": 9444, "token": advprint.CFG["token"]}
        with open(advprint.config_path(), "w", encoding="utf-8") as f:
            json.dump(disk, f)
        # with the env set (what the interpreter does at import time:
        # CFG["port"] = int(_env("PORT", "9235"))) config.json may NOT
        # override the port:
        monkeypatch.setenv("ADVPRINT_PORT", "9333")
        advprint.CFG["port"] = 9333
        advprint.init_config()
        assert advprint.CFG["port"] == 9333   # env wins
        # without the env, the saved port applies:
        monkeypatch.delenv("ADVPRINT_PORT")
        advprint.CFG["port"] = 9235           # import-time default
        advprint.init_config()
        assert advprint.CFG["port"] == 9444
    finally:
        for k, v in saved.items():
            if v is not None:
                advprint.CFG[k] = v
        advprint.init_config()


def test_port_cli_set_and_show(tmp_path, monkeypatch, capsys):
    saved = {k: advprint.CFG.get(k) for k in ("data_dir", "port", "token")}
    try:
        advprint.CFG["data_dir"] = str(tmp_path)
        advprint.CFG["port"] = 9235
        with open(advprint.config_path(), "w", encoding="utf-8") as f:
            json.dump({"token": advprint.CFG["token"]}, f)
        assert advprint.cmd_port("9300") == 0
        assert advprint.CFG["port"] == 9300
        disk = json.load(open(advprint.config_path(), encoding="utf-8"))
        assert disk.get("port") == 9300
        out = capsys.readouterr().out
        assert "9300" in out and "Restart" in out
        for bad in ("abc", "80", "631", "9100", "70000"):
            assert advprint.cmd_port(bad) == 1
        assert advprint.cmd_port() == 0          # show only
        assert "Hub port (current): 9300" in capsys.readouterr().out
    finally:
        for k, v in saved.items():
            if v is not None:
                advprint.CFG[k] = v
        advprint.init_config()


def test_boot_busy_port_message_lists_the_escapes(monkeypatch, capsys):
    # the FATAL bind branch is exercised by the message unit itself:
    # the v3.4.7 block must name config.json, the CLI and the env
    import inspect
    src = inspect.getsource(advprint.cmd_serve)
    assert "[PORT]" in src
    assert "config.json" in src and "ADVPRINT_PORT" in src
    assert cli_hint_in(src)


def cli_hint_in(src):
    return 'port 9300' in src


def test_settings_panel_port_row_is_real():
    # the ONE UI Settings panel really posts the port now (the old code
    # only toasted "port lives in config.json")
    assert "CONFIGURABLE HUB PORT" in CONSOLE
    assert "patch.port = pv" in CONSOLE
    assert "port lives in config.json" not in CONSOLE
    assert "HUB PORT" in CONSOLE


# ---------------------------------------------------------------
# 2. DROPZONE WATCH FIX
# ---------------------------------------------------------------

def test_dropzone_toggle_wiring_in_console():
    # the button exists, follows the live state, and posts the opposite
    assert 'id="dzWatchBtn"' in CONSOLE
    assert "dzWatchOn" in CONSOLE
    assert 'body: { drop_enabled: want }' in CONSOLE
    assert 'dzWatchOn ? "Disable" : "Enable"' in CONSOLE
    # the old always-false handler is gone
    assert "/^Disable$/" not in CONSOLE
    # the watching stat renders ON/OFF instead of 1/0
    assert 'd.enabled ? "ON" : "OFF"' in CONSOLE


def test_dropzone_config_roundtrip(hub, clean_cfg):
    code, r = hub.post("/config", body={"drop_enabled": True})
    assert code == 200
    code, d = hub.get("/dropzone")
    assert code == 200 and d.get("enabled") is True
    code, r = hub.post("/config", body={"drop_enabled": False})
    assert code == 200
    code, d = hub.get("/dropzone")
    assert code == 200 and d.get("enabled") is False


# ---------------------------------------------------------------
# 3. STRICT LAN SHARE - IP HIT LIST
# ---------------------------------------------------------------

def test_ip_hits_record_only_when_strict(clean_cfg):
    advprint.ip_hits_clear()
    advprint.CFG["lan_strict"] = False
    advprint._ip_hit_record("10.1.1.1", True)
    assert advprint.ip_hits_snapshot()["hits"] == []
    advprint.CFG["lan_strict"] = True
    advprint._ip_hit_record("10.1.1.1", True)
    advprint._ip_hit_record("10.1.1.1", False)
    advprint._ip_hit_record("10.1.1.2", False)
    snap = advprint.ip_hits_snapshot()
    assert snap["strict"] is True
    by_ip = {h["ip"]: h for h in snap["hits"]}
    assert by_ip["10.1.1.1"]["count"] == 2
    assert by_ip["10.1.1.1"]["allowed"] is False     # last state wins
    assert by_ip["10.1.1.2"]["allowed"] is False
    advprint.ip_hits_clear()
    assert advprint.ip_hits_snapshot()["hits"] == []


def test_ip_hits_ring_is_capped(clean_cfg):
    advprint.ip_hits_clear()
    advprint.CFG["lan_strict"] = True
    for i in range(150):
        advprint._ip_hit_record("10.9.%d.%d" % (i // 256, i % 256), True)
    snap = advprint.ip_hits_snapshot()
    assert len(snap["hits"]) <= advprint._IP_HITS_CAP
    advprint.ip_hits_clear()


def test_strict_lan_http_flow(hub, clean_cfg):
    code, r = hub.post("/config", body={"lan_strict": True})
    assert code == 200 and r.get("ok") is True
    code, h = hub.get("/lan/hits")
    assert code == 200 and h.get("strict") is True
    # this very request came from loopback -> recorded + allowed
    hits = {x["ip"]: x for x in h.get("hits", [])}
    assert "127.0.0.1" in hits and hits["127.0.0.1"]["allowed"] is True
    # a LAN PC hits the hub (refused - not on the list yet) ...
    advprint._ip_hit_record("10.55.66.77", False)
    # one-click allow replaces "*" (the lock-down moment) ...
    assert advprint.CFG.get("allowed_ips") == ["*"]
    code, r = hub.post("/lan/allow", body={"ip": "10.55.66.77"})
    assert code == 200 and r.get("ok") is True
    assert r.get("allowed_ips") == ["10.55.66.77"]
    assert r.get("acl_restricted") is True
    assert "ONLY" in r.get("note", "")
    # ... then appends ...
    code, r = hub.post("/lan/allow", body={"ip": "10.55.66.88"})
    assert code == 200 and r.get("allowed_ips") == ["10.55.66.77",
                                                    "10.55.66.88"]
    # ... the hit row flips without waiting for the next hit ...
    code, h = hub.get("/lan/hits")
    by_ip = {x["ip"]: x for x in h.get("hits", [])}
    assert by_ip["10.55.66.77"]["allowed"] is True
    # ... and remove blocks it again
    code, r = hub.post("/lan/allow", body={"ip": "10.55.66.77",
                                           "remove": True})
    assert code == 200 and r.get("allowed_ips") == ["10.55.66.88"]
    # guard rails
    code, r = hub.post("/lan/allow", body={"ip": "127.0.0.1"})
    assert code == 400
    code, r = hub.post("/lan/allow", body={"ip": ""})
    assert code == 400
    code, r = hub.post("/lan/allow", body={"ip": "10.1.1.1 <script>"})
    assert code == 400
    # clear
    code, r = hub.post("/lan/hits/clear", body={})
    assert code == 200 and r.get("hits") == []
    # restore the open hub
    code, r = hub.post("/config", body={"allowed_ips": ["*"],
                                        "lan_strict": False})
    assert code == 200


def test_strict_lan_ui_present():
    assert "Strict LAN mode" in CONSOLE
    assert 'id="strictSwitch"' in CONSOLE
    assert 'id="hitsBody"' in CONSOLE
    assert "/lan/allow" in CONSOLE and "/lan/hits" in CONSOLE
    assert "strictToggle" in DASHBOARD and "lanAllow" in DASHBOARD


def test_gate_still_denies_unlisted_ips(clean_cfg):
    # the ACL semantics are untouched: strict only ADDS the hit list
    assert advprint.ip_allowed_by_list("10.55.66.77", ["*"]) is True
    assert advprint.ip_allowed_by_list("10.55.66.77",
                                       ["10.55.66.88"]) is False
    assert advprint.ip_allowed_by_list("10.55.66.77",
                                       ["10.55.66.0/24"]) is True
    assert advprint.ip_allowed_by_list("10.55.66.77",
                                       ["10.55.*"]) is True


# ---------------------------------------------------------------
# 4. URL RULES THAT REALLY MATCH
# ---------------------------------------------------------------

def test_rule_pattern_semantics():
    # glob: anchored, * = anything, everything else literal
    g = advprint.rule_pattern_to_regex("*://www.htncr.org/lab/*", "glob")
    assert g.search("https://www.htncr.org/lab/x?y=1")
    assert not g.search("https://www.htncr.org/other/x")
    # contains: plain substring, case-insensitive
    c = advprint.rule_pattern_to_regex("Receipt-Print", "contains")
    assert c.search("https://www.htncr.org/lab/receipt-print/5/client")
    # regex: full expressions, case-insensitive
    r = advprint.rule_pattern_to_regex(r"HTNCR\.org/lab/sample/\d+$",
                                       "regex")
    assert r.search("https://www.htncr.org/lab/sample/203182")
    assert not r.search("https://www.htncr.org/lab/sample/203182/x")
    # unknown type degrades to glob, bad regex never matches
    assert advprint.rule_pattern_to_regex("a?b", "weird")
    assert advprint.evaluate_rules(
        [{"pattern": "([", "type": "regex", "printer": "X"}],
        "https://x/[") is None


def test_rule_matches_skips_off_and_content_rules():
    assert advprint.evaluate_rules(
        [{"pattern": "sample", "type": "contains", "printer": "X",
          "on": False}], U3) is None
    assert advprint.evaluate_rules(
        [{"pattern": "sample", "type": "contains", "printer": "X",
          "enabled": False}], U3) is None
    # a content rule needs the right detected kind
    zr = {"name": "zpl", "match": "content", "kind": "zpl",
          "printer": "Zebra", "action": "raw", "on": True}
    assert advprint.rule_matches(zr, "https://x/any", kind="zpl")
    assert not advprint.rule_matches(zr, "https://x/any", kind="html")
    assert not advprint.rule_matches(zr, "https://x/any")
    # an optional title filter must sit inside the page title
    tr = {"pattern": "sample", "type": "contains", "printer": "T",
          "title": "Lab", "on": True}
    assert advprint.rule_matches(tr, U3, title="HTNCR Lab portal")
    assert not advprint.rule_matches(tr, U3, title="Other")


def test_the_four_htncr_recipes():
    hits = [advprint.evaluate_rules(RECIPES, u) for u in
            (U1, U2, U3, U4, U4B)]
    assert hits[0]["name"] == "Single-test report"      # ONE test id
    assert hits[1] is None                              # MANY ids -> default
    assert hits[2]["name"] == "Sample label ZPL"        # sample -> Zebra
    assert hits[3]["name"] == "Receipt A5"              # receipt client
    assert hits[4]["name"] == "Receipt A5"              # receipt admin
    # a report WITHOUT any tests[] query also falls through to default
    assert advprint.evaluate_rules(
        RECIPES,
        "https://www.htncr.org/lab/medical_reports/pdf/203182") is None


def test_rules_test_endpoint(hub, clean_cfg):
    code, r = hub.post("/config", body={"rules_mirror": RECIPES})
    assert code == 200
    # the cleaner KEPT the type field now (the v3.4.7 fix)
    saved = advprint.CFG.get("rules_mirror") or []
    assert saved and all(x.get("type") == "regex" for x in saved)
    code, r = hub.post("/rules/test", body={"url": U1})
    assert code == 200 and r.get("matched") is True
    assert r.get("printer") == "Report Printer"
    assert r["rule"]["type"] == "regex"
    assert r["rule"]["name"] == "Single-test report"
    code, r = hub.post("/rules/test", body={"url": U2})
    assert code == 200 and r.get("matched") is False
    assert "OS default" in r.get("printer", "")
    code, r = hub.get("/rules/test?url=" +
                      "https%3A%2F%2Fwww.htncr.org%2Flab%2Fsample%2F203182")
    assert code == 200 and r.get("matched") is True
    assert r.get("printer") == "Zebra ZPL"
    code, r = hub.post("/rules/test",
                       body={"url": U3, "kind": "html"})
    # kind only matters to CONTENT rules - the URL rule still fires
    assert code == 200 and r.get("matched") is True
    code, r = hub.post("/rules/test", body={})
    assert code == 400
    # an off rule is not fired by the tester either
    off = [dict(RECIPES[0], on=False)] + RECIPES[1:]
    code, _ = hub.post("/config", body={"rules_mirror": off})
    assert code == 200
    code, r = hub.post("/rules/test", body={"url": U1})
    assert code == 200 and r.get("matched") is False


def test_rules_editor_ui_wiring():
    assert 'id="re-ptype"' in CONSOLE
    assert 'value="regex"' in CONSOLE
    assert "RULE_RECIPES" in CONSOLE and "fillRuleRecipes" in CONSOLE
    # the recipes carry the user's four htncr.org patterns
    assert "htncr" in CONSOLE and "tests%5B%5D" in CONSOLE
    assert "receipt-print" in CONSOLE and "lab/sample" in CONSOLE
    # the test box is REALLY wired (no more static demo result)
    assert 'id="ruleTestBtn"' in CONSOLE
    assert "/rules/test" in CONSOLE
    assert "ruleTestRun" in CONSOLE
    assert "fires <b>Rule 1" not in CONSOLE          # old demo text gone
    # the table shows the type chip
    assert "RULE_TYPE_LABEL" in CONSOLE
    # saveRule persists the type
    assert "return (pt && [\"glob\", \"regex\", \"contains\"]" in CONSOLE


# ---------------------------------------------------------------
# 5. NO VERSION PREFIXES IN UI NOTES
# ---------------------------------------------------------------

def test_no_version_prefixes_in_ui_notes():
    for pat in ("v2.8 \u00b7 ", "v3.2.6 \u00b7 ", "v3.2.3 \u00b7 ",
                "v3.3.0 \u2014 ", "v3.3.4 AUTOCRX \u2014", "v3.3.5 \u2014 ",
                "since v2.6.4"):
        assert pat not in CONSOLE, pat
    for pat in ("&nbsp;- v2.2:", "&nbsp;- v2.3:", "&nbsp;- v2.7.0:",
                "&nbsp;- v2.8:", "&nbsp;- v2.9:"):
        assert pat not in DASHBOARD, pat   # visible h2 subtitles only
        assert pat not in CONSOLE, pat
    # the About card talks about the port correctly
    assert "port 9235 by default (changeable in Settings)" in CONSOLE


# ---------------------------------------------------------------
# misc: the latent POST /config crash guard
# ---------------------------------------------------------------

def test_config_post_with_zero_valid_keys_is_safe(hub):
    code, r = hub.post("/config", body={"totally_unknown_key": 1})
    assert code == 400 and r.get("ok") is False
    code, r = hub.post("/config", body={"port": "not-a-number"})
    assert code == 400
    # the hub still answers (the old code could NameError past this)
    code, r = hub.get("/health")
    assert code == 200
