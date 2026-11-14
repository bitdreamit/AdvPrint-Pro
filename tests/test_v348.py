"""v3.4.8 - RULES TABLE FITS (EDIT BUTTON NEVER LEAVES THE CARD) +
RULE EDITOR URL-TYPE SAVES REAL KINDS + RUN BOOKKEEPING SYNCED.

The user reported (with the column list "Rule / URL / address filter /
Match by / Page content / URL type / Printer / What to print / Cpl /
Paper / On / Auto / Runs") that "th so td outside when paper or other
extra selected edit button goes outside". Measured on v3.4.7: the
14-column rules table forced a 1145px minimum width through the nowrap
headers inside a 990px card - the Runs column AND the Edit/Del buttons
rendered outside the card border (editRight 1399 > card right 1245).
Every fix is locked here, plus the A-to-Z audit gaps:

 1. TABLE FIT (the reported bug)
    - .tbl headers may wrap (white-space:normal), the rules table is
      compact (tighter cells, shrunken min-widths)
    - the pattern + page-content cells clamp with an ellipsis
    - EVERY ONE UI table sits in a .tbl-wrap that scrolls horizontally
      INSIDE the card as a last resort (13/13 wrapped)

 2. RULE EDITOR URL-TYPE KIND FIX (audit gap)
    - the old saveRule mapped the select positionally with the array
      ["", "pdf", "web", "text"]: PDF link saved kind "" (Any),
      Web page saved kind "pdf", Plain text saved kind "web", Any
      saved kind "text" - and "web" is a kind detectTabKind NEVER
      answers (pdf | image | zpl | text | html), so a "Web page"
      content rule could never fire
    - the select now carries real VALUES (pdf / web / text / zpl /
      image / ""), ZPL label page + Image page joined the list
    - saveRule normalizes "web" -> "html" and defaults a content rule
      left on Any to html (a content rule without a kind is skipped)
    - BOTH matchers accept legacy kind "web" as "html"
      (extension matchRule + hub rule_matches)

 3. RUN BOOKKEEPING SYNCED (audit gap)
    - the extension pushed only the runs counter, the hub cleaner
      dropped last_run + title - the ONE UI "last HH:MM" never showed
    - rulesWithRuns pushes last_run now; the cleaner keeps title and
      last_run on central edits

 4. VERSION 3.4.8 everywhere + the embedded console is fresh.
"""
import json
import os
import re

import pytest

import advprint

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXT = os.path.join(ROOT, "extension")

CONSOLE = advprint.CONSOLE_HTML
DASHBOARD = advprint.DASHBOARD_HTML
ADVPRINT_SRC = advprint.__source_text__ if hasattr(advprint, "__source_text__") else ""


def _src():
    path = advprint.__file__
    return open(path, encoding="utf-8").read()


BGJS = open(os.path.join(EXT, "background.js"), encoding="utf-8").read()


# ------------------------------------------------------------
# 1. the reported bug: the rules table fits + nothing leaves the card
# ------------------------------------------------------------
def test_rules_table_is_compact_and_wrapped():
    m = re.search(r'<div class="tbl-wrap">\s*<table class="tbl compact"'
                  r'[^>]*>', CONSOLE)
    assert m, "the 14-column rules table must be class 'tbl compact' " \
              "and sit inside a .tbl-wrap"
    # every header of the user's column list is still there
    hdr = re.search(r'<table class="tbl compact".*?<tr>(.*?)</tr>',
                    CONSOLE, re.S).group(1)
    for col in ("Rule", "URL / address filter", "Match by", "Page content",
                "URL type", "Printer", "What to print", "Cpl", "Paper",
                "On", "Auto", "Runs"):
        assert ">" + col + "<" in hdr or ">" + col + " </" in hdr or \
            col in hdr, "rules header lost column %s" % col


