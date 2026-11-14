"""v3.5.0 - PRO THEMES + DASHBOARD DATA VIEW FIXES (on the working
v3.4.8.1 base).

The user asked to apply the Pro Theme UI to the current console design
and ship the full source + docs as v3.5.0.  These tests lock:

A. THE PRO THEME ENGINE is in the served ONE UI
   - 7 themes with their data-theme CSS blocks (Cobalt is the default
     :root, Classic IDM keeps the original v3.2.1 IDM blue alive);
   - light/dark modes (data-mode), density / corners / frame options;
   - the early-apply script runs BEFORE first paint (no flash of the
     wrong theme);
   - the Theme menu (data-theme-set) + Settings > Appearance card
     (themeGrid tiles + reset) + window.AdvTheme API;
   - the icon-tooltip helper for the compact sidebar/toolbar;
   - the state is saved in localStorage under "advprintTheme";
B. the DASHBOARD DATA VIEW fixes
   - the "IPP printer" glance row has its own branch (READY + endpoint)
     and can no longer be hijacked by the mDNS discovery text;
   - an "idle" printer counts as usable in the dashboard stat AND the
     status bar (only a really "offline" printer is down);
   - the In Queue stat no longer double-counts held jobs;
   - progress widths are rounded (no "66.66666666666667%");
C. the REVERTED buggy-3.4.8 rule-editor kind remap STAYS absent
   (value-attribute select, ZPL/Image editor options, web->html alias,
   value-based save) - locked by test_v348, re-checked here because the
   theme source the UI was built from still carried them;
D. NO template-preview layer leaks into the served console;
E. version coherence 3.5.0 across hub copies, embedded consoles,
   extension, installers and VERSION.txt; console copies byte-identical;
F. the local QR generator (additive) is present so QR tiles render
   without the hub.
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONSOLE_PATH = os.path.join(ROOT, "tool", "unix", "hub", "console.html")

THEMES = ("cobalt", "classic", "emerald", "violet", "graphite",
          "midnight", "carbon")


def console():
    return open(CONSOLE_PATH, encoding="utf-8").read()


def embedded(path):
    src = open(os.path.join(ROOT, path), encoding="utf-8").read()
    m = re.search(r'CONSOLE_HTML = r"""(.*?)\n"""', src, re.S)
    assert m, "CONSOLE_HTML block not found in " + path
    return m.group(1)


# ---------------- A. the Pro Theme engine -------------------------------

def test_all_seven_theme_css_blocks():
    s = console()
    for t in THEMES:
        if t == "cobalt":
            # the default theme IS the :root palette
            assert "--blue:#2554d9" in s
        else:
            assert 'html[data-theme="%s"]{' % t in s, t
    assert 'html[data-mode="dark"]{color-scheme:dark}' in s


def test_early_apply_before_first_paint():
    s = console()
    assert "AdvPrint theme engine (early apply" in s
    # head = everything before </head>; being IN head proves the script
    # is parser-blocking and sets the theme before the body's first paint
    head = s.split("</head>")[0]
    assert "AdvPrint theme engine (early apply" in head
    assert "window.AdvTheme=" in head, "early-apply must live in <head>"


def test_theme_state_persisted_in_localstorage():
    s = console()
    assert 'K="advprintTheme"' in s
    assert "localStorage.getItem(K)" in s and "localStorage.setItem(K" in s


def test_theme_menu_and_appearance_card():
    s = console()
    for t in THEMES:
        assert 'data-theme-set="%s"' % t in s, "menu item missing: " + t
    assert 'data-theme-set="system"' in s
    assert 'id="appearanceCard"' in s
    assert 'id="themeGrid"' in s and 'role="radiogroup"' in s
    assert 'id="apprReset"' in s and 'id="themeStatus"' in s
    # the engine block
    assert ("AdvPrint theme engine \u2014 Settings > Appearance + Theme menu"
            in s)
    assert "window.AdvTheme" in s


def test_density_corners_frame_options():
    s = console()
    for attr in ("data-density", "data-corners", "data-frame"):
        assert "html[" + attr in s, attr + " CSS missing"
    assert 'density:"comfortable"' in s and 'corners:"rounded"' in s \
        and 'frame:"framed"' in s


def test_icon_tooltip_helper_present():
    s = console()
    assert "icon-only labels" in s and 'id="uiTip"' in s


def test_legacy_theme_select_row_gone():
    s = console()
    assert "Windows IDM (Blue)</option>" not in s
    assert "<label>THEME</label>" not in s
    assert 'setSel(sels[1], "Windows IDM (Blue)")' not in s


# ---------------- B. dashboard data view fixes --------------------------

def test_ipp_glance_row_has_own_branch():
    s = console()
    assert 'key.indexOf("ipp printer") === 0' in s
    assert "cfgCache.ipp_printer" in s
    # mDNS is its own branch again (no ipp||mdns catch-all)
    assert 'key.indexOf("ipp") >= 0 || key.indexOf("mdns") >= 0' not in s
    assert 'key.indexOf("mdns") >= 0' in s
    assert 'key.indexOf("raw") === 0' in s
    assert 'key.indexOf("dropzone") === 0' in s


def test_idle_printer_counts_as_usable():
    s = console()
    assert s.count('p.status === "ready" || p.status === "idle"') == 2


def test_inqueue_no_double_count():
    s = console()
    assert 'q.pending + (q.held ? " (+" + q.held + ")" : "")' not in s
    assert 'stats[2].querySelector(".v").textContent = q.pending;' in s
    assert '(q.held + " held")' in s


def test_progress_width_rounded():
    s = console()
    assert "round(Math.max(6" in s
    # the old unrounded literal may only appear in the fix's own comment
    for line in s.splitlines():
        if "66.66666666666667%" in line:
            assert "v3.5.0: round" in line, "unrounded width live: " + line.strip()[:90]


# ---------------- C. the reverted kind remap stays absent ---------------

def test_rule_editor_select_has_no_value_attributes():
    s = console()
    assert ('<select class="inp2" id="re-type"><option selected>PDF link'
            '</option><option>Web page</option>'
            '<option>Plain text / stream</option><option>Any</option>'
            '</select>') in s
    # the EDITOR carries no kind value attributes (the rule TEST box
    # legitimately offers page-kind filters - different control)


def test_kind_labels_v347_form():
    assert ('var KIND_LABELS = { "": "Any", pdf: "PDF link", web: "Web page", '
            'text: "Plain text / stream", url: "URL type" };') in console()


def test_no_web_html_alias_anywhere():
    s = console()
    assert 'if (rk === "web") rk = "html";' not in s
    assert 'if (v === "web") v = "html";' not in s
    assert 'html: "Web page"' not in s
    bg = open(os.path.join(ROOT, "extension", "background.js"),
              encoding="utf-8").read()
    assert 'r.kind === "web" ? "html" : r.kind' not in bg


def test_save_rule_positional_kind_intact():
    s = console()
    assert ('kind: ["", "pdf", "web", "text"][$("re-type").selectedIndex] '
            '!== undefined') in s
    assert 'setSel($("re-type"), KIND_LABELS[r.kind] || "Any");' in s


# ---------------- D. no template preview layer leaks --------------------

def test_no_preview_layer_in_served_console():
    s = console()
    for marker in ("__AP_TPL__", "apTplChip", "cannedServed",
                   "TEMPLATE PREVIEW", "TEMPLATE LAYER"):
        assert marker not in s, marker + " leaked into the real console"
    assert "__ADVPRINT_BOOT_JSON__" in s  # hub injects the real boot JSON


# ---------------- E. version coherence ----------------------------------

def test_console_copies_byte_identical():
    a = os.path.join(ROOT, "tool", "unix", "hub", "console.html")
    b = os.path.join(ROOT, "tool", "windows", "portable", "hub", "console.html")
    assert open(a, "rb").read() == open(b, "rb").read()


def test_embedded_consoles_are_the_v350_theme_console():
    disk = open(CONSOLE_PATH, encoding="utf-8").read()
    for path in ("tool/unix/hub/advprint.py",
                 "tool/windows/portable/hub/advprint.py",
                 "installer/stage/hub/advprint.py"):
        emb = embedded(path)
        assert emb == disk, "stale embedded console: " + path


def test_version_350_everywhere():
    adv = open(os.path.join(ROOT, "tool", "unix", "hub", "advprint.py"),
               encoding="utf-8").read()
    assert 'VERSION = "3.5.0"' in adv
    assert 'VERSION_NAME = ("v3.5.0 (PRO THEMES' in adv
    man = json.load(open(os.path.join(ROOT, "extension", "manifest.json")))
    assert man["version"] == "3.5.0"
    vt = open(os.path.join(ROOT, "VERSION.txt"), encoding="utf-8").read()
    assert vt.startswith("AdvPrint Pro (Advanced Printer) 3.5.0")
    nsi = open(os.path.join(ROOT, "installer", "setup.nsi"),
               encoding="utf-8").read()
    assert 'VIProductVersion "3.5.0.0"' in nsi
    assert '"DisplayVersion" "3.5.0"' in nsi
    # both hub copies carry the same VERSION
    win = open(os.path.join(ROOT, "tool", "windows", "portable", "hub",
                            "advprint.py"), encoding="utf-8").read()
    assert 'VERSION = "3.5.0"' in win


def test_v350_version_surfaces_in_console():
    s = console()
    assert "Console v3.5.0" in s
    assert 'BOOT.version || "3.5.0"' in s
    assert "AdvPrint Pro hub v3.5.0 started" in s
    # no stale "current" version strings
    for line in s.splitlines():
        if "3.2.1" in line or "3.4.8" in line:
            assert any(k in line for k in
                       ("v3.2.", "rev-4", "v3.4.7", "v3.4.8 TABLE FIT",
                        "v3.4.8: clamp", "v3.4.7", "v3.4.8 KIND",
                        "3.4.8 attempt")), \
                "stale current-version line: " + line.strip()[:100]


# ---------------- F. local QR generator ---------------------------------

def test_local_qr_generator_present():
    s = console()
    assert "window.apQRsvg" in s
    assert "v3.5.0 LOCAL QR GENERATOR" in s
