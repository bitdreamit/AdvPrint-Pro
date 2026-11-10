"""v3.2.1 THE ONE UI - the hub serves the approved rev-4 All-in-One
console at /ui, / and /dashboard.

- The console UI is EMBEDDED in advprint.py itself (CONSOLE_HTML):
  the UI can never go missing on an install, whatever files exist.
- GET /ui?token=... answers with the embedded UI - Cache-Control:
  no-store, text/html.
- WITHOUT a valid token: 401 (+ the readable HTML auth error page for
  browsers, JSON for API clients) - same auth model as /dashboard.
- console.html also ships next to advprint.py so the on-disk layout
  matches the docs; the embedded copy is always authoritative.
- /ui is listed in the /docs route table."""
import os

import pytest

import advprint

CONSOLE_NAME = "console.html"


def _console_dir():
    return os.path.dirname(advprint.__file__)


def test_ui_serves_console_html(hub):
    code, page = hub.get("/ui")
    assert code == 200
    html = page.decode("utf-8") if isinstance(page, bytes) else str(page)
    assert "Printing Hub" in html
    assert "THE ONE UI" in html
    assert 'id="p-dashboard"' in html


def test_ui_no_token_is_rejected(hub):
    code, payload = hub.get("/ui", token=None)
    assert code == 401


def test_ui_wrong_token_is_rejected(hub):
    code, _ = hub.get("/ui", token="wrong-token-123")
    assert code == 401


def test_ui_browser_gets_html_auth_error(hub):
    # Browsers (Accept: text/html) never get a raw JSON blob: on the
    # hub PC itself (loopback) the v2.6.4 owner-redirect page answers
    # (200, meta-refresh to the working /ui?token=... URL); a remote
    # browser gets the readable 401 HTML auth page. JSON clients get
    # a plain 401 (test_ui_no_token_is_rejected).
    code, payload = hub.get("/ui", token=None,
                            headers={"Accept": "text/html"})
    body = payload.decode("utf-8") if isinstance(payload, bytes) else \
        str(payload)
    assert (code == 200 and ("/ui" in body or "dashboard" in body)) or \
        (code == 401 and "html" in body.lower())


def test_ui_embedded_survives_missing_console_file(hub, monkeypatch):
    # v3.2.1: the UI lives INSIDE advprint.py (CONSOLE_HTML). Even when
    # console.html cannot be found on disk - a damaged install, a broken
    # copy step - the hub STILL serves the full approved All-in-One UI.
    # (The v3.2.0 build served the old dashboard here; that class of
    # bug is impossible with the embedded UI.)
    real = os.path.join

    def fake_join(*parts):
        r = real(*parts)
        if r.endswith(CONSOLE_NAME):
            return r + ".definitely-missing"
        return r

    monkeypatch.setattr(advprint.os.path, "join", fake_join)
    code, page = hub.get("/ui")
    assert code == 200
    html = page.decode("utf-8") if isinstance(page, bytes) else str(page)
    assert 'id="p-dashboard"' in html and "Printing Hub" in html


def test_console_html_embedded_in_hub_source():
    # v3.2.1: CONSOLE_HTML must be a module constant with the full
    # rev-4 markup - this is what makes the UI un-missable.
    src = open(os.path.join(_console_dir(), "advprint.py"),
               encoding="utf-8").read()
    assert "CONSOLE_HTML = r" in src
    assert 'page = CONSOLE_HTML' in src
    for pid in ("dashboard queue history printers lan connections hub "
                "dropzone rules power browser extension debug audit logs "
                "settings about").split():
        assert f'id="p-{pid}"' in src, f"panel {pid} missing from CONSOLE_HTML"
    assert "__ADVPRINT_BOOT_JSON__" in src


def test_ui_listed_in_docs(hub):
    code, d = hub.get("/")
    assert code == 200
    text = str(d)
    assert "/ui" in text


def test_console_file_ships_next_to_hub():
    p = os.path.join(_console_dir(), CONSOLE_NAME)
    assert os.path.exists(p), "console.html must ship next to advprint.py"
    src = open(p, encoding="utf-8").read()
    # the console is API-driven: token header + the live endpoints
    for api in ("/health", "/stats", "/queue", "/printers", "/jobs",
                "/audit", "/config", "X-AdvPrint-Token"):
        assert api in src, "console.html must use " + api
