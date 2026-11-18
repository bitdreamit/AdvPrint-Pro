"""v3.5.6 - LAN ADMIN CONSOLE + IPP:// PRINTER URLS

The owner asked for two things:
  1. "is it correct http i think it be ipp://" - the add-printer URLs
     the hub SHOWS (row chip, Android guide, landing page, gated page)
     now display the ipp:// scheme Android's manual-add screen accepts;
     an http:// URL keeps Android's Save button disabled. The hub still
     SPEAKS plain HTTP/IPP - display only. The /qr?kind=ipp payload
     STAYS http:// (phone cameras cannot open ipp:// links, v3.2.6).
  2. "any ip allow to access admin console ui if permission like
     loopback 127.0.0.1 and self ip auto add extra ips also access
     admin controlled from different ip same network. so control more
     easy" - THE ONE UI is now reachable from the hub PC's own network
     (ui_admin_mode="lan", factory default) plus admin_ips entries from
     ANY network, with "self" keeping the exact v3.2.6 lock and "any"
     opening it for everything LAYER 1 lets in. Every remote console
     session is audited (ui.remote_admin).

Also locks: version coherence 3.5.8, the v3.5.5 build kit untouched.
"""
import json
import os
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V = "3.5.8"
EXT_ID = "likldbkamojokkfdlcjibiljpgbbnohc"

CONSOLE_PATHS = [
    os.path.join(ROOT, "tool", "unix", "hub", "console.html"),
    os.path.join(ROOT, "tool", "windows", "portable", "hub", "console.html"),
]
ADV_PATHS = [
    os.path.join(ROOT, "tool", "unix", "hub", "advprint.py"),
    os.path.join(ROOT, "tool", "windows", "portable", "hub", "advprint.py"),
]

sys.path.insert(0, os.path.join(ROOT, "tool", "windows", "portable", "hub"))
import advprint  # noqa: E402


def console():
    return open(CONSOLE_PATHS[0], encoding="utf-8").read()


def adv():
    return open(ADV_PATHS[0], encoding="utf-8").read()


# ---------------- A. version coherence 3.5.8 --------------------------

def test_v356_hub_version():
    assert advprint.VERSION == V
    assert advprint.VERSION_NAME.startswith(
        "v3.5.8 (CRX SIGNATURE VERIFIED + LAN ADMIN CONSOLE")
    assert "ipp://" in advprint.VERSION_NAME
    assert "admin_ips" in advprint.VERSION_NAME


def test_v356_version_txt():
    s = open(os.path.join(ROOT, "VERSION.txt"), encoding="utf-8").read()
    assert ("AdvPrint Pro (Advanced Printer) %s - built" % V) in s


def test_v356_extension_version_files():
    m = json.load(open(os.path.join(ROOT, "extension", "manifest.json"),
                       encoding="utf-8"))
    assert m["version"] == V
    popup = open(os.path.join(ROOT, "extension", "popup.html"),
                 encoding="utf-8").read()
    assert ("id=\"ver\">v%s<" % V) in popup
    i18n = open(os.path.join(ROOT, "extension", "i18n.js"),
                encoding="utf-8").read()
    assert i18n.count(V) >= 3          # header + EN + BN brandLine
    api = open(os.path.join(ROOT, "extension", "content", "api.js"),
               encoding="utf-8").read()
    assert ('_apVerFallback = "%s"' % V) in api
    opts = open(os.path.join(ROOT, "extension", "options.html"),
                encoding="utf-8").read()
    assert ("v%s" % V) in opts


def test_v356_console_version_spots():
    c = console()
    assert "AdvPrint Pro by Bit Dream IT" in c   # v3.5.8 brand title
    assert ('<div class="v">v%s</div>' % V) in c
    assert c.count('(BOOT.version || "%s")' % V) == 3
    a = adv()
    assert "AdvPrint Pro by Bit Dream IT" in a   # v3.5.8 brand title


def test_v356_installer_version_spots():
    nsi = open(os.path.join(ROOT, "installer", "setup.nsi"),
               encoding="utf-8").read()
    assert 'OutFile "../dist/AdvPrint-Pro-Setup-%s.exe"' % V in nsi
    assert 'VIProductVersion "%s.0"' % V in nsi
    assert '"DisplayVersion" "%s"' % V in nsi
    ctrl = open(os.path.join(ROOT, "installer", "deb", "DEBIAN", "control"),
                encoding="utf-8").read()
    assert ("Version: %s" % V) in ctrl


# ---------------- B. ipp:// printer-URI display fix -------------------

