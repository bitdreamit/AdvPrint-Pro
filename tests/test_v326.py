"""v3.2.6 - SEVEN USER-REPORTED BUGS + THE UI SECURITY MODEL.

Locks the whole release end to end:

* BUG 1  History / Queue clear really cleans (/queue/clear cancels AND
         removes, honors finished:true as a /history/clear alias, the
         console "Clear ALL history" button calls /history/clear)
* BUG 2  /printers ipp_path is the BARE queue slug - no doubled
         /ipp/print/ipp/print/ on the Details button
* BUG 3  LAN panel header Disable/Enable is wired + Copy URL carries
         the token; extra IPP: ON/OFF header toggle
* BUG 4  LAN-share row Copy URL carries the token (same action)
* BUG 5  /qr?kind=ipp encodes the http:// printer URL; console keeps
         ipp:// for display/copy
* BUG 6  no backdated v3.0.7 install doc + in-UI Docs modal
* SECURITY  _mgmt_locked: local-only console/settings; LAN keeps the
         print surface; own-IP allowance; branded 403
* REMOVE the numbered CLI menu (tool.py opens the console) and the
         tray menu is Dashboard / Restart / Exit only
* NEW    LAN share ON auto-enables the IPP printer
* version coherence 3.2.6 everywhere
"""
import json
import os
import re
import urllib.request

import pytest

import advprint
from conftest import ROOT

HUB_DIR = os.path.join(ROOT, "tool", "windows", "portable", "hub")
EXT = os.path.join(ROOT, "extension")
CONSOLE = open(os.path.join(HUB_DIR, "console.html"),
               encoding="utf-8").read()
ADVPRINT_SRC = open(os.path.join(HUB_DIR, "advprint.py"),
                    encoding="utf-8").read()
TOOL_SRC = open(os.path.join(HUB_DIR, "tool.py"),
                encoding="utf-8").read()
TRAY_SRC = open(os.path.join(HUB_DIR, "tray_windows.py"),
                encoding="utf-8").read()
NSI = open(os.path.join(ROOT, "installer", "setup.nsi"),
           encoding="utf-8").read()


def _own_ip_of(adv):
    """The sandbox machine's own LAN IP (as own_ip_set() computes it)."""
    ips = adv.own_ip_set()
    for ip in sorted(ips):
        if ip not in ("127.0.0.1", "::1", "::ffff:127.0.0.1"):
            return ip
    return "127.0.0.1"


class _Stub:
    """Duck-typed Handler: only what the gate touches."""

    def __init__(self, ip, method):
        self._ip = ip
        self.command = method

    def _client_ip(self):
        return self._ip

    def _is_own_host(self):
        return advprint.Handler._is_own_host(self)


# ------------------------------------------------------------
# BUG 1 - clear REALLY cleans
# ------------------------------------------------------------
def _seed(adv, title, status):
    return adv.db_add("pdf", title, "PDF", 1, "/tmp/x.pdf", "test-v326",
                      "127.0.0.1", status=status)


def test_v326_queue_clear_cancels_and_removes_everything(hub):
    _seed(advprint, "v326-q1", "queued")
    _seed(advprint, "v326-q2", "held")
    _seed(advprint, "v326-q3", "scheduled")
    _seed(advprint, "v326-q4", "printed")
    code, d = hub.post("/queue/clear")
    assert code == 200 and d["ok"], d
    assert d["canceled"] >= 3 and d["removed"] >= 4, d
    left = [j["status"] for j in advprint.db_list(limit=500)]
    assert left == [], "queue/clear must leave NO rows - got %r" % left


def test_v326_history_clear_keeps_waiting_jobs(hub):
    _seed(advprint, "v326-h1", "printed")
    _seed(advprint, "v326-h2", "failed")
    _seed(advprint, "v326-h3", "queued")
    code, d = hub.post("/history/clear")
    assert code == 200 and d["ok"] and d["deleted"] >= 2, d
    left = [j["status"] for j in advprint.db_list(limit=500)]
    assert "queued" in left, "history/clear must never touch waiting jobs"
    assert "printed" not in left and "failed" not in left


