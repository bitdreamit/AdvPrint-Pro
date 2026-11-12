"""v3.2.5 - THE TOOLBAR POPUP IS BACK.

Locks the popup contract end to end:
* manifest default_popup + version coherence
* popup.html / popup.js / i18n.js exist in extension/
* the popup footer is BRANDING ONLY (no Console/Dashboard/Debug/API)
* popup.js has no dead footer listeners and no dead options.html anchors
* every popup i18n key exists (en + bn)
* every sendMessage type popup.js uses exists in background.js
* setup.nsi packs popup.html + popup.js again
* the hub VERSION / VERSION_NAME / VERSION.txt / manifest agree on 3.2.5
"""
import json
import os
import re

import pytest

import advprint
from conftest import ROOT

EXT = os.path.join(ROOT, "extension")


# ------------------------------------------------------------
# manifest: the popup opens again
# ------------------------------------------------------------
def test_v324_manifest_opens_the_popup():
    man = json.load(open(os.path.join(EXT, "manifest.json"),
                         encoding="utf-8"))
    assert man["version"] == "3.3.1"
    act = man.get("action", {})
    assert act.get("default_popup") == "popup.html", \
        "v3.2.6 must open the toolbar popup again"
    assert act.get("default_title") == "AdvPrint Pro"
    # the options page stays exactly where it was
    assert man.get("options_ui", {}).get("page") == "options.html"


def test_v324_popup_files_exist():
    for f in ("popup.html", "popup.js", "i18n.js", "options.html",
              "options.js", "background.js"):
        p = os.path.join(EXT, f)
        assert os.path.exists(p), "missing extension file: " + f


# ------------------------------------------------------------
# popup.html: branding-only footer + no dead link elements
# ------------------------------------------------------------
def test_v324_popup_footer_branding_only():
    s = open(os.path.join(EXT, "popup.html"), encoding="utf-8").read()
    m = re.search(r"<footer>(.*?)</footer>", s, re.S)
    assert m, "popup footer missing"
    footer = m.group(1)
    assert "100% local" in footer and "no cloud" in footer
    assert "Bit Dream IT" in footer and "Healthcare Solutions" in footer
    # the old footer links must NOT exist as elements
    for gone in ("lnkConsole", "lnkDash", "lnkDebug", "lnkApi",
                 ">Console</a>", ">Dashboard</a>", ">Debug</a>", ">API</a>"):
        assert gone not in s, "popup carries a removed footer link: " + gone


def test_v324_popup_keeps_options_button():
    s = open(os.path.join(EXT, "popup.html"), encoding="utf-8").read()
    assert 'id="bOpts"' in s, "the Options button must stay in the popup"
    js = open(os.path.join(EXT, "popup.js"), encoding="utf-8").read()
    assert 'openOptionsPage' in js
    # and the header version chip matches the manifest version
    assert '<span class="ver" id="ver">v3.3.1</span>' in s


def test_v324_popup_js_no_dead_listeners():
    js = open(os.path.join(EXT, "popup.js"), encoding="utf-8").read()
    # the four footer-link listeners were removed - the elements do not
    # exist, so any listener left would throw and kill the popup
    for gone in ('$("lnkDash")', '$("lnkConsole")', '$("lnkDebug")',
                 '$("lnkApi")', 'options.html#connections',
                 'options.html#debug', 'options.html#api',
                 'options.html#lan-settings'):
        assert gone not in js, "dead reference left in popup.js: " + gone
    # token help + share-send fallback go through the options page now
    assert js.count("openOptionsPage") >= 3


def test_v324_popup_js_no_hook_switch():
    """v3.0.2 decision preserved: the window.print() hook switch lives
    ONLY in the ONE UI Power Switches tab."""
    s = open(os.path.join(EXT, "popup.html"), encoding="utf-8").read()
    assert "hookPrint" not in s


# ------------------------------------------------------------
# i18n: every popup string exists in BOTH languages
# ------------------------------------------------------------
def _i18n_keys_for_lang(block):
    return set(re.findall(r'^\s{6}([A-Za-z0-9_]+):', block, re.M))


