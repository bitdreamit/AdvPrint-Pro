"""v3.3.5 - MANUAL RE-SCAN + AUTO-CRX-ON-INSTALL (two features survive
into v3.4.7 unchanged; the third, the DEDICATED QUEUE PORTS
experiment, was REMOVED again in v3.4.7 - ONE port serves every queue
now, see tests/test_v346.py).

FEATURE 2 "printer page when Show other PCs (LAN / IPP) on it auto
          load every time no need this page has re-scan option it just
          manualy trige when need". Fix: the remote list renders from
          the LAST MANUAL SCAN (zero network on the 3 s poll) and a
          fresh probe happens ONLY via the Re-scan button / the switch
          (GET /peer/status?fresh=1).

FEATURE 3 "when tool install it auto add update crx extention so
          extention also built in in this tool auto update or install
          this extention". Fix: the installer writes the FULL policy
          (Forcelist + Allowlist + Sources, HKLM + HKCU, + Opera), and
          the hub re-applies the per-user HKCU pass SILENTLY on every
          start (autocrx_hkcu, no UAC, no .bat).
"""
import hashlib
import json
import os
import re

import pytest

import advprint

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------
# helpers / fixtures
# ---------------------------------------------------------------

@pytest.fixture()
def two_printers(monkeypatch):
    names = ["HP Laser 103", "Epson L3250"]
    monkeypatch.setattr(advprint, "list_printers_cached",
                        lambda max_age=30.0: list(names))
    return names


def _parse_records(packet):
    """Tiny DNS answer parser for OUR mDNS packets (no compression)."""
    i = 12
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
            pos = pos + ln
        return ".".join(labels), pos

    for _ in range(qd):
        _, i = _name(i)
        i += 4
    out = []
    for _ in range(an):
        name, i = _name(i)
        rtype = int.from_bytes(packet[i:i + 2], "big")
        i += 2 + 2 + 4
        rdlen = int.from_bytes(packet[i:i + 2], "big")
        i += 2
        out.append((name, rtype, packet[i:i + rdlen]))
        i += rdlen
    return out


class _CaptureSock:
    def __init__(self):
        self.sent = []

    def sendto(self, pkt, addr):
        self.sent.append((bytes(pkt), addr))


# ---------------------------------------------------------------
# FEATURE 2 - manual re-scan of the other PC's printers
# ---------------------------------------------------------------

def _console_src():
    return open(os.path.join(ROOT, "tool", "unix", "hub", "advprint.py"),
                encoding="utf-8", errors="replace").read()


def test_remote_list_renders_from_cached_scan_not_from_poll():
    src = _console_src()
    # poll() renders the CACHED remote list (zero network)
    assert re.search(r"renderPrinters\(pr\.printers \|\| \[\]\);",
                     src)
    # loadLanPeer no longer re-renders the remote printers
    m = re.search(r"function loadLanPeer\(\)\{(.{0,1200}?)\n\}",
                  src, re.S)
    assert m and "renderRemotePrinters(st);" not in m.group(1)


def test_manual_scan_helpers_exist_and_fresh_param_is_wired():
    src = _console_src()
    assert "function scanRemotePrinters(manual)" in src
    assert 'api("/peer/status?fresh=1")' in src
    assert 'remoteScanState.scanned = true' in src
    # the Re-scan action triggers the fresh scan when the switch is on
    assert 'if (cfgCache.show_remote_printers) { scanRemotePrinters(true); }' \
        in src
    # the server honours fresh=1 (skips the 8 s probe cache)
    assert 'fresh=str((q or {}).get("fresh") or "") == "1"' in src
    # the switch ON is a manual trigger too
    assert "scanRemotePrinters(false);" in src


def test_manual_scan_hint_card_present():
    src = _console_src()
    assert "data-remotescan" in src
    assert "Other PCs' printers: press Re-scan" in src
    assert "no automatic loading" in src


def test_peer_status_fresh_endpoint(hub, monkeypatch):
    # the paired peer is absent in the test hub - the endpoint must
    # still answer 200 with configured:false for fresh=1
    code, j = hub.get("/peer/status?fresh=1")
    assert code == 200
    assert j["ok"] is True
    assert j["configured"] is False


# ---------------------------------------------------------------
# FEATURE 3 - auto CRX on install / on hub start
# ---------------------------------------------------------------

def test_autocrx_hkcu_config_key_exists():
    assert "autocrx_hkcu" in advprint.CONFIG_KEYS
    assert advprint.CONFIG_TYPES.get("autocrx_hkcu") is bool
    assert advprint.CFG.get("autocrx_hkcu", True) in (True, False)


def test_autocrx_hkcu_auto_off_windows_is_honest(monkeypatch):
    monkeypatch.setattr(advprint, "IS_WIN", False)
    assert advprint.autocrx_hkcu_auto() is None


def test_autocrx_hkcu_auto_disabled_by_config(monkeypatch):
    monkeypatch.setattr(advprint, "IS_WIN", True)
    old = advprint.CFG.get("autocrx_hkcu")
    advprint.CFG["autocrx_hkcu"] = False
    try:
        assert advprint.autocrx_hkcu_auto() is None
    finally:
        advprint.CFG["autocrx_hkcu"] = old


