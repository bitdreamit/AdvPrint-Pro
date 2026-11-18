#!/usr/bin/env python3
"""v3.5.6 release smoke - boots the REAL hub and probes the ONE UI.

Verification carried from v3.5.3 (status bar always visible) plus the
v3.5.6 version coherence:

  - /health reports version 3.5.6 (+ default_printer/raw/worker);
  - /extension/info reports 3.5.6 and stale:false;
  - the served /ui page: title has v3.5.6, the status bar sits fully
    inside the viewport at 1280x720 and 1440x900, document scroll
    height == viewport height (no hidden overflow), the status bar
    version pane reads "Printing Hub v3.5.6", zero JS errors;
  - screenshots saved to docs/ for the release notes.

Run:  python3 scripts/smoke_v354.py
"""
import json
import os
import socket
import sys
import tempfile
import threading
import urllib.request
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
    data_dir = tempfile.mkdtemp(prefix="advprint-smoke-356-")
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


def get_json(base, path, token=None):
    req = urllib.request.Request(base + path)
    if token:
        req.add_header("X-AdvPrint-Token", token)
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


def probe_page(base, width, height, shot):
    from playwright.sync_api import sync_playwright
    errors = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": width, "height": height})
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text)
                if m.type == "error" else None)
        page.goto(base + "/ui", wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(1200)
        title = page.title()
        sb = page.locator(".statusbar").bounding_box()
        metrics = page.evaluate("""() => ({
            vh: window.innerHeight,
            dh: document.documentElement.scrollHeight,
            desk: document.querySelector('.desktop')
                     .getBoundingClientRect().bottom,
            sbText: document.querySelector('.statusbar').innerText
                        .replace(/\\s+/g, ' ').trim()
        })""")
        page.screenshot(path=shot)
        browser.close()
    return title, sb, metrics, errors


def main():
    base, token = boot_hub()
    print("hub on", base)
    health = get_json(base, "/health")
    assert health.get("version") == "3.5.6", health
    print("/health version:", health["version"],
          "| default_printer:", health.get("default_printer"),
          "| worker_alive:", health.get("worker_alive"),
          "| raw_active:", health.get("raw_active"))
    ext = get_json(base, "/extension/info", token)
    print("/extension/info:", ext.get("version"), "stale:", ext.get("stale"))
    assert ext.get("version") == "3.5.6" and not ext.get("stale")

    rows = []
    ok = True
    for w, h, name in ((1280, 720, "v3.5.6-preview-720p.png"),
                       (1440, 900, "v3.5.6-preview-900p.png")):
        title, sb, m, errors = probe_page(
            base, w, h, os.path.join(DOCS, name))
        inside = sb and sb["y"] >= 0 and (sb["y"] + sb["height"]) <= m["vh"]
        no_overflow = m["dh"] == m["vh"]
        ver_ok = ("v3.5.6" in title) and ("Printing Hub v3.5.6" in m["sbText"])
        row = dict(viewport="%dx%d" % (w, h),
                   statusbar="%d..%d" % (sb["y"], sb["y"] + sb["height"]),
                   viewport_h=m["vh"], desktop_bottom=round(m["desk"]),
                   scroll_h=m["dh"], js_errors=len(errors),
                   title_ok=ver_ok)
        rows.append(row)
        ok = ok and inside and no_overflow and ver_ok and not errors
        print(json.dumps(row))
        if errors:
            print("  JS errors:", errors[:5])
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
