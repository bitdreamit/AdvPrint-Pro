"""v3.2.2 - EVERY IPP PATTERN + WORKING SWITCHES + NO POPUP.

Covers the three user-reported v3.2.1 defects:
  1. "both all ipp pattern need access able"  - ipp://ip:9235/ipp/print,
     http://ip:9235/ipp/print AND the NEW standard-port mirror
     http://ip:631/ipp/print (Android's Default Print Service ignores
     custom ports on manual add - it always tries port 631 first).
  2. "in android it not success to connect"   - mDNS discovery is now
     decoupled from share_lan (ipp_printer mode owns discovery + the
     LAN listener), so the printer appears by itself everywhere.
  3. "Any togol not work"                     - every switch in the ONE
     UI is now a real control: a delegated click handler flips it and
     saves instantly through the panel's own save path.
  4. "popup also no need"                     - popup.html/popup.js are
     gone; the toolbar icon opens the console.
"""
import json
import os
import re
import struct
import urllib.error
import urllib.request

import pytest

import advprint

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


# ------------------------------------------------------------
# 1) the standard-port IPP mirror really serves IPP
# ------------------------------------------------------------

def _ipp_print_job(printer_uri, title="v322-mirror-probe"):
    # RFC 8010 wire form: version(2) op-id(2) request-id(4)
    #   0x01 operation-attributes-tag, then charset/lang/uri/user/name,
    #   0x03 end-of-attributes, then the document.
    body = (struct.pack(">BBH", 1, 1, 0x0002) + struct.pack(">I", 7) +
            b"\x01")

    def attr(b, t, name, val):
        b += struct.pack(">B", t) + struct.pack(">H", len(name)) + name
        b += struct.pack(">H", len(val)) + val
        return b
    body = attr(body, 0x47, b"attributes-charset", b"utf-8")
    body = attr(body, 0x48, b"attributes-natural-language", b"en")
    body = attr(body, 0x45, b"printer-uri", printer_uri)
    body = attr(body, 0x42, b"requesting-user-name", b"probe")
    body = attr(body, 0x42, b"job-name", title.encode())
    body = attr(body, 0x49, b"document-format", b"application/pdf")
    body += b"\x03%PDF-1.4\n%v322 mirror probe\n%%EOF\n"
    return body


def test_v322_ipp_mirror_serves_print_job(hub, monkeypatch):
    """http://<lan-ip>:9631/ipp/print must answer a real IPP Print-Job
    with 0x0000 successful-ok (the Android manual-add path)."""
    monkeypatch.setattr(advprint, "lan_ip", lambda: "127.0.0.2")
    old = advprint.CFG.get("ipp_standard_port")
    advprint.CFG["ipp_standard_port"] = 9631
    try:
        err = advprint.ipp631_listen_start()
        assert err is None, err
        assert advprint._IPP631_STATE["up"] is True
        try:
            req = urllib.request.Request(
                "http://127.0.0.2:9631/ipp/print",
                data=_ipp_print_job(b"ipp://127.0.0.2:9631/ipp/print"),
                headers={"Content-Type": "application/ipp"})
            resp = urllib.request.urlopen(req, timeout=5).read()
            status = struct.unpack(">BBH", resp[:4])[2]
            assert status == 0x0000, "IPP Print-Job via the mirror failed"
            # the job really entered the queue
            jobs = advprint.db_list(5)
            assert any("v322-mirror-probe" in (j["title"] or "")
                       for j in jobs), "mirror job not queued"
        finally:
            advprint.ipp631_listen_stop()
        assert advprint._IPP631_STATE["up"] is False
    finally:
        if old is None:
            advprint.CFG.pop("ipp_standard_port", None)
        else:
            advprint.CFG["ipp_standard_port"] = old