def test_autocrx_hkcu_writes_all_policies(monkeypatch):
    """Simulate the silent HKCU pass: reg writes are recorded, not run."""
    monkeypatch.setattr(advprint, "IS_WIN", True)
    advprint._AUTOCRX_AUTO_STATE["done"] = False
    old = advprint.CFG.get("autocrx_hkcu")
    advprint.CFG["autocrx_hkcu"] = True
    wrote = {}

    def fake_add(full_key, name, data):
        wrote[(full_key, name)] = data
        return True

    monkeypatch.setattr(advprint, "_ext_reg_add", fake_add)
    monkeypatch.setattr(advprint, "_ext_reg_query_values",
                        lambda key: {})
    fake_crx = {"ext_id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}
    monkeypatch.setattr(advprint, "crx_package", lambda: fake_crx)
    try:
        r = advprint.autocrx_hkcu_auto()
    finally:
        advprint.CFG["autocrx_hkcu"] = old
    assert r and r["ok"] is True
    assert len(r["written"]) == len(advprint.EXT_ACTIVATE_BROWSERS)
    # every browser got Forcelist + Allowlist + Sources under HKCU
    for frag, name in advprint.EXT_ACTIVATE_BROWSERS:
        base = "HKCU\\SOFTWARE\\Policies\\%s" % frag
        fl = [k for k in wrote if k[0] == base + "\\ExtensionInstallForcelist"]
        al = [k for k in wrote if k[0] == base + "\\ExtensionInstallAllowlist"]
        so = [k for k in wrote if k[0] == base + "\\ExtensionInstallSources"]
        assert fl and al and so, name
    # the forcelist value points at THIS hub's updates.xml
    fl_val = list(wrote.values())[0]
    assert fl_val.startswith("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa;")
    assert "/extension/updates.xml" in fl_val


def test_autocrx_hkcu_runs_once_per_process():
    advprint._AUTOCRX_AUTO_STATE["done"] = True
    assert advprint.autocrx_hkcu_auto() is None
    advprint._AUTOCRX_AUTO_STATE["done"] = False


def test_serve_starts_the_autocrx_thread():
    src = _console_src()
    assert "target=_autocrx_auto_thread" in src.replace(" ", "") or \
        "_autocrx_auto_thread" in src
    assert "advprint-autocrx" in src


def test_installer_has_the_full_policy_and_cleanup_rule():
    """v3.4.7: the FULL policy stays; the queue-port RANGE rule is gone
    (ONE port again) but its delete-rule survives so an upgrade from a
    v3.3.5 install removes the leftover 9235-9259 firewall rule."""
    nsi = open(os.path.join(ROOT, "installer", "setup.nsi"),
               encoding="utf-8", errors="replace").read()
    for browser in ["Google\\Chrome", "Microsoft\\Edge",
                    "BraveSoftware\\Brave", "Chromium", "Vivaldi",
                    "Opera Software\\Opera"]:
        assert browser in nsi
    assert "ExtensionInstallAllowlist" in nsi
    assert "ExtensionInstallSources" in nsi
    assert "HKCU \"SOFTWARE\\Policies\\${POLPATH}\\ExtensionInstallForcelist\"" in nsi
    # the 9235-9259 range rule is NOT added any more ...
    assert 'add rule name="AdvPrint Pro Queues"' not in nsi
    # ... but an old v3.3.5 rule is still cleaned up on upgrade
    assert 'delete-rule name="AdvPrint Pro Queues"' in nsi
    # and the ONE hub-port rule stays
    assert 'add rule name="AdvPrint Pro" dir=in action=allow ' \
        'protocol=TCP localport=9235' in nsi


# ---------------------------------------------------------------
# release coherence
# ---------------------------------------------------------------

def test_version_coherence_346():
    assert advprint.VERSION == "3.4.8"
    vtxt = open(os.path.join(ROOT, "VERSION.txt"), encoding="utf-8").read()
    assert "3.4.8" in vtxt
    manifest = json.load(open(os.path.join(ROOT, "extension",
                                           "manifest.json"),
                              encoding="utf-8"))
    assert manifest["version"] == "3.4.8"
    popup = open(os.path.join(ROOT, "extension", "popup.html"),
                 encoding="utf-8").read()
    assert 'id="ver">v3.4.8<' in popup
    i18n = open(os.path.join(ROOT, "extension", "i18n.js"),
                encoding="utf-8").read()
    assert i18n.count("3.4.8") >= 2          # brandLine en + bn


def test_hub_copies_byte_identical():
    a = os.path.join(ROOT, "tool", "unix", "hub", "advprint.py")
    b = os.path.join(ROOT, "tool", "windows", "portable", "hub",
                     "advprint.py")
    ha = hashlib.md5(open(a, "rb").read()).hexdigest()
    hb = hashlib.md5(open(b, "rb").read()).hexdigest()
    assert ha == hb, "the two hub copies must be byte-identical"
