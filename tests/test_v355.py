"""v3.5.5 - FULL SOURCE + WINDOWS BUILD KIT

A user build report ("stage/install/hub-stop.ps1 -> no files found",
Error in script "setup.nsi" on line 198) showed that an incomplete
source tree failed minutes deep inside makensis, and that building
still needed a Linux box. This suite locks the v3.5.5 release:

A. the Windows build kit ships in the tree:
   - build.cmd (one-click launcher: python discovery + cryptography
     install + build-all.py),
   - scripts/build-all.py - the cross-platform canonical builder,
   - docs/BUILD-WINDOWS.md - the step-by-step guide,
B. build-all.py fails LOUD and EARLY:
   - REQUIRED_TREE_FILES covers every staged source (incl. the
     hub-stop.ps1 from the support case) and the stage copy step
     dies on a missing file instead of skipping it silently,
   - setup.nsi is pre-validated: every File reference must resolve
     and OutFile must match VERSION.txt,
   - unix/windows twin files must be byte-identical,
   - the DEB is built in pure Python (no WSL/dpkg-deb),
C. the CRX pipeline is unchanged and gated (stable key, 4-copy sync,
   Chrome-identical verify, payload version 3.5.6),
D. the usual version coherence 3.5.6 (hub / extension / installer),
E. v3.5.4 + v3.5.3 + v3.5.2 fixes untouched (statusbar, tok-mask,
   success rate, history tools).
"""
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V = "3.5.6"
EXT_ID = "likldbkamojokkfdlcjibiljpgbbnohc"

CONSOLE_PATHS = [
    os.path.join(ROOT, "tool", "unix", "hub", "console.html"),
    os.path.join(ROOT, "tool", "windows", "portable", "hub", "console.html"),
    os.path.join(ROOT, "installer", "stage", "hub", "console.html"),
]
ADV_PATHS = [
    os.path.join(ROOT, "tool", "unix", "hub", "advprint.py"),
    os.path.join(ROOT, "tool", "windows", "portable", "hub", "advprint.py"),
    os.path.join(ROOT, "installer", "stage", "hub", "advprint.py"),
]
CRX_PATHS = [
    os.path.join(ROOT, "prebuilt", "AdvPrint-Pro.crx"),
    os.path.join(ROOT, "tool", "unix", "hub", "extension", "AdvPrint-Pro.crx"),
    os.path.join(ROOT, "tool", "windows", "portable", "hub", "extension",
                 "AdvPrint-Pro.crx"),
]


def console():
    return open(CONSOLE_PATHS[0], encoding="utf-8").read()


def adv():
    return open(ADV_PATHS[0], encoding="utf-8").read()


def crx3mod():
    sys.path.insert(0, os.path.join(ROOT, "tool"))
    import crx3
    return crx3


# ---------------- A. the Windows build kit ships in the tree ----------

def test_kit_files_present():
    for rel in ("build.cmd", "scripts/build-all.py", "docs/BUILD-WINDOWS.md",
                "README-BUILDKIT.txt", "docs/BUILD-FROM-SOURCE.md"):
        p = os.path.join(ROOT, *rel.split("/"))
        assert os.path.exists(p), "build kit file missing: " + rel


def test_build_cmd_is_a_real_launcher():
    s = open(os.path.join(ROOT, "build.cmd"), encoding="utf-8").read()
    assert "scripts\\build-all.py" in s, "build.cmd must call the builder"
    assert "cryptography" in s, "build.cmd must install the dependency"
    assert "Add python.exe to PATH" in s, "build.cmd must explain the PATH trap"


def test_build_windows_doc_covers_the_flow():
    s = open(os.path.join(ROOT, "docs", "BUILD-WINDOWS.md"),
             encoding="utf-8").read()
    for needle in ("python.org", "nsis.sourceforge.io", "build.cmd",
                   "crx3.py verify", "SHA256SUMS", "no WSL"):
        assert needle in s, "BUILD-WINDOWS.md must mention " + needle


# ---------------- B. loud, early failure guards ------------------------

def test_required_tree_list_includes_the_support_case_file():
    s = open(os.path.join(ROOT, "scripts", "build-all.py"),
             encoding="utf-8").read()
    assert "REQUIRED_TREE_FILES" in s
    assert '"tool/windows/portable/install/hub-stop.ps1"' in s, \
        "the file from the support case must be on the required list"
    assert "TWIN_FILES" in s and "validate_nsi_refs" in s


def test_stage_copy_never_skips_missing_files():
    s = open(os.path.join(ROOT, "scripts", "build-all.py"),
             encoding="utf-8").read()
    assert "missing stage source" in s, \
        "the stage copy step must die loudly on a missing source file"


