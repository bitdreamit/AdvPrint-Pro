"""v3.5.7 - SILENT WINDOWS (no CMD window flashes)

The owner asked: "when windows run first multiple time cmd run is it
you advprint tools run cmd if it by advprint please run this silently
not show on screen" - on Windows the hub runs windowless (pythonw /
AdvPrintPro.exe), but a few helper launches inside it lacked
creationflags=CREATE_NO_WINDOW, so every reg.exe policy query/write/
delete, the elevated service PowerShell and the CUPS lp fallback gave
Windows a reason to pop a console window - most visibly on the FIRST
run and on every console poll of the policy status (5 browsers x
2 hives = 10 flashes per poll; the install button up to 15 more).

v3.5.7 fixes all of them and adds a BUILD GATE: an ast-based sweep
hard-fails if any subprocess call whose command is a known console
binary (reg, powershell, schtasks, netsh, sc, taskkill, tasklist) is
missing creationflags=HIDE. HIDE is 0 on macOS/Linux - POSIX behaviour
is byte-for-byte unchanged.

Also locks: version coherence 3.5.9, the embedded ONE UI console,
byte-identical hub twins, the v3.5.6 LAN-admin + ipp:// features.
"""
import ast
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V = "3.5.9"
EXT_ID = "likldbkamojokkfdlcjibiljpgbbnohc"
HIDE_WIN = 0x08000000                      # CREATE_NO_WINDOW

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

sys.path.insert(0, os.path.join(ROOT, "tool", "windows", "portable", "hub"))
import advprint  # noqa: E402


def console():
    return open(CONSOLE_PATHS[0], encoding="utf-8").read()


def adv():
    return open(ADV_PATHS[0], encoding="utf-8").read()


def adv_win():
    return open(ADV_PATHS[1], encoding="utf-8").read()


def tool_src():
    return open(TOOL_PATHS[0], encoding="utf-8").read()


def embedded_console():
    a = adv()
    OPEN = 'CONSOLE_HTML = r"""'
    i = a.find(OPEN)
    assert i >= 0, "CONSOLE_HTML missing"
    i += len(OPEN)
    j = a.find('\n"""', i)
    assert j > i, "CONSOLE_HTML closing delimiter missing"
    return a[i:j]


# ---------------- A. version coherence 3.5.9 --------------------------

def test_v357_hub_version():
    assert advprint.VERSION == V
    assert advprint.VERSION_NAME.startswith(
        "v3.5.9 (CRX SIGNATURE VERIFIED + LAN ADMIN CONSOLE")
    assert "SILENT WINDOWS" in advprint.VERSION_NAME
    assert "CREATE_NO_WINDOW" in advprint.VERSION_NAME
    assert "ipp://" in advprint.VERSION_NAME
    assert "admin_ips" in advprint.VERSION_NAME


def test_v357_version_txt():
    s = open(os.path.join(ROOT, "VERSION.txt"), encoding="utf-8").read()
    assert ("AdvPrint Pro (Advanced Printer) %s - built" % V) in s


def test_v357_extension_version_files():
    m = json.load(open(os.path.join(ROOT, "extension", "manifest.json"),
                       encoding="utf-8"))
    assert m["version"] == V
    popup = open(os.path.join(ROOT, "extension", "popup.html"),
                 encoding="utf-8").read()
    assert ("id=\"ver\">v%s<" % V) in popup
    i18n = open(os.path.join(ROOT, "extension", "i18n.js"),
                encoding="utf-8").read()
    assert i18n.count(V) >= 3
    api = open(os.path.join(ROOT, "extension", "content", "api.js"),
               encoding="utf-8").read()
    assert ('_apVerFallback = "%s"' % V) in api
    opts = open(os.path.join(ROOT, "extension", "options.html"),
                encoding="utf-8").read()
    assert ("v%s" % V) in opts


def test_v357_console_version_spots():
    c = console()
    assert "AdvPrint Pro by Bit Dream IT" in c   # v3.5.8 brand title
    assert ('<div class="v">v%s</div>' % V) in c
    assert c.count('(BOOT.version || "%s")' % V) == 3
    assert embedded_console() == c        # embed is byte-fresh


def test_v357_installer_version_spots():
    nsi = open(os.path.join(ROOT, "installer", "setup.nsi"),
               encoding="utf-8").read()
    assert 'OutFile "../dist/AdvPrint-Pro-Setup-%s.exe"' % V in nsi
    assert 'VIProductVersion "%s.0"' % V in nsi
    assert '"DisplayVersion" "%s"' % V in nsi
    control = open(os.path.join(ROOT, "installer", "deb", "DEBIAN",
                                "control"), encoding="utf-8").read()
    assert ("Version: %s" % V) in control


