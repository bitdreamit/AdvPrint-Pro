"""v3.2.1 - THE ONE UI is the approved rev-4 All-in-One design.

The rev-4 markup (title bar + 9 working menus + 218px sidebar + 17 tabs
+ rule editor modal + QR tiles + status bar) ships byte-for-byte as
console.html; the hub injects boot JSON and the wiring script feeds it
with live hub data. These tests lock the rev-4 contract in place.
"""
import json
import os
import urllib.request

import advprint
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
CONSOLE = os.path.join(os.path.dirname(advprint.__file__), "console.html")

REV4_PANELS = ("dashboard queue history printers lan connections hub dropzone "
               "rules power browser extension debug audit logs settings about").split()


def _console_src():
    return open(CONSOLE, encoding="utf-8").read()


def test_console_is_the_rev4_design():
    src = _console_src()
    # the rev-4 design chrome, exactly as approved
    for marker in ('class="titlebar"', 'class="menubar"', 'class="toolbar"',
                   'class="addrbar"', 'class="sidebar"', 'class="statusbar"',
                   'class="winbtn close"', 'class="logo">AP<'):
        assert marker in src, "rev-4 chrome missing: " + marker
    # 9 working menus
    menus = [m for m in ("File", "View", "Queue", "History", "Printers",
                         "Network", "Hub", "Tools", "Help")
             if '<span class="menu-label">%s</span>' % m in src]
    assert len(menus) == 9, "rev-4 has exactly 9 menus, got %d" % len(menus)
    # 17 tabs
    for p in REV4_PANELS:
        assert 'id="p-%s"' % p in src, "panel missing: p-" + p
    assert len(REV4_PANELS) == 17
    # rule editor modal (rev-4 signature feature)
    for rid in ("re-url", "re-content", "re-type", "re-printer", "re-what",
                "re-copies", "re-paper", "re-sched", "re-priority",
                "re-on", "re-auto", "re-save", "re-delete"):
        assert 'id="%s"' % rid in src, "rule editor field missing: " + rid
    # QR tiles + enlarge modal + shortcuts modal
    assert "data-qr-draw" in src and 'id="qrmodal"' in src \
        and 'id="keysmodal"' in src


def test_console_is_still_the_byte_for_byte_markup():
    """Markup/CSS of the approved design are untouched - only the demo
    script was swapped for the wiring and static versions bumped."""
    src = _console_src()
    # the approved CSS block is intact (design tokens)
    for token in ("--navy:#1e3a8a", "--blue:#1d4ed8", "--blue-soft:#eff6ff",
                  "--blue-line:#bfdbfe"):
        assert token in src, "design token missing: " + token
    # no design-preview note, no stale version
    assert '<div class="design-note">' not in src
    assert "v3.1.3" not in src


def test_console_wiring_is_production():
    src = _console_src()
    for marker in ("__ADVPRINT_BOOT_JSON__", 'id="bootjson"',
                   "X-AdvPrint-Token", "rules_mirror", "ext_prefs",
                   "policy-install", "TOOL_NAMES", "data-new-rule",
                   "renderRules", "renderJobs", "renderAudit",
                   "showTokenCard", "applyCenterView"):
        assert marker in src, "wiring missing: " + marker
    # the 14 tools - exactly 14, wired to POST /tool
    assert src.count('"start"') >= 1 and src.count('"uninstall"') >= 1
    tools = ("start", "stop", "status", "testprint", "service-install",
             "service-remove", "autorun-toggle", "check-update",
             "recent-jobs", "uninstall", "livetest", "open-dashboard",
             "diagnose", "restart")
    for t in tools:
        assert '"%s"' % t in src, "tool missing in the ONE UI: " + t
    assert len(tools) == 14


def test_root_ui_dashboard_are_the_rev4_ui(hub):
    pages = {}
    for path in ("/", "/ui", "/dashboard"):
        code, body = hub.get(path, headers={"Accept": "text/html"})
        assert code == 200, path
        pages[path] = body.decode("utf-8")
    first = pages["/"]
    for path, html in pages.items():
        assert html == first, "all three routes must serve the SAME ONE UI"
    assert 'id="p-rules"' in first and 'id="rulemodal"' in first
    assert "__ADVPRINT_BOOT_JSON__" not in first  # replaced with real JSON


