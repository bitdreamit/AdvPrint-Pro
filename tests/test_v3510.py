r"""v3.5.10 - ONE POWER SWITCH (POPUP + CONSOLE + OPTIONS = THE SAME SWITCH)

The owner reported three switch bugs:

  1. "popup switch off after some time it auto on why"  - the popup
     master switch wrote only chrome.storage.local while the hub sync
     copied the STALE console value back over it on the 5-minute alarm
     (the hub never even learned about popup changes).
  2. "this switch why not same operation both"          - console
     switch = hub write, popup switch = local write: two operations.
  3. "queue on off noeffect in ui why"                  - the Queue
     tab status card was STATIC demo HTML ("Queue mode ON" + "hub
     #2047 in progress" hardcoded) and adoption took up to 5 minutes.

Locked here: version coherence 3.5.10, the bidirectional sync engine
(PUSH within a second with print_defaults preservation, the
no-auto-revert pending guard, the 1-minute EXT_PREF_SYNC_ALARM, the
getCfg popup-open sync, the popup live mirror), the LIVE queue card,
the behavioral simulation (tests/ext_sync_sim.js runs the REAL
background.js against a simulated chrome + hub and replays the exact
owner scenario), byte-identical twins, the carried v3.5.9/v3.5.8/
v3.5.7 guarantees and the release docs.
"""
import importlib.util
import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V = "3.5.10"
EXT_ID = "likldbkamojokkfdlcjibiljpgbbnohc"
BRAND = "AdvPrint Pro by Bit Dream IT"

CONSOLE_PATHS = [
    os.path.join(ROOT, "tool", "unix", "hub", "console.html"),
    os.path.join(ROOT, "tool", "windows", "portable", "hub", "console.html"),
]
ADV_PATHS = [
    os.path.join(ROOT, "tool", "unix", "hub", "advprint.py"),
    os.path.join(ROOT, "tool", "windows", "portable", "hub", "advprint.py"),
]
TOOL_PATHS = [
    os.path.join(ROOT, "tool", "unix", "hub", "tool.py"),
    os.path.join(ROOT, "tool", "windows", "portable", "hub", "tool.py"),
]
EXT = os.path.join(ROOT, "extension")

sys.path.insert(0, os.path.join(ROOT, "tool", "windows", "portable", "hub"))
import advprint  # noqa: E402


def console():
    return open(CONSOLE_PATHS[0], encoding="utf-8").read()


def adv():
    return open(ADV_PATHS[0], encoding="utf-8").read()


def bg():
    return open(os.path.join(EXT, "background.js"), encoding="utf-8").read()


def popup_js():
    return open(os.path.join(EXT, "popup.js"), encoding="utf-8").read()


# ---------------- A. version coherence 3.5.10 --------------------------

def test_v3510_hub_version():
    assert advprint.VERSION == V
    assert advprint.VERSION_NAME.startswith(
        "v3.5.10 (CRX SIGNATURE VERIFIED + LAN ADMIN CONSOLE")
    assert "ONE POWER SWITCH" in advprint.VERSION_NAME
    assert "POPUP + CONSOLE + OPTIONS" in advprint.VERSION_NAME
    # carried-forward guarantees stay in the release string
    assert "UNBREAKABLE DEB BUILD" in advprint.VERSION_NAME
    assert "SCANNER-PROOF STAGING" in advprint.VERSION_NAME
    assert "REAL WINDOW BUTTONS + BRAND + TAB MEMORY" in advprint.VERSION_NAME
    assert "SILENT WINDOWS" in advprint.VERSION_NAME
    assert "CREATE_NO_WINDOW" in advprint.VERSION_NAME
    assert "ipp://" in advprint.VERSION_NAME


def test_v3510_version_txt():
    s = open(os.path.join(ROOT, "VERSION.txt"), encoding="utf-8").read()
    assert ("AdvPrint Pro (Advanced Printer) %s - built" % V) in s


def test_v3510_extension_version_files():
    m = json.load(open(os.path.join(EXT, "manifest.json"), encoding="utf-8"))
    assert m["version"] == V
    popup = open(os.path.join(EXT, "popup.html"), encoding="utf-8").read()
    assert ('id="ver">v%s<' % V) in popup
    i18n = open(os.path.join(EXT, "i18n.js"), encoding="utf-8").read()
    assert i18n.count(V) >= 3
    api = open(os.path.join(EXT, "content", "api.js"), encoding="utf-8").read()
    assert ('_apVerFallback = "%s"' % V) in api
    opts = open(os.path.join(EXT, "options.html"), encoding="utf-8").read()
    assert ("v%s" % V) in opts


