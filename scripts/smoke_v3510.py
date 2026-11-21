#!/usr/bin/env python3
"""v3.5.10 release smoke - boots the REAL hub and probes the ONE UI.

The v3.5.10 change is the ONE POWER SWITCH release (popup + console +
options = the same switch, locked by tests/test_v3510.py + the
behavioral simulation tests/ext_sync_sim.js). The browser-side half is
locked here with the real hub + a real Chromium page:

  - /health reports 3.5.10; the served /ui title is the BRAND;
  - the Queue tab status card is LIVE: it reads "Queue mode ON" with a
    RUNNING chip on a fresh hub (the old card was static demo HTML);
  - flipping the console Queue-mode switch (the same key the popup
    switch writes) changes the card to "Queue mode OFF - instant
    print" AND POSTs ext_prefs.queueMode=false to the hub (/config
    proves it), and the switch does NOT snap back over the 3 s poll;
  - flipping the master switch OFF saves ext_prefs.enabled=false and
    shows the honest gray state; flipping both back restores ON;
  - the status bar reads "Printing Hub v3.5.10", zero JS errors;
  - screenshots saved to docs/ (720p + 900p + the OFF state).

Run:  python3 scripts/smoke_v3510.py
"""
import json
import os
import socket
import sys
import tempfile
import threading
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "tool", "windows", "portable", "hub"))

import advprint  # noqa: E402

DOCS = os.path.join(ROOT, "docs")
V = "3.5.10"


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def boot_hub():
    data_dir = tempfile.mkdtemp(prefix="advprint-smoke-3510-")
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


def hub_config(base, token):
    r = urllib.request.Request(base + "/config")
    r.add_header("X-AdvPrint-Token", token)
    with urllib.request.urlopen(r, timeout=10) as f:
        return json.loads(f.read().decode())


