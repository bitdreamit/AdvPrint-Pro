"""v3.2.8 - THE ipp:// + HTTP-PAGE FIX RELEASE.

Locks the two user-reported bugs end to end:

BUG 1 - the IPP landing page printed the protocol twice
  ("ipp://http://192.168.1.101:9235/ipp/print"): ipp_landing_html()
  prepended ipp:// to lan_share_url("ipp") - which returns an http://
  URL since the v3.2.6 QR fix - so the page showed a doubled scheme
  that Windows/macOS/iOS/CUPS refuse. v3.2.8 adds _ipp_scheme_url() /
  ipp_scheme_bare(): strip the web scheme first, then prepend ipp://.

BUG 2 - window.advprint.printPdf() (and every other page-API method)
  worked on https:// sites but was refused on http:// pages when the
  Website API list contained an https://host/* pattern: the v2.9.1
  allowlist pinned the SCHEME. v3.2.8 rule: the HOST is what you
  allow - a pattern pinning http(s) matches that host on BOTH web
  schemes. The refusal message points to the real editor (Console >
  Connections > Website API) and suggests a ready-made pattern.

Also locked: version coherence 3.2.8 everywhere, the console Website
API hint inside the embedded UI, byte-identical hub copies, the new
scripts/embed_console.py, and the new release docs.
"""
import importlib.util
import json
import os
import re
import urllib.parse

import pytest

import advprint
from conftest import ROOT

HUB_DIR = os.path.join(ROOT, "tool", "windows", "portable", "hub")
UNIX_HUB = os.path.join(ROOT, "tool", "unix", "hub")
EXT = os.path.join(ROOT, "extension")

CONSOLE = open(os.path.join(HUB_DIR, "console.html"), encoding="utf-8").read()
UNIX_CONSOLE = open(os.path.join(UNIX_HUB, "console.html"),
                    encoding="utf-8").read()
ADVPRINT_SRC = open(os.path.join(HUB_DIR, "advprint.py"),
                    encoding="utf-8").read()
BG_SRC = open(os.path.join(EXT, "background.js"), encoding="utf-8").read()
VERSION_TXT = open(os.path.join(ROOT, "VERSION.txt"), encoding="utf-8").read()
MANIFEST = json.load(open(os.path.join(EXT, "manifest.json"),
                          encoding="utf-8"))
CHANGELOG = open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8").read()


# ---------------------------------------------------------------
# 1. version coherence 3.2.8
# ---------------------------------------------------------------

def test_version_328_everywhere():
    assert advprint.VERSION == "3.3.5"
    assert advprint.VERSION_NAME.startswith("v3.3.5")
    assert "DEDICATED QUEUE PORTS" in advprint.VERSION_NAME
    assert "3.3.5" in VERSION_TXT
    assert MANIFEST["version"] == "3.3.5"
    assert 'var _apVerFallback = "3.3.5";' in open(
        os.path.join(EXT, "content", "api.js"), encoding="utf-8").read()
    assert 'BOOT.version || "3.3.5"' in CONSOLE
    assert "## v3.2.9 - THE MULTI-PC IPP RELEASE" in CHANGELOG
    nsi = open(os.path.join(ROOT, "installer", "setup.nsi"),
               encoding="utf-8").read()
    assert 'VIProductVersion "3.3.5.0"' in nsi
    assert "AdvPrint-Pro-Setup-3.3.5.exe" in nsi


def test_release_docs_328_exist():
    notes = open(os.path.join(ROOT, "docs", "RELEASE-NOTES-v3.2.8.md"),
                 encoding="utf-8").read()
    assert "ipp://http://" in notes          # the exact symptom
    assert "HOST is what you allow" in notes
    guide = open(os.path.join(ROOT,
                 "docs", "AdvPrint-Pro-v3.2.8-A-to-Z-DEV-GUIDE.md"),
                 encoding="utf-8").read()
    assert "_ipp_scheme_url" in guide
    assert "scripts/embed_console.py" in guide


# ---------------------------------------------------------------
# 2. BUG 1 - the ipp:// scheme helpers + the clean landing page
# ---------------------------------------------------------------