def test_v3510_console_version_spots():
    c = console()
    assert ('<div class="stat"><div class="d">hub</div>'
            '<div class="v">v%s</div>' % V) in c
    assert c.count('(BOOT.version || "%s")' % V) == 3


def test_v3510_embedded_console_is_fresh():
    a = adv()
    OPEN = 'CONSOLE_HTML = r"""'
    i = a.find(OPEN)
    assert i >= 0, "CONSOLE_HTML missing"
    i += len(OPEN)
    j = a.find('\n"""', i)
    assert j > i, "CONSOLE_HTML closing delimiter missing"
    assert a[i:j] == console()        # embed is byte-fresh


def test_v3510_installer_version_spots():
    nsi = open(os.path.join(ROOT, "installer", "setup.nsi"),
               encoding="utf-8").read()
    assert 'OutFile "../dist/AdvPrint-Pro-Setup-%s.exe"' % V in nsi
    assert 'VIProductVersion "%s.0"' % V in nsi
    assert '"DisplayVersion" "%s"' % V in nsi
    control = open(os.path.join(ROOT, "installer", "deb", "DEBIAN",
                                "control"), encoding="utf-8").read()
    assert ("Version: %s" % V) in control


def test_v3510_hub_twins_byte_identical():
    assert open(ADV_PATHS[0], "rb").read() == open(ADV_PATHS[1], "rb").read()
    assert open(CONSOLE_PATHS[0], "rb").read() == \
        open(CONSOLE_PATHS[1], "rb").read()
    assert open(TOOL_PATHS[0], "rb").read() == open(TOOL_PATHS[1], "rb").read()


def test_v3510_previous_features_carried():
    c = console()
    # brand title (v3.5.8)
    assert "<title>%s \u2014 Innovative Healthcare Solutions</title>" % BRAND in c
    # tab memory + URL path (v3.5.8)
    assert 'var AP_TAB_KEY = "ap_console_tab";' in c
    assert 'u.searchParams.set("path", name);' in c
    # real window buttons (v3.5.8)
    assert "(function winbtnsReal(){" in c
    assert "    window.close();" in c
    # scanner-proof DEB helpers (v3.5.9, live in build-all.py)
    b = open(os.path.join(ROOT, "scripts", "build-all.py"),
             encoding="utf-8").read()
    assert "def _read_visible(" in b
    assert "def build_deb_scannerproof(" in b


# ---------------- B. the ONE POWER SWITCH sync engine ------------------

def test_v3510_push_engine_exists():
    s = bg()
    assert "const EXT_PREF_SYNC_ALARM = \"advprintExtPrefSync\";" in s
    assert "const EXT_PREF_KEYS = [\"enabled\", \"queueMode\", \"rulesPaused\", \"hookPrint\"," in s
    for fn in ("pushExtPrefsToHub", "scheduleExtPrefsPush",
               "pullExtPrefsFromHub", "extPrefSyncTick"):
        assert ("function %s(" % fn) in s, "missing " + fn
    assert "_extPrefPushPending" in s and "_extPrefPushTimer" in s


def test_v3510_push_preserves_print_defaults():
    """The push must POST a FULL ext_prefs object merged with the hub
    copy (whole-dict replace on the hub side) - print_defaults and the
    console-owned keys survive a popup flip."""
    s = bg()
    assert "const prefs = Object.assign({}, hubPrefs, patch);" in s
    assert "prefs.print_defaults = st.printDefaults || {};" in s
    assert 'ext_sync_at: new Date().toISOString()' in s


def test_v3510_no_auto_revert_guard():
    """THE auto-ON fix: adoptHubExtPrefs must refuse the stale hub copy
    while a local change is still pending its hub push."""
    s = bg()
    i = s.index("async function adoptHubExtPrefs(")
    body = s[i:i + 800]
    assert "if (_extPrefPushPending) return;" in body, \
        "adoption must be skipped while a local push is pending"