def test_v324_popup_i18n_complete():
    s = open(os.path.join(EXT, "i18n.js"), encoding="utf-8").read()
    html = open(os.path.join(EXT, "popup.html"), encoding="utf-8").read()
    js = open(os.path.join(EXT, "popup.js"), encoding="utf-8").read()
    used = set(re.findall(r'AdvPrintI18n\.t\("([A-Za-z0-9_]+)"\)', js))
    used |= set(re.findall(r'data-i18n="([A-Za-z0-9_]+)"', html))
    assert used, "no i18n keys detected in the popup"
    en = _i18n_keys_for_lang(re.search(r'\ben:\s*\{.*?\n    \},', s, re.S).group(0))
    bn = _i18n_keys_for_lang(re.search(r'\bbn:\s*\{.*?\n    \}', s, re.S).group(0))
    missing_en = sorted(k for k in used if k not in en)
    missing_bn = sorted(k for k in used if k not in bn)
    assert not missing_en, "popup i18n keys missing (en): %s" % missing_en
    assert not missing_bn, "popup i18n keys missing (bn): %s" % missing_bn
    # no stale version strings in user-visible i18n VALUES (the en/bn
    # brandLine values must carry the CURRENT version, not an old one)
    assert "Version 3.2.2" not in s and "\u09b8\u0982\u09b8\u09cd\u0995\u09b0\u09a3 3.2.2" not in s, \
        "i18n brandLine still carries an old version"


# ------------------------------------------------------------
# popup.js <-> background.js message contract
# ------------------------------------------------------------
def test_v324_popup_message_types_supported():
    js = open(os.path.join(EXT, "popup.js"), encoding="utf-8").read()
    bg = open(os.path.join(EXT, "background.js"), encoding="utf-8").read()
    used = set(re.findall(r'type:\s*"([A-Za-z0-9_]+)"', js))
    # NOTE: openHubPage was ONLY used by the removed footer links - the
    # v3.2.5 popup reaches the console through the Options button.
    expected = {"getCfg", "saveCfg", "hubStatus", "hubJobs", "hubConfigSet",
                "printTab", "printScreenshot", "queueAction", "jobPrintNow",
                "flushRetries", "retryInfo", "tokenDetect"}
    assert expected <= used, "popup lost message types: %s" % (expected - used)
    handled = set(re.findall(r'case "([A-Za-z0-9_]+)"', bg))
    missing = sorted(used - handled)
    assert not missing, "background.js does not handle: %s" % missing


def test_v324_disabled_errors_point_at_the_popup():
    bg = open(os.path.join(EXT, "background.js"), encoding="utf-8").read()
    assert "enable it in the popup (toolbar icon)" in bg
    assert 'enable it in the Console (Power Switches)' in bg  # Console-only switch
    # the console-open fallback stays for builds without a popup
    assert "chrome.action.onClicked" in bg and "/ui" in bg


# ------------------------------------------------------------
# packaging: NSIS packs the popup again
# ------------------------------------------------------------
def test_v324_nsis_packs_popup():
    nsi = open(os.path.join(ROOT, "installer", "setup.nsi"),
               encoding="utf-8").read()
    assert 'File "/oname=popup.html" "../extension/popup.html"' in nsi
    assert 'File "/oname=popup.js" "../extension/popup.js"' in nsi
    assert 'OutFile "../dist/AdvPrint-Pro-Setup-3.3.1.exe"' in nsi
    assert 'VIProductVersion "3.3.1.0"' in nsi


# ------------------------------------------------------------
# version coherence: one version everywhere
# ------------------------------------------------------------
def test_v324_version_coherence():
    assert advprint.VERSION == "3.3.1"
    assert advprint.VERSION_NAME.startswith("v3.3.1")
    vt = open(os.path.join(ROOT, "VERSION.txt"), encoding="utf-8").read()
    assert "3.3.1" in vt
    man = json.load(open(os.path.join(EXT, "manifest.json"),
                         encoding="utf-8"))
    assert man["version"] == advprint.VERSION
    opt = open(os.path.join(EXT, "options.html"), encoding="utf-8").read()
    assert "v3.3.1" in opt, "options brand line must carry v3.2.8"


def test_v324_hub_still_reports_324():
    """/health keeps reporting the live VERSION (popup shows it)."""
    assert advprint.VERSION == "3.3.1"
    # the ACL feature from v3.2.3 is still wired
    assert advprint.CFG.get("allowed_ips") == ["*"]
    assert hasattr(advprint, "ip_allowed_by_list")