@pytest.mark.parametrize("url,expected", [
    ("http://192.168.1.101:9235/ipp/print",
     "ipp://192.168.1.101:9235/ipp/print"),
    ("https://192.168.1.101:9235/ipp/print",
     "ipp://192.168.1.101:9235/ipp/print"),
    ("HTTP://192.168.1.101:9235/ipp/print",
     "ipp://192.168.1.101:9235/ipp/print"),          # uppercase scheme
    ("ipp://192.168.1.101:9235/ipp/print",
     "ipp://192.168.1.101:9235/ipp/print"),          # idempotent
    ("192.168.1.101:9235/ipp/print",
     "ipp://192.168.1.101:9235/ipp/print"),          # bare host:port
    ("http://10.26.94.206:631/ipp/print/HP-Laser",
     "ipp://10.26.94.206:631/ipp/print/HP-Laser"),   # per-printer, 631
])
def test_ipp_scheme_url_helper(url, expected):
    assert advprint._ipp_scheme_url(url) == expected


@pytest.mark.parametrize("url,bare", [
    ("http://192.168.1.101:9235/ipp/print", "192.168.1.101:9235/ipp/print"),
    ("https://192.168.1.101:9235/ipp/print", "192.168.1.101:9235/ipp/print"),
    ("ipp://192.168.1.101:9235/ipp/print", "192.168.1.101:9235/ipp/print"),
])
def test_ipp_scheme_bare_helper(url, bare):
    assert advprint.ipp_scheme_bare(url) == bare


def test_ipp_landing_page_shows_clean_ipp_url(hub, cfg_reset, monkeypatch):
    # determinism: pin the LAN IP the landing page reports
    monkeypatch.setattr(advprint, "lan_ip", lambda: "192.168.1.101")
    advprint.CFG["share_lan"] = True
    html = advprint.ipp_landing_html()
    port = advprint.CFG["port"]
    # the clean printer URL - the EXACT form the user asked for
    assert "ipp://192.168.1.101:%d/ipp/print" % port in html
    assert "http://192.168.1.101:%d/ipp/print" % port in html
    # the doubled scheme must never appear again
    assert "ipp://http://" not in html
    assert "ipp://https://" not in html
    # the AI-Lab hostname and the add-it-as-a-printer sentence survive
    assert "Add it as a printer - do not open it in a browser" in html


def test_ipp_landing_loopback_when_lan_off(hub, cfg_reset, monkeypatch):
    monkeypatch.setattr(advprint, "lan_ip", lambda: "10.26.94.206")
    advprint.CFG["share_lan"] = False
    html = advprint.ipp_landing_html()
    port = advprint.CFG["port"]
    assert "ipp://127.0.0.1:%d/ipp/print" % port in html
    assert "ipp://http://" not in html


def test_per_printer_landing_stays_correct():
    # ipp_queue_url() always built the ipp:// form from a bare IP - the
    # bug was ONLY in ipp_landing_html(); make sure it stayed clean
    url = advprint.ipp_queue_url("HP Laser 103 107 108")
    assert url.startswith("ipp://")
    assert "http://" not in url


# ---------------------------------------------------------------
# 3. BUG 2 - the Website API allowlist is scheme-blind
# ---------------------------------------------------------------

def api_site_allowed_py(origin, sites):
    """Faithful Python port of background.js apiSiteAllowed() (v3.2.8)
    - run the REAL matching matrix as a live test."""
    if not sites:
        return False
    try:
        u = urllib.parse.urlsplit(origin or "")
        host = (u.hostname or "").lower()
        scheme = (u.scheme or "").replace(":", "")
    except Exception:
        return False
    if not host:
        return False
    for raw in sites:
        pat = str(raw or "").strip().lower()
        if not pat:
            continue
        p_scheme, rest = None, pat
        m = re.match(r"^([a-z*]+)://(.*)$", pat)
        if m:
            p_scheme, rest = m.group(1), m.group(2)
        p_host = rest.split("/")[0]
        web = scheme in ("http", "https")
        pinned_web = p_scheme in ("http", "https")
        scheme_ok = (not p_scheme or p_scheme == "*" or
                     p_scheme == scheme or (web and pinned_web))
        host_ok = (p_host == "*" or p_host == host or
                   (p_host.startswith("*.") and
                    (host == p_host[2:] or
                     host.endswith("." + p_host[2:]))))
        if scheme_ok and host_ok:
            return True
    return False