def test_v326_queue_clear_finished_alias(hub):
    _seed(advprint, "v326-f1", "canceled")
    _seed(advprint, "v326-f2", "queued")
    code, d = hub.post("/queue/clear", body={"finished": True})
    assert code == 200 and d["ok"] and d.get("deleted") >= 1, d
    left = [j["status"] for j in advprint.db_list(limit=500)]
    assert "queued" in left and "canceled" not in left


def test_v326_console_clear_buttons_hit_the_right_endpoints():
    assert 'await api("/history/clear", { method: "POST" })' in CONSOLE, \
        "Clear ALL history must call /history/clear (bug 1)"
    old = ('api("/queue/clear", { method: "POST", '
           'body: { finished: true } })')
    assert old not in CONSOLE, "the ignored finished:true body is gone"
    assert "the queue AND the history come back clean" in CONSOLE


# ------------------------------------------------------------
# BUG 2 - no doubled /ipp/print
# ------------------------------------------------------------
def test_v326_printers_api_returns_bare_slug(hub, monkeypatch):
    monkeypatch.setattr(advprint, "list_printers_cached",
                        lambda max_age=0.0: ["Microsoft Print to PDF"])
    monkeypatch.setattr(advprint, "printers_status_cached",
                        lambda: {"Microsoft Print to PDF": "ready"})
    monkeypatch.setattr(advprint, "default_printer_cached",
                        lambda: "Microsoft Print to PDF")
    code, d = hub.get("/printers")
    assert code == 200 and d["ok"]
    item = [p for p in d["printers"] if p.get("ipp_path")][0]
    slug = item["ipp_path"]
    assert not slug.startswith("ipp/print/"), \
        "ipp_path must be the BARE slug - got %r" % slug
    assert "/" not in slug, "slug must not contain a path segment"
    # the full ipp:// URL stays real
    assert item["ipp_queue"].startswith("ipp://")


def test_v326_console_details_button_no_double_prefix():
    assert 'esc(p.ipp_path || "")' in CONSOLE
    handler = re.search(
        r'window\.open\(BASE \+ "/ipp/print" \+ \(slug \? "/" \+ slug : ""\)',
        CONSOLE)
    assert handler, "the data-open handler must join the slug safely"
    assert '"/ipp/print/" + op.dataset.open' not in CONSOLE


# ------------------------------------------------------------
# BUG 3 + 4 + NEW FEATURE - LAN header switches, token copy, IPP toggle
# ------------------------------------------------------------
def test_v326_lan_header_buttons_exist_and_are_wired():
    assert 'id="lanTopToggle"' in CONSOLE
    assert 'id="ippTopToggle"' in CONSOLE
    assert "cfgCache.share_lan === false ? \"Enable\" : \"Disable\"" in CONSOLE
    assert "IPP: " in CONSOLE and "ipp_printer: on" in CONSOLE
    # the row-level extra IPP toggle exists and maps to ipp_printer
    assert 'class="btn small ipp-tgl"' in CONSOLE
    assert ('k.indexOf("Network printer (IPP)") === 0'
            '? "ipp_printer"' in CONSOLE.replace(" ", "")) or \
           ('k.indexOf("Network printer (IPP)") === 0 ? "ipp_printer"'
            in CONSOLE)


def test_v326_copy_hub_url_carries_token():
    m = re.search(r'"copy-hub-url": function\(\)\{[\s\S]{0,500}?\},',
                  CONSOLE)
    assert m, "copy-hub-url action missing"
    body = m.group(0)
    assert "encodeURIComponent(TOKEN)" in body, \
        "Copy URL must include the token (bugs 3+4)"
    assert "/ui?token=" in body


