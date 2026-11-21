"""v3.5.8 - REAL WINDOW BUTTONS + BRAND + TAB MEMORY

The owner asked (after v3.5.7 "work fine"):
  1. the fake minimize / maximize / close title-bar buttons must
     CORRECT and ACTUALLY WORK;
  2. the title "AdvPrint Pro - Printing Hub . ALL-IN-ONE Console vX -
     Pro Themes" must be REPLACED by "AdvPrint Pro by Bit Dream IT -
     Innovative Healthcare Solutions";
  3. tab URL path support: click History -> ?path=history in the URL
     -> refresh stays on History; if no path is in the URL the last
     tab is saved internally so a reload still lands on it;
  4. "Dashboard with uuid show no need just Dashboard need" - the
     uuid-looking machine id next to Dashboard (and in the old title
     bar) is gone;
  5. "cmd powershell hiddenly work need no flick any" - the v3.5.7
     SILENT WINDOWS guarantee stays (CREATE_NO_WINDOW everywhere).

Locked here: version coherence 3.5.10, the brand title (exact), the
absence of the old composite title + machine id in the UI source, the
tab-memory source shape, the real window-button source shape + CSS,
byte-identical twins, the release docs.
"""
import json
import os
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V = "3.5.10"
EXT_ID = "likldbkamojokkfdlcjibiljpgbbnohc"
BRAND = "AdvPrint Pro by Bit Dream IT"
BRAND_TITLE = ("AdvPrint Pro by Bit Dream IT "
               "\u2014 Innovative Healthcare Solutions")

CONSOLE_PATHS = [
    os.path.join(ROOT, "tool", "unix", "hub", "console.html"),
    os.path.join(ROOT, "tool", "windows", "portable", "hub", "console.html"),
]
ADV_PATHS = [
    os.path.join(ROOT, "tool", "unix", "hub", "advprint.py"),
    os.path.join(ROOT, "tool", "windows", "portable", "hub", "advprint.py"),
]
TOOL_PATHS = [
    os.path.join(ROOT, "tool", "unix", "hub", "tool.py"),
    os.path.join(ROOT, "tool", "windows", "portable", "hub", "tool.py"),
]

sys.path.insert(0, os.path.join(ROOT, "tool", "windows", "portable", "hub"))
import advprint  # noqa: E402


def console():
    return open(CONSOLE_PATHS[0], encoding="utf-8").read()


def adv():
    return open(ADV_PATHS[0], encoding="utf-8").read()


def embedded_console():
    a = adv()
    OPEN = 'CONSOLE_HTML = r"""'
    i = a.find(OPEN)
    assert i >= 0, "CONSOLE_HTML missing"
    i += len(OPEN)
    j = a.find('\n"""', i)
    assert j > i, "CONSOLE_HTML closing delimiter missing"
    return a[i:j]


# ---------------- A. version coherence 3.5.10 --------------------------

def test_v358_hub_version():
    assert advprint.VERSION == V
    assert advprint.VERSION_NAME.startswith(
        "v3.5.10 (CRX SIGNATURE VERIFIED + LAN ADMIN CONSOLE")
    assert "REAL WINDOW BUTTONS + BRAND + TAB MEMORY" in advprint.VERSION_NAME
    assert "SILENT WINDOWS" in advprint.VERSION_NAME
    assert "CREATE_NO_WINDOW" in advprint.VERSION_NAME
    assert "ipp://" in advprint.VERSION_NAME
    assert "admin_ips" in advprint.VERSION_NAME


def test_v358_version_txt():
    s = open(os.path.join(ROOT, "VERSION.txt"), encoding="utf-8").read()
    assert ("AdvPrint Pro (Advanced Printer) %s - built" % V) in s


def test_v358_extension_version_files():
    m = json.load(open(os.path.join(ROOT, "extension", "manifest.json"),
                       encoding="utf-8"))
    assert m["version"] == V
    popup = open(os.path.join(ROOT, "extension", "popup.html"),
                 encoding="utf-8").read()
    assert ("id=\"ver\">v%s<" % V) in popup
    i18n = open(os.path.join(ROOT, "extension", "i18n.js"),
                encoding="utf-8").read()
    assert i18n.count(V) >= 3
    api = open(os.path.join(ROOT, "extension", "content", "api.js"),
               encoding="utf-8").read()
    assert ('_apVerFallback = "%s"' % V) in api
    opts = open(os.path.join(ROOT, "extension", "options.html"),
                encoding="utf-8").read()
    assert ("v%s" % V) in opts