def test_every_oneui_table_has_the_scroll_wrapper():
    tables = re.findall(r'<table class="tbl[^>]*>', CONSOLE)
    wraps = re.findall(r'<div class="tbl-wrap">', CONSOLE)
    assert len(tables) == 13, "expected 13 ONE UI tables, got %d" % len(tables)
    assert len(wraps) == 13, "every ONE UI table must sit in a .tbl-wrap " \
        "(got %d wraps for %d tables)" % (len(wraps), len(tables))
    # each table must be IMMEDIATELY preceded by its wrapper
    for m in re.finditer(r'<table class="tbl[^>]*>', CONSOLE):
        pre = CONSOLE[max(0, m.start() - 40):m.start()]
        assert 'tbl-wrap' in pre, "a table renders without its wrapper"


def test_tbl_headers_may_wrap_and_compact_cells():
    th = re.search(r'\.tbl th\{[^}]*\}', CONSOLE).group(0)
    assert "white-space:normal" in th, \
        "headers must be allowed to wrap (the old nowrap forced 1145px)"
    assert ".tbl-wrap{overflow-x:auto}" in CONSOLE
    assert ".tbl.compact th,.tbl.compact td{padding:6px 6px}" in CONSOLE


def test_rendered_rule_cells_clamp_long_text():
    assert 'td[4].className = "doc"' in CONSOLE, \
        "the page-content cell must clamp with the .doc ellipsis"
    assert 'max-width:100px' in CONSOLE, "content clamp width missing"
    # the pattern cell keeps its demo clamp
    assert 'class="mono doc" style="max-width:112px' in CONSOLE


def test_dashboard_rules_ui_untouched():
    # the classic dashboard has no rules table; make sure its tables
    # were not touched by the wrapper pass
    assert '<div class="tbl-wrap">' not in DASHBOARD


# ------------------------------------------------------------
# 2. the rule editor saves REAL kinds now
# ------------------------------------------------------------
def test_url_type_select_carries_values():
    sel = re.search(r'<select class="inp2" id="re-type">(.*?)</select>',
                    CONSOLE, re.S).group(1)
    opts = re.findall(r'<option value="([^"]*)"', sel)
    assert opts == ["pdf", "web", "text", "zpl", "image", ""], opts
    assert "ZPL label page" in sel and "Image page" in sel


def test_saverule_normalizes_web_and_defaults_content_to_html():
    assert 'if (v === "web") v = "html";' in CONSOLE
    assert 'if ($("re-content").value.trim() && !v) v = "html";' in CONSOLE
    assert '["pdf", "html", "text", "zpl", "image", ""]' in CONSOLE
    # the old positional (shifted) mapping is gone
    assert '["", "pdf", "web", "text"]' not in CONSOLE
    # match no longer depends on a select index
    assert 'match: $("re-content").value.trim() ? "content" : "url",' \
        in CONSOLE


def test_editor_opens_by_value_not_label():
    assert 'var rt = $("re-type"), rk = String(r.kind || "");' in CONSOLE
    assert 'if (rk === "web") rk = "html";' in CONSOLE


def test_kind_labels_cover_every_detected_kind():
    assert 'html: "Web page"' in CONSOLE
    assert 'zpl: "ZPL label page"' in CONSOLE
    assert 'image: "Image page"' in CONSOLE
    assert 'web: "Web page"' in CONSOLE          # legacy display alias


def test_hub_matcher_aliases_legacy_web_kind():
    rule = {"match": "content", "kind": "web", "pattern": "*", "on": True}
    assert advprint.rule_matches(rule, "https://x/", "", "html") is True
    assert advprint.rule_matches(rule, "https://x/", "", "text") is False
    html_rule = {"match": "content", "kind": "html", "pattern": "*"}
    assert advprint.rule_matches(html_rule, "https://x/", "", "html") is True
    # a content rule without a kind never matches (unchanged semantics)
    assert advprint.rule_matches({"match": "content", "pattern": "*"},
                                 "https://x/", "", "html") is False


def test_extension_matcher_aliases_legacy_web_kind():
    assert 'const wantKind = r.kind === "web" ? "html" : r.kind;' in BGJS


