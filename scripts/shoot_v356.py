#!/usr/bin/env python3
"""v3.5.6 UI shoot: LAN tab (Console admin access card + ipp:// chips)
and the add-printer guide (Android ipp:// row). Saves screenshots to
docs/ for the release notes."""
import socket
import sys
import tempfile
import threading
import time
from http.server import ThreadingHTTPServer

HERE = __import__("os").path.dirname(__file__)
ROOT = __import__("os").path.dirname(HERE)
sys.path.insert(0, ROOT + "/tool/windows/portable/hub")

import advprint  # noqa: E402


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def main():
    data_dir = tempfile.mkdtemp(prefix="advprint-shoot-356-")
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
    base = "http://127.0.0.1:%d" % port
    token = advprint.CFG["token"]
    print("hub on", base)

    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch(args=["--no-sandbox"])
        pg = b.new_page(viewport={"width": 1440, "height": 900})
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(base + "/ui?token=" + token, wait_until="networkidle")
        time.sleep(1.2)
        # the sandbox cannot bind the real port 631 (needs admin) - feed
        # the LIVE render function the health fields a real LAN hub has,
        # so the screenshots show the actual v3.5.6 LAN state
        INJECT = """
          window._lastHealth = window._lastHealth || {};
          window._lastHealth.ipp_std = {up: true, port: 631,
            addrs: ["[::]:631", "192.168.1.2:631"]};
          window._lastHealth.ui_admin_subnets = ["192.168.1.0/24"];
          window._lastHealth.ui_admin_urls = ["http://192.168.1.2:9235/ui"];
          renderLanRows();
          document.getElementById('row-ipp631').querySelector('.lv')
            .textContent;
        """
        pg.evaluate("showTab('lan')")
        time.sleep(1.6)
        chip = pg.evaluate(INJECT)      # inject + render + read atomically
        pg.screenshot(path=ROOT + "/docs/v3.5.6-lan-admin-card.png",
                      full_page=False)
        pg.evaluate("document.getElementById('uamMode')"
                    ".scrollIntoView({block:'center'})")
        time.sleep(0.5)
        pg.screenshot(path=ROOT + "/docs/v3.5.6-console-admin-card.png",
                      full_page=False)
        # admin card close-up
        el = pg.query_selector("#uamMode")
        assert el, "Console admin access card missing"
        card = pg.evaluate("document.getElementById('uamUrls').textContent")
        print("uamUrls text:", card[:120])
        print("row-ipp631  :", (chip or "")[:120])
        assert chip.startswith("ipp://"), chip
        # add an admin IP through the real UI
        pg.fill("#adminIpInput", "192.168.1.2")
        pg.click("#adminIpAdd")
        time.sleep(1.5)
        chips = pg.evaluate(
            "[...document.querySelectorAll('#adminIpList .chip .mono')]"
            ".map(x => x.textContent)")
        print("admin chips :", chips)
        assert "192.168.1.2" in chips
        mode = pg.evaluate("document.getElementById('uamMode').textContent")
        print("mode chip   :", mode)
        # printers tab - Android guide shows ipp://
        pg.evaluate("showTab('printers')")
        time.sleep(1.2)
        guide = pg.evaluate(
            "document.getElementById('ippGuideAndroid631').textContent")
        print("android631  :", guide)
        assert guide.startswith("ipp://")
        pg.evaluate("document.getElementById('ippGuideAndroid631')"
                    ".scrollIntoView({block:'center'})")
        time.sleep(0.5)
        pg.screenshot(path=ROOT + "/docs/v3.5.6-printers-ipp-guide.png",
                      full_page=False)
        b.close()
    print("JS errors:", len(errs), errs[:2])
    assert not errs
    print("UI SHOOT PASS")


if __name__ == "__main__":
    main()