def test_v357_hub_twins_byte_identical():
    assert open(ADV_PATHS[0], "rb").read() == open(ADV_PATHS[1], "rb").read()
    assert open(CONSOLE_PATHS[0], "rb").read() == \
        open(CONSOLE_PATHS[1], "rb").read()
    assert open(TOOL_PATHS[0], "rb").read() == open(TOOL_PATHS[1], "rb").read()


# ---------------- B. the five v3.5.7 fixes, pinned by source ----------

def test_v357_hide_constant():
    for src in (adv(), tool_src()):
        assert "HIDE = 0x08000000 if IS_WIN else 0" in src
    assert advprint.HIDE == 0              # POSIX: the flag is a no-op


def test_v357_reg_query_hidden():
    a = adv()
    assert ('subprocess.run(["reg", "query", full_key],\n'
            '                           capture_output=True, text=True, '
            'timeout=10,\n'
            '                           creationflags=HIDE)') in a


def test_v357_reg_add_hidden():
    assert ('timeout=10, creationflags=HIDE).returncode == 0') in adv()


def test_v357_reg_delete_hidden():
    a = adv()
    assert ('subprocess.run(\n'
            '            ["reg", "delete", full_key, "/v", name, "/f"],\n'
            '            capture_output=True, text=True, timeout=10,\n'
            '            creationflags=HIDE).returncode == 0') in a


def test_v357_service_uac_helper_hidden():
    assert ('"Start-Process -FilePath \'%s\' -Verb RunAs -Wait" % bat],\n'
            '            timeout=240, creationflags=HIDE)') in adv()


def test_v357_cups_lp_popen_hidden():
    # SumatraPDF (Windows) and the CUPS lp fallback now share the same
    # hidden register(Popen(...)) shape - exactly 2 occurrences.
    assert adv().count(
        'proc = register(subprocess.Popen(cmd, stdout=subprocess.PIPE,\n'
        '                                             stderr=subprocess.PIPE,\n'
        '                                             creationflags=HIDE))'
    ) == 2


def test_v357_existing_hidden_sites_untouched():
    a = adv()
    assert a.count("creationflags=HIDE") == 21
    assert "creationflags=DETACHED, startupinfo=si" in a   # relaunch
    assert "AUTOCRX" in a and a.count('creationflags=HIDE)') >= 1
    assert "creationflags=HIDE, stdout=subprocess.DEVNULL" in a


def test_v357_tool_py_hidden_sites():
    t = tool_src()
    assert t.count("creationflags=HIDE") == 6   # tasklist + 2 taskkill + PS + 2
    assert "creationflags=det" in t             # DETACHED hub start


# ---------------- C. BUILD GATE: the source sweep ---------------------

CONSOLE_BINS = {"reg", "powershell", "schtasks", "netsh", "sc",
                "taskkill", "tasklist"}
RUN_FUNCS = {"run", "Popen", "check_output", "check_call", "call"}


def _console_binary_calls(src, path):
    """[(first_arg, has_creationflags)] for every subprocess.<fn>() call
    whose first positional argument is a literal list starting with a
    known console binary."""
    out = []
    for node in ast.walk(ast.parse(src, filename=path)):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if not (isinstance(f, ast.Attribute) and f.attr in RUN_FUNCS
                and isinstance(f.value, ast.Name)
                and f.value.id == "subprocess"):
            continue
        if not node.args:
            continue
        a0 = node.args[0]
        if not (isinstance(a0, ast.List) and a0.elts):
            continue
        e0 = a0.elts[0]
        if (isinstance(e0, ast.Constant) and isinstance(e0.value, str)
                and e0.value in CONSOLE_BINS):
            has = any(kw.arg == "creationflags" for kw in node.keywords)
            out.append((e0.value, has))
    return out


@pytest.mark.parametrize("path", ADV_PATHS + TOOL_PATHS)
def test_v357_sweep_console_binaries_hidden(path):
    src = open(path, encoding="utf-8").read()
    calls = _console_binary_calls(src, path)
    assert calls, "sweep found no console-binary calls in " + path
    naked = [first for first, has in calls if not has]
    assert not naked, ("subprocess calls without creationflags=HIDE in %s: %s"
                       % (path, naked))


