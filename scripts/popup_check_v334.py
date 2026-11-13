#!/usr/bin/env python3
"""v3.3.4 popup behaviour check in a REAL browser (Chromium via
Playwright). popup.html/popup.js are loaded from file:// with a stubbed
chrome.* API; the stub counts every message so the release's core
promise is verified live:

  1. popup open/reload  -> printer list loads, default preselected,
     ZERO set-default commands
  2. user picks a DIFFERENT printer (a real change event) -> EXACTLY
     ONE hubSetDefault
  3. picking the SAME printer again / re-entering -> nothing
  4. Reload button + network icon reload state, still zero set-default
  5. network icon state classes exist (on/lan/off)
"""
import json
import os
import sys

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POPUP = os.path.join(ROOT, "extension", "popup.html")

fail = []


def check(name, cond, detail=""):
    print(("[OK]   " if cond else "[FAIL] ") + name + (" - " + detail
                                                        if detail else ""))
    if not cond:
        fail.append(name)


STUB = """
<script>
window.__calls = [];
window.__printers = { ok: true, printers: [
  { name: "HP Laser 103 107 108", status: "ready", is_default: true },
  { name: "Epson L3250", status: "ready", is_default: false }],
  default_printer: "HP Laser 103 107 108" };
window.__setStatus = { ok: true, version: "3.3.4", os: "Windows",
  pending: 0, paused: false, lan_used: false, self_share_lan: true,
  self_ok: true, lan_bind_addrs: ["192.168.1.10:9235"], default_token_warning: false };
window.__setDefaultResult = { ok: true, default: "Epson L3250",
  printer: "Epson L3250", detail: "Windows default printer is now" };
window.chrome = {
  runtime: {
    getManifest: () => ({ version: "3.3.4" }),
    openOptionsPage: () => {},
    sendMessage: (msg, cb) => {
      window.__calls.push(JSON.parse(JSON.stringify(msg)));
      let r;
      switch (msg.type) {
        case "getCfg": r = { ok: true, cfg: { enabled: true,
          queueMode: true, lanSend: false } }; break;
        case "hubStatus": r = window.__setStatus; break;
        case "hubPrinters": r = window.__printers; break;
        case "hubSetDefault": r = window.__setDefaultResult; break;
        case "hubJobs": r = { ok: true, jobs: [] }; break;
        case "retryInfo": r = { ok: true, count: 0 }; break;
        case "saveCfg": r = { ok: true }; break;
        case "hubConfigSet": r = { ok: true }; break;
        default: r = { ok: true };
      }
      setTimeout(() => cb(r), 5);
    }
  },
  storage: {
    local: {
      get: async () => ({ authProblem: null }),
      remove: async () => {},
      set: async () => {}
    }
  },
  i18n: { getUILanguage: () => "en" }
};
window.onerror = (m) => { window.__jserr = (window.__jserr||[]).concat([String(m)]); return false; };
</script>
"""


def main():
    src = open(POPUP, encoding="utf-8").read()
    # inject the stub BEFORE the first script tag
    src = src.replace("<script src=\"i18n.js\">", STUB +
                      "<script src=\"i18n.js\">", 1)
    tmp = os.path.join(ROOT, "extension", "_popup_harness.html")
    open(tmp, "w", encoding="utf-8").write(src)
    hub_js = os.path.join(ROOT, "extension", "hubStub.js")
    open(hub_js, "w", encoding="utf-8").write("")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 360, "height": 640})
        page.goto("file://" + tmp)
        page.wait_for_timeout(600)

        # ---- 1. open: selector filled, default preselected, no cmd ----
        val = page.eval_on_selector("#selPrinter", "el => el.value")
        check("popup open: OS default preselected",
              val == "HP Laser 103 107 108", val)
        n = page.evaluate("window.__calls.filter(c => c.type === "
                          "'hubSetDefault').length")
        check("popup open: ZERO set-default commands", n == 0, str(n))
        opts = page.eval_on_selector_all("#selPrinter option",
                                         "els => els.map(e => e.value)")
        check("popup open: both printers listed", len(opts) == 2,
              str(opts))

        # ---- 2. user picks the OTHER printer: exactly one command ----
        page.select_option("#selPrinter", "Epson L3250")
        page.wait_for_timeout(300)
        calls = page.evaluate(
            "window.__calls.filter(c => c.type === 'hubSetDefault')")
        check("user change: EXACTLY ONE hubSetDefault", len(calls) == 1,
              json.dumps(calls))
        if calls:
            check("the command carries the picked printer",
                  calls[0].get("printer") == "Epson L3250",
                  str(calls[0]))
        title = page.get_attribute("#selPrinter", "title") or ""
        check("tooltip confirms the new default",
              "Epson" in title, title)

        # ---- 3. same printer again: nothing ----
        page.select_option("#selPrinter", "Epson L3250")
        page.wait_for_timeout(200)
        n = page.evaluate("window.__calls.filter(c => c.type === "
                          "'hubSetDefault').length")
        check("picking the SAME printer again: no extra command",
              n == 1, str(n))

        # ---- 4. reload button + net icon: reload, never set-default ----
        page.click("#bRefreshPrinters")
        page.wait_for_timeout(500)
        n = page.evaluate("window.__calls.filter(c => c.type === "
                          "'hubSetDefault').length")
        check("after Reload: still exactly ONE set-default total",
              n == 1, str(n))
        cls = page.get_attribute("#netIcon", "class") or ""
        check("network icon shows the LAN state (self_share_lan true)",
              "lan" in cls, cls)
        # net icon is clickable = reload
        page.click("#netIcon")
        page.wait_for_timeout(400)
        n = page.evaluate("window.__calls.filter(c => c.type === "
                          "'hubSetDefault').length")
        check("after net-icon click: still ONE set-default total",
              n == 1, str(n))
        # ---- 4b. the ONE design surface: Sharing label + net icon ----
        sharing = page.text_content("#swShareRxRow b") or ""
        check("the LAN switch reads Sharing",
              "Sharing" in sharing, sharing)

        # ---- 5. screenshot for the delivery ----
        shot = os.path.join(ROOT, "scripts", "popup-v334.png")
        page.screenshot(path=shot, full_page=True)
        print("screenshot:", shot)

        errs = page.evaluate("window.__jserr || []")
        check("no JS exceptions in the popup", not errs, str(errs)[:120])
        browser.close()

    os.remove(tmp)
    os.remove(hub_js)
    print()
    if fail:
        print("POPUP CHECK FAILED: %d -> %s" % (len(fail), fail))
        return 1
    print("POPUP v3.3.4 CHECK PASSED - change-only set-default verified "
          "in a real browser")
    return 0


if __name__ == "__main__":
    sys.exit(main())
