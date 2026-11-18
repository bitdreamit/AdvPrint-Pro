"""v3.5.3 - STATUS BAR ALWAYS VISIBLE (the bottom bar stays on screen)

v3.5.2 was confirmed working; the user then reported the last layout
bug: the status bar (Hub Running / IP:port / Printers / Queue /
History / LAN / DropZone / Uptime / version) rendered BELOW the
viewport bottom edge - "outside bottom, not showing". This suite locks
the fix and proves nothing else moved:

A. the root-cause CSS is fixed in EVERY console copy:
   - body{margin:0} (the UA default 8px margin pushed the frame down)
   - .desktop{...box-sizing:border-box} (100vh is the REAL height)
   - .window{...box-sizing:border-box} (the 1px border adds no height)
B. the fix is present in the EMBEDDED CONSOLE_HTML inside advprint.py
   (the copy the hub actually serves at /ui);
C. the embedded payload still equals the standalone console.html;
D. the three console.html + three advprint.py copies stay
   byte-identical (stage copy optional - build artifact);
E. the usual version coherence 3.5.3 (hub / extension / installer);
F. v3.5.2 fixes untouched: success rate math, save-password CSS,
   date-wise filter, per-row View button, date+time rows.
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
V = "3.5.6"  # follows the current release (v3.5.5 bump)


def console():
    return open(CONSOLE_PATHS[0], encoding="utf-8").read()


def adv():
    return open(ADV_PATHS[0], encoding="utf-8").read()


# ---------------- A. the statusbar fix itself ----------------

def test_body_margin_reset():
    s = console()
    m = re.search(r"^body\{([^}]*)\}", s, re.M)
    assert m, "body{...} rule not found"
    assert "margin:0" in m.group(1), \
        "body must reset the UA default margin (the 8px push)"


def test_desktop_border_box():
    s = console()
    m = re.search(r"^\.desktop\{([^}]*)\}", s, re.M)
    assert m, ".desktop{...} rule not found"
    assert "box-sizing:border-box" in m.group(1), \
        ".desktop must be border-box so height:100vh includes the padding"
    assert "height:100vh" in m.group(1)
    assert "padding:14px" in m.group(1)


def test_window_border_box():
    s = console()
    m = re.search(r"^\.window\{.*?\}\n", s, re.M | re.S)
    assert m, ".window{...} rule not found"
    assert "box-sizing:border-box" in m.group(0), \
        ".window must be border-box so its 1px border adds no height"
    assert "min-height:0" in m.group(0), ".window must stay shrinkable"


def test_statusbar_still_last_frame_child():
    s = console()
    body_pos = s.index('<div class="body">')
    statusbar_pos = s.index('<div class="statusbar">')
    main_close = s.index("</main>", body_pos)
    assert body_pos < main_close < statusbar_pos, \
        "the statusbar must stay the last child of the window frame"
    m = re.search(r"^\.statusbar\{([^}]*)\}", s, re.M)
    assert m and "flex:0 0 auto" in m.group(1), \
        ".statusbar must stay flex:0 0 auto inside the column flex"


# ---------------- B. the embedded copy carries the fix ----------------

def test_embedded_console_carries_fix():
    a = adv()
    m = re.search(r'CONSOLE_HTML = r"""(.*?)"""', a, re.S)
    emb = m.group(1)
    assert "body{margin:0;" in emb
    assert ".desktop{height:100vh;box-sizing:border-box;" in emb
    assert "ALL-IN-ONE Console v" + V in emb


# ---------------- C. embedded == standalone ----------------

def test_embedded_matches_standalone():
    m = re.search(r'CONSOLE_HTML = r"""(.*?)"""', adv(), re.S)
    assert m.group(1) == console() + "\n"


# ---------------- D. copies byte-identical ----------------

def test_console_copies_byte_identical():
    blobs = [open(p, "rb").read() for p in CONSOLE_PATHS if os.path.exists(p)]
    assert len(blobs) >= 2
    assert len(set(blobs)) == 1


def test_advprint_copies_byte_identical():
    blobs = [open(p, "rb").read() for p in ADV_PATHS if os.path.exists(p)]
    assert len(blobs) >= 2
    assert len(set(blobs)) == 1


# ---------------- E. version coherence 3.5.3 ----------------

def test_version_everywhere():
    a = adv()
    assert 'VERSION = "' + V + '"' in a
    assert 'VERSION_NAME = ("v' + V + ' (CRX SIGNATURE VERIFIED' in a
    vt = open(os.path.join(ROOT, "VERSION.txt"), encoding="utf-8").read()
    assert V in vt
    man = json.load(open(os.path.join(ROOT, "extension", "manifest.json"),
                         encoding="utf-8"))
    assert man["version"] == V
    popup = open(os.path.join(ROOT, "extension", "popup.html"),
                 encoding="utf-8").read()
    assert 'id="ver">v' + V + "</span>" in popup
    i18n = open(os.path.join(ROOT, "extension", "i18n.js"),
                encoding="utf-8").read()
    assert i18n.count("Version " + V) == 1
    api = open(os.path.join(ROOT, "extension", "content", "api.js"),
               encoding="utf-8").read()
    assert 'var _apVerFallback = "' + V + '";' in api
    nsi = open(os.path.join(ROOT, "installer", "setup.nsi"),
               encoding="utf-8").read()
    assert 'OutFile "../dist/AdvPrint-Pro-Setup-' + V + '.exe"' in nsi
    assert 'VIProductVersion "' + V + '.0"' in nsi
    assert '"DisplayVersion" "' + V + '"' in nsi
    deb = open(os.path.join(ROOT, "installer", "deb", "DEBIAN", "control"),
               encoding="utf-8").read()
    assert "Version: " + V in deb
    assert a.count('(BOOT.version || "' + V + '")') == 3
    assert "ALL-IN-ONE Console v" + V in a
    assert '<div class="stat"><div class="d">hub</div><div class="v">v' + V + '</div>' in console()


# ---------------- F. v3.5.2 fixes untouched ----------------

def test_v352_fixes_still_present():
    s = console()
    # real success rate (counts behind the percentage)
    assert "v3.5.2 REAL SUCCESS RATE" in s
    # save-password fix (CSS-masked token boxes + autocomplete off)
    assert ".tok-mask{-webkit-text-security:disc}" in s
    # date+time rows
    assert "histDateFetch" in s
    # per-row View button + server-side date filter
    assert "/file?view=1" in s
    assert "date_from" in s
    a = adv()
    assert 'VERSION = "' + V + '"' in a
    # success math: printed + saved, canceled excluded
    assert "printed" in a and "saved" in a


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-q", "--no-header", "-p", "no:cacheprovider"]))
