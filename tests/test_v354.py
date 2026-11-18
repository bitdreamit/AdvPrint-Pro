"""v3.5.4 - CRX SIGNATURE VERIFIED (full release)

v3.5.3 kept the status bar always visible but shipped its .crx with a
STALE signature - the CRX3 header was signed over an older zip than the
archive actually packed inside, and Chrome refused the file with "CRX
signature verification failed" while the 3.5.2 crx kept working. This
suite locks the v3.5.4 full release:

A. the CRX is signed and verified:
   - tool/crx3.py carries the Chrome-identical verify command
     ("CRX3 SignedData\\0" context) and the stable-key pack path;
   - scripts/build-all.sh hard-fails the build unless the CRX
     signature matches the archive inside;
   - every shipped CRX copy (prebuilt/ + both hub embeds) verifies
     with payload version 3.5.4 and the STABLE extension ID
     likldbkamojokkfdlcjibiljpgbbnohc;
B. the v3.5.3 statusbar fix is untouched in every console copy:
   body{margin:0}, .desktop/.window box-sizing:border-box, the
   statusbar stays the last frame child (flex:0 0 auto);
C. the embedded CONSOLE_HTML equals the standalone console.html and
   the three console + three advprint copies stay byte-identical;
D. the usual version coherence 3.5.4 (hub / extension / installer);
E. v3.5.2 fixes untouched: success rate math, save-password CSS,
   date-wise filter, per-row View button, date+time rows.
"""
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V = "3.5.9"
EXT_ID = "likldbkamojokkfdlcjibiljpgbbnohc"

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
CRX_PATHS = [
    os.path.join(ROOT, "prebuilt", "AdvPrint-Pro.crx"),
    os.path.join(ROOT, "tool", "unix", "hub", "extension", "AdvPrint-Pro.crx"),
    os.path.join(ROOT, "tool", "windows", "portable", "hub", "extension",
                 "AdvPrint-Pro.crx"),
]


def console():
    return open(CONSOLE_PATHS[0], encoding="utf-8").read()


def adv():
    return open(ADV_PATHS[0], encoding="utf-8").read()


def crx3mod():
    sys.path.insert(0, os.path.join(ROOT, "tool"))
    import crx3
    return crx3


# ---------------- A. the CRX is signed and verified ----------------

def test_crx3_tool_has_chrome_identical_verify():
    src = open(os.path.join(ROOT, "tool", "crx3.py"), encoding="utf-8").read()
    assert 'SIGNATURE_CONTEXT = b"CRX3 SignedData\\x00"' in src, \
        "crx3.py must sign/verify with Chromium's exact context"
    assert 'choices=("pack", "info", "verify")' in src, \
        "crx3.py must expose the verify CLI"
    assert "def verify_crx(" in src


def test_build_all_has_hard_signature_gate():
    s = open(os.path.join(ROOT, "scripts", "build-all.sh"),
             encoding="utf-8").read()
    assert "crx3.py verify" in s, \
        "build-all.sh must run the CRX signature verification"
    assert "refusing to ship" in s, \
        "the verification must be a HARD gate (exit non-zero)"


def test_every_crx_copy_verifies_354():
    crx3 = crx3mod()
    for p in CRX_PATHS:
        assert os.path.exists(p), "missing CRX copy: " + p
        info = crx3.crx_info(p)
        assert info["extension_id"] == EXT_ID, \
            "extension ID must stay stable: " + p
        assert info["version"] == V, "CRX payload must be " + V + ": " + p
        out = subprocess.run(
            [sys.executable, os.path.join(ROOT, "tool", "crx3.py"),
             "verify", p, V],
            capture_output=True, text=True)
        assert out.returncode == 0, \
            "signature verification failed for %s:\n%s%s" % (
                p, out.stdout, out.stderr)


def test_all_crx_copies_byte_identical():
    blobs = [open(p, "rb").read() for p in CRX_PATHS]
    assert len(blobs) == 3 and len(set(blobs)) == 1, \
        "prebuilt + both hub embeds must be the same signed package"


def test_stable_key_still_in_tree():
    pem = os.path.join(ROOT, "extension-signing", "advprint-printer.pem")
    assert os.path.exists(pem), "the stable release key must stay in the tree"
    crx3 = crx3mod()
    spki = crx3.spki_from_private_pem(open(pem, "rb").read())
    assert crx3.crx_id_from_spki(spki) == EXT_ID, \
        "the tree key must keep deriving the SAME extension ID"


# ---------------- B. the v3.5.3 statusbar fix is untouched ---------

def test_body_margin_reset():
    s = console()
    m = re.search(r"^body\{([^}]*)\}", s, re.M)
    assert m and "margin:0" in m.group(1)


def test_desktop_and_window_border_box():
    s = console()
    m = re.search(r"^\.desktop\{([^}]*)\}", s, re.M)
    assert m and "box-sizing:border-box" in m.group(1)
    assert "height:100vh" in m.group(1) and "padding:14px" in m.group(1)
    m = re.search(r"^\.window\{.*?\}\n", s, re.M | re.S)
    assert m and "box-sizing:border-box" in m.group(0)
    assert "min-height:0" in m.group(0)


def test_statusbar_still_last_frame_child():
    s = console()
    body_pos = s.index('<div class="body">')
    statusbar_pos = s.index('<div class="statusbar">')
    main_close = s.index("</main>", body_pos)
    assert body_pos < main_close < statusbar_pos
    m = re.search(r"^\.statusbar\{([^}]*)\}", s, re.M)
    assert m and "flex:0 0 auto" in m.group(1)


# ---------------- C. embedded == standalone, copies identical -------

def test_embedded_console_matches_standalone():
    m = re.search(r'CONSOLE_HTML = r"""(.*?)"""', adv(), re.S)
    assert m.group(1) == console() + "\n"
    assert "AdvPrint Pro by Bit Dream IT" in m.group(1)  # v3.5.8 brand


def test_console_copies_byte_identical():
    blobs = [open(p, "rb").read() for p in CONSOLE_PATHS if os.path.exists(p)]
    assert len(blobs) >= 2 and len(set(blobs)) == 1


def test_advprint_copies_byte_identical():
    blobs = [open(p, "rb").read() for p in ADV_PATHS if os.path.exists(p)]
    assert len(blobs) >= 2 and len(set(blobs)) == 1


# ---------------- D. version coherence 3.5.4 ------------------------

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
    assert i18n.count(V) == 3  # header + EN + BN brand lines
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
    assert "AdvPrint Pro by Bit Dream IT" in a   # v3.5.8 brand title
    assert '<div class="stat"><div class="d">hub</div><div class="v">v' \
        + V + '</div>' in console()
    readme = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
    assert "What's new in v" + V in readme
    start = open(os.path.join(ROOT, "START-HERE.txt"),
                 encoding="utf-8").read()
    assert start.startswith("AdvPrint Pro (Advanced Printer) v" + V)


# ---------------- E. v3.5.2 fixes untouched --------------------------

def test_v352_fixes_still_present():
    s = console()
    assert "v3.5.2 REAL SUCCESS RATE" in s
    assert ".tok-mask{-webkit-text-security:disc}" in s
    assert "histDateFetch" in s
    assert "/file?view=1" in s
    assert "date_from" in s
    a = adv()
    assert "printed" in a and "saved" in a


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-q", "--no-header", "-p", "no:cacheprovider"]))