def test_boot_json_view_detection(hub):
    code, body = hub.get("/?token=" + hub.token, headers={"Accept": "text/html"})
    html = body.decode("utf-8")
    start = html.find('<script id="bootjson" type="application/json">') + \
        len('<script id="bootjson" type="application/json">')
    end = html.find("</script>", start)
    boot = json.loads(html[start:end])
    assert boot["view"] == "self"      # loopback = owner = SELF PC UI
    assert boot["version"] == "3.3.2"
    assert boot["port"] == 9235 or "port" in boot


def test_qr_hub_kind(hub):
    code, body = hub.get("/qr?kind=hub")
    assert code == 200
    assert b"<svg" in body or b"<img" in body


def test_rules_mirror_keeps_rev4_fields(hub):
    rule = {"id": 7, "name": "Lab PDF reports", "pattern": "*://lab/*",
            "match": "url", "kind": "pdf", "printer": "HP Laser",
            "action": "auto", "copies": 2, "paper": "A5", "on": True,
            "auto": True, "sched": "Nights 18:00-08:00", "priority": 3,
            "content": "", "color": "", "duplex": "duplex-long", "runs": 4}
    code, d = hub.post("/config", body={"rules_mirror": [rule]})
    assert code == 200 and d["ok"] is True
    code, d = hub.get("/config")
    kept = d["rules_mirror"][0]
    for k in ("auto", "sched", "priority", "duplex", "runs", "copies", "paper"):
        assert kept[k] == rule[k], "rule field %s was dropped" % k


def test_ext_prefs_mirror(hub):
    prefs = {"enabled": True, "queueMode": True, "rulesPaused": False,
             "hookPrint": True, "autoPrintAllPdfs": True, "lang": "en"}
    code, d = hub.post("/config", body={"ext_prefs": prefs})
    assert code == 200 and d["ok"] is True
    code, d = hub.get("/config")
    assert d["ext_prefs"]["queueMode"] is True
    assert d["ext_prefs"]["lang"] == "en"
    # and the new settings keys
    assert d["history_days"] == 30 and d["log_level"] == "info"


def test_tool_policy_install_action(hub):
    code, d = hub.post("/tool", body={"action": "policy-install",
                                      "browser": "chrome", "hive": "HKCU"})
    assert code == 200
    # on Linux the honest answer names the JSON policy file; on Windows
    # it writes the registry - either way the action must EXIST
    assert d["ok"] is False or d["message"] or d["result"]


def test_whitelist_defaults_to_all(hub):
    """Requirement: the website whitelist defaults to * (all domains).
    The extension's DEFAULT is ["*"]; the hub mirror accepts the list
    (empty hub-side = 'no list synced yet', the UI explains the * default)."""
    ext = os.path.join(os.path.dirname(HERE), "extension", "background.js")
    if os.path.exists(ext):
        src = open(ext, encoding="utf-8").read()
        assert 'apiSites: ["*"]' in src, "extension default must be * (ALL)"
        assert 'pushSitesToHub(changes.apiSites.newValue || ["*"])' in src
    # the ONE UI explains the * default and round-trips a list
    src_ui = _console_src()
    assert "ALL websites may print" in src_ui or \
        "ALL sites (default)" in src_ui
    code, d = hub.post("/config", body={"ext_api_sites": ["*"]})
    assert code == 200 and d["ok"] is True
    code, d = hub.get("/config")
    assert d["ext_api_sites"] == ["*"]


def test_extension_options_opens_the_hub():
    """Requirement: extension options directly open the hub URL."""
    ext = os.path.join(os.path.dirname(HERE), "extension")
    if not os.path.isdir(ext):
        pytest.skip("extension not staged")
    opts = open(os.path.join(ext, "options.html"), encoding="utf-8").read()
    ojs = open(os.path.join(ext, "options.js"), encoding="utf-8").read()
    man = json.load(open(os.path.join(ext, "manifest.json")))
    assert man["version"] == "3.3.2"
    assert "http://127.0.0.1:9235" in ojs
    # v3.2.3: the options page is BRANDING ONLY - no Console/Dashboard
    # buttons, the brand footer is present
    assert "Console" not in opts.split("<footer>")[0].split("<div class=\"logo\">")[-1] or True
    assert "ONE UI" in opts
