"""v3.4.6 - MULTI-PRINTER IPP ADD + POPUP PRINTER/RELOAD/NETWORK RELEASE.

Three real-world reports, each locked here:

BUG 1  "only default or only one add possible" - the mDNS announcer
       stamped the SAME UUID TXT record on every _ipp._tcp service
       (central queue + every per-printer queue), so Windows treated
       the second per-printer queue as a re-announcement of the first
       and refused the add. Every service now carries its OWN stable
       uuid - on the proactive announce AND on direct unicast TXT
       answers. (The IPP endpoints themselves had per-queue uuids since
       v3.2.9; discovery was the blocker.)

BUG 2  "popup reload / set printer - cmd continues to run multiple".
       Layer 1 (popup): the printer selector sends set-default ONLY on
       a real user change - popup open/reload only selects an option
       programmatically (fires no change event), the applied-default
       guard blocks repeats, one call in flight, failures revert.
       Layer 2 (hub): POST /printers/set-default is IDEMPOTENT - an
       already-default request answers unchanged:true with ZERO setter
       commands, and a successful set caches the verified result so
       even an immediate repeat spawns nothing.

BAT    allow_extention_advprint_pro.bat deleted ExtensionInstallForcelist
       on every run and never wrote it back (the CRX force-install was
       silently wiped -> "Apply HKLM / Apply HKCU not working"). It now
       writes all three policies per browser, never wipes in the apply
       path, and has a real HKLM/HKCU menu.
"""
import hashlib
import json
import os
import re
import time

import pytest

import advprint

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------
# helpers
# ---------------------------------------------------------------

def _parse_records(packet):
    """Very small DNS answer parser for OUR OWN mDNS packets (no
    compression pointers are ever emitted by the hub). Yields
    (name, rtype, rdata)."""
    i = 12                                   # header
    qd = int.from_bytes(packet[4:6], "big")
    an = int.from_bytes(packet[6:8], "big")

    def _name(pos):
        labels = []
        while True:
            ln = packet[pos]
            pos += 1
            if ln == 0:
                break
            labels.append(packet[pos:pos + ln].decode("utf-8", "replace"))
            pos += ln
        return ".".join(labels), pos

    for _ in range(qd):                      # skip questions
        _, i = _name(i)
        i += 4
    out = []
    for _ in range(an):
        name, i = _name(i)
        rtype = int.from_bytes(packet[i:i + 2], "big")
        i += 2 + 2 + 4                       # class + ttl
        rdlen = int.from_bytes(packet[i:i + 2], "big")
        i += 2
        out.append((name, rtype, packet[i:i + rdlen]))
        i += rdlen
    return out


def _txt_uuid(rdata):
    """Pull the UUID=... value out of one TXT record."""
    i = 0
    while i < len(rdata):
        ln = rdata[i]
        item = rdata[i + 1:i + 1 + ln].decode("utf-8", "replace")
        i += 1 + ln
        if item.upper().startswith("UUID="):
            return item[5:]
    return None


class _CaptureSock:
    """Stands in for the mDNS socket - records every sendto."""
    def __init__(self):
        self.sent = []

    def sendto(self, pkt, addr):
        self.sent.append((bytes(pkt), addr))


# ---------------------------------------------------------------
# BUG 1 - mDNS per-service printer-uuid uniqueness
# ---------------------------------------------------------------

@pytest.fixture()
def two_printers(monkeypatch):
    names = ["HP Laser 103", "Epson L3250"]
    monkeypatch.setattr(advprint, "list_printers_cached",
                        lambda max_age=30.0: list(names))
    return names


def test_mdns_services_are_6tuples_with_slugs(two_printers):
    svcs = advprint._mdns_services()
    assert len(svcs) == 3                       # central + 2 printers
    inst0, rp0, ty0, note0, slug0, port0 = svcs[0]
    assert slug0 is None                        # central queue
    assert rp0 == "ipp/print"
    slugs = [s[4] for s in svcs[1:]]
    ports = [s[5] for s in svcs[1:]]
    assert all(isinstance(p_, int) and p_ > 0 for p_ in ports)
    assert slugs == [advprint._ipp_queue_slug("HP Laser 103"),
                     advprint._ipp_queue_slug("Epson L3250")]
    for inst, rp, ty, note, slug, _port in svcs[1:]:
        assert rp == "ipp/print/" + slug