def test_v3510_one_minute_sync_alarm():
    s = bg()
    assert "chrome.alarms.create(EXT_PREF_SYNC_ALARM, { periodInMinutes: 1 })" in s
    assert s.count('chrome.alarms.create(EXT_PREF_SYNC_ALARM') == 2, \
        "top level + onStartup must both create the 1-minute alarm"
    assert "if (alarm && alarm.name === EXT_PREF_SYNC_ALARM) {" in s
    assert "extPrefSyncTick();             // v3.5.10 ONE POWER SWITCH" in s


def test_v3510_onchanged_pushes_power_keys():
    """The single choke point: ANY local power-key write (popup switch,
    Options switch, content script) triggers the push."""
    s = bg()
    assert "if (EXT_PREF_KEYS.some((k) => changes[k])) {" in s
    assert "    invalidateCfg();\n    scheduleExtPrefsPush();" in s


def test_v3510_getcfg_syncs_on_popup_open():
    s = bg()
    assert 'case "getCfg":' in s
    assert "extPrefSyncTick();" in s.split('case "getCfg":', 1)[1][:600]


def test_v3510_popup_live_mirror():
    s = popup_js()
    assert "chrome.storage.onChanged.addListener" in s
    assert "if (changes.enabled || changes.queueMode) {" in s
    assert "ONE POWER SWITCH" in s
    # the switch handlers say the same-switch truth
    assert "same switch as the Console, synced" in s
    assert "(synced to the Console)" in s


def test_v3510_extension_js_wellformed():
    for f in ("background.js", "popup.js", "options.js"):
        src = open(os.path.join(EXT, f), encoding="utf-8").read()
        assert "v2.8.0" not in src, f + " still hardcodes an old version"
    node = None
    for cand in ("node", "/usr/bin/node", "/usr/local/bin/node"):
        try:
            subprocess.run([cand, "--version"], capture_output=True)
            node = cand
            break
        except OSError:
            continue
    if node is None:
        pytest.skip("node not available for the JS syntax gate")
    for f in ("background.js", "popup.js"):
        out = subprocess.run([node, "--check", os.path.join(EXT, f)],
                             capture_output=True, text=True)
        assert out.returncode == 0, "%s no longer parses:\n%s" % (
            f, out.stderr)


def test_v3510_behavioral_simulation():
    """THE owner scenario, replayed against the REAL background.js:
    popup OFF -> hub learns it; popup OFF while hub offline -> pending;
    stale hub copy arrives -> NO auto-revert; hub back -> pending push
    lands; console flips back ON -> browser follows; getCfg adopts."""
    sim = os.path.join(ROOT, "tests", "ext_sync_sim.js")
    assert os.path.exists(sim)
    node = None
    for cand in ("node", "/usr/bin/node", "/usr/local/bin/node"):
        try:
            subprocess.run([cand, "--version"], capture_output=True)
            node = cand
            break
        except OSError:
            continue
    if node is None:
        pytest.skip("node not available for the behavioral simulation")
    out = subprocess.run([node, sim], capture_output=True, text=True,
                         timeout=60, cwd=ROOT)
    assert out.returncode == 0, \
        "behavioral simulation FAILED:\nstdout=%s\nstderr=%s" % (
            out.stdout, out.stderr)
    data = json.loads(out.stdout.strip().splitlines()[-1])
    assert data["pass"] is True
    need = {"popupOffReachesHub", "printDefaultsPreserved", "hubKeysMerged",
            "offlineFlipStaysLocal", "noAutoRevertWhilePending",
            "pendingPushLands", "pendingFlagCleared", "consoleFlipFollows",
            "getCfgSyncsExtPrefs", "alarmWired"}
    missing = need - set(data["checks"])
    assert not missing, "simulation missing checks: %s" % missing
    bad = [k for k, v in data["checks"].items() if v is not True]
    assert not bad, "simulation checks not true: %s" % bad


# ---------------- C. the LIVE queue card -------------------------------

def test_v3510_queue_card_is_live():
    c = console()
    assert 'id="qmodeHead"' in c
    assert "function renderQueueMode(jobs){" in c
    assert "renderQueueMode(jobs);          /* v3.5.10 live queue-mode card */" in c
    assert 'var on = (cfgCache.ext_prefs || {}).queueMode !== false;' in c
    assert "PAUSED: jobs wait in order (Resume releases them)" in c
    assert "instant print: every job goes straight to the printer" in c
    # the static demo text is gone for good
    assert "hub #2047 in progress" not in c