# ------------------------------------------------------------
# BUG 5 - QR encodes http://, copy keeps ipp://
# ------------------------------------------------------------
def test_v326_qr_ipp_encodes_http_url(hub):
    code, svg = hub.get("/qr?kind=ipp")
    assert code == 200 and b"<svg" in (svg if isinstance(svg, bytes)
                                       else svg.encode())
    assert "ipp://" not in advprint.lan_share_url("ipp"), \
        "the QR payload URL must be http:// (bug 5)"
    # the handler pins the http URL explicitly (source-level lock)
    m = re.search(r'kind == "ipp":[\s\S]{0,300}?url = '
                  r'"http://%s:%d/ipp/print"', ADVPRINT_SRC)
    assert m, "/qr handler must hard-pin the http:// payload for ipp"


def test_v326_qr_modal_shows_both_urls():
    assert "QR code contains: " in CONSOLE
    assert "printer-add URL (copy): " in CONSOLE
    assert "Google search" in CONSOLE   # the reason is documented


# ------------------------------------------------------------
# BUG 6 - docs not backdated + in-UI docs
# ------------------------------------------------------------
def test_v326_no_backdated_307_strings():
    assert '" (v3.0.7)</h2>"' not in ADVPRINT_SRC
    assert "(v%s)</h2>\" % VERSION" in ADVPRINT_SRC, \
        "the self-host extension page must show the CURRENT version"
    assert "v3.0.7: Chrome/Edge/Brave" not in ADVPRINT_SRC, \
        "the /docs install section must not claim v3.0.7"
    assert "v@@VERSION@@: Chrome/Edge/Brave" in ADVPRINT_SRC


def test_v326_in_ui_docs_modal():
    assert 'id="docsmodal"' in CONSOLE
    assert "function docsHtml()" in CONSOLE
    assert "function openDocs(" in CONSOLE
    assert '"open-docs": function(){ openDocs(); }' in CONSOLE
    assert 'if (t === "Docs") b.onclick = function(){ openDocs(); };' \
        in CONSOLE
    assert 'openDocs("d-notes")' in CONSOLE
    assert 'id="docs-lnk-old"' in CONSOLE
    # the docs content covers the new security model + the QR rule
    assert "The console UI is local-only" in CONSOLE
    assert "d-notes" in CONSOLE and "d-ipp" in CONSOLE


# ------------------------------------------------------------
# SECURITY - the UI gate
# ------------------------------------------------------------
def test_v326_gate_module_tables_exist():
    for name in ("MGMT_OPEN_GET_EXACT", "MGMT_OPEN_GET_PREFIX",
                 "MGMT_OPEN_POST_EXACT", "MGMT_OPEN_POST_PREFIX",
                 "own_ip_set"):
        assert hasattr(advprint, name), name


def test_v326_gate_matrix_local_always_passes():
    h = _Stub("127.0.0.1", "GET")
    assert advprint.Handler._is_own_host(h)
    assert not advprint.Handler._mgmt_locked(h, "/ui")
    assert not advprint.Handler._mgmt_locked(h, "/config")
    assert not advprint.Handler._mgmt_locked(h, "/dashboard")


def test_v326_gate_matrix_own_lan_ip_passes():
    own = _own_ip_of(advprint)
    h = _Stub(own, "GET")
    assert advprint.Handler._is_own_host(h), \
        "the hub PC's own LAN IP must pass (owner is never locked out)"
    assert not advprint.Handler._mgmt_locked(h, "/ui?token=x".split("?")[0])


def test_v326_gate_matrix_remote_print_surface_open():
    for route in ("/health", "/jobs", "/printers", "/send", "/connect",
                  "/testprint"):
        h = _Stub("192.168.1.77", "GET")
        assert not advprint.Handler._mgmt_locked(h, route), route
    for route in ("/ipp/print", "/ipp/print/microsoft-print-to-pdf",
                  "/extension/updates.xml", "/extension/AdvPrint-Pro.crx"):
        h = _Stub("192.168.1.77", "GET")
        assert not advprint.Handler._mgmt_locked(h, route), route
    for route in ("/print", "/send", "/jobs/12/cancel",
                  "/jobs/12/print-now", "/jobs/bulk-reprint",
                  "/ipp/print", "/client/report"):
        h = _Stub("192.168.1.77", "POST")
        assert not advprint.Handler._mgmt_locked(h, route), route


