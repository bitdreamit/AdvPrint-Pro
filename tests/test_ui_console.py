"""v3.1.3 THE ONE UI - the hub serves the IDM-style console at /ui.

- GET /ui?token=... answers with console.html from disk (next to
  advprint.py) - Cache-Control: no-store, text/html.
- WITHOUT a valid token: 401 (+ the readable HTML auth error page for
  browsers, JSON for API clients) - same auth model as /dashboard.
- When console.html is MISSING next to advprint.py the hub answers
  with a small fallback page that points at the classic dashboard
  (never a crash, never a blank page).
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
    assert "AdvPrint Pro Console" in html
    assert "THE ONE UI" in html


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


def test_ui_fallback_page_when_console_missing(hub, monkeypatch):
    real = os.path.join

    def fake_join(*parts):
        # make EVERY path look like it does not contain console.html
        r = real(*parts)
        if r.endswith(CONSOLE_NAME):
            return r + ".definitely-missing"
        return r

    monkeypatch.setattr(advprint.os.path, "join", fake_join)
    code, page = hub.get("/ui")
    assert code == 200
    html = page.decode("utf-8") if isinstance(page, bytes) else str(page)
    assert "console.html" in html and "/dashboard" in html


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
