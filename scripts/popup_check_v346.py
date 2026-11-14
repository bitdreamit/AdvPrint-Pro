#!/usr/bin/env python3
"""v3.4.6 popup behaviour check in a REAL browser (Chromium via
Playwright). popup.html/popup.js are loaded from file:// with a stubbed
chrome.* API - the stub now mirrors the REAL hub wire format (the hub
answers "default"; "default_printer" never existed - the v3.3.4 stub
reproduced the bug, which is why the selector always showed the FIRST
printer). Verified live:

  1. popup open  -> printer list loads, the hub's CURRENT default is
     preselected (FIELD FIX), the option is marked [default],
     ZERO set-default commands
  2. user picks a DIFFERENT printer (a real change event) -> EXACTLY
     ONE hubSetDefault + the choice is REMEMBERED (advLastPrinter)
  3. picking the SAME printer again / Reload / net icon -> nothing
  4. "next open" with the default unknown -> the REMEMBERED printer is
     auto-selected (memory), tooltip says "Last used"
  5. "next open" with the default present -> the default wins,
     still zero commands
  6. no JS exceptions
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
window.__store = { authProblem: null, advLastPrinter: "" };
window.__printers = { ok: true, printers: [
  { name: "HP Laser 103 107 108", status: "ready", is_default: true },
  { name: "Epson L3250", status: "ready", is_default: false }],
  default: "HP Laser 103 107 108" };
window.__setStatus = { ok: true, version: "3.4.6", os: "Windows",
  pending: 0, paused: false, lan_used: false, self_share_lan: true,
  self_ok: true, lan_bind_addrs: ["192.168.1.10:9235"], default_token_warning: false };
window.__setDefaultResult = { ok: true, default: "Epson L3250",
  printer: "Epson L3250", detail: "Windows default printer is now" };
window.chrome = {
  runtime: {
    getManifest: () => ({ version: "3.4.6" }),
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
      get: async (d) => {
        const out = {};
        for (const k of Object.keys(d || {}))
          out[k] = (k in window.__store) ? window.__store[k] : d[k];
        return out;
      },
      remove: async (k) => { delete window.__store[k]; },
      set: async (o) => { Object.assign(window.__store, o);
        window.__calls.push({ type: "__storageSet",
                              data: JSON.parse(JSON.stringify(o)) }); }
    }
  },
  i18n: { getUILanguage: () => "en" }
};
window.onerror = (m) => { window.__jserr = (window.__jserr||[]).concat([String(m)]); return false; };
</script>
"""


def main():
    src = open(POPUP, encoding="utf-8").read()
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

        # ---- 1. open: the hub's CURRENT default preselected ----
        val = page.eval_on_selector("#selPrinter", "el => el.value")
        check("popup open: OS default preselected (field fix)",
              val == "HP Laser 103 107 108", val)
        n = page.evaluate("window.__calls.filter(c => c.type === "
                          "'hubSetDefault').length")
        check("popup open: ZERO set-default commands", n == 0, str(n))
        texts = page.eval_on_selector_all(
            "#selPrinter option", "els => els.map(e => e.textContent)")
        check("the OS default is marked [default]",
              any("[default]" in t for t in texts), str(texts))

        # ---- 2. user picks the OTHER printer: ONE cmd + remembered --
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
        remembered = page.evaluate("window.__store.advLastPrinter")
        check("the choice is REMEMBERED (advLastPrinter)",
              remembered == "Epson L3250", str(remembered))
        title = page.get_attribute("#selPrinter", "title") or ""
        check("tooltip confirms the new default",
              "Epson" in title, title)

        # ---- 3. same printer again / reload / net icon: nothing ----
        page.select_option("#selPrinter", "Epson L3250")
        page.wait_for_timeout(200)
        n = page.evaluate("window.__calls.filter(c => c.type === "
                          "'hubSetDefault').length")
        check("picking the SAME printer again: no extra command",
              n == 1, str(n))
        page.click("#bRefreshPrinters")
        page.wait_for_timeout(500)
        n = page.evaluate("window.__calls.filter(c => c.type === "
                          "'hubSetDefault').length")
        check("after Reload: still exactly ONE set-default total",
              n == 1, str(n))
        page.click("#netIcon")
        page.wait_for_timeout(400)
        n = page.evaluate("window.__calls.filter(c => c.type === "
                          "'hubSetDefault').length")
        check("after net-icon click: still ONE set-default total",
              n == 1, str(n))
        cls = page.get_attribute("#netIcon", "class") or ""
        check("network icon shows the LAN state (self_share_lan true)",
              "lan" in cls, cls)
        sharing = page.text_content("#swShareRxRow b") or ""
        check("the LAN switch reads Sharing",
              "Sharing" in sharing, sharing)

        # ---- 4. "next open", hub default UNKNOWN -> memory wins ----
        page.evaluate(
            "window.__printers.default = '';")
        page.evaluate("loadPrinters()")
        page.wait_for_timeout(300)
        val = page.eval_on_selector("#selPrinter", "el => el.value")
        check("next open (default unknown): REMEMBERED printer selected",
              val == "Epson L3250", val)
        title = page.get_attribute("#selPrinter", "title") or ""
        check("memory tooltip says Last used", "Last used" in title,
              title)
        n = page.evaluate("window.__calls.filter(c => c.type === "
                          "'hubSetDefault').length")
        check("memory open: still ZERO extra set-default", n == 1, str(n))

        # ---- 5. "next open", default present -> default wins ----
        page.evaluate(
            "window.__printers.default = 'HP Laser 103 107 108';")
        page.evaluate("loadPrinters()")
        page.wait_for_timeout(300)
        val = page.eval_on_selector("#selPrinter", "el => el.value")
        check("next open (default present): the DEFAULT is selected",
              val == "HP Laser 103 107 108", val)
        n = page.evaluate("window.__calls.filter(c => c.type === "
                          "'hubSetDefault').length")
        check("default open: still ZERO extra set-default", n == 1,
              str(n))

        # ---- 6. screenshot for the delivery ----
        shot = os.path.join(ROOT, "scripts", "popup-v346.png")
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
    print("POPUP v3.4.6 CHECK PASSED - default field fix + last-used "
          "memory verified in a real browser")
    return 0


if __name__ == "__main__":
    sys.exit(main())
