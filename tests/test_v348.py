"""v3.4.8 - RULES TABLE FITS (layout-only release on the working v3.4.7 base).

The user reported the previous v3.4.8 attempt "not work, fully bug" and
asked to REVERT to the working v3.4.7 build.  This release therefore
contains EXACTLY ONE functional change - the ONE UI rules-table layout
fix - plus the version bump.  These tests lock BOTH sides:

A. the table fix is present (headers wrap, compact rules table,
   .tbl-wrap horizontal scroll inside the card, content-cell clamp);
B. the REVERTED risky changes stay absent (rule-editor kind remapping,
   run-bookkeeping push, /rules/test GET/POST signature change) - so a
   future build cannot silently re-introduce them;
C. the installer runtime is still bundled (the buggy attempt lost
   python311.zip, which would ship a Setup EXE without Python);
D. the usual version coherence 3.4.8 across hub / extension / installer.
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tool", "unix", "hub"))

CONSOLE_PATH = os.path.join(ROOT, "tool", "unix", "hub", "console.html")


def console():
    return open(CONSOLE_PATH, encoding="utf-8").read()


# ---------------- A. the table fix is present ---------------------------

def test_tbl_wrap_css_present():
    s = console()
    assert ".tbl-wrap{overflow-x:auto}" in s
    assert ".tbl.compact th,.tbl.compact td{padding:6px 6px}" in s
    assert ".tbl.compact .doc{max-width:118px}" in s


def test_headers_may_wrap():
    s = console()
    assert "white-space:normal;vertical-align:bottom" in s
    assert re.search(r"\.tbl th\{[^}]*white-space:normal", s)


def test_rules_table_compact_and_wrapped():
    s = console()
    assert '<div class="tbl-wrap"><table class="tbl compact" style="font-size:10px">' in s
    # measured column widths
    for w in ('style="width:22px"', 'style="min-width:58px"',
              'style="min-width:80px"', 'style="min-width:70px"',
              'style="width:26px"', 'style="width:46px"',
              'style="width:52px"', 'style="width:84px"'):
        assert w in s, w


def test_all_one_ui_tables_wrapped_mtable_untouched():
    s = console()
    assert s.count('<div class="tbl-wrap"><table class="tbl') == 13
    assert '<div class="tbl-wrap"><table class="mtable">' not in s
    assert '<table class="mtable">' in s


def test_render_rules_clamps_content_cell():
    s = console()
    assert 'td[4].className = "doc";' in s
    assert 'td[4].setAttribute("style", "max-width:100px;font-weight:500");' in s
    assert 'td[4].removeAttribute("style");' in s


def test_console_copies_byte_identical():
    a = os.path.join(ROOT, "tool", "unix", "hub", "console.html")
    b = os.path.join(ROOT, "tool", "windows", "portable", "hub", "console.html")
    assert open(a, "rb").read() == open(b, "rb").read()


def test_embedded_console_fresh():
    """The CONSOLE_HTML embedded in advprint.py must be the patched one."""
    src = open(os.path.join(ROOT, "tool", "unix", "hub", "advprint.py"),
               encoding="utf-8").read()
    m = re.search(r'CONSOLE_HTML = r"""(.*?)\n"""', src, re.S)
    assert m, "CONSOLE_HTML block not found"
    emb = m.group(1)
    assert '<div class="tbl-wrap"><table class="tbl compact"' in emb
    assert 'BOOT.version || "3.4.8"' in emb


# ---------------- B. the reverted risky changes stay absent --------------

def test_rule_editor_select_unchanged_from_347():
    """The v3.4.7 select carries NO value attributes - the buggy remap
    (value=pdf/web/... + ZPL/Image options) must stay reverted."""
    s = console()
    assert ('<select class="inp2" id="re-type"><option selected>PDF link</option>'
            '<option>Web page</option><option>Plain text / stream</option>'
            '<option>Any</option></select>') in s


def test_kind_labels_unchanged_from_347():
    assert ('var KIND_LABELS = { "": "Any", pdf: "PDF link", web: "Web page", '
            'text: "Plain text / stream", url: "URL type" };') in console()


def test_save_rule_has_no_kind_iife():
    """The buggy build wrapped saveRule in an IIFE - must not return."""
    s = console()
    assert "saveRule normalizes" not in s
    assert 'r.kind === "web" ? "html" : r.kind' not in s


def test_background_js_has_no_web_alias():
    src = open(os.path.join(ROOT, "extension", "background.js"),
               encoding="utf-8").read()
    assert 'r.kind === "web" ? "html" : r.kind' not in src
    assert "last_run: (s && s.lastRun)" not in src


def test_rules_test_handler_single_form():
    """The /rules/test route still answers the plain v3.4.7 engine call."""
    src = open(os.path.join(ROOT, "tool", "unix", "hub", "advprint.py"),
               encoding="utf-8").read()
    assert "res = rule_test_result(u_test)" in src
    assert 'res = rule_test_result(\n' not in src


# ---------------- C. the installer runtime is still bundled --------------

def test_python_runtime_present():
    """The FULL unpacked runtime must still be bundled (the buggy 3.4.8
    attempt deleted it -> Setup EXE without Python)."""
    rt = os.path.join(ROOT, "tool", "windows", "portable", "installer",
                      "runtime")
    z = os.path.join(rt, "python311.zip")
    assert os.path.isfile(z), "python311.zip missing - Setup EXE would break"
    assert os.path.getsize(z) > 3 * 1024 * 1024
    files = os.listdir(rt)
    assert len(files) >= 30, f"runtime truncated: only {len(files)} files"
    assert "AdvPrintPro.exe" in files, "pythonw-clone launcher missing"


# ---------------- D. version coherence 3.4.8 -----------------------------

def test_version_everywhere():
    adv = open(os.path.join(ROOT, "tool", "unix", "hub", "advprint.py"),
               encoding="utf-8").read()
    assert 'VERSION = "3.4.8"' in adv
    assert 'VERSION_NAME = ("v3.4.8 (RULES TABLE FITS' in adv
    assert "CONFIGURABLE HUB PORT" in adv  # historical keyword kept
    vt = open(os.path.join(ROOT, "VERSION.txt"), encoding="utf-8").read()
    assert "3.4.8" in vt
    man = json.load(open(os.path.join(ROOT, "extension", "manifest.json"),
                         encoding="utf-8"))
    assert man["version"] == "3.4.8"
    popup = open(os.path.join(ROOT, "extension", "popup.html"),
                 encoding="utf-8").read()
    assert 'id="ver">v3.4.8</span>' in popup
    i18n = open(os.path.join(ROOT, "extension", "i18n.js"),
                encoding="utf-8").read()
    assert i18n.count("3.4.8") >= 2  # brandLine en + bn
    api = open(os.path.join(ROOT, "extension", "content", "api.js"),
               encoding="utf-8").read()
    assert 'var _apVerFallback = "3.4.8";' in api
    nsi = open(os.path.join(ROOT, "installer", "setup.nsi"),
               encoding="utf-8").read()
    assert 'OutFile "../dist/AdvPrint-Pro-Setup-3.4.8.exe"' in nsi
    assert 'VIProductVersion "3.4.8.0"' in nsi
    assert '"DisplayVersion" "3.4.8"' in nsi