def test_rules_test_endpoint_understands_the_alias(hub):
    rules = [{"id": 1, "name": "Web page rule", "pattern": "*",
              "match": "content", "kind": "web", "printer": "Zebra",
              "on": True}]
    code, r = hub.post("/config", {"rules_mirror": rules})
    assert code == 200 and r.get("ok"), r
    try:
        code, t = hub.get("/rules/test?url=https://anything.example.com/x"
                          "&kind=html")
        assert code == 200
        assert t.get("matched") and \
            t["rule"].get("name") == "Web page rule", t
        code, t2 = hub.get("/rules/test?url=https://anything.example.com/x"
                           "&kind=text")
        assert code == 200 and not t2.get("matched")
    finally:
        # leave the session hub clean - a leftover catch-all rule would
        # re-route the worker tests that run after this file
        hub.post("/config", {"rules_mirror": []})


def test_rules_test_get_form_honors_kind_and_title():
    # v3.4.8 GET/POST parity: the GET form used to silently drop
    # &kind= and &title= (rule_test_result got only the URL)
    src = _src()
    get_form = re.search(
        r'if route == "/rules/test":\s*# v3\.4\.7 URL RULE TEST(.*?)'
        r'return self\._send\(200, res\)', src, re.S).group(1)
    assert 'q.get("kind"' in get_form and 'q.get("title"' in get_form, \
        "the GET /rules/test form must pass kind + title like POST"


# ------------------------------------------------------------
# 3. run bookkeeping reaches the ONE UI
# ------------------------------------------------------------
def test_cleaner_keeps_title_and_last_run(hub):
    rules = [{"id": 7, "name": "With bookkeeping", "pattern": "*://a/*",
              "printer": "P", "title": "Invoice",
              "last_run": "2026-11-14T14:22:08.000Z", "runs": 5}]
    code, r = hub.post("/config", {"rules_mirror": rules})
    assert code == 200
    code, cfg = hub.get("/config")
    got = cfg["rules_mirror"][0]
    assert got["title"] == "Invoice"
    assert got["last_run"] == "2026-11-14T14:22:08.000Z"
    assert got["runs"] == 5


def test_extension_pushes_last_run():
    assert "last_run: (s && s.lastRun) || r.last_run || \"\"" in BGJS
    assert "last_run" in CONSOLE and "last " in CONSOLE  # the cell renders it


# ------------------------------------------------------------
# 4. version coherence 3.4.8
# ------------------------------------------------------------
def test_v348_version_coherence():
    assert advprint.VERSION == "3.4.8"
    assert advprint.VERSION_NAME.startswith("v3.4.8")
    vt = open(os.path.join(ROOT, "VERSION.txt"), encoding="utf-8").read()
    assert "3.4.8" in vt
    man = json.load(open(os.path.join(EXT, "manifest.json"),
                         encoding="utf-8"))
    assert man["version"] == "3.4.8"
    nsi = open(os.path.join(ROOT, "installer", "setup.nsi"),
               encoding="utf-8").read()
    assert 'VIProductVersion "3.4.8.0"' in nsi
    assert "AdvPrint-Pro-Setup-3.4.8.exe" in nsi
    popup = open(os.path.join(EXT, "popup.html"), encoding="utf-8").read()
    assert 'id="ver">v3.4.8<' in popup
    i18n = open(os.path.join(EXT, "i18n.js"), encoding="utf-8").read()
    assert "Version 3.4.8" in i18n
    assert i18n.count("3.4.8") >= 2
    apijs = open(os.path.join(EXT, "content", "api.js"),
                 encoding="utf-8").read()
    assert 'var _apVerFallback = "3.4.8";' in apijs
    assert 'BOOT.version || "3.4.8"' in CONSOLE


def test_hub_copies_stay_byte_identical():
    unix = open(os.path.join(ROOT, "tool", "unix", "hub", "advprint.py"),
                encoding="utf-8").read()
    win = open(os.path.join(ROOT, "tool", "windows", "portable", "hub",
                            "advprint.py"), encoding="utf-8").read()
    assert unix == win, "the two hub copies diverged"
    # and the embedded console matches the standalone file
    m = re.search(r'CONSOLE_HTML = r"""(.*?)"""', unix, re.S)
    con = open(os.path.join(ROOT, "tool", "unix", "hub", "console.html"),
               encoding="utf-8").read()
    assert m and m.group(1).rstrip("\n") == con.rstrip("\n"), \
        "embedded console is stale - run scripts/embed_console.py"