def test_v3510_console_same_switch_notes():
    c = console()
    assert "it is <b>THE SAME switch</b> (synced within a second, last flip wins)" in c
    assert "These switches are <b>THE SAME switches</b> as the extension popup" in c
    assert "the popup and every paired browser adopt them within seconds" in c
    assert "within 5 min (or on next start)" not in c


def test_v3510_console_js_wellformed():
    node = None
    for cand in ("node", "/usr/bin/node", "/usr/local/bin/node"):
        try:
            subprocess.run([cand, "--version"], capture_output=True)
            node = cand
            break
        except OSError:
            continue
    if node is None:
        pytest.skip("node not available for the JS syntax gate")
    import re
    html = console()
    for i, s in enumerate(re.findall(r"<script[^>]*>(.*?)</script>", html,
                                     __import__("re").S)):
        p = os.path.join("/tmp", "v3510_console_script_%d.js" % i)
        open(p, "w", encoding="utf-8").write(s)
        out = subprocess.run([node, "--check", p],
                             capture_output=True, text=True)
        assert out.returncode == 0, "console script %d broke:\n%s" % (
            i, out.stderr)


# ---------------- D. carried guarantees --------------------------------

def test_v3510_silent_windows_carried():
    a, t = adv(), open(TOOL_PATHS[0], encoding="utf-8").read()
    assert "HIDE = 0x08000000 if IS_WIN else 0" in a
    assert a.count("creationflags=HIDE") == 21
    assert t.count("creationflags=HIDE") == 6
    assert "CREATE_NO_WINDOW" in advprint.VERSION_NAME
    assert advprint.HIDE == 0              # POSIX: the flag is a no-op


def test_v3510_extension_id_stable():
    assert EXT_ID in adv()
    assert advprint.EXT_CRX_ID == EXT_ID


def test_v3510_start_here_notes():
    sh = open(os.path.join(ROOT, "START-HERE.txt"), encoding="utf-8").read()
    assert ("AdvPrint Pro (Advanced Printer) v%s - START HERE" % V) in sh
    assert "QUICK NOTE ON v3.5.10 - ONE POWER SWITCH (POPUP + CONSOLE = THE SAME SWITCH)" in sh
    assert "QUICK NOTE ON v3.5.9 - UNBREAKABLE DEB BUILD (SCANNER-PROOF STAGING)" in sh
    assert "QUICK NOTE ON v3.5.8" in sh     # the v3.5.8 note stays
    for probe in ("IT AUTO ON", "NOT SAME OPERATION", "NO EFFECT IN UI",
                  "last flip wins"):
        assert probe in sh, "START-HERE v3.5.10 note lost: " + probe


# ---------------- E. release docs ---------------------------------------

def test_v3510_release_docs():
    ch = open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8").read()
    assert ch.count("## v%s" % V) == 1
    assert "ONE POWER SWITCH" in ch
    assert "auto-ON" in ch
    rd = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
    assert ("## What's new in v%s (%s" % (V, "ONE POWER SWITCH")) in rd
    rn = os.path.join(ROOT, "docs", "RELEASE-NOTES-v%s.md" % V)
    assert os.path.exists(rn)
    body = open(rn, encoding="utf-8").read()
    assert "ONE POWER SWITCH" in body
    assert "last writer wins" in body
    assert "_extPrefPushPending" in body
    assert os.path.exists(os.path.join(ROOT, "scripts",
                          "smoke_v%s.py" % V.replace(".", "")))


def test_v3510_buildall_header_documents_the_fix():
    s = open(os.path.join(ROOT, "scripts", "build-all.py"),
             encoding="utf-8").read()
    assert "9. v3.5.10 ONE POWER SWITCH" in s
    assert "8. v3.5.9 DEB HARDENING" in s   # history stays


def test_v3510_buildall_imports_clean():
    """build-all.py must stay import-safe (no side effects at import
    time) so tests can drive its functions directly."""
    spec = importlib.util.spec_from_file_location(
        "buildall_v3510", os.path.join(ROOT, "scripts", "build-all.py"))
    buildall = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(buildall)
    assert callable(buildall.build_deb_scannerproof)
    assert callable(buildall.parse_version)