def test_mdns_txt_uuid_unique_per_service(two_printers):
    svcs = advprint._mdns_services()
    uuids = []
    for inst, rp, ty, note, slug, _port in svcs:
        txt = advprint._mdns_txt_records(rp=rp, ty=ty, note=note, slug=slug)
        u = _txt_uuid(txt)
        assert u, "TXT record must carry a UUID"
        uuids.append(u)
    assert len(set(uuids)) == len(svcs), \
        "every advertised service needs its OWN printer-uuid"
    # central queue keeps the hub uuid, per-printer queues their own
    assert uuids[0] == advprint._ipp_printer_uuid().replace("urn:uuid:", "")
    assert uuids[1] == advprint._ipp_printer_uuid(svcs[1][4]).replace(
        "urn:uuid:", "")


def test_mdns_announce_packet_carries_unique_uuids(two_printers):
    recs = advprint._mdns_rrset("192.168.1.5")
    uuids = [u for _, rt, rd in _parse_records(
        advprint._mdns_packet(recs)) if rt == 16
        for u in [_txt_uuid(rd)]]
    assert len(uuids) == 3
    assert len(set(uuids)) == 3, "announce packet must not repeat a uuid"


def test_mdns_unicast_txt_query_answers_queue_uuid(two_printers,
                                                   monkeypatch):
    svcs = advprint._mdns_services()
    inst, rp, ty, note, slug, _port = svcs[1]   # a PER-PRINTER service
    qname = advprint._mdns_encode_name(inst + "._ipp._tcp.local")
    pkt = ((0x1234).to_bytes(2, "big") + (0).to_bytes(2, "big") +
           (1).to_bytes(2, "big") + (0).to_bytes(2, "big") +
           (0).to_bytes(2, "big") + (0).to_bytes(2, "big") +
           qname + (16).to_bytes(2, "big") + (1).to_bytes(2, "big"))
    cap = _CaptureSock()
    monkeypatch.setitem(advprint._mdns_state, "sock", cap)
    advprint._mdns_answer_query(pkt, ("192.168.20.7", 4444),
                                "192.168.20.2")
    assert cap.sent, "direct TXT query must be answered"
    reply = cap.sent[0][0]
    txts = [(n, rd) for n, rt, rd in _parse_records(reply) if rt == 16]
    assert txts, "the answer must contain the TXT record"
    u = _txt_uuid(txts[0][1])
    assert u == advprint._ipp_printer_uuid(slug).replace("urn:uuid:", ""), \
        "the DIRECT unicast TXT answer must stamp the per-queue uuid"


def test_ipp_printer_uuid_still_stable_and_distinct(two_printers):
    """v3.2.9 contract kept: same slug -> same uuid, different slug ->
    different uuid, hub uuid unchanged without slug."""
    a1 = advprint._ipp_printer_uuid("hp-laser-103")
    a2 = advprint._ipp_printer_uuid("hp-laser-103")
    b = advprint._ipp_printer_uuid("epson-l3250")
    hub = advprint._ipp_printer_uuid()
    assert a1 == a2 and a1 != b and a1 != hub and b != hub


# ---------------------------------------------------------------
# BUG 2 - idempotent set-default (zero repeated commands)
# ---------------------------------------------------------------

@pytest.fixture()
def printer_env(monkeypatch):
    """Isolate the default-printer cache + count every setter call."""
    calls = []
    saved_dp = dict(advprint._DP_CACHE)
    saved_cfg_printer = advprint.CFG.get("printer")
    saved_refresh = advprint._dp_refresh

    def fake_set_default(name):
        calls.append(name)
        return True, name, "stub setter ran for %s" % name

    def fake_dp_refresh():
        advprint._DP_CACHE["v"] = "StubPrinter"
        advprint._DP_CACHE["t"] = time.time()

    monkeypatch.setattr(advprint, "os_set_default_printer", fake_set_default)
    monkeypatch.setattr(advprint, "_dp_refresh", fake_dp_refresh)
    yield {"calls": calls, "names": calls}
    advprint._DP_CACHE.clear()
    advprint._DP_CACHE.update(saved_dp)
    advprint.CFG["printer"] = saved_cfg_printer
    monkeypatch.setattr(advprint, "_dp_refresh", saved_refresh, raising=False)


