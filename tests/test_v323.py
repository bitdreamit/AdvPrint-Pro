"""v3.2.3 - CLEAN UI + EVERY SWITCH VERIFIED + ALLOWED IPS.

Locks:
* the Hub-switch 400 fix (escpos_codepage / thermal_text_engine accepted)
* the Allowed-IPS matcher + config round-trip + /health fields
* the toolbar / address-bar / dashboard de-duplication (embedded UI)
* the branding-only extension options page
"""
import json
import os

import pytest

import advprint
from conftest import ROOT

UI = advprint.CONSOLE_HTML


# ------------------------------------------------------------
# THE switch bug: Hub-panel saves must never 400 again
# ------------------------------------------------------------
def test_v323_hub_switch_config_types_accepted():
    """The Hub panel posts these two keys with every switch save - they
    were missing from CONFIG_TYPES, so EVERY Hub switch save died with
    400 'unknown config key' and no Hub switch ever persisted."""
    assert advprint.CONFIG_TYPES.get("escpos_codepage") is str
    assert advprint.CONFIG_TYPES.get("thermal_text_engine") is str


def test_v323_thermal_and_codepage_validation(hub):
    code, d = hub.post("/config", body={"thermal_text_engine": "banana"})
    assert code == 400
    code, d = hub.post("/config", body={"thermal_text_engine": "builtin"})
    assert code == 200 and d.get("ok") is True
    code, d = hub.post("/config", body={"escpos_codepage": "CP850!"})
    assert code == 400                      # punctuation rejected
    code, d = hub.post("/config", body={"escpos_codepage": "cp850"})
    assert code == 200
    code, d = hub.get("/config")
    assert d["thermal_text_engine"] == "builtin"
    assert d["escpos_codepage"] == "cp850"


# ------------------------------------------------------------
# ALLOWED IPS - matcher
# ------------------------------------------------------------
def test_v323_acl_matcher_star_and_exact():
    f = advprint.ip_allowed_by_list
    assert f("10.26.94.5", ["*"]) is True           # factory default
    assert f("10.26.94.5", []) is True              # empty treated as all
    assert f("10.26.94.5", ["10.26.94.5"]) is True  # exact
    assert f("10.26.94.6", ["10.26.94.5"]) is False
    assert f("::ffff:10.26.94.5", ["10.26.94.5"]) is True   # v4-mapped
    assert f("10.26.94.5%0", ["10.26.94.5"]) is True        # zone suffix


def test_v323_acl_matcher_cidr_and_wildcard():
    f = advprint.ip_allowed_by_list
    assert f("10.26.94.77", ["10.26.94.0/24"]) is True
    assert f("10.27.94.77", ["10.26.94.0/24"]) is False
    assert f("10.26.7.1", ["10.26.*"]) is True
    assert f("10.27.7.1", ["10.26.*"]) is False
    # a typo'd CIDR must DENY (stricter), never silently open
    assert f("10.26.94.5", ["10.26.94.0/99"]) is False
    # multiple entries, "*" anywhere wins
    assert f("8.8.8.8", ["10.26.94.5", "*"]) is True


def test_v323_acl_config_roundtrip(hub):
    # add two entries -> restricted mode
    code, d = hub.post("/config", body={
        "allowed_ips": ["10.26.94.100", "10.26.94.0/24", "*", "  "],
    })
    assert code == 200
    code, d = hub.get("/config")
    assert d["allowed_ips"] == ["*"]        # "*" anywhere -> all again
    code, d = hub.post("/config", body={"allowed_ips": ["10.26.94.100"]})
    assert code == 200
    code, d = hub.get("/config")
    assert d["allowed_ips"] == ["10.26.94.100"]
    # empty list can never lock the owner out -> back to ["*"]
    code, d = hub.post("/config", body={"allowed_ips": []})
    assert code == 200
    code, d = hub.get("/config")
    assert d["allowed_ips"] == ["*"]


def test_v323_acl_health_fields(hub):
    code, d = hub.post("/config", body={"allowed_ips": ["10.26.94.100"]})
    assert code == 200
    code, h = hub.get("/health")
    assert code == 200
    assert h["allowed_ips"] == ["10.26.94.100"]
    assert h["acl_restricted"] is True
    hub.post("/config", body={"allowed_ips": ["*"]})
    code, h = hub.get("/health")
    assert h["acl_restricted"] is False


