#!/usr/bin/env python3
"""v3.5.8 dev probe - boot the REAL hub, open the ONE UI, screenshot
Dashboard + History + print runtime facts (title, url, dashSub text).
Ground truth for the user's v3.5.8 report (uuid on Dashboard?)."""
import json
import os
import socket
import sys
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
    import tempfile
    data_dir = tempfile.mkdtemp(prefix="advprint-probe-358-")
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


def main():
    base, token = boot_hub()
    print("BASE", base, "TOKEN", token[:4] + "..." + token[-4:])
    from playwright.sync_api import sync_playwright
    errors = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.on("pageerror", lambda e: errors.append("PAGEERR " + str(e)))
        page.on("console", lambda m: errors.append("CONERR " + m.text)
                if m.type == "error" else None)
        page.goto(base + "/ui", wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(1500)
        facts = page.evaluate("""() => ({
            title: document.title,
            url: location.href,
            dashSub: (document.getElementById('dashSub')||{}).textContent,
            titlebar: (document.querySelector('.titlebar .t-main')||{}).textContent,
            statusbar: (document.querySelector('.statusbar')||{}).textContent,
        })""")
        print(json.dumps(facts, indent=2, ensure_ascii=False))
        page.screenshot(path=os.path.join(DOCS, "probe-358-dashboard.png"))
        # history tab
        page.evaluate("showTab('history')")
        page.wait_for_timeout(600)
        print("URL after History click:", page.url)
        print("TITLE on history:", page.title())
        page.screenshot(path=os.path.join(DOCS, "probe-358-history.png"))
        # reload - where does it land?
        page.reload(wait_until="networkidle")
        page.wait_for_timeout(800)
        vis = page.evaluate("document.querySelector('.panel.active').id")
        print("Panel after reload:", vis)
        browser.close()
    print("JS errors:", errors if errors else "none")


if __name__ == "__main__":
    main()