class TestWebsiteApiSchemeBlind:
    # the user's exact case: https pattern + http page
    SITES = ["https://reports.example.com/*"]

    def test_https_pattern_allows_http_page(self):
        assert api_site_allowed_py("http://reports.example.com", self.SITES)
        assert api_site_allowed_py(
            "http://reports.example.com/lab/report.pdf", self.SITES)

    def test_https_pattern_still_allows_https_page(self):
        assert api_site_allowed_py("https://reports.example.com", self.SITES)

    def test_http_pattern_allows_https_page(self):
        assert api_site_allowed_py(
            "https://reports.example.com", ["http://reports.example.com/*"])

    def test_scheme_wildcards_unchanged(self):
        sites = ["*://www.htncr.org/*", "www.htncr.org"]
        assert api_site_allowed_py("http://www.htncr.org", sites)
        assert api_site_allowed_py("https://www.htncr.org", sites)

    def test_star_default_unchanged(self):
        assert api_site_allowed_py("http://anything.local", ["*"])
        assert api_site_allowed_py("https://anything.local", ["*"])

    def test_subdomain_wildcard_unchanged(self):
        sites = ["*.example.org"]
        assert api_site_allowed_py("http://lab.example.org", sites)
        assert api_site_allowed_py("https://mail.example.org", sites)
        assert api_site_allowed_py("https://example.org", sites)   # bare apex

    def test_other_hosts_still_refused(self):
        sites = ["https://reports.example.com/*"]
        assert not api_site_allowed_py("http://evil.example.com", sites)
        assert not api_site_allowed_py("https://other.example.org", sites)
        # prefix hosts are not suffix-matched
        assert not api_site_allowed_py(
            "http://reports.example.com.evil.io", sites)

    def test_file_origin_never_matches(self):
        assert not api_site_allowed_py("file:///C:/x/y.html",
                                       ["https://reports.example.com/*"])
        assert not api_site_allowed_py("file:///C:/x/y.html", ["*://*/*"])

    def test_empty_list_off(self):
        assert not api_site_allowed_py("http://reports.example.com", [])
        assert not api_site_allowed_py("http://reports.example.com", None)


def test_background_js_has_scheme_blind_matcher():
    # the v3.2.8 clause really ships in the extension
    assert "const schemeOk = !pScheme || pScheme === \"*\" || " \
        "pScheme === scheme ||" in BG_SRC
    assert "(WEB && PINNED_WEB);" in BG_SRC
    assert "v3.2.8 BUG FIX 2" in BG_SRC


def test_background_js_refusal_message_points_to_console():
    assert "open the AdvPrint Pro Console (/ui), Connections tab > " in BG_SRC
    assert "Website API, and add this site (one line: \" + hint +" in BG_SRC
    # the old pointer (to a page that never had the editor) is gone
    assert "add the site in AdvPrint Pro Options > Website API" not in BG_SRC


def test_console_hint_documents_the_scheme_rule():
    # the Website API card explains the rule - in the source UI AND the
    # embedded copy the hub actually serves
    for src in (CONSOLE, UNIX_CONSOLE, advprint.CONSOLE_HTML):
        assert "the SCHEME does not matter" in src
        assert "https://host/*" in src
        assert "http://" in src


# ---------------------------------------------------------------
# 4. embed helper + tree hygiene
# ---------------------------------------------------------------

def test_embed_console_script_exists():
    p = os.path.join(ROOT, "scripts", "embed_console.py")
    src = open(p, encoding="utf-8").read()
    assert 'CONSOLE_HTML = r"""' in src
    # the script names BOTH hub copies (built via os.path.join, so the
    # components appear separately in the source)
    for token in ('"tool", "unix", "hub", "advprint.py"',
                  '"tool", "windows", "portable", "hub", "advprint.py"',
                  '"tool", "windows", "portable", "hub", "console.html"'):
        assert token in src, token


def test_hub_copies_byte_identical():
    for name in ("advprint.py", "console.html"):
        a = open(os.path.join(UNIX_HUB, name), "rb").read()
        b = open(os.path.join(HUB_DIR, name), "rb").read()
        assert a == b, "%s copies drifted" % name
    m = re.search(r'CONSOLE_HTML = r"""(.*?)"""', ADVPRINT_SRC, re.S)
    assert m and m.group(1).rstrip("\n") == CONSOLE.rstrip("\n"), "embedded console is stale"