def test_v358_console_version_spots():
    c = console()
    assert ('<div class="stat"><div class="d">hub</div>'
            '<div class="v">v%s</div>' % V) in c
    assert c.count('(BOOT.version || "%s")' % V) == 3
    assert embedded_console() == c        # embed is byte-fresh


def test_v358_installer_version_spots():
    nsi = open(os.path.join(ROOT, "installer", "setup.nsi"),
               encoding="utf-8").read()
    assert 'OutFile "../dist/AdvPrint-Pro-Setup-%s.exe"' % V in nsi
    assert 'VIProductVersion "%s.0"' % V in nsi
    assert '"DisplayVersion" "%s"' % V in nsi
    control = open(os.path.join(ROOT, "installer", "deb", "DEBIAN",
                                "control"), encoding="utf-8").read()
    assert ("Version: %s" % V) in control


def test_v358_hub_twins_byte_identical():
    assert open(ADV_PATHS[0], "rb").read() == open(ADV_PATHS[1], "rb").read()
    assert open(CONSOLE_PATHS[0], "rb").read() == \
        open(CONSOLE_PATHS[1], "rb").read()
    assert open(TOOL_PATHS[0], "rb").read() == open(TOOL_PATHS[1], "rb").read()


# ---------------- B. the brand title (exact) --------------------------

def test_v358_brand_document_title():
    for src in (console(), embedded_console()):
        assert "<title>%s</title>" % BRAND_TITLE in src
        assert "Pro Themes" not in src


def test_v358_titlebar_brand_only():
    c = console()
    assert ('<div class="t-main">%s <small>\u2014 Innovative Healthcare '
            'Solutions</small></div>' % BRAND) in c
    # the old composite title bar is gone for good
    assert "All-in-One Console" not in c
    # renderFrame never re-introduces version/machine-id into the bar
    assert ('if (t) t.textContent = " \\u2014 Innovative Healthcare '
            'Solutions";') in c
    assert '" \\u00b7 All-in-One Console v"' not in c
    assert '(h.host || BOOT.host || "PC")' not in c


def test_v358_address_bar_and_menubar_brand():
    c = console()
    assert ("http://10.26.94.206:9235/ui \u2014 %s</span>" % BRAND) in c
    assert ('ab.textContent = BASE + "/ui \\u2014 %s"' % BRAND) in c
    assert '"<b>%s</b> \\u00b7 "' % BRAND in c
    assert "ALL-IN-ONE" not in re.sub(r"<!--.*?-->", "", c, flags=re.S)


def test_v358_brand_survives_in_documents():
    # About / docs wording that legitimately keeps "THE ONE UI" wording
    # must still exist for the historical suites (v3.2.x pins)
    assert "THE ONE UI" in console()
    assert "Printing Hub" in console()


# ---------------- C. no machine id on the Dashboard -------------------

def test_v358_dashboard_subtitle_clean():
    c = console()
    assert ('<h2>Dashboard</h2><span class="sub" id="dashSub">live \u00b7 '
            'every feature in ONE window</span>') in c
    assert ('if (sub) sub.textContent = "live \\u00b7 every feature in '
            'ONE window";') in c
    # the machine-id fallback is gone from the subtitle renderer
    assert '(h.host || BOOT.host || "this PC")' not in c


# ---------------- D. tab memory + URL path ----------------------------

def test_v358_tab_memory_source_shape():
    c = console()
    assert 'var AP_TAB_KEY = "ap_console_tab";' in c
    assert "function apTabValid(name){" in c
    assert "function apTabRemember(name){" in c
    assert 'localStorage.setItem(AP_TAB_KEY, name);' in c
    assert 'u.searchParams.set("path", name);' in c
    assert "history.replaceState(null, \"\", u.pathname + \"?\" + " \
           "u.searchParams.toString());" in c
    # ?path wins, then the legacy #tab= hash, then the saved tab
    assert 'searchParams.get("path")' in c
    assert "location.hash.match(/tab=([a-z]+)/)" in c
    assert "localStorage.getItem(AP_TAB_KEY)" in c


