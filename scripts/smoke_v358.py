#!/usr/bin/env python3
"""v3.5.8 release smoke - boots the REAL hub and probes the ONE UI.

Verification carried from v3.5.3 (status bar always visible) + v3.5.7
(version coherence, silent windows) plus the NEW v3.5.8 behaviours:

  - /health reports 3.5.8; the served /ui title is the BRAND
    "AdvPrint Pro by Bit Dream IT - Innovative Healthcare Solutions";
  - the Dashboard subtitle has NO machine id (uuid gone);
  - clicking History writes ?path=history into the URL (token kept),
    stores the last tab, and a RELOAD lands back on History;
  - a plain /ui (no ?path) restores the SAVED last tab;
  - the minimize button REALLY collapses the window to its title bar
    and a second click restores it;
  - the maximize button requests REAL fullscreen (or the in-page
    edge-to-edge fallback -> .maxed);
  - the close button calls window.close() and, when the browser
    blocks it, shows the honest toast;
  - the status bar sits fully inside the viewport at 1280x720 and
    1440x900, the status bar version pane reads "Printing Hub v3.5.8",
    zero JS errors; screenshots saved to docs/.

Run:  python3 scripts/smoke_v358.py
"""
import json
import os
import socket
import sys
import tempfile
import threading
from http.server import ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "tool", "windows", "portable", "hub"))

import advprint  # noqa: E402

DOCS = os.path.join(ROOT, "docs")


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def boot_hub():
    data_dir = tempfile.mkdtemp(prefix="advprint-smoke-358-")
    port = free_port()
    advprint.CFG["data_dir"] = data_dir
    advprint.CFG["port"] = port
    advprint.CFG["host"] = "127.0.0.1"
    advprint.db_init()
    advprint.RESUME_EVENT.set()
    advprint.start_worker()
    httpd = ThreadingHTTPServer(("127.0.0.1", port), advprint.Handler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return "http://127.0.0.1:%d" % port, advprint.CFG["token"]


def probe_page(base, width, height, shot, seed_tab=None, path_param=None):
    """Open /ui and return the behaviour facts for one viewport."""
    from playwright.sync_api import sync_playwright
    errors = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--no-sandbox"])
        ctx = browser.new_context(viewport={"width": width, "height": height})
        page = ctx.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text)
                if m.type == "error" else None)
        url = base + "/ui"
        if path_param:
            url += "?path=" + path_param
        page.goto(url, wait_until="networkidle", timeout=30000)
        if seed_tab:                       # simulate the saved-tab memory
            page.evaluate("localStorage.setItem('ap_console_tab', '%s')"
                          % seed_tab)
            page.goto(base + "/ui", wait_until="networkidle")
        page.wait_for_timeout(1200)
        facts = page.evaluate("""() => ({
            vh: window.innerHeight,
            sbText: (document.querySelector('.statusbar')||{}).textContent || '',
            sbBox: (document.querySelector('.statusbar')
                    ? document.querySelector('.statusbar')
                        .getBoundingClientRect().toJSON() : null),
            titlebar: (document.querySelector('.titlebar .t-main')||{}).textContent,
            dashSub: (document.getElementById('dashSub')||{}).textContent,
            active: (document.querySelector('.panel.active')||{}).id,
            url: location.href,
            ls: localStorage.getItem('ap_console_tab'),
        })""")
        sb = facts.pop("sbBox")
        page.screenshot(path=shot)
        browser.close()
        errors = [e for e in errors if "favicon" not in e.lower()]
        return facts, sb, errors