def test_v356_row_ipp631_shows_ipp_scheme():
    c = console()
    assert ('ipp://IP:631/ipp/print answers like a real printer') in c
    # the live chip text (JS) uses ipp:// with hubHost() for [v6]
    assert '"ipp://" + hubHost(hubIp()) + ":" + (std.port || 631)' in c
    assert '"http://" + hubHost(hubIp()) + ":" + (std.port || 631)' not in c
    # and the EMBEDDED copy of the UI carries the same fix
    a = adv()
    assert ('ipp://IP:631/ipp/print answers like a real printer') in a
    assert '"ipp://" + hubHost(hubIp())' in a


def test_v356_android_guide_uses_ipp_scheme():
    c = console()
    assert 'id="ippGuideAndroid631">ipp://10.26.94.206:631/ipp/print</span>' in c
    assert '"ipp://" + hubIp() + ":631/ipp/print"' in c
    # the guide EXPLAINS the Android Save-button rule
    assert "Save button" in c and "ipp://" in c
    a = adv()
    assert '"ipp://" + hubIp() + ":631/ipp/print"' in a


def test_v356_windows_add_printer_still_http():
    # Windows' "Add a printer using an IP address" box wants http:// -
    # that guide URL keeps its scheme (both-styles card stays honest)
    c = console()
    assert 'id="ippGuideWin">http://' in c
    assert 'id="ippUrlHttp"' in c


def test_v356_ipp_landing_and_locked_page_show_ipp():
    a = adv()
    # the ipp_landing_html standard-port note is Android-facing
    assert 'Standard port also UP: <code>ipp://' in a
    assert "Android's manual add accepts this scheme" in a
    # the gated-page print hint uses ipp:// too
    seg = a[a.find("_ui_locked_answer"):a.find("_ui_locked_answer") + 5000]
    assert "ipp://" in seg


def test_v356_qr_payload_stays_http():
    # v3.2.6 BUG 5 pin untouched: phone cameras cannot open ipp://
    assert 'url = "http://%s:%d/ipp/print" % (' in adv()
    assert advprint.lan_share_url("ipp").startswith("http://")


def test_v356_twins_byte_identical():
    import filecmp
    for rel in ("hub/advprint.py", "hub/console.html", "hub/gui_app.py"):
        u = os.path.join(ROOT, "tool", "unix", rel)
        w = os.path.join(ROOT, "tool", "windows", "portable", rel)
        assert filecmp.cmp(u, w, shallow=False), rel + " drifted"


# ---------------- C. the LAN admin console feature --------------------

def test_v356_cfg_defaults():
    assert advprint.CFG["ui_admin_mode"] == "lan"
    assert advprint.CFG["admin_ips"] == []
    assert "ui_admin_mode" in advprint.CONFIG_KEYS
    assert "admin_ips" in advprint.CONFIG_KEYS
    assert advprint.CONFIG_TYPES["ui_admin_mode"] is str
    assert advprint.CONFIG_TYPES["admin_ips"] is list


def test_v356_subnet_key_semantics():
    f = advprint._subnet_key
    assert f("192.168.1.57") == (4, "192.168.1.0")
    assert f("192.168.1.200") == (4, "192.168.1.0")
    assert f("192.168.2.1") == (4, "192.168.2.0")
    assert f("::ffff:192.168.1.57") == (4, "192.168.1.0")
    assert f("fd00::1234") == (6, "fd00::")
    assert f("fd00:abcd::1") == (6, "fd00:abcd::")
    assert f("127.0.0.1") is None          # loopback is own-host anyway
    assert f("::1") is None
    assert f("garbage") is None
    assert f("") is None
    assert f(None) is None


def test_v356_admin_matrix_unit():
    ks = {(4, "192.168.1.0"), (4, "10.26.94.0")}
    f = advprint.ui_admin_allows
    # mode lan (factory default): the whole /24 controls the console
    assert f("192.168.1.57", subnet_keys=ks)
    assert f("192.168.1.200", subnet_keys=ks)
    assert not f("10.26.93.1", subnet_keys=ks)
    assert not f("8.8.8.8", subnet_keys=ks)
    # mode self: the exact v3.2.6 lock
    assert not f("192.168.1.57", mode="self", subnet_keys=ks)
    # mode any: everything layer 1 already let in
    assert f("8.8.8.8", mode="any", subnet_keys=ks)
    # admin_ips: exact / CIDR / wildcard, honoured in EVERY mode
    assert f("10.26.93.1", admin_rules=["10.26.93.1"], subnet_keys=ks)
    assert f("10.26.93.1", admin_rules=["10.26.93.0/24"], subnet_keys=ks)
    assert f("10.26.93.1", admin_rules=["10.26.93.*"], subnet_keys=ks)
    assert f("10.26.93.1", mode="self", admin_rules=["10.26.93.1"],
             subnet_keys=ks)
    # CRITICAL: an EMPTY admin list must NEVER widen the gate
    # (ip_allowed_by_list maps [] -> ["*"]; admin_ips must not)
    assert not f("8.8.8.8", admin_rules=[], subnet_keys=ks)
    assert not advprint.admin_ips_hit("8.8.8.8")
    # bogus mode falls back to the factory default, never to "any"
    assert f("192.168.1.57", mode="bogus", subnet_keys=ks)
    assert not f("8.8.8.8", mode="bogus", subnet_keys=ks)