def test_v358_showtab_guarded_and_remembering():
    c = console()
    assert "function showTab(name){\n  if (!apTabValid(name)) return;" in c
    assert "  if (name === \"rules\") renderRules();\n  apTabRemember(name);\n}" in c
    # an unknown tab can no longer blank the console
    assert 'if (el) el.classList.add("active");' not in c


def test_v358_old_hash_restore_replaced():
    c = console()
    assert "(function apTabRestore(){" in c
    assert "(function(){\n  var m = location.hash.match" not in c


# ---------------- E. REAL window buttons ------------------------------

def test_v358_window_buttons_real():
    c = console()
    assert "(function winbtnsReal(){" in c
    # minimize = collapse to the title bar, second click restores
    assert 'win.classList.toggle("minimized", on);' in c
    # maximize = real fullscreen, with the in-page fallback
    assert "if (document.fullscreenElement){" in c
    assert "document.exitFullscreen()" in c
    assert "el.requestFullscreen()" in c
    assert "p.catch(softMax)" in c
    # close = real window.close + honest blocked-toast
    assert "    window.close();" in c
    assert "blocked closing this tab" in c
    # title-bar double-click toggles maximize like a desktop app
    assert 'tb.addEventListener("dblclick"' in c
    # leaving fullscreen keeps the frame state in sync
    assert 'document.addEventListener("fullscreenchange"' in c


def test_v358_window_button_css():
    c = console()
    assert ".window.minimized{flex:0 0 auto}" in c
    assert ".window.minimized > :not(.titlebar){display:none !important}" in c
    assert ".window.maxed{border-radius:0 !important;max-width:none !important}" in c
    assert ".desktop.maxed{padding:0 !important}" in c


# ---------------- F. silent windows carried (v3.5.7) ------------------

def test_v358_silent_windows_carried():
    a, t = adv(), open(TOOL_PATHS[0], encoding="utf-8").read()
    assert "HIDE = 0x08000000 if IS_WIN else 0" in a
    assert a.count("creationflags=HIDE") == 21
    assert t.count("creationflags=HIDE") == 6
    assert "CREATE_NO_WINDOW" in advprint.VERSION_NAME
    assert advprint.HIDE == 0              # POSIX: the flag is a no-op


# ---------------- G. release docs pinned ------------------------------

def test_v358_release_docs():
    ch = open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8").read()
    assert ch.count("## v%s" % V) == 1
    assert "REAL WINDOW BUTTONS + BRAND + TAB MEMORY" in ch
    rd = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
    # the v3.5.8 section stays in README; the CURRENT top section
    # follows the running release (v3.5.9 UNBREAKABLE DEB BUILD)
    assert ("## What's new in v3.5.8 (REAL WINDOW BUTTONS + BRAND + "
            "TAB MEMORY)") in rd
    assert ("## What's new in v%s (%s" % (V, "ONE POWER SWITCH")) in rd
    sh = open(os.path.join(ROOT, "START-HERE.txt"), encoding="utf-8").read()
    assert ("AdvPrint Pro (Advanced Printer) v%s - START HERE" % V) in sh
    assert "QUICK NOTE ON v3.5.10" in sh
    rn = os.path.join(ROOT, "docs", "RELEASE-NOTES-v%s.md" % V)
    assert os.path.exists(rn)
    body = open(rn, encoding="utf-8").read()
    assert "REAL WINDOW BUTTONS" in body
    assert "SILENT WINDOWS" in body
    assert os.path.exists(os.path.join(ROOT, "scripts",
                          "smoke_v%s.py" % V.replace(".", "")))


def test_v358_extension_id_stable():
    assert EXT_ID in adv()
    assert advprint.EXT_CRX_ID == EXT_ID


# ---------------- H. the served page boots clean ----------------------

@pytest.mark.parametrize("path", CONSOLE_PATHS)
def test_v358_console_html_wellformed(path):
    html = open(path, encoding="utf-8").read()
    assert html.lstrip().startswith("<!DOCTYPE html>")
    assert html.rstrip().endswith("</html>")
    assert '""' + '"' not in html        # embed safety (no triple quotes)
    for marker in ('class="titlebar"', 'class="winbtn close"',
                   'id="dashSub"', 'AP_TAB_KEY'):
        assert marker in html, marker