def click_probe(base, shot_prefix):
    """Drive the REAL window buttons + tab URL memory end to end."""
    from playwright.sync_api import sync_playwright
    errors = []
    out = {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--no-sandbox"])
        ctx = browser.new_context(viewport={"width": 1280, "height": 800})
        page = ctx.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text)
                if m.type == "error" else None)
        page.goto(base + "/ui", wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(800)

        # --- tab URL path + memory --------------------------------
        page.click('.sb-item[data-tab="history"]')
        page.wait_for_timeout(400)
        u = page.url
        out["url_after_history"] = ("path=history" in u) and ("token=" in u)
        out["ls_after_history"] = page.evaluate(
            "localStorage.getItem('ap_console_tab')")
        page.reload(wait_until="networkidle")
        page.wait_for_timeout(600)
        out["panel_after_reload"] = page.evaluate(
            "document.querySelector('.panel.active').id")
        # plain /ui with no ?path -> saved tab wins
        page2 = ctx.new_page()
        page2.goto(base + "/ui", wait_until="networkidle")
        page2.wait_for_timeout(600)
        out["panel_saved_tab"] = page2.evaluate(
            "document.querySelector('.panel.active').id")
        page2.close()

        # --- minimize: really collapses ----------------------------
        page.click('.winbtn:has-text("\u2500")')
        page.wait_for_timeout(300)
        out["minimized"] = page.evaluate(
            "document.querySelector('.window').classList.contains('minimized')")
        out["menubar_hidden"] = page.evaluate(
            "document.querySelector('.menubar').offsetHeight === 0")
        page.screenshot(path=shot_prefix + "-minimized.png")
        page.click('.winbtn:has-text("\u2500")')
        page.wait_for_timeout(300)
        out["restored"] = page.evaluate(
            "!document.querySelector('.window')"
            ".classList.contains('minimized')")
        out["menubar_back"] = page.evaluate(
            "document.querySelector('.menubar').offsetHeight > 0")

        # --- maximize: real fullscreen (or soft fallback) ----------
        page.click('.winbtn:has-text("\u25a1")')
        page.wait_for_timeout(500)
        out["fullscreen"] = page.evaluate(
            "!!document.fullscreenElement || "
            "document.querySelector('.window').classList.contains('maxed')")
        page.evaluate("document.exitFullscreen && document.exitFullscreen()")
        page.wait_for_timeout(300)
        out["unmaxed"] = page.evaluate(
            "!document.querySelector('.window').classList.contains('maxed')")

        # --- close: window.close blocked -> honest toast -----------
        # (first let the restore toast expire so the probe reads the
        # close toast, not the older one)
        page.wait_for_timeout(2900)
        page.click(".winbtn.close")
        page.wait_for_timeout(1100)
        out["close_toast"] = " || ".join(page.evaluate(
            "Array.from(document.querySelectorAll('.toast, [class*=toast]'))"
            ".map(function(t){ return t.textContent; })"))
        browser.close()
    errors = [e for e in errors if "favicon" not in e.lower()]
    return out, errors


def main():
    base, token = boot_hub()
    print("BASE", base)
    import json as _j
    req_ok = True

    import urllib.request
    r = urllib.request.Request(base + "/health")
    r.add_header("X-AdvPrint-Token", token)
    with urllib.request.urlopen(r, timeout=10) as f:
        h = _j.loads(f.read().decode())
    print("health version:", h.get("version"))
    req_ok &= h.get("version") == "3.5.8"

    ok = True
    for w, hgt, name in ((1280, 720, "v3.5.8-preview-720p.png"),
                         (1440, 900, "v3.5.8-preview-900p.png")):
        facts, sb, errors = probe_page(
            base, w, hgt, os.path.join(DOCS, name))
        title_ok = ("AdvPrint Pro by Bit Dream IT" in facts["titlebar"]
                    and "Innovative Healthcare Solutions" in facts["titlebar"])
        sb_in = sb and (sb["y"] >= 0) and (sb["y"] + sb["height"] <= facts["vh"] + 1)
        ver_ok = "Printing Hub v3.5.8" in facts["sbText"]
        uuid_ok = ("c-" not in (facts["dashSub"] or "")
                   and "live" in (facts["dashSub"] or ""))
        print("%dx%d title_ok=%s statusbar_inside=%s ver_ok=%s "
              "no_uuid=%s errors=%s" % (w, hgt, title_ok, bool(sb_in),
                                        ver_ok, uuid_ok,
                                        errors or "none"))
        ok &= title_ok and sb_in and ver_ok and uuid_ok and not errors

    beh, errors = click_probe(base, os.path.join(DOCS, "v3.5.8-behaviour"))
    print(_j.dumps(beh, indent=2))
    checks = [
        beh["url_after_history"], beh["ls_after_history"] == "history",
        beh["panel_after_reload"] == "p-history",
        beh["panel_saved_tab"] == "p-history",
        beh["minimized"], beh["menubar_hidden"], beh["restored"],
        beh["menubar_back"], beh["fullscreen"], beh["unmaxed"],
        "blocked closing" in (beh["close_toast"] or ""),
    ]
    ok &= all(checks) and not errors
    if errors:
        print("JS errors:", errors)

    print("\nSMOKE v3.5.8:", "PASS" if (ok and req_ok) else "FAIL")
    return 0 if (ok and req_ok) else 1


if __name__ == "__main__":
    sys.exit(main())