def test_v326_gate_matrix_remote_management_locked():
    locked = ["/ui", "/dashboard", "/docs", "/", "/qr", "/stats",
              "/audit", "/audit.csv", "/export/history.csv", "/debug",
              "/diagnostics", "/peers", "/config", "/dropzone",
              "/lan/selftest", "/token/current", "/queue"]
    for route in locked:
        h = _Stub("192.168.1.77", "GET")
        assert advprint.Handler._mgmt_locked(h, route), route
    for route in ("/config", "/token/rotate", "/autostart", "/tool",
                  "/restart", "/queue/pause", "/queue/clear",
                  "/history/clear", "/jobs/release_all",
                  "/printers/set-default", "/livetest",
                  "/extension/policy/install", "/firewall/allow",
                  "/dropzone/open", "/ip-printer/test"):
        h = _Stub("192.168.1.77", "POST")
        assert advprint.Handler._mgmt_locked(h, route), route


def test_v326_gate_wired_into_get_and_post():
    for m in ("do_GET", "do_POST"):
        seg = re.search(r"def %s\(self\):[\s\S]{0,900}?_do_(?:get|post)"
                        "_impl\\(\\)" % m, ADVPRINT_SRC)
        assert seg, m
        assert "_mgmt_locked" in seg.group(0), \
            "%s must run the v3.2.6 UI gate" % m
        assert "_ui_locked_answer" in seg.group(0)


def test_v326_locked_page_is_helpful():
    assert "the console runs on" in ADVPRINT_SRC
    assert "local-only endpoint" in ADVPRINT_SRC
    assert "/ipp/print" in \
        ADVPRINT_SRC[ADVPRINT_SRC.find("_ui_locked_answer"):
                     ADVPRINT_SRC.find("_ui_locked_answer") + 4000]


def test_v326_loopback_ui_still_serves_console(hub):
    code, page = hub.get("/ui")
    assert code == 200 and b"AdvPrint" in (page if isinstance(page, bytes)
                                           else page.encode())
    # GET /config answers the redacted config for the owner
    code, d = hub.get("/config")
    assert code == 200 and "allowed_ips" in d


def test_v326_lan_security_note_in_console():
    assert "v3.2.6 security" in CONSOLE
    assert "only on this PC" in CONSOLE


# ------------------------------------------------------------
# NEW FEATURE - LAN share ON auto-enables IPP
# ------------------------------------------------------------
def test_v326_lan_share_on_enables_ipp_printer(hub):
    snap = {k: advprint.CFG.get(k) for k in ("share_lan", "ipp_printer",
                                             "ipp_mdns")}
    try:
        advprint.CFG["share_lan"] = False
        advprint.CFG["ipp_printer"] = False
        code, d = hub.post("/config", body={"share_lan": True})
        assert code == 200 and d["ok"]
        assert "share_lan" in d["changed"]
        assert "ipp_printer" in d["changed"], \
            "LAN sharing ON must auto-enable the IPP printer"
        assert advprint.CFG["ipp_printer"] is True
    finally:
        advprint.CFG.update(snap)
        disk = {k: advprint.CFG[k] for k in advprint.CONFIG_KEYS}
        advprint.write_config_file(disk)


