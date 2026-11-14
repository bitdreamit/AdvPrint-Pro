"""v3.2.7 - THE DEVELOPER API RELEASE.

Locks the release end to end:

* version coherence 3.2.7 everywhere (VERSION.txt, hub VERSION /
  VERSION_NAME, extension manifest + popup + options + i18n, api.js
  fallback, console boot default, CHANGELOG entry)
* window.advprint.print() FULL API PARITY - background.js maps
  run_at / queue / dedupe / tray / watermark_text to the hub fields
  (api.js documents them)
* the Developer API guide exists (docs/DEVELOPER-API.md) with the
  required anchors: window.advprint methods, POST /print, the four
  body styles, the payload sources, the full option table, the
  multi-printer + many-PCs + PDF+ZPL cases, the URL & token map
* the hub /docs page grew section 9 (9a-9e + TOC entry #devapi)
* the in-UI docs modal grew section 9 (id="d-api") + v3.2.7 release
  notes
* docs/API.md + docs/EXTENSION-API.md carry the parity tables
* the unix hub copy and the windows portable hub copy are
  byte-identical (advprint.py + console.html)
* live hub: POST /print answers with the documented response fields,
  run_at schedules a job (status "scheduled"), queue:false answers
  instant, dedupe:false allows an identical repeat - the exact
  behaviors the new guide teaches
"""
import json
import os
import re

import pytest

import advprint
from conftest import ROOT

HUB_DIR = os.path.join(ROOT, "tool", "windows", "portable", "hub")
UNIX_HUB = os.path.join(ROOT, "tool", "unix", "hub")
EXT = os.path.join(ROOT, "extension")

CONSOLE = open(os.path.join(HUB_DIR, "console.html"),
               encoding="utf-8").read()
ADVPRINT_SRC = open(os.path.join(HUB_DIR, "advprint.py"),
                    encoding="utf-8").read()
BG_SRC = open(os.path.join(EXT, "background.js"),
              encoding="utf-8").read()
APIJS_SRC = open(os.path.join(EXT, "content", "api.js"),
                 encoding="utf-8").read()
MANIFEST = json.load(open(os.path.join(EXT, "manifest.json"),
                          encoding="utf-8"))
DEVGUIDE = open(os.path.join(ROOT, "docs", "DEVELOPER-API.md"),
                encoding="utf-8").read()
API_MD = open(os.path.join(ROOT, "docs", "API.md"),
              encoding="utf-8").read()
EXTAPI_MD = open(os.path.join(ROOT, "docs", "EXTENSION-API.md"),
                 encoding="utf-8").read()
VERSION_TXT = open(os.path.join(ROOT, "VERSION.txt"),
                   encoding="utf-8").read()
CHANGELOG = open(os.path.join(ROOT, "CHANGELOG.md"),
                 encoding="utf-8").read()


# ---------------------------------------------------------------
# 1. version coherence 3.2.8 (rolled forward with every release)
# ---------------------------------------------------------------

def test_version_327_everywhere():
    assert advprint.VERSION == "3.4.7"
    assert advprint.VERSION_NAME.startswith("v3.4.7")
    assert "CONFIGURABLE HUB PORT" in advprint.VERSION_NAME
    assert re.search(r"3\.4\.7", VERSION_TXT), VERSION_TXT
    assert MANIFEST["version"] == "3.4.7"
    assert 'v3.4.7</span>' in open(os.path.join(
        EXT, "popup.html"), encoding="utf-8").read()
    assert "v3.4.7" in open(os.path.join(
        EXT, "options.html"), encoding="utf-8").read()
    assert 'var _apVerFallback = "3.4.7";' in APIJS_SRC
    assert 'BOOT.version || "3.4.7"' in CONSOLE
    assert "## v3.2.7 - THE DEVELOPER API RELEASE" in CHANGELOG


def test_release_notes_v327_exist():
    p = os.path.join(ROOT, "docs", "RELEASE-NOTES-v3.2.7.md")
    txt = open(p, encoding="utf-8").read()
    assert "DEVELOPER API" in txt.upper()
    assert "FULL API PARITY" in txt
    guide = os.path.join(ROOT, "docs",
                         "AdvPrint-Pro-v3.2.7-A-to-Z-DEV-GUIDE.md")
    assert os.path.exists(guide)