def probe(base, token):
    """Drive the real console page: read the live card, flip the
    switches, prove the hub learned it and the card follows."""
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
        url = base + "/ui?" + urllib.parse.urlencode({"token": token})
        page.goto(url, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(1500)
        out["titlebar"] = page.evaluate(
            "(document.querySelector('.titlebar .t-main')||{}).textContent")
        out["sb_version"] = page.evaluate(
            "(document.querySelector('.statusbar')||{}).textContent || ''")

        # --- the LIVE queue card on a fresh hub -------------------
        page.click('.sb-item[data-tab="queue"]')
        page.wait_for_timeout(1500)          # let poll() land once
        out["card_fresh"] = page.evaluate(
            "(document.getElementById('qmodeHead')||{}).textContent || ''")
        out["card_fresh_on"] = ("Queue mode <b>ON</b>" in
                                page.evaluate(
            "(document.getElementById('qmodeHead')||{}).innerHTML"))
        out["card_fresh_running_chip"] = page.evaluate(
            "(function(){var h=document.getElementById('qmodeHead');"
            "return h && !!h.querySelector('.chip.ok');})()")

        # --- flip the QUEUE-MODE switch (popup-identical key) ------
        page.evaluate(
            "document.querySelectorAll('#p-power .tgl .switch')[1].click()")
        page.wait_for_timeout(1200)          # 400 ms debounce + POST
        cfg = hub_config(base, token)
        out["hub_queue_mode_off"] = \
            (cfg.get("ext_prefs") or {}).get("queueMode") is False
        out["card_off_text"] = page.evaluate(
            "(document.getElementById('qmodeHead')||{}).innerHTML")
        out["card_shows_off"] = "Queue mode <b>OFF</b>" in \
            out["card_off_text"]
        # the switch must NOT snap back over the 3 s poll
        page.wait_for_timeout(3600)
        out["switch_stays_off"] = page.evaluate(
            "!document.querySelectorAll('#p-power .tgl .switch')[1]"
            ".classList.contains('on')")
        cfg = hub_config(base, token)
        out["hub_queue_mode_still_off"] = \
            (cfg.get("ext_prefs") or {}).get("queueMode") is False
        page.screenshot(path=os.path.join(DOCS,
                        "v3.5.10-queue-mode-off.png"))

        # --- flip the MASTER switch OFF ----------------------------
        page.evaluate(
            "document.querySelectorAll('#p-power .tgl .switch')[0].click()")
        page.wait_for_timeout(1200)
        cfg = hub_config(base, token)
        out["hub_enabled_off"] = \
            (cfg.get("ext_prefs") or {}).get("enabled") is False
        # print_defaults untouched, console-owned keys untouched
        out["master_flip_only_enabled"] = (
            (cfg.get("ext_prefs") or {}).get("queueMode") is False and
            (cfg.get("ext_prefs") or {}).get("hookPrint") in (None, True))

        # --- flip both back ON (last writer wins, hub follows) -----
        page.evaluate(
            "document.querySelectorAll('#p-power .tgl .switch')[0].click()")
        page.evaluate(
            "document.querySelectorAll('#p-power .tgl .switch')[1].click()")
        page.wait_for_timeout(1200)
        cfg = hub_config(base, token)
        ep = cfg.get("ext_prefs") or {}
        out["flipped_back_on"] = ep.get("enabled") is True and \
            ep.get("queueMode") is True
        out["card_back_on"] = "Queue mode <b>ON</b>" in page.evaluate(
            "(document.getElementById('qmodeHead')||{}).innerHTML")

        # --- viewport checks (720p + 900p) -------------------------
        for w, hgt, name in ((1280, 720, "v3.5.10-preview-720p.png"),
                             (1440, 900, "v3.5.10-preview-900p.png")):
            page.set_viewport_size({"width": w, "height": hgt})
            page.wait_for_timeout(400)
            box = page.evaluate(
                "(function(){var s=document.querySelector('.statusbar');"
                "return s ? s.getBoundingClientRect().toJSON() : null;})()")
            out["sb_in_viewport_%dx%d" % (w, hgt)] = bool(box) and \
                box["top"] >= 0 and box["bottom"] <= hgt
        page.screenshot(path=os.path.join(DOCS, "v3.5.10-preview-900p.png"))
        browser.close()
    errors = [e for e in errors if "favicon" not in e.lower()]
    return out, errors


def main():
    base, token = boot_hub()
    print("BASE", base)
    ok = True

    r = urllib.request.Request(base + "/health")
    r.add_header("X-AdvPrint-Token", token)
    with urllib.request.urlopen(r, timeout=10) as f:
        h = json.loads(f.read().decode())
    print("health version:", h.get("version"))
    ok &= h.get("version") == V

    out, errors = probe(base, token)
    for k in sorted(out):
        v = out[k]
        if isinstance(v, str) and len(v) > 90:
            v = v[:90] + "..."
        print("  %-30s %s" % (k, v))
    ok &= out.get("titlebar", "").find("AdvPrint Pro by Bit Dream IT") >= 0
    ok &= ("Printing Hub v%s" % V) in out.get("sb_version", "")
    ok &= out.get("card_fresh_on") is True
    ok &= out.get("card_fresh_running_chip") is True
    ok &= out.get("hub_queue_mode_off") is True
    ok &= out.get("card_shows_off") is True
    ok &= out.get("switch_stays_off") is True
    ok &= out.get("hub_queue_mode_still_off") is True
    ok &= out.get("hub_enabled_off") is True
    ok &= out.get("master_flip_only_enabled") is True
    ok &= out.get("flipped_back_on") is True
    ok &= out.get("card_back_on") is True
    ok &= out.get("sb_in_viewport_1280x720") is True
    ok &= out.get("sb_in_viewport_1440x900") is True
    ok &= not errors
    if errors:
        print("JS ERRORS:")
        for e in errors[:10]:
            print("   ", e[:200])

    print("\n%s" % ("SMOKE v3.5.10 PASS" if ok else "SMOKE v3.5.10 FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