def test_v322_ipp_mirror_landing_and_redirect(hub, monkeypatch):
    """GET /ipp/print on the mirror = the how-to page; everything else
    redirects to the main hub port."""
    monkeypatch.setattr(advprint, "lan_ip", lambda: "127.0.0.2")
    old = advprint.CFG.get("ipp_standard_port")
    advprint.CFG["ipp_standard_port"] = 9632
    try:
        assert advprint.ipp631_listen_start() is None
        try:
            page = urllib.request.urlopen(
                "http://127.0.0.2:9632/ipp/print", timeout=5).read().decode()
            assert "IPP network printer" in page
            assert "Android" in page and "AirPrint" in page
            # unknown path -> redirect to the main port (no auto-follow)
            class _NoRedirect(urllib.request.HTTPRedirectHandler):
                def redirect_request(self, *a, **k):
                    return None
            op = urllib.request.build_opener(_NoRedirect)
            try:
                op.open("http://127.0.0.2:9632/dashboard", timeout=5)
                redirected = False
            except urllib.error.HTTPError as e:
                redirected = e.code in (301, 302, 303, 307)
                loc = e.headers.get("Location", "")
                assert ":%d/dashboard" % advprint.CFG["port"] in loc, \
                    "mirror must send non-IPP paths to the main port " + loc
            assert redirected, "non-IPP paths must leave the mirror"
        finally:
            advprint.ipp631_listen_stop()
    finally:
        if old is None:
            advprint.CFG.pop("ipp_standard_port", None)
        else:
            advprint.CFG["ipp_standard_port"] = old


def test_v322_config_key_accepted_and_persisted(hub):
    code, d = hub.post("/config", {"ipp_standard_port": 0})
    assert code == 200 and d.get("ok") is True
    code, d = hub.get("/config")
    assert d["ipp_standard_port"] == 0
    code, d = hub.post("/config", {"ipp_standard_port": 631})
    assert code == 200


def test_v322_health_carries_ipp_state(hub):
    code, d = hub.get("/health")
    assert code == 200
    assert "ipp_std" in d and "ipp_mdns_up" in d and "ipp_urls" in d
    assert set(d["ipp_urls"]) == {"ipp", "http", "std"}


# ------------------------------------------------------------
# 2) discovery decoupled from share_lan
# ------------------------------------------------------------

def test_v322_mdns_want_follows_ipp_printer(monkeypatch):
    """The mDNS loop must run when ONLY ipp_printer is on (v3.2.1
    required share_lan too - fresh IPP installs never advertised)."""
    src = open(os.path.join(ROOT, "tool", "unix", "hub", "advprint.py"),
               encoding="utf-8").read()
    m = re.search(r"want = \(ipp_printer_enabled\(\) and.*?\)\n",
                  src, re.S)
    assert m, "mdns want expression not found"
    assert "share_lan" not in m.group(0), \
        "discovery must not depend on share_lan anymore (Android fix)"


def test_v322_lan_listener_starts_for_ipp_printer():
    src = open(os.path.join(ROOT, "tool", "unix", "hub", "advprint.py"),
               encoding="utf-8").read()
    m = re.search(r"def lan_listen_ensure.*?(?=\ndef |\n# -{10,})",
                  src, re.S)
    assert m and ('bool(CFG.get("share_lan")) or ipp_printer_enabled()'
                  in m.group(0)), \
        "LAN listener must auto-start when IPP printer mode is on"


def test_v322_mdns_txt_carries_airprint_keys():
    src = open(os.path.join(ROOT, "tool", "unix", "hub", "advprint.py"),
               encoding="utf-8").read()
    for key in ('"rp", rp', '"URF", "V1.4"', '"pdl", "application/pdf',
                '"usb_MFG"', '"txtvers", "1"'):
        assert key in src, "AirPrint TXT key missing: %s" % key


# ------------------------------------------------------------
# 3) the switches really work (delegated toggle + instant save)
# ------------------------------------------------------------

def _ui():
    return open(os.path.join(ROOT, "tool", "unix", "hub", "console.html"),
                encoding="utf-8").read()


def test_v322_switch_delegated_handler_wired():
    ui = _ui()
    assert 'ev.target.closest(".switch")' in ui, \
        "no delegated switch click handler"
    assert "s.classList.toggle(\"on\")" in ui, \
        "the handler never flips the switch"
    assert 'zone.id === "rulemodal"' in ui, \
        "rule editor switches must toggle"