def test_developer_api_doc_has_permission_section():
    doc = open(os.path.join(ROOT, "docs", "DEVELOPER-API.md"),
               encoding="utf-8").read()
    assert "Website API permission" in doc
    assert "The v3.2.8 scheme rule" in doc
    assert "works on https, not on http" in doc
    assert 'version;     // -> "3.3.0"' in doc


# ---------------------------------------------------------------
# 5. live hub - the landing page over HTTP carries the clean URL
# ---------------------------------------------------------------

def test_live_ipp_landing_http(hub, cfg_reset, monkeypatch):
    monkeypatch.setattr(advprint, "lan_ip", lambda: "192.168.1.101")
    advprint.CFG["share_lan"] = True
    code, page = hub.get("/ipp/print", token=None)
    assert code == 200
    html = page.decode("utf-8", "replace") if isinstance(page, bytes) \
        else str(page)
    port = advprint.CFG["port"]
    assert "ipp://192.168.1.101:%d/ipp/print" % port in html
    assert "ipp://http://" not in html


# ---------------------------------------------------------------
# 6. v3.2.8 STALE-CRX GUARD - the Bug 2 DELIVERY trap
#    (hub served extension 3.2.6 while the hub was 3.2.8, so Chrome
#    never updated and every browser kept the old http-page refusal)
# ---------------------------------------------------------------

BUILD_SH = open(os.path.join(ROOT, "scripts", "build-all.sh"),
                encoding="utf-8").read()


def test_ver_lt():
    f = advprint._ver_lt
    assert f("3.2.6", "3.2.8")
    assert f("3.1.9", "3.2.0")
    assert f("3.2", "3.2.1")
    assert not f("3.2.8", "3.2.8")
    assert not f("3.2.8", "3.2.6")
    assert not f("4.0", "3.9.9")
    assert f("", "3.2.8")
    assert not f("3.2.8a", "3.2.8")


def _crx_manifest_version(path):
    import io
    import struct
    import zipfile
    d = open(path, "rb").read()
    assert d[:4] == b"Cr24", "not a CRX3: %s" % path
    hlen, = struct.unpack("<I", d[8:12])
    with zipfile.ZipFile(io.BytesIO(d[12 + hlen:])) as z:
        return json.loads(z.read("manifest.json").decode("utf-8"))["version"]


def test_embedded_crx_copies_fresh():
    """Every embedded hub CRX copy must carry the hub's own version -
    a stale copy silently stops all browser auto-updates."""
    for p in (os.path.join(UNIX_HUB, "extension", "AdvPrint-Pro.crx"),
              os.path.join(HUB_DIR, "extension", "AdvPrint-Pro.crx")):
        assert os.path.exists(p), "missing embedded CRX: %s" % p
        assert _crx_manifest_version(p) == advprint.VERSION, \
            "STALE served extension %s (%s != %s)" % (
                p, _crx_manifest_version(p), advprint.VERSION)


def test_ext_health_stale_flag():
    h = advprint.ext_health()
    assert h.get("served") is True
    assert h.get("version") == advprint.VERSION
    assert h.get("hub_version") == advprint.VERSION
    assert h.get("stale") is False


def test_build_script_syncs_embedded_crx():
    assert "STALE-CRX GUARD" in BUILD_SH
    assert "tool/unix/hub/extension/AdvPrint-Pro.crx" in BUILD_SH
    assert "tool/windows/portable/hub/extension/AdvPrint-Pro.crx" in BUILD_SH
    assert "CRX version $CRXV != hub version" in BUILD_SH


def test_console_has_stale_crx_warning():
    assert 'id="extStaleWarn"' in CONSOLE
    assert 'id="extStaleTxt"' in CONSOLE
    assert "/extension/info" in CONSOLE
    assert "Stale CRX" in CONSOLE


def test_extension_page_stale_guard_source():
    assert "STALE-CRX GUARD" in ADVPRINT_SRC
    assert '"stale": bool(c) and _ver_lt(c["version"], VERSION)' \
        in ADVPRINT_SRC
    assert "hub_version" in ADVPRINT_SRC