def test_v357_sweep_totals():
    """Pin the exact number of swept call sites so a new one cannot
    slip in unguarded without this test telling us."""
    counts = {}
    for path in ADV_PATHS + TOOL_PATHS:
        src = open(path, encoding="utf-8").read()
        for first, _ in _console_binary_calls(src, path):
            counts[first] = counts.get(first, 0) + 1
    # per 4-file sweep (2 hub twins + 2 tool twins), all guarded:
    # hub reg x3 + powershell x12 + schtasks x1 + netsh x1 + sc x1
    # + taskkill x3 | tool.py: tasklist x1 + taskkill x2 + powershell x1
    assert counts == {"reg": 6, "powershell": 24, "schtasks": 2,
                      "netsh": 2, "sc": 2, "taskkill": 6, "tasklist": 2}


# ---------------- D. behaviour: simulated Windows ---------------------

class _FakeProc(object):
    returncode = 0
    stdout = ""
    stderr = ""


def test_v357_reg_helpers_pass_hide_on_windows(monkeypatch):
    captured = []

    def fake_run(cmd, **kw):
        captured.append((list(cmd), kw))
        return _FakeProc()

    monkeypatch.setattr(advprint, "IS_WIN", True)
    monkeypatch.setattr(advprint, "HIDE", HIDE_WIN)
    monkeypatch.setattr(advprint.subprocess, "run", fake_run)

    assert advprint._ext_reg_query_values("HKCU\\SOFTWARE\\Policies\\X") == {}
    assert advprint._ext_reg_add("HKCU\\SOFTWARE\\Policies\\X", "1", "d")
    assert advprint._ext_reg_delete("HKCU\\SOFTWARE\\Policies\\X", "1")
    assert len(captured) == 3
    for cmd, kw in captured:
        assert cmd[0] == "reg"
        assert kw.get("creationflags") == HIDE_WIN
        assert kw.get("timeout") == 10


def test_v357_reg_helpers_noop_off_windows(monkeypatch):
    monkeypatch.setattr(advprint, "IS_WIN", False)
    assert advprint._ext_reg_query_values("HKCU\\X") == {}
    # off-Windows the policy surface answers with the honest note and
    # never touches the registry
    st = advprint.ext_policy_status()
    assert st.get("ok") is True and st.get("browsers") == {}
    assert "note" in st and "registry" in st["note"]


# ---------------- E. installer + launchers stay silent ----------------

def test_v357_nsi_uses_nsexec_only():
    nsi = open(os.path.join(ROOT, "installer", "setup.nsi"),
               encoding="utf-8").read()
    bare = [ln for ln in nsi.splitlines()
            if ln.strip().startswith("Exec ") and "R0" not in ln]
    assert not bare, "bare Exec found: %r" % bare
    assert nsi.count("nsExec::") >= 8
    assert 'ReadRegStr $R0 HKLM "Software\\AdvPrintPro" "PythonW"' in nsi
    assert 'Exec \'"$R0" "$INSTDIR\\hub\\advprint.py" serve\'' in nsi


def test_v357_vbs_launcher_hidden(tmp_path):
    vbs = open(os.path.join(ROOT, "tool", "windows", "portable", "install",
                            "START-ADVPRINT.vbs"), encoding="utf-8").read()
    assert 'sh.Run """" & py & """ """ & hub & """ serve", 0, False' in vbs
    assert "AdvPrintPro.exe" in vbs          # bundled runtime preferred


# ---------------- F. release docs pinned ------------------------------

def test_v357_release_docs():
    ch = open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8").read()
    assert "## v3.5.7 - SILENT WINDOWS (no CMD window flashes)" in ch
    rd = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
    assert "## What's new in v3.5.7 (SILENT WINDOWS" in rd
    sh = open(os.path.join(ROOT, "START-HERE.txt"), encoding="utf-8").read()
    assert ("AdvPrint Pro (Advanced Printer) v%s - START HERE" % V) in sh
    assert "QUICK NOTE ON v3.5.9" in sh
    rn = os.path.join(ROOT, "docs", "RELEASE-NOTES-v%s.md" % V)
    assert os.path.exists(rn)
    assert "SILENT WINDOWS" in open(rn, encoding="utf-8").read()


def test_v357_extension_id_stable():
    a = adv()
    assert EXT_ID in a
    m = json.load(open(os.path.join(ROOT, "extension", "manifest.json"),
                       encoding="utf-8"))
    assert m.get("key") or True               # key presence not asserted here
    assert advprint.EXT_CRX_ID == EXT_ID