def test_selfheal_embedded_install_scripts_byte_identical():
    """Round-2 support case: antivirus quarantine must never break the
    build - every staged install script needs an embedded fallback that
    matches the tree byte for byte."""
    import base64
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "build_all_module", os.path.join(ROOT, "scripts", "build-all.py"))
    ba = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ba)
    for name in ba.STAGE_INSTALL_FILES:
        assert name in ba.EMBEDDED_INSTALL_FILES, \
            "%s has no embedded fallback copy" % name
        raw = base64.b64decode(ba.EMBEDDED_INSTALL_FILES[name])
        tree = open(os.path.join(ROOT, "tool", "windows", "portable",
                                 "install", name), "rb").read()
        assert raw == tree, "%s embedded copy drifted from the tree" % name


def test_makensis_postmortem_and_retry_present():
    s = open(os.path.join(ROOT, "scripts", "build-all.py"),
             encoding="utf-8").read()
    assert "def run_makensis(" in s, "makensis must be wrapped"
    assert "def nsi_missing_refs(" in s, \
        "the post-mortem must re-resolve every setup.nsi File reference"
    assert "Add-MpPreference -ExclusionPath" in s, \
        "the antivirus fix hint must be printed"


def test_makensis_abs_script_and_forced_retry():
    """Round-3 support case: on Windows the compile died at the FIRST
    File directive (setup.nsi line 198, hub-stop.ps1) with
    'no files found' while Python saw every staged file present before
    AND after. The build must now compile absolute-path-validated
    input, and 'no files found' must ALWAYS force a re-stage + retry."""
    s = open(os.path.join(ROOT, "scripts", "build-all.py"),
             encoding="utf-8").read()
    assert "def _makensis_abs_script(" in s, \
        "makensis must compile an absolute-path-validated script"
    assert '"setup-abs.nsi"' in s
    assert "no files found" in s, \
        "'no files found' must trigger a forced re-stage + retry"
    nsi = open(os.path.join(ROOT, "installer", "setup.nsi"),
               encoding="utf-8").read()
    assert '!cd "${__FILEDIR__}"' in nsi, \
        "setup.nsi must be working-directory independent"


def test_pure_python_deb_builder_present():
    s = open(os.path.join(ROOT, "scripts", "build-all.py"),
             encoding="utf-8").read()
    assert "def build_deb(" in s
    assert "debian-binary" in s and "control.tar.gz" in s, \
        "the DEB must be written by stdlib ar/tar code (no WSL needed)"


def test_setup_nsi_refs_all_resolve_and_version_matches():
    nsi = open(os.path.join(ROOT, "installer", "setup.nsi"),
               encoding="utf-8", errors="replace").read()
    missing = []
    for line in nsi.splitlines():
        if not re.match(r"\s*File\b", line):
            continue
        line = line.split(";")[0]
        if "/nonfatal" in line:
            continue
        paths = re.findall(r'"([^"]+)"', line)
        if not paths:
            continue
        src = paths[-1]
        if src.startswith("$"):
            continue
        p = os.path.join(ROOT, "installer", *src.split("/"))
        if "*" in src:
            p = os.path.dirname(p)
        if not os.path.exists(p):
            missing.append(src)
    assert not missing, "setup.nsi File refs missing on disk: %s" % missing
    vt = open(os.path.join(ROOT, "VERSION.txt"), encoding="utf-8").read()
    m = re.search(r'(?m)^OutFile\s+"\.\.[\\/]dist[\\/]AdvPrint-Pro-Setup-(.+)\.exe"', nsi)
    assert m and m.group(1) in vt, "setup.nsi OutFile must match VERSION.txt"


def test_twin_files_byte_identical():
    for name in ("advprint.py", "console.html", "gui_app.py"):
        a = os.path.join(ROOT, "tool", "unix", "hub", name)
        b = os.path.join(ROOT, "tool", "windows", "portable", "hub", name)
        assert os.path.exists(a) and os.path.exists(b), name
        assert open(a, "rb").read() == open(b, "rb").read(), \
            "twin drifted: " + name


# ---------------- C. the CRX pipeline is unchanged and gated ----------

def test_crx3_tool_has_chrome_identical_verify():
    src = open(os.path.join(ROOT, "tool", "crx3.py"), encoding="utf-8").read()
    assert 'SIGNATURE_CONTEXT = b"CRX3 SignedData\\x00"' in src
    assert "def verify_crx(" in src


def test_build_all_has_hard_signature_gate():
    s = open(os.path.join(ROOT, "scripts", "build-all.py"),
             encoding="utf-8").read()
    assert "crx3.py\", \"verify\"" in s or "crx3.py verify" in s, \
        "build-all.py must run the CRX signature verification"
    assert "extension ID changed!" in s, \
        "the stable-ID guard must stay"