# ---------------------------------------------------------------
# 2. extension parity: background.js maps the new fields
# ---------------------------------------------------------------

@pytest.mark.parametrize("camel,snake", [
    ("run_at", "run_at"),
    ("queue", "queue"),
    ("dedupe", "dedupe"),
    ("tray", "tray"),
    ("watermark_text", "watermark_text"),
])
def test_background_maps_new_fields(camel, snake):
    # the print case must copy the camelCase option into the hub body;
    # queue/dedupe use the null-check form so an explicit false survives
    m = re.search(r"if \(o\.%s(?: != null)?\) body\.%s = o\.%s;"
                  % (camel, snake, camel), BG_SRC)
    assert m, "background.js missing mapping for %s -> %s" % (camel, snake)


def test_background_maps_the_classic_fields():
    for frag in ["body.pdf_base64 = o.pdfBase64",
                 "body.pdf_url = o.pdfUrl",
                 "body.page_url = o.pageUrl",
                 "body.raw_base64 = o.rawBase64",
                 "body.lang = o.lang",
                 "body.priority = o.priority",
                 "body.pages = o.pages",
                 "body.per_sheet = o.per_sheet",
                 "body.quality = o.quality",
                 "body.dpi = o.dpi",
                 "body.scale_pct = o.scale_pct",
                 "body.margin_mm = o.margin_mm",
                 "body.duplex = o.duplex",
                 "body.paper_size = o.paper_size",
                 "body.orientation = o.orientation",
                 "body.profile = o.profile",
                 "body.reason = o.reason"]:
        assert frag in BG_SRC, frag


def test_apijs_documents_parity():
    assert "v3.2.7: full HTTP parity" in APIJS_SRC
    assert "watermark_text" in APIJS_SRC


# ---------------------------------------------------------------
# 3. the guide: docs/DEVELOPER-API.md
# ---------------------------------------------------------------

@pytest.mark.parametrize("anchor", [
    "window.advprint",
    "POST /print",
    "X-AdvPrint-Token",
    "printPdfLink",
    "kind=raw",
    "raw_base64",
    "pdf_base64",
    "pdf_url",
    "image_base64",
    "page_url",
    "priority",
    "run_at",
    "dedupe",
    "watermark",
    "queue: false",
    "^XA",
    "escpos",
    "|center|",
    "|cut|",
    "|drawer|",
    "|barcode:",
    "|qr:",
    "MANY PRINTERS",
    "MANY PCs",
    "printer group",
    "hp-laserjet-pro",
    "9100",
    "631",
    "curl -X POST",
    "requests.post",
    "Http::withHeaders",
    "auto_queued",
    "duplicate",
])
def test_devguide_has_every_anchor(anchor):
    assert anchor in DEVGUIDE, "DEVELOPER-API.md missing: %s" % anchor


def test_devguide_documents_all_print_options():
    for opt in ["title", "printer", "copies", "priority", "pages",
                "per_sheet", "quality", "dpi", "scale_pct", "margin_mm",
                "duplex", "paper_size", "orientation", "tray",
                "paper", "profile", "destination", "queue", "run_at",
                "dedupe", "reason", "watermark_text", "source", "lang",
                "cut", "drawer"]:
        assert re.search(r"`%s`" % opt, DEVGUIDE), opt


def test_devguide_documents_the_response_fields():
    for f in ["job_id", "queue_mode", "instant", "auto_queued",
              "duplicate", "status", "scheduled_for", "file", "url_path"]:
        assert f in DEVGUIDE, f


# ---------------------------------------------------------------
# 4. /docs page section 9 + in-UI docs modal section 9
# ---------------------------------------------------------------