def test_v356_admin_ips_hit_rules():
    advprint.CFG["admin_ips"] = ["192.168.50.2", "10.9.0.0/16", "77.*"]
    try:
        assert advprint.admin_ips_hit("192.168.50.2")
        assert advprint.admin_ips_hit("10.9.44.6")
        assert advprint.admin_ips_hit("77.12.3.4")
        assert not advprint.admin_ips_hit("192.168.50.3")
        assert not advprint.admin_ips_hit("")
    finally:
        advprint.CFG["admin_ips"] = []


class _Stub:
    """Duck-typed Handler for the gate matrix (same as test_v326)."""

    def __init__(self, ip, method):
        self._ip = ip
        self.command = method

    def _client_ip(self):
        return self._ip

    def _is_own_host(self):
        return advprint.Handler._is_own_host(self)


@pytest.fixture()
def gate_env():
    """Freeze own-ip + subnet caches so the matrix is machine-independent."""
    old_own = dict(advprint._OWN_IPS_CACHE)
    old_sub = dict(advprint._SUBNET_CACHE)
    old_mode = advprint.CFG.get("ui_admin_mode")
    old_admins = advprint.CFG.get("admin_ips")
    advprint._OWN_IPS_CACHE["ips"] = {"127.0.0.1", "::1",
                                      "::ffff:127.0.0.1", "10.26.94.206"}
    advprint._OWN_IPS_CACHE["t"] = advprint.time.time() + 999
    advprint._SUBNET_CACHE["keys"] = {(4, "10.26.94.0")}
    advprint._SUBNET_CACHE["t"] = advprint.time.time() + 999
    advprint.CFG["ui_admin_mode"] = "lan"
    advprint.CFG["admin_ips"] = []
    yield
    advprint._OWN_IPS_CACHE.update(old_own)
    advprint._SUBNET_CACHE.update(old_sub)
    advprint.CFG["ui_admin_mode"] = old_mode
    advprint.CFG["admin_ips"] = old_admins


def test_v356_gate_own_host_always_passes(gate_env):
    for ip in ("127.0.0.1", "::1", "10.26.94.206"):
        h = _Stub(ip, "GET")
        assert advprint.Handler._is_own_host(h)
        assert not advprint.Handler._mgmt_locked(h, "/ui")
        assert not advprint.Handler._mgmt_locked(h, "/config")


def test_v356_gate_lan_mode_same_subnet_controls_console(gate_env):
    # the user's exact scenario: a DIFFERENT-IP PC/phone on the SAME
    # network opens the console + settings like the hub PC does
    h = _Stub("10.26.94.57", "GET")
    for route in ("/ui", "/dashboard", "/config", "/stats", "/audit",
                  "/queue", "/history/clear"):
        assert not advprint.Handler._mgmt_locked(h, route), route
    h2 = _Stub("10.26.94.57", "POST")
    for route in ("/config", "/jobs/release_all", "/token/rotate",
                  "/queue/pause"):
        assert not advprint.Handler._mgmt_locked(h2, route), route
    # ...while another SUBNET stays on the print surface only
    s = _Stub("192.168.7.9", "GET")
    assert advprint.Handler._mgmt_locked(s, "/ui")
    assert advprint.Handler._mgmt_locked(s, "/config")
    assert not advprint.Handler._mgmt_locked(s, "/health")
    sp = _Stub("192.168.7.9", "POST")
    assert not advprint.Handler._mgmt_locked(sp, "/print")
    assert advprint.Handler._mgmt_locked(sp, "/config")


def test_v356_gate_self_mode_restores_v326_lock(gate_env):
    advprint.CFG["ui_admin_mode"] = "self"
    h = _Stub("10.26.94.57", "GET")
    assert advprint.Handler._mgmt_locked(h, "/ui")
    # ...but an admin_ips entry STILL gets in (any-mode override)
    advprint.CFG["admin_ips"] = ["10.26.94.57"]
    assert not advprint.Handler._mgmt_locked(h, "/ui")
    assert not advprint.Handler._mgmt_locked(h, "/config")


def test_v356_gate_any_mode(gate_env):
    advprint.CFG["ui_admin_mode"] = "any"
    h = _Stub("203.0.113.5", "GET")
    assert not advprint.Handler._mgmt_locked(h, "/ui")
    assert not advprint.Handler._mgmt_locked(h, "/config")