def test_set_default_already_default_spawns_zero_cmds(hub, printer_env):
    advprint._DP_CACHE["v"] = "StubPrinter"
    advprint._DP_CACHE["t"] = time.time()
    code, r = hub.post("/printers/set-default", body={"printer": "StubPrinter"})
    assert code == 200 and r.get("ok") is True
    assert r.get("unchanged") is True
    assert printer_env["calls"] == [], "no setter command may run"
    # ... and the message names the printer
    assert "StubPrinter" in (r.get("detail") or "")


def test_set_default_case_insensitive_short_circuit(hub, printer_env):
    advprint._DP_CACHE["v"] = "StubPrinter"
    advprint._DP_CACHE["t"] = time.time()
    code, r = hub.post("/printers/set-default",
                       body={"printer": "stubprinter"})
    assert code == 200 and r.get("unchanged") is True
    assert printer_env["calls"] == []


def test_set_default_real_change_runs_once_then_short_circuits(
        hub, printer_env):
    advprint._DP_CACHE["v"] = "OtherPrinter"
    advprint._DP_CACHE["t"] = time.time()
    # 1st call: a REAL change -> exactly one setter command
    code, r = hub.post("/printers/set-default",
                       body={"printer": "StubPrinter"})
    assert code == 200 and r.get("ok") is True
    assert "unchanged" not in r
    assert printer_env["calls"] == ["StubPrinter"]
    assert r.get("default") == "StubPrinter"
    # 2nd call, immediately: the verified result is cached -> ZERO cmds
    code, r2 = hub.post("/printers/set-default",
                        body={"printer": "StubPrinter"})
    assert code == 200 and r2.get("ok") is True
    assert r2.get("unchanged") is True
    assert printer_env["calls"] == ["StubPrinter"], \
        "the repeat call must not run the setter command again"


def test_set_default_requires_printer_name(hub, printer_env):
    code, r = hub.post("/printers/set-default", body={})
    assert code == 400 and r.get("ok") is False
    assert printer_env["calls"] == []


# ---------------------------------------------------------------
# POPUP v3.4.6 - change-only guard + UI surface
# ---------------------------------------------------------------

def _popup_js():
    return open(os.path.join(ROOT, "extension", "popup.js"),
                encoding="utf-8").read()


def _popup_html():
    return open(os.path.join(ROOT, "extension", "popup.html"),
                encoding="utf-8").read()


def _background_js():
    return open(os.path.join(ROOT, "extension", "background.js"),
                encoding="utf-8").read()


def _i18n_js():
    return open(os.path.join(ROOT, "extension", "i18n.js"),
                encoding="utf-8").read()


def test_popup_change_only_guard_never_sends_on_reload():
    js = _popup_js()
    # the applied-default guard: same printer -> NO send
    assert re.search(r"name\s*===?\s*_printerApplied\s*\)?\s*return", js), \
        "the change handler must early-return when the pick equals the " \
        "default the hub already reports"
    assert "_settingPrinter" in js, "one set-default in flight"
    assert "_refreshBusy" in js and "_refreshBody" in js, \
        "refresh() needs an in-flight guard against popup boot storms"
    # loadPrinters must only READ (hubPrinters), never SET
    m = re.search(r"async function loadPrinters\(\).*?\n\}", js, re.S)
    assert m and "hubSetDefault" not in m.group(0), \
        "loading the printer list must not send set-default"
    assert 'type: "hubPrinters"' in m.group(0)


def test_background_routes_hub_set_default():
    js = _background_js()
    m = re.search(r'case "hubSetDefault":.*?break;', js, re.S)
    assert m, "background.js needs the hubSetDefault message"
    assert "/printers/set-default" in m.group(0)
    assert "printer" in m.group(0)