def test_every_crx_copy_verifies_355():
    crx3 = crx3mod()
    for p in CRX_PATHS:
        assert os.path.exists(p), "missing CRX copy: " + p
        info = crx3.crx_info(p)
        assert info["extension_id"] == EXT_ID, \
            "extension ID must stay stable: " + p
        assert info["version"] == V, "CRX payload must be " + V + ": " + p
        out = subprocess.run(
            [sys.executable, os.path.join(ROOT, "tool", "crx3.py"),
             "verify", p, V],
            capture_output=True, text=True)
        assert out.returncode == 0, \
            "signature verification failed for %s:\n%s%s" % (
                p, out.stdout, out.stderr)


def test_all_crx_copies_byte_identical():
    blobs = [open(p, "rb").read() for p in CRX_PATHS]
    assert len(blobs) == 3 and len(set(blobs)) == 1


def test_stable_key_still_in_tree():
    pem = os.path.join(ROOT, "extension-signing", "advprint-printer.pem")
    assert os.path.exists(pem)
    crx3 = crx3mod()
    spki = crx3.spki_from_private_pem(open(pem, "rb").read())
    assert crx3.crx_id_from_spki(spki) == EXT_ID


# ---------------- D. version coherence 3.5.6 --------------------------

def test_version_everywhere():
    a = adv()
    assert 'VERSION = "' + V + '"' in a
    assert 'VERSION_NAME = ("v' + V + ' (CRX SIGNATURE VERIFIED' in a
    vt = open(os.path.join(ROOT, "VERSION.txt"), encoding="utf-8").read()
    assert V in vt
    man = json.load(open(os.path.join(ROOT, "extension", "manifest.json"),
                         encoding="utf-8"))
    assert man["version"] == V
    popup = open(os.path.join(ROOT, "extension", "popup.html"),
                 encoding="utf-8").read()
    assert 'id="ver">v' + V + "</span>" in popup
    i18n = open(os.path.join(ROOT, "extension", "i18n.js"),
                encoding="utf-8").read()
    assert i18n.count("Version " + V) == 1
    assert i18n.count(V) == 3  # header + EN + BN brand lines
    api = open(os.path.join(ROOT, "extension", "content", "api.js"),
               encoding="utf-8").read()
    assert 'var _apVerFallback = "' + V + '";' in api
    opts = open(os.path.join(ROOT, "extension", "options.html"),
                encoding="utf-8").read()
    assert "v" + V in opts, "the stale v3.5.1 verchip must be current"
    assert "v3.5.1" not in opts
    nsi = open(os.path.join(ROOT, "installer", "setup.nsi"),
               encoding="utf-8").read()
    assert 'OutFile "../dist/AdvPrint-Pro-Setup-' + V + '.exe"' in nsi
    assert 'VIProductVersion "' + V + '.0"' in nsi
    assert '"DisplayVersion" "' + V + '"' in nsi
    deb = open(os.path.join(ROOT, "installer", "deb", "DEBIAN", "control"),
               encoding="utf-8").read()
    assert "Version: " + V in deb
    assert a.count('(BOOT.version || "' + V + '")') == 3
    assert "ALL-IN-ONE Console v" + V in a
    assert '<div class="stat"><div class="d">hub</div><div class="v">v' \
        + V + '</div>' in console()
    readme = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
    assert "What's new in v" + V in readme
    start = open(os.path.join(ROOT, "START-HERE.txt"),
                 encoding="utf-8").read()
    assert start.startswith("AdvPrint Pro (Advanced Printer) v" + V)
    changelog = open(os.path.join(ROOT, "CHANGELOG.md"),
                     encoding="utf-8").read()
    assert changelog.count("## v" + V) == 1
    assert os.path.exists(os.path.join(ROOT, "docs",
                          "RELEASE-NOTES-v" + V + ".md"))
    assert os.path.exists(os.path.join(ROOT, "scripts", "smoke_v" + V.replace(".", "") + ".py"))


def test_embedded_console_matches_standalone():
    m = re.search(r'CONSOLE_HTML = r"""(.*?)"""', adv(), re.S)
    assert m.group(1) == console() + "\n"
    assert "ALL-IN-ONE Console v" + V in m.group(1)


# ---------------- E. earlier fixes untouched --------------------------

def test_v353_statusbar_fix_still_present():
    s = console()
    m = re.search(r"^body\{([^}]*)\}", s, re.M)
    assert m and "margin:0" in m.group(1)
    m = re.search(r"^\.statusbar\{([^}]*)\}", s, re.M)
    assert m and "flex:0 0 auto" in m.group(1)
    body_pos = s.index('<div class="body">')
    statusbar_pos = s.index('<div class="statusbar">')
    main_close = s.index("</main>", body_pos)
    assert body_pos < main_close < statusbar_pos


def test_v352_fixes_still_present():
    s = console()
    assert "v3.5.2 REAL SUCCESS RATE" in s
    assert ".tok-mask{-webkit-text-security:disc}" in s
    assert "histDateFetch" in s
    assert "/file?view=1" in s
    assert "date_from" in s
    a = adv()
    assert "printed" in a and "saved" in a


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-q", "--no-header", "-p", "no:cacheprovider"]))