def test_v323_acl_loopback_owner_never_blocked(hub):
    """The hub PC itself must NEVER be locked out: with a restrictive
    list, loopback requests still pass the gate (401-without-token is
    fine - that is auth, not the ACL)."""
    hub.post("/config", body={"allowed_ips": ["10.99.99.99"]})
    code, body = hub.get("/health", token=None)   # loopback, no token
    assert code == 200 and body["ok"] is True     # NOT 403
    hub.post("/config", body={"allowed_ips": ["*"]})


def test_v323_acl_default_config_key():
    assert advprint.CFG.get("allowed_ips") == ["*"]
    assert "allowed_ips" in advprint.CONFIG_KEYS
    assert advprint.CONFIG_TYPES.get("allowed_ips") is list


# ------------------------------------------------------------
# ONE UI, ONE BUTTON - embedded UI invariants
# ------------------------------------------------------------
def test_v323_toolbar_has_only_real_actions():
    tb = UI[UI.find('class="toolbar"'):UI.find("ADDRESS BAR")]
    # no tab navigation left in the toolbar
    assert 'data-tab=' not in tb
    # the four real actions exist
    for label in ("New Job", "Pause Queue", "Release ALL", "Test Page"):
        assert "<span>%s</span>" % label in tb
    # status chips live here now
    assert 'id="chipLan"' in tb and 'id="chipIpp"' in tb


def test_v323_about_settings_exist_once_in_nav():
    """About/Settings buttons appear exactly ONCE in the always-visible
    chrome (the sidebar) - not in the toolbar, not in the address bar."""
    tb = UI[UI.find('class="toolbar"'):UI.find("ADDRESS BAR")]
    assert ">Settings</span>" not in tb and ">About</span>" not in tb
    side = UI[UI.find('class="sidebar"'):UI.find("======== CONTENT")]
    assert side.count('data-tab="settings"') == 1
    assert side.count('data-tab="about"') == 1


def test_v323_address_bar_has_no_pill_buttons():
    addr = UI[UI.find("ADDRESS BAR"):UI.find("======== BODY")]
    assert "pill-btn" not in addr
    assert "token ok" in addr               # URL + lock remain


def test_v323_dashboard_quick_actions_gone():
    dash = UI[UI.find('id="p-dashboard"'):UI.find("= LAN SHARING")]
    assert "Quick actions" not in dash
    assert 'data-tab="dropzone">&#128449; Open DropZone' not in dash
    # the duplicate Test Page / Open Printers buttons are gone
    assert ">Open Printers<" not in dash


def test_v323_acl_card_present_in_lan_tab():
    lan = UI[UI.find('id="p-lan"'):UI.find('id="p-dropzone"')]
    for needle in ("aclMode", "aclInput", "aclAdd", "aclAllowAll",
                   "aclList", "Allowed IPs"):
        assert needle in lan, needle
    # the render + save JS is embedded too
    assert "function renderAcl()" in UI and "function saveAcl(" in UI


def test_v323_hub_panel_refreshes_on_poll():
    assert "refreshHubPanel();" in UI[UI.find("async function poll"):]


def test_v323_savehub_demo_path_guard():
    seg = UI[UI.find("async function saveHub"):UI.find("function extPrefsFromPanels")]
    assert "!== (cfgCache.file_dir || \"\")" in seg
    assert "!== (cfgCache.sumatra_path || \"\")" in seg


# ------------------------------------------------------------
# Extension options = branding only
# ------------------------------------------------------------
def test_v323_options_page_branding_only():
    p = os.path.join(ROOT, "extension", "options.html")
    s = open(p, encoding="utf-8").read()
    assert "<footer>" in s and "</footer>" in s
    foot = s.split("<footer>")[1].split("</footer>")[0]
    assert "100% local" in foot and "no cloud" in foot
    assert "Bit Dream IT" in foot and "Innovative Healthcare Solutions" in foot
    # no Console / Dashboard / Debug / API buttons anywhere
    for gone in ("lnkConsole", "lnkDash", "lnkDebug", "lnkApi",
                 ">Console</a>", ">Dashboard</a>"):
        assert gone not in s, gone
    # the ONE UI is where the options live
    assert "ONE UI" in s
    assert "v3.3.0" in s   # v3.2.5: version bumped


def test_v323_options_js_auto_open():
    p = os.path.join(ROOT, "extension", "options.js")
    s = open(p, encoding="utf-8").read()
    assert 'HUB = "http://127.0.0.1:9235"' in s
    assert "/health" in s and "location.href" in s