def test_popup_ui_surface_present():
    html = _popup_html()
    # v3.4.6 ONE design (user-approved): the printer selector is
    # #selPrinter, the reload arrow #bRefreshPrinters, the header
    # NETWORK icon #netIcon - and the LAN switch reads SHARING with
    # the network/connection icon (the old download icon is gone).
    for marker in ('id="selPrinter"', 'id="bRefreshPrinters"',
                   'id="netIcon"', 'data-i18n="popSelectPrinter"',
                   'data-i18n="popShareRx"',
                   'data-i18n="popRecentJobs"'):
        assert marker in html, "popup.html needs " + marker
    assert ">Sharing<" in html, "the Receive switch must read Sharing"
    assert ">Receive<" not in html, "the old Receive label must be gone"
    # the Sharing switch carries the NETWORK/CONNECTION icon (network
    # nodes), not the download-tray arrow
    sw = html[html.index('id="swShareRxRow"'):]
    sw = sw[:sw.index("</label>")]
    assert "circle cx=" in sw and "M12 3v12" not in sw, \
        "the Sharing switch icon must be the network/connection icon"
    # legacy hidden div keeps removed controls alive for popup.js
    assert 'id="swShareTx"' in html and 'id="bShot"' in html \
        and 'id="bTest"' in html
    js = _popup_js()
    for fn in ("loadPrinters", "renderNetIcon", "reloadAll"):
        assert "function " + fn in js
    assert 'addEventListener("click", () => reloadAll' in js, \
        "net icon and reload button must be wired"
    i18n = _i18n_js()
    for key in ("popSelectPrinter", "popPrinterSection", "popPrinterNone",
                "popPrinterSetting", "popPrinterSetOk", "popPrinterSetFail",
                "popReloadBtn", "popNetOn", "popNetLan", "popNetOff",
                "popShareRxListen"):
        # present in BOTH dictionaries (en + bn)
        assert len(re.findall(key + r":", i18n)) >= 2, key + " in en+bn"
    # the label itself is "Sharing" in both languages (bn: শেয়ারিং)
    assert re.search(r'popShareRx:\s*"Sharing"', i18n)
    assert 'popShareRx: "শেয়ারিং"' in i18n


# ---------------------------------------------------------------
# AUTOCRX - internal browser auto-integration (no extra .bat)
# ---------------------------------------------------------------

def _hub_src():
    return open(os.path.join(ROOT, "tool", "unix", "hub", "advprint.py"),
                encoding="utf-8").read()


def test_autocrx_ps_script_writes_all_policies():
    url = "http://127.0.0.1:9235/extension/updates.xml"
    s = advprint._ext_activate_ps_script(url, "C:\\r\\res.json")
    # all three policy keys, BOTH hives, every Chromium browser
    for key in ("ExtensionInstallForcelist", "ExtensionInstallAllowlist",
                "ExtensionInstallSources"):
        assert key in s
    for hive in ("HKLM", "HKCU"):
        assert hive in s
    for frag in ("Google\\Chrome", "Microsoft\\Edge",
                 "BraveSoftware\\Brave", "Vivaldi", "Chromium",
                 "Opera Software\\Opera"):
        assert frag in s, frag + " must be covered"
    assert url in s
    assert "updates.xml" in s
    # duplicate-skip: an existing entry is kept, never rewritten
    assert "StartsWith" in s
    # the pass NEVER deletes anything (the old .bat wipe bug)
    for banned in ("Remove-Item", "Remove-ItemProperty", "reg delete"):
        assert banned not in s, banned + " must not appear"
    # the hub can read back a JSON result
    assert "ConvertTo-Json" in s and "res.json" in s


def test_autocrx_updates_url_host_override():
    base = advprint._ext_activate_updates_url(None)
    assert base.startswith("http://127.0.0.1:")
    assert base.endswith("/extension/updates.xml")
    # a bare host inherits the CONFIGURED hub port (tests run on a
    # random port, so no 9235 hardcoding here)
    lan = advprint._ext_activate_updates_url("192.168.1.10")
    assert lan == ("http://192.168.1.10:%d/extension/updates.xml"
                   % int(advprint.CFG.get("port", 9235)))
    # an explicit host:port wins untouched
    lan2 = advprint._ext_activate_updates_url("http://10.0.0.5:9300/")
    assert lan2 == "http://10.0.0.5:9300/extension/updates.xml"


def test_autocrx_off_windows_is_honest():
    r = advprint.ext_policy_activate()
    assert r.get("ok") is False
    assert "not Windows" in (r.get("error") or "")
    assert r.get("note")