def test_v326_explicit_ipp_off_beats_the_linkage(hub):
    snap = {k: advprint.CFG.get(k) for k in ("share_lan", "ipp_printer")}
    try:
        advprint.CFG["ipp_printer"] = False
        code, d = hub.post("/config",
                           body={"share_lan": True, "ipp_printer": False})
        assert code == 200 and d["ok"]
        assert advprint.CFG["ipp_printer"] is False, \
            "an explicit ipp_printer:false must win"
    finally:
        advprint.CFG.update(snap)
        disk = {k: advprint.CFG[k] for k in advprint.CONFIG_KEYS}
        advprint.write_config_file(disk)


# ------------------------------------------------------------
# REMOVE - the CLI menu is gone
# ------------------------------------------------------------
def test_v326_tool_has_no_interactive_menu():
    assert "Choose [0-14]" not in TOOL_SRC
    assert "def menu(" not in TOOL_SRC
    assert "MENU = " not in TOOL_SRC
    assert "open_console" in TOOL_SRC
    assert "/ui?token=" in TOOL_SRC, "no-args must open THE ONE UI"


def test_v326_tool_keeps_repair_subcommands():
    for cmd in ("status", "start", "stop", "restart", "testprint",
                "history", "autorun", "livetest", "diagnose",
                "dashboard", "service-install", "service-remove",
                "update-check", "uninstall"):
        assert '"%s"' % cmd in TOOL_SRC, cmd


def test_v326_no_tool_shortcut_in_nsis():
    assert "AdvPrint Tool.lnk" not in NSI
    assert "AdvPrint Console.lnk" in NSI


def test_v326_portable_bat_points_at_the_console():
    bat = open(os.path.join(ROOT, "tool", "windows", "portable",
                            "AdvPrint-Tool.bat"),
               encoding="utf-8", errors="replace").read()
    assert "the console IS the" in bat.lower() or "THE ONE UI" in bat


# ------------------------------------------------------------
# REMOVE - the tray menu is 3 items
# ------------------------------------------------------------
def test_v326_tray_menu_is_dashboard_restart_exit():
    m = re.search(r"def _menu_items\(self\):[\s\S]{0,700}?return \[[\s\S]*?\]",
                  TRAY_SRC)
    assert m, "_menu_items not found"
    body = m.group(0)
    assert "M_OPEN" in body and "M_RESTART" in body and "M_EXIT" in body
    for gone in ("M_TEST", "M_PAUSE", "M_AUTO", "M_FIREWALL"):
        assert gone not in body, \
            "tray must not offer %s any more (v3.2.6 user request)" % gone
    assert "Exit, Dashboard, Restart" in TRAY_SRC  # the v3.2.6 comment


# ------------------------------------------------------------
# version coherence 3.2.6
# ------------------------------------------------------------
def test_v326_version_coherence():
    assert advprint.VERSION == "3.2.7"
    assert advprint.VERSION_NAME.startswith("v3.2.7")
    vt = open(os.path.join(ROOT, "VERSION.txt"), encoding="utf-8").read()
    assert "3.2.7" in vt
    man = json.load(open(os.path.join(EXT, "manifest.json"),
                         encoding="utf-8"))
    assert man["version"] == "3.2.7"
    assert 'VIProductVersion "3.2.7.0"' in NSI
    assert "AdvPrint-Pro-Setup-3.2.7.exe" in NSI
    popup = open(os.path.join(EXT, "popup.html"), encoding="utf-8").read()
    assert "v3.2.7" in popup
    i18n = open(os.path.join(EXT, "i18n.js"), encoding="utf-8").read()
    assert "Version 3.2.7" in i18n
    # the embedded console matches the standalone file exactly
    m = re.search(r'CONSOLE_HTML = r"""(.*?)"""', ADVPRINT_SRC, re.S)
    assert m and m.group(1) == CONSOLE, "embedded console is stale"


def test_v326_extension_page_serves_current_version(hub):
    code, page = hub.get("/extension")
    txt = page.decode("utf-8", "replace") if isinstance(page, bytes) \
        else str(page)
    assert code == 200
    assert "(v3.2.7)" in txt, "the self-host page must not be backdated"
    assert "v3.0.7" not in txt