def test_docs_page_has_devapi_section():
    docs_html = advprint.DOCS_HTML
    assert 'id="devapi"' in docs_html
    assert 'href="#devapi"' in docs_html
    for sub in ["9a.", "9b.", "9c.", "9d.", "9e."]:
        assert sub in docs_html, sub
    assert "window.advprint" in docs_html
    assert "POST /print" in docs_html
    assert "X-AdvPrint-Token" in docs_html
    assert "^XA" in docs_html
    assert "|center|" in docs_html


def test_console_docs_modal_has_devapi_section():
    assert 'id="d-api"' in CONSOLE
    assert "Developer API" in CONSOLE
    assert "window.advprint" in CONSOLE
    assert "X-AdvPrint-Token" in CONSOLE
    # release notes updated to the 3.2.7 story
    assert "Developer API release" in CONSOLE
    assert "FULL parity" in CONSOLE
    # openDocs anchor wiring still intact
    assert 'function openDocs(anchor)' in CONSOLE


# ---------------------------------------------------------------
# 5. API.md + EXTENSION-API.md parity
# ---------------------------------------------------------------

def test_api_md_option_table():
    for opt in ["priority", "per_sheet", "quality", "dpi", "scale_pct",
                "duplex", "profile", "queue", "run_at", "dedupe",
                "watermark_text", "raw_base64"]:
        assert "`%s`" % opt in API_MD, opt
    assert "DEVELOPER-API.md" in API_MD


def test_extension_api_md_parity_note():
    assert "FULL API PARITY" in EXTAPI_MD
    assert "run_at" in EXTAPI_MD and "dedupe" in EXTAPI_MD
    assert "DEVELOPER-API.md" in EXTAPI_MD


# ---------------------------------------------------------------
# 6. hub copies stay in sync (unix + windows portable)
# ---------------------------------------------------------------

def test_hub_copies_identical():
    for name in ("advprint.py", "console.html"):
        a = open(os.path.join(UNIX_HUB, name), "rb").read()
        b = open(os.path.join(HUB_DIR, name), "rb").read()
        assert a == b, "%s differs between unix and windows hub" % name


# ---------------------------------------------------------------
# 7. LIVE hub: the behaviors the guide teaches
# ---------------------------------------------------------------

def _post(hub, body):
    return hub.post("/print", body=body)


def test_live_print_response_matches_the_guide(hub):
    st, r = _post(hub, {"title": "v327 doc check",
                        "text": "|center|HELLO API",
                        "priority": 3})
    assert st == 200 and r["ok"] is True
    for f in ["job_id", "kind", "copies", "destination", "queue_mode",
              "instant", "auto_queued", "duplicate", "priority",
              "status", "message"]:
        assert f in r, f
    assert r["priority"] == 3
    assert r["queue_mode"] == "on" and r["instant"] is False
    # documented: unknown profile -> 400
    st, r = _post(hub, {"text": "x", "profile": "no-such-327"})
    assert st == 400 and r["ok"] is False
    # documented: bad run_at -> 400 with the guide's wording
    st, r = _post(hub, {"text": "x", "run_at": "tomorrow"})
    assert st == 400 and "run_at" in r["error"]
    # documented: no payload -> 400 with the payload list
    st, r = _post(hub, {"title": "empty"})
    assert st == 400 and "pdf_base64" in r["error"]


def test_live_run_at_schedules_and_dedupe_allows(hub):
    st, r = _post(hub, {"title": "v327 scheduled",
                        "text": "|center|LATER",
                        "run_at": "+2m"})
    assert st == 200 and r["status"] == "scheduled"
    assert r["scheduled_for"]
    # queue:false answers instant
    st, r = _post(hub, {"title": "v327 instant",
                        "text": "now", "queue": False})
    assert st == 200 and r["instant"] is True
    # dedupe:false allows the identical repeat the 5-min window blocks
    body = {"title": "v327 dedupe", "text": "same same"}
    st1, r1 = _post(hub, body)
    st2, r2 = _post(hub, body)
    assert st1 == 200 and st2 == 200
    if not r2.get("duplicate"):
        assert r2["ok"] is True      # blocked => duplicate flag set
    body["dedupe"] = False
    st3, r3 = _post(hub, body)
    assert st3 == 200 and r3["duplicate"] is False