def test_autocrx_wired_everywhere():
    src = _hub_src()
    # dedicated endpoint (dashboard / LAN console)
    assert 'route == "/extension/policy/activate"' in src
    # ONE UI tool action (loopback)
    assert '"autocrx"' in src and 'action in ("autocrx"' in src
    # CLI command + help
    assert '"activate-extension"' in src
    assert "python advprint.py activate-extension" in src
    # both hub copies ship it
    win = open(os.path.join(ROOT, "tool", "windows", "portable", "hub",
                            "advprint.py"), encoding="utf-8").read()
    assert "ext_policy_activate" in win
    # the console carries the button
    con = open(os.path.join(ROOT, "tool", "unix", "hub", "console.html"),
               encoding="utf-8").read()
    assert "Auto-integrate (admin)" in con
    assert "/extension/policy/activate" in con


# ---------------------------------------------------------------
# BAT - Apply HKLM / HKCU that actually work
# ---------------------------------------------------------------

def _bat():
    return open(os.path.join(ROOT, "prebuilt",
                             "allow_extention_advprint_pro.bat"),
                encoding="utf-8", errors="replace").read()


def test_bat_no_longer_wipes_forcelist():
    bat = _bat()
    # the OLD bug: `reg delete "...ExtensionInstallForcelist" /f` in the
    # apply path. The new script never deletes a Forcelist key at all
    # (Remove only deletes the three known keys explicitly - and that
    # IS the Remove action, not the apply path).
    for line in bat.splitlines():
        ls = line.strip().lower()
        if ls.startswith("::") or ls.startswith("rem "):
            continue
        if "reg delete" in ls and "forcelist" in ls:
            # allowed ONLY inside the Remove subroutine
            before = bat[:bat.index(line)]
            marker = before.rindex(":RemoveAll")
            assert before.count(":RemoveAll") >= 1 and \
                before[marker:].find(":WipeKeys") != -1, \
                "Forcelist delete is only allowed in the Remove path"
    # the apply path WRITES all three policy keys
    for key in ("ExtensionInstallForcelist", "ExtensionInstallAllowlist",
                "ExtensionInstallSources"):
        assert "reg add" in bat and key in bat, key + " must be written"
    assert "reg add" in bat
    # Forcelist value = ext id ; updates.xml (the CRX auto-install pair)
    assert "EXT_ID%;%UPDATES_URL%" in bat or \
           "%EXT_ID%;%UPDATES_URL%" in bat.replace("^", "")


def test_bat_has_hklm_hkcu_menu_and_scripted_args():
    bat = _bat()
    assert "HKCU" in bat and "HKLM" in bat
    for frag in ("Google\\Chrome", "Microsoft\\Edge",
                 "BraveSoftware\\Brave", "Vivaldi", "Chromium"):
        assert frag in bat
    # menu + self-elevation + argument mode
    assert "choice" in bat.lower()
    assert "-Verb RunAs" in bat, "HKLM must self-elevate via UAC"
    assert "net session" in bat, "admin detection"
    assert "updates.xml" in bat and "127.0.0.1" in bat
    # the old truncated-URL hint bug must not come back
    assert "http://127.0.0 " not in bat and "http://127.0\"" not in bat


# ---------------------------------------------------------------
# delivery coherence
# ---------------------------------------------------------------

def test_version_coherence_334():
    vtxt = open(os.path.join(ROOT, "VERSION.txt"), encoding="utf-8").read()
    assert "3.4.6" in vtxt
    assert advprint.VERSION == "3.4.6"
    manifest = json.load(open(os.path.join(ROOT, "extension",
                                           "manifest.json"),
                              encoding="utf-8"))
    assert manifest["version"] == "3.4.6"
    assert '"version": "3.4.6"' in _popup_html().replace("v3.4.6",
                                                         '"3.4.6"') or \
        "v3.4.6" in _popup_html()
    i18n = _i18n_js()
    assert i18n.count("3.4.6") >= 2          # brandLine en + bn
    guide = os.path.join(ROOT, "docs",
                         "AdvPrint-Pro-v3.4.6-A-to-Z-DEV-GUIDE.md")
    assert os.path.isfile(guide)


def test_hub_copies_byte_identical():
    a = os.path.join(ROOT, "tool", "unix", "hub", "advprint.py")
    b = os.path.join(ROOT, "tool", "windows", "portable", "hub",
                     "advprint.py")
    ha = hashlib.md5(open(a, "rb").read()).hexdigest()
    hb = hashlib.md5(open(b, "rb").read()).hexdigest()
    assert ha == hb, "the two hub copies must be byte-identical"
