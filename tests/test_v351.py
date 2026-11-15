"""v3.5.1 - DASHBOARD LIVE DATA (dashboard-only bug fix on the working
v3.5.0 ProTheme base).

The user reported: "in all previous version dashboard data so fake -
it always show 33.3% success and default printer and other this is not
dynamic". Root cause: parts of the ONE UI dashboard were static demo
markup that no render code ever replaced (the hub already returned
every real value). These tests lock the fix:

A. every dashboard dynamic value is id-wired and written by the new
   renderDashboard() (uptime, service, listen, LAN, IPP, RAW, DropZone,
   Connections, token, default printer name/status/hold, recent-jobs
   caption, dashboard subtitle);
B. the old key-guessing "glance" loop is GONE (it left rows static and
   clobbered the IPP row with the mDNS text);
C. the uptime clock actually fires now (read from /stats - /health
   carries no uptime_s);
D. loadConnections publishes the live peer counts; poll refreshes
   DropZone every cycle;
E. no static demo value survives in the served dashboard markup;
F. the embedded CONSOLE_HTML in advprint.py is the SAME fresh console
   (a stale embed would serve the old fake dashboard);
G. the three console.html copies + three advprint.py copies stay
   byte-identical;
H. the usual version coherence 3.5.1 across hub / extension / installer;
I. theme engine still present (v3.5.0 features untouched).
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CONSOLE_PATHS = [
    os.path.join(ROOT, "tool", "unix", "hub", "console.html"),
    os.path.join(ROOT, "tool", "windows", "portable", "hub", "console.html"),
    os.path.join(ROOT, "installer", "stage", "hub", "console.html"),
]
ADV_PATHS = [
    os.path.join(ROOT, "tool", "unix", "hub", "advprint.py"),
    os.path.join(ROOT, "tool", "windows", "portable", "hub", "advprint.py"),
    os.path.join(ROOT, "installer", "stage", "hub", "advprint.py"),
]
# v3.5.3: V follows the manifest (single source of truth) instead of
# a frozen string - the coherence checks below stay meaningful on
# every later release without being edited again.
V = json.load(open(os.path.join(ROOT, "extension", "manifest.json"),
                   encoding="utf-8"))["version"]

# ---------------- A. the dashboard is id-wired + rendered ----------------

DASH_IDS = ["dashSub", "dashUptime", "dashService", "dashListen", "dashLan",
            "dashIpp", "dashRaw", "dashDrop", "dashConn", "dashToken",
            "dpName", "dpStatus", "dpHold", "dashRecentCap"]


def console():
    return open(CONSOLE_PATHS[0], encoding="utf-8").read()


def test_dashboard_ids_present():
    s = console()
    for i in DASH_IDS:
        assert ('id="%s"' % i) in s, i


def test_renderdashboard_exists_and_writes_every_row():
    s = console()
    assert "function renderDashboard(h, st, q, pr){" in s
    assert "function renderDashConn(){" in s
    assert "var dashConnState = null;" in s
    for call in ('setT("dashUptime"', 'setH("dashService"', 'setT("dashListen"',
                 'setH("dashLan"', 'setH("dashToken"', 'setH("dashIpp"',
                 'setH("dashRaw"', 'setH("dashDrop"', 'renderDashConn();',
                 'setT("dpName"', 'setH("dpStatus"', 'setH("dpHold"',
                 '$("dashRecentCap")', '$("dashSub")'):
        assert call in s, call


def test_renderstats_calls_renderdashboard():
    s = console()
    assert "renderDashboard(h, st, q, pr);" in s


# ---------------- B. the old glance loop is gone --------------------------

def test_glance_loop_removed():
    s = console()
    assert 'var glance = qsa("#p-dashboard .kv .k");' not in s
    # the IPP row is never again clobbered by the mDNS text
    assert 'key.indexOf("ipp") >= 0 || key.indexOf("mdns") >= 0' not in s
    assert "printers announce themselves" not in s


# ---------------- C. the uptime clock fires ------------------------------

def test_uptime_read_from_stats():
    s = console()
    assert "(st.uptime_s || h.uptime_s)" in s
    assert "hubStartTime = Date.now() - (st.uptime_s || h.uptime_s) * 1000;" in s
    # the header chip + statusbar both tick from hubStartTime
    assert 'setT("dashUptime", hubStartTime ? "uptime " + fmtUptime(hubStartTime) : "uptime \\u2014");' in s
    assert 'sb[8].textContent = hubStartTime ? "Uptime " + fmtUptime(hubStartTime) : "Uptime \\u2014";' in s


# ---------------- D. connections + dropzone live feeds -------------------

def test_loadconnections_publishes_peer_counts():
    s = console()
    assert ("dashConnState = { pcs: 1 + ((lanPeerState && lanPeerState.configured) ? 1 : 0),"
            in s)
    assert "return !!(p.up || p.alive); }).length };" in s
    assert "renderDashConn();" in s


def test_poll_refreshes_dropzone():
    s = console()
    m = re.search(r"async function poll\(\)\{.*?\n\}", s, re.S)
    assert m, "poll() not found"
    body = m.group(0)
    assert "loadDropzone();" in body
    assert "loadConnections();" in body


# ---------------- E. no static demo values left --------------------------

def test_static_demo_values_replaced_by_id_wired_placeholders():
    """The formerly static values either disappeared or now sit inside
    id-wired elements that renderDashboard() overwrites on every poll."""
    s = console()
    # uptime: the hardcoded 04:12:37 is GONE (placeholder em-dash + id)
    assert "04:12:37" not in s
    assert 'id="dashUptime">uptime \u2014</span>' in s
    # every other former static row keeps its initial sample text only as
    # the fallback INSIDE its id-wired element (verified by DASH_IDS) -
    # assert the sample texts are always paired with an id on the same tag
    for anchor_id, sample in (("dashRecentCap", "last 6 of 38 today"),
                              ("dashConn", "2 peers"),
                              ("dpName", "HP Laser 103 107 108"),
                              ("dashRaw", "10.26.94.206:9100")):
        i = s.find(sample)
        assert i >= 0, sample
        seg = s[max(0, i - 120):i]
        assert 'id="%s"' % anchor_id in seg, (anchor_id, sample)
    # the KPI fallback version shows the current release, not v3.2.1
    assert '<div class="stat"><div class="d">hub</div><div class="v">v' + V + '</div>' in s


# ---------------- F. the embedded console is fresh ------------------------

def test_embedded_console_fresh():
    src = open(ADV_PATHS[0], encoding="utf-8").read()
    m = re.search(r'CONSOLE_HTML = r"""(.*?)\n"""\n', src, re.S)
    assert m, "CONSOLE_HTML block not found"
    emb = m.group(1)
    for i in ("dashUptime", "dpName", "dpHold"):
        assert 'id="%s"' % i in emb, i
    assert "function renderDashboard(h, st, q, pr){" in emb
    assert "(st.uptime_s || h.uptime_s)" in emb
    assert 'var glance = qsa("#p-dashboard .kv .k");' not in emb


# ---------------- G. copies stay byte-identical ---------------------------

def test_console_copies_byte_identical():
    blobs = [open(p, "rb").read() for p in CONSOLE_PATHS]
    assert len(set(blobs)) == 1


def test_advprint_copies_byte_identical():
    blobs = [open(p, "rb").read() for p in ADV_PATHS]
    assert len(set(blobs)) == 1


def test_console_embed_safe():
    s = console()
    assert '"""' not in s.replace('r"""', "")  # no triple quotes in the UI source


# ---------------- H. version coherence 3.5.1 ------------------------------

def test_version_everywhere():
    adv = open(ADV_PATHS[0], encoding="utf-8").read()
    assert 'VERSION = "' + V + '"' in adv
    assert ('VERSION_NAME = ("v' + V) in adv  # name starts with the current version
    assert "RULES TABLE FITS" not in adv.split("CONSOLE_HTML")[0].split("VERSION_NAME")[1][:200]
    # the constants swallowed by nothing - the hub must stay importable
    for k in ("FULL_BRAND", "BRANDING", "IS_WIN = sys.platform", "HIDE = "):
        assert k in adv, k
    vt = open(os.path.join(ROOT, "VERSION.txt"), encoding="utf-8").read()
    assert V in vt
    man = json.load(open(os.path.join(ROOT, "extension", "manifest.json"),
                         encoding="utf-8"))
    assert man["version"] == V
    popup = open(os.path.join(ROOT, "extension", "popup.html"),
                 encoding="utf-8").read()
    assert 'id="ver">v' + V + "</span>" in popup
    i18n = open(os.path.join(ROOT, "extension", "i18n.js"), encoding="utf-8").read()
    assert i18n.count("Version " + V) == 1
    assert i18n.count("\u09b8\u0982\u09b8\u09cd\u0995\u09b0\u09a3 " + V) == 1
    api = open(os.path.join(ROOT, "extension", "content", "api.js"),
               encoding="utf-8").read()
    assert 'var _apVerFallback = "' + V + '";' in api
    nsi = open(os.path.join(ROOT, "installer", "setup.nsi"), encoding="utf-8").read()
    assert 'OutFile "../dist/AdvPrint-Pro-Setup-' + V + '.exe"' in nsi
    assert 'VIProductVersion "' + V + '.0"' in nsi
    assert '"DisplayVersion" "' + V + '"' in nsi
    deb = open(os.path.join(ROOT, "installer", "deb", "DEBIAN", "control"),
               encoding="utf-8").read()
    assert "Version: " + V in deb
    # the boot-json version fallbacks inside the embedded console
    assert emb_fallbacks(adv) == 3


def emb_fallbacks(adv):
    return adv.count('(BOOT.version || "' + V + '")')


# ---------------- I. v3.5.0 theme engine untouched ------------------------

def test_theme_engine_still_present():
    s = console()
    assert "AdvPrint theme engine" in s
    assert "window.AdvTheme" in s
    assert 'id="themeGrid"' in s
    assert 'id="appearanceCard"' in s
    assert s.count('data-theme-set="') >= 7  # 7 themes + system in the menu
