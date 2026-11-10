"""v3.2.0 THE ONE ALL-IN-ONE UI - every browser URL serves the approved
IDM console, SELF vs CENTER view injection, the /tool API (the desktop
tool's 14 menu actions over HTTP) and the central rule manager mirror.

- GET /  (browser)        -> console.html with boot JSON (self on loopback)
- GET /ui?token=...       -> same page, __ADVPRINT_BOOT_JSON__ replaced
- GET /dashboard?token=.. -> same page (ONE UI, no separate URLs)
- boot JSON says which view: "self" for the hub PC owner (loopback),
  "center" for a LAN PC (?view=center forces the CENTER PC UI preview)
- POST /tool {action}     -> the 14 desktop-tool actions; loopback+token
- POST /config rules_mirror accepts rule DICTS (not stringified reprs)
"""
import json
import os

import pytest

import advprint


def _boot(html):
    m = '__ADVPRINT_BOOT_JSON__'
    start = html.find('<script id="bootjson" type="application/json">')
    assert start >= 0, "console.html must carry the boot JSON script tag"
    tail = html[start:]
    return tail


def test_ui_and_dashboard_and_root_all_serve_one_ui(hub):
    pages = {}
    for path in ("/ui", "/dashboard", "/"):
        code, body = hub.get(path, headers={"Accept": "text/html"})
        assert code == 200, path
        pages[path] = body.decode("utf-8")
    for path, html in pages.items():
        assert "Printing Hub" in html, path
        assert "THE ONE UI" in html, path
        # the boot placeholder must be REPLACED with real JSON
        assert "__ADVPRINT_BOOT_JSON__" not in html, path
        assert '"view"' in html and '"version"' in html, path


def test_boot_json_self_on_loopback(hub):
    code, body = hub.get("/ui")
    html = body.decode("utf-8")
    start = html.find('<script id="bootjson" type="application/json">') + \
        len('<script id="bootjson" type="application/json">')
    end = html.find("</script>", start)
    boot = json.loads(html[start:end])
    assert boot["view"] == "self"          # loopback client = the owner
    assert boot["version"] == advprint.VERSION
    assert "host" in boot and "lan_ip" in boot and "port" in boot


def test_view_override_center(hub):
    code, body = hub.get("/ui?view=center")
    html = body.decode("utf-8")
    start = html.find('<script id="bootjson" type="application/json">') + \
        len('<script id="bootjson" type="application/json">')
    end = html.find("</script>", start)
    boot = json.loads(html[start:end])
    assert boot["view"] == "center"        # CENTER PC UI preview


def test_console_ships_one_ui_markers():
    p = os.path.join(os.path.dirname(advprint.__file__), "console.html")
    src = open(p, encoding="utf-8").read()
    for marker in ("Tools", "data-tool", "rules_mirror",
                   "Website API permission", "CENTER PC UI",
                   "ExtensionInstallForcelist", "Brave",
                   "/tool", "/qr", "/dropzone", "/peers",
                   "X-AdvPrint-Token", "success_rate",
                   # v3.2.1 rev-4 ONE UI markers
                   'id="p-rules"', 'id="rulemodal"', 'id="qrmodal"',
                   'id="bootjson"', "ExtensionInstallForcelist"):
        assert marker in src, "console.html must contain " + marker


def test_tool_api_actions(hub):
    # status: the live service/autostart/firewall snapshot
    code, d = hub.post("/tool", body={"action": "status"})
    assert code == 200 and d["ok"] is True
    r = d["result"]
    for k in ("version", "service", "autostart", "firewall", "queue",
              "data_dir"):
        assert k in r
    assert r["version"] == advprint.VERSION

    # recent-jobs returns a list
    code, d = hub.post("/tool", body={"action": "recent-jobs"})
    assert code == 200 and isinstance(d["result"]["jobs"], list)

    # unknown action is a clean 400
    code, d = hub.post("/tool", body={"action": "does-not-exist"})
    assert code == 400 and d["ok"] is False


def test_tool_api_requires_token(hub):
    code, _ = hub.post("/tool", body={"action": "status"}, token=None)
    assert code in (401, 403)


def test_config_rules_mirror_roundtrip(hub):
    rules = [
        {"id": 1, "name": "lab reports", "pattern": "*://www.htncr.org/*",
         "match": "url", "kind": "", "printer": "HP Laser 103 107 108",
         "action": "auto", "copies": 2, "paper": "A4", "on": True,
         "runs": 7},
        {"id": 2, "name": "thermal receipts", "pattern": "*",
         "match": "content", "kind": "zpl", "printer": "",
         "action": "auto", "copies": 1, "paper": "", "on": False,
         "runs": 0},
    ]
    code, d = hub.post("/config", body={"rules_mirror": rules})
    assert code == 200 and d["ok"] is True
    code, cfg = hub.get("/config")
    assert code == 200
    back = cfg["rules_mirror"]
    assert len(back) == 2
    assert back[0]["name"] == "lab reports"
    assert back[0]["copies"] == 2 and back[0]["runs"] == 7
    assert back[1]["match"] == "content" and back[1]["kind"] == "zpl"
    assert back[1]["on"] is False


def test_config_rules_mirror_rejects_junk(hub):
    code, d = hub.post("/config", body={"rules_mirror": ["not-a-dict"]})
    assert code == 400 and "objects" in d["error"]


def test_config_ext_sites_mirror(hub):
    code, d = hub.post("/config", body={"ext_api_sites": ["*"]})
    assert code == 200 and d["ok"] is True
    code, cfg = hub.get("/config")
    assert cfg["ext_api_sites"] == ["*"]


def test_whitelist_default_all_domains():
    """v3.2.0: the extension's Website API whitelist defaults to '*' -
    ALL domains are allowed out of the box."""
    root = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.dirname(advprint.__file__)))))
    bg = open(os.path.join(root, "extension", "background.js"),
              encoding="utf-8").read()
    assert 'apiSites: ["*"]' in bg