def test_v356_remote_admin_audited(gate_env, hub):
    advprint.CFG["ui_admin_mode"] = "lan"
    advprint._ACL_AUDIT_TS.clear()
    h = _Stub("10.26.94.57", "GET")
    assert not advprint.Handler._mgmt_locked(h, "/ui")
    code, audit = hub.get("/audit?limit=40")
    assert code == 200
    rows = [r for r in audit.get("entries", [])
            if r.get("event") == "ui.remote_admin"
            and r.get("ip") == "10.26.94.57"]
    assert rows, "a same-network console session must be audited"


def test_v356_config_roundtrip_and_validation(hub):
    old_mode = advprint.CFG.get("ui_admin_mode")
    old_admins = advprint.CFG.get("admin_ips")
    try:
        code, r = hub.post("/config", body={"ui_admin_mode": "any"})
        assert code == 200 and r.get("ok"), r
        assert advprint.CFG["ui_admin_mode"] == "any"
        code, r = hub.post("/config", body={"ui_admin_mode": "banana"})
        assert code == 400 and "ui_admin_mode must be" in r.get("error", "")
        code, r = hub.post("/config",
                           body={"admin_ips": ["192.168.1.2", " 10.9.0.0/16 ",
                                               "", "192.168.1.2",
                                               "x" * 100]})
        assert code == 200, r
        assert advprint.CFG["admin_ips"] == ["192.168.1.2", "10.9.0.0/16",
                                             "x" * 64]
        code, cfg = hub.get("/config")
        assert code == 200
        assert cfg["ui_admin_mode"] == "any"
        assert cfg["admin_ips"] == ["192.168.1.2", "10.9.0.0/16", "x" * 64]
    finally:
        advprint.CFG["ui_admin_mode"] = old_mode
        advprint.CFG["admin_ips"] = old_admins


def test_v356_health_has_admin_fields(hub):
    code, h = hub.get("/health")
    assert code == 200
    assert h["ui_admin_mode"] in ("self", "lan", "any")
    assert isinstance(h["admin_ips"], list)
    assert isinstance(h["ui_admin_subnets"], list)
    assert h["ui_admin_mode"] != "self" or h["ui_admin_urls"] == []


def test_v356_console_admin_card_present():
    c = console()
    # markup
    for el in ("uamSelf", "uamLan", "uamAny", "uamMode", "uamSubnet",
               "adminIpInput", "adminIpAdd", "adminIpList", "uamUrls"):
        assert 'id="%s"' % el in c, el
    # render + wiring + poll hook
    assert "function renderUiAdmin()" in c
    assert "function saveUiAdmin(" in c
    assert "{ ui_admin_mode: mode }" in c
    assert "{ admin_ips: cur }" in c
    assert "renderUiAdmin();   /* v3.5.6: the Console admin access card */" in c
    # the embedded copy of the UI carries the card too
    a = adv()
    assert 'id="uamSelf"' in a
    assert "function renderUiAdmin()" in a


def test_v356_security_note_and_docs_updated():
    c = console()
    assert "Security model (v3.5.6)" in c
    assert "ui.remote_admin" in c
    assert "The console UI is gated (v3.5.6)" in c
    a = adv()
    assert "Security model (v3.5.6)" in a


# ---------------- D. v3.5.5 build kit untouched -----------------------

def test_v356_kit_files_present():
    for rel in ("build.cmd", "scripts/build-all.py", "docs/BUILD-WINDOWS.md",
                "README-BUILDKIT.txt", "docs/BUILD-FROM-SOURCE.md",
                "scripts/bump_356.py"):
        p = os.path.join(ROOT, *rel.split("/"))
        assert os.path.exists(p), "build kit file missing: " + rel


def test_v356_buildall_hardening_carried():
    s = open(os.path.join(ROOT, "scripts", "build-all.py"),
             encoding="utf-8").read()
    for marker in ("def wipe(", "_makensis_abs_script(", "def validate_nsi_refs(",
                   "REQUIRED_TREE_FILES", "EMBEDDED_INSTALL_FILES",
                   "TWIN_FILES", "STAGE_INSTALL_FILES"):
        assert marker in s, marker


def test_v356_required_tree_files_all_present():
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    try:
        import buildall_guard  # not a module - fallback below
    except Exception:
        pass
    sys.path.pop(0)
    # inline re-check instead of importing build-all (it runs code)
    src = open(os.path.join(ROOT, "scripts", "build-all.py"),
               encoding="utf-8").read()
    m = re.search(r"REQUIRED_TREE_FILES = \[(.*?)\]", src, re.S)
    assert m
    files = re.findall(r'"([^"]+)"', m.group(1))
    assert len(files) >= 38
    missing = [f for f in files
               if not os.path.exists(os.path.join(ROOT, f))]
    assert not missing, "missing tree files: %s" % missing