def test_v322_switch_saves_are_wired():
    ui = _ui()
    # power/browser -> ext_prefs, hub -> saveHub, settings -> saveSettingsPanel
    assert 'scope === "p-power" || scope === "p-browser") saveExtPrefs()' in ui
    assert 'scope === "p-hub") saveHub()' in ui
    assert 'scope === "p-settings") saveSettingsPanel()' in ui
    assert 'body: { drop_delete: v }' in ui
    # saves clear the dirty keys so the poll may refresh again
    assert 'k.indexOf("hub_") === 0' in ui
    assert 'k.indexOf("#p-power") === 0' in ui


def test_v322_settings_tray_switches_refuse():
    # v3.2.5 BUG FIX 6: the OLD refuse-with-a-toast behavior is GONE -
    # "Start with Windows" now really toggles (POST /autostart writes /
    # removes the Startup shortcut) and reads the REAL state from
    # /health. Minimize-to-tray keeps its hint.
    ui = _ui()
    assert "Start with Windows is managed by the service/tray" not in ui, \
        "v3.2.5 removed the refuse-toast - the switch must work now"
    assert "/autostart" in ui, "the switch must call POST /autostart"
    assert "Minimize to tray is the desktop-app default" in ui
    assert "autoStartState = !!h.autostart" in ui, \
        "the UI must read the REAL /health autostart state"


# ------------------------------------------------------------
# 4) no popup + menu items all fire real actions
# ------------------------------------------------------------

def test_v322_extension_has_no_popup():
    # v3.2.4: the POPUP IS BACK (default_popup again) - the state lock
    # now asserts the CURRENT reality; see tests/test_v324.py for the
    # full popup contract.
    ext = os.path.join(ROOT, "extension")
    assert os.path.exists(os.path.join(ext, "popup.html"))
    assert os.path.exists(os.path.join(ext, "popup.js"))
    man = json.load(open(os.path.join(ext, "manifest.json"),
                         encoding="utf-8"))
    assert man.get("action", {}).get("default_popup") == "popup.html"
    bg = open(os.path.join(ext, "background.js"), encoding="utf-8").read()
    assert "chrome.action.onClicked" in bg   # stays as the no-popup fallback
    assert "/ui" in bg


def test_v322_no_demo_stub_menu_items():
    ui = _ui()
    stubs = re.findall(r'data-toast="[^"]*\(demo\)"', ui)
    assert not stubs, "menu/panel demo stubs left: %s" % stubs[:3]


def test_v322_menu_items_fire_real_actions():
    ui = _ui()
    for act in ("export-history", "queue-clear-finished", "copy-hub-url",
                "fw-allow", "fw-status", "restart", "rotate-token",
                "testprint", "open-docs", "open-github"):
        assert 'data-act="%s"' % act in ui, "menu action missing: " + act
    assert 'data-tool="service-install"' in ui
    assert 'data-tool="check-update"' in ui


def test_v322_no_duplicate_save_push_buttons():
    ui = _ui()
    assert ui.count("Save &amp; push to browsers") == 0, \
        "the duplicated save buttons must be gone (switches save instantly)"


def test_v322_lan_tab_carries_platform_guide():
    ui = _ui()
    for needle in ("ippUrlIpp", "ippUrlHttp", "Windows 10 / 11",
                   "macOS", "iPhone / iPad", "Android", "Default Print Service",
                   "IPP Device", "Bonjour list", "AirPrint"):
        assert needle in ui, "LAN tab guide missing: " + needle
    # the live-fill render updates the guide URLs from the running hub
    assert 'ipEl("ippGuideWin", lanBase() + "/ipp/print")' in ui
    assert 'window._lastHealth' in ui and "ipp_mdns_up" in ui


def test_v322_version_strings_agree():
    assert advprint.VERSION == "3.2.9"
    vt = open(os.path.join(ROOT, "VERSION.txt"), encoding="utf-8").read()
    assert "3.2.9" in vt
    man = json.load(open(os.path.join(ROOT, "extension", "manifest.json"),
                         encoding="utf-8"))
    assert man["version"] == "3.2.9"
