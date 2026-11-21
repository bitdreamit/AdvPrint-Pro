r"""v3.5.9 - UNBREAKABLE DEB BUILD (SCANNER-PROOF STAGING)

The owner reported: the FIRST v3.5.8 build died in the DEB stage with

  FileNotFoundError: ...dist\deb-build\advprint-pro_3.5.8\opt\
  advprint\hub\console.html

and only the SECOND run succeeded. Root cause: the pure-Python DEB
packer walks the staged tree (os.walk) and then opens each file - the
Windows on-access scanner (Defender real-time protection) hid the
freshly copied console.html for a moment BETWEEN the walk and the
open(). The same failure class as the v3.5.5 makensis "no files found"
case; nothing was actually missing.

Locked here: version coherence 3.5.10, the visibility-retry read (a
momentary hide self-heals), the loud walk (a hidden directory raises
instead of being silently skipped), the file-by-file verification of
the staged tree, build_deb(expect=...) catching a vanish between the
verify and the walk, the full build_deb_scannerproof() cycle healing a
real mid-cycle vanish (and the produced .deb parsed member-by-member),
byte-identical twins, the silent-windows carry-over and the release
docs.
"""
import importlib.util
import io
import json
import os
import sys
import tarfile

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

sys.path.insert(0, os.path.join(ROOT, "tool", "windows", "portable", "hub"))
import advprint  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "buildall", os.path.join(ROOT, "scripts", "build-all.py"))
buildall = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(buildall)


def console():
    return open(CONSOLE_PATHS[0], encoding="utf-8").read()


def adv():
    return open(ADV_PATHS[0], encoding="utf-8").read()


# ---------------- A. version coherence 3.5.10 --------------------------

def test_v359_hub_version():
    assert advprint.VERSION == V
    assert advprint.VERSION_NAME.startswith(
        "v3.5.10 (CRX SIGNATURE VERIFIED + LAN ADMIN CONSOLE")
    assert "UNBREAKABLE DEB BUILD" in advprint.VERSION_NAME
    assert "SCANNER-PROOF STAGING" in advprint.VERSION_NAME
    assert "_read_visible" not in advprint.VERSION_NAME  # prose, not code
    # carried-forward guarantees stay in the release string
    assert "REAL WINDOW BUTTONS + BRAND + TAB MEMORY" in advprint.VERSION_NAME
    assert "SILENT WINDOWS" in advprint.VERSION_NAME
    assert "CREATE_NO_WINDOW" in advprint.VERSION_NAME
    assert "ipp://" in advprint.VERSION_NAME
    assert "admin_ips" in advprint.VERSION_NAME


def test_v359_version_txt():
    s = open(os.path.join(ROOT, "VERSION.txt"), encoding="utf-8").read()
    assert ("AdvPrint Pro (Advanced Printer) %s - built" % V) in s


def test_v359_extension_version_files():
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


def test_v359_console_version_spots():
    c = console()
    assert ('<div class="stat"><div class="d">hub</div>'
            '<div class="v">v%s</div>' % V) in c
    assert c.count('(BOOT.version || "%s")' % V) == 3


def test_v359_embedded_console_is_fresh():
    a = adv()
    OPEN = 'CONSOLE_HTML = r"""'
    i = a.find(OPEN)
    assert i >= 0, "CONSOLE_HTML missing"
    i += len(OPEN)
    j = a.find('\n"""', i)
    assert j > i, "CONSOLE_HTML closing delimiter missing"
    assert a[i:j] == console()        # embed is byte-fresh


def test_v359_installer_version_spots():
    nsi = open(os.path.join(ROOT, "installer", "setup.nsi"),
               encoding="utf-8").read()
    assert 'OutFile "../dist/AdvPrint-Pro-Setup-%s.exe"' % V in nsi
    assert 'VIProductVersion "%s.0"' % V in nsi
    assert '"DisplayVersion" "%s"' % V in nsi
    control = open(os.path.join(ROOT, "installer", "deb", "DEBIAN",
                                "control"), encoding="utf-8").read()
    assert ("Version: %s" % V) in control


def test_v359_hub_twins_byte_identical():
    assert open(ADV_PATHS[0], "rb").read() == open(ADV_PATHS[1], "rb").read()
    assert open(CONSOLE_PATHS[0], "rb").read() == \
        open(CONSOLE_PATHS[1], "rb").read()
    assert open(TOOL_PATHS[0], "rb").read() == open(TOOL_PATHS[1], "rb").read()


def test_v359_v358_features_carried():
    c = console()
    # brand title (v3.5.8)
    assert "<title>%s \u2014 Innovative Healthcare Solutions</title>" % BRAND in c
    # tab memory + URL path (v3.5.8)
    assert 'var AP_TAB_KEY = "ap_console_tab";' in c
    assert 'u.searchParams.set("path", name);' in c
    # real window buttons (v3.5.8)
    assert "(function winbtnsReal(){" in c
    assert "    window.close();" in c


# ---------------- B. the scanner-proof layers -------------------------

def test_v359_read_visible_heals_a_momentary_hide(tmp_path, monkeypatch):
    """The EXACT v3.5.8 failure shape: os.walk already listed the file,
    the first open() hits FileNotFoundError (scanner hid it), the file
    is visible again on the next attempt -> _read_visible succeeds."""
    import builtins
    f = tmp_path / "console.html"
    f.write_bytes(b"hello deb")
    real_open = builtins.open
    state = {"hidden": True}

    def flaky_open(path, *a, **k):
        if state["hidden"] and \
                os.path.abspath(str(path)) == os.path.abspath(str(f)):
            state["hidden"] = False
            raise FileNotFoundError(2, "hidden by scanner", str(path))
        return real_open(path, *a, **k)

    monkeypatch.setattr(builtins, "open", flaky_open)
    monkeypatch.setattr(buildall.time, "sleep", lambda s: None)
    assert buildall._read_visible(str(f)) == b"hello deb"


def test_v359_read_visible_gives_up_loudly(tmp_path, monkeypatch):
    """A genuinely gone (quarantined) file must raise, not hang."""
    import builtins
    f = tmp_path / "gone.html"
    real_open = builtins.open

    def gone_open(path, *a, **k):
        if os.path.abspath(str(path)) == os.path.abspath(str(f)):
            raise FileNotFoundError(2, "quarantined", str(path))
        return real_open(path, *a, **k)

    monkeypatch.setattr(builtins, "open", gone_open)
    monkeypatch.setattr(buildall.time, "sleep", lambda s: None)
    with pytest.raises(FileNotFoundError):
        buildall._read_visible(str(f), attempts=3)


def test_v359_tar_from_dir_heals_a_hidden_file(tmp_path, monkeypatch):
    d = tmp_path / "stage"
    (d / "opt" / "advprint").mkdir(parents=True)
    (d / "opt" / "advprint" / "a.txt").write_bytes(b"A" * 10)
    (d / "opt" / "advprint" / "console.html").write_bytes(b"<html>x</html>")
    import builtins
    real_open = builtins.open
    state = {"hidden": True}

    def flaky_open(path, *a, **k):
        if state["hidden"] and str(path).endswith("console.html"):
            state["hidden"] = False
            raise FileNotFoundError(2, "hidden", str(path))
        return real_open(path, *a, **k)

    monkeypatch.setattr(builtins, "open", flaky_open)
    monkeypatch.setattr(buildall.time, "sleep", lambda s: None)
    blob = buildall._tar_from_dir(str(d))
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tf:
        assert tf.extractfile("./opt/advprint/console.html").read() \
            == b"<html>x</html>"
        assert tf.extractfile("./opt/advprint/a.txt").read() == b"A" * 10


def test_v359_walk_skips_nothing_silently(tmp_path, monkeypatch):
    """A hidden DIRECTORY must never be silently omitted - that would
    quietly ship an incomplete .deb. The onerror hook re-raises."""
    d = tmp_path / "stage"
    d.mkdir()
    (d / "a").mkdir()
    (d / "a" / "x.txt").write_bytes(b"x")
    (d / "b").mkdir()
    (d / "b" / "y.txt").write_bytes(b"y")
    real_scandir = os.scandir

    def flaky_scandir(path):
        if os.path.basename(os.fspath(path)) == "b":
            raise PermissionError(13, "scanner holds it", str(path))
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", flaky_scandir)
    with pytest.raises(PermissionError):
        buildall._tar_from_dir(str(d))


def test_v359_expected_layout_covers_the_real_tree():
    """deb_expected_files() mirrors exactly what stage_deb_tree copies."""
    expect = buildall.deb_expected_files()
    assert "DEBIAN/control" in expect
    assert "opt/advprint/hub/advprint.py" in expect
    assert "opt/advprint/hub/console.html" in expect
    assert "opt/advprint/hub/gui_app.py" in expect
    assert "opt/advprint/hub/extension/AdvPrint-Pro.crx" in expect
    assert "opt/advprint/hub/service/AdvPrintProService.cs" in expect
    assert "usr/bin/advprint" in expect
    assert "usr/lib/systemd/user/advprint.service" in expect
    # every hub html the source ships is expected in the payload
    htmldir = os.path.join(ROOT, "tool", "unix", "hub")
    for name in sorted(os.listdir(htmldir)):
        if name.endswith(".html"):
            assert "opt/advprint/hub/" + name in expect


# ---------------- C. the full scanner-proof cycle ---------------------

WHUB = os.path.join(ROOT, "tool", "windows", "portable", "hub")
SVC = os.path.join(WHUB, "service", "AdvPrintProService.cs")


def _staged_tree(tmp_path):
    """Run the REAL stage_deb_tree against the real source tree, into a
    temp deb-root; returns (tmp, deb_root, out, crx)."""
    V_ = buildall.parse_version()
    crx = tmp_path / "fake.crx"
    crx.write_bytes(b"PK\x03\x04fake-crx-for-cycle-tests")
    deb_root = str(tmp_path / "deb-build")
    tmp = os.path.join(deb_root, "advprint-pro_%s" % V_)
    buildall.stage_deb_tree(tmp, V_, str(crx), WHUB, SVC, deb_root=deb_root)
    return tmp, deb_root, str(tmp_path / "out.deb"), str(crx)


def test_v359_stage_tree_and_verify(tmp_path):
    tmp, deb_root, out, crx = _staged_tree(tmp_path)
    assert buildall.verify_deb_stage(tmp) == []
    ctl = open(os.path.join(tmp, "DEBIAN", "control"),
               encoding="utf-8").read()
    assert ("Version: %s" % buildall.parse_version()) in ctl
    assert open(os.path.join(tmp, "opt", "advprint", "hub", "console.html"),
                "rb").read() == open(CONSOLE_PATHS[0], "rb").read()


def test_v359_verify_deb_stage_reports_missing(tmp_path):
    tmp, deb_root, out, crx = _staged_tree(tmp_path)
    os.remove(os.path.join(tmp, "opt", "advprint", "hub", "console.html"))
    assert buildall.verify_deb_stage(tmp) == ["opt/advprint/hub/console.html"]


def test_v359_build_deb_expect_catches_prewalk_vanish(tmp_path):
    """The v3.5.8 bug shape: file gone BEFORE the walk. Without the
    expect check the tar would SUCCEED and quietly ship an incomplete
    .deb; with it the build fails loudly with the file name."""
    tmp, deb_root, out, crx = _staged_tree(tmp_path)
    os.remove(os.path.join(tmp, "opt", "advprint", "hub", "console.html"))
    with pytest.raises(FileNotFoundError) as ei:
        buildall.build_deb(tmp, out, expect=buildall.deb_expected_files())
    assert "console.html" in str(ei.value)


def test_v359_scannerproof_cycle_restages_and_succeeds(tmp_path,
                                                       monkeypatch):
    """End-to-end proof: reproduce the v3.5.8 failure (console.html
    vanishes right before the tar) and watch the cycle re-stage and
    succeed - then parse the produced .deb member-by-member."""
    tmp, deb_root, out, crx = _staged_tree(tmp_path)
    calls = {"build": 0, "stage": 0}
    real_build, real_stage = buildall.build_deb, buildall.stage_deb_tree

    def flaky_build(staged, out_path, expect=None):
        calls["build"] += 1
        if calls["build"] == 1:
            # the scanner eats the file between verify and the walk
            os.remove(os.path.join(staged, "opt", "advprint", "hub",
                                   "console.html"))
        return real_build(staged, out_path, expect=expect)

    def counting_stage(t, V_, crx_, whub, svc, deb_root=None):
        calls["stage"] += 1
        return real_stage(t, V_, crx_, whub, svc, deb_root=deb_root)

    monkeypatch.setattr(buildall, "build_deb", flaky_build)
    monkeypatch.setattr(buildall, "stage_deb_tree", counting_stage)
    monkeypatch.setattr(buildall.time, "sleep", lambda s: None)
    buildall.build_deb_scannerproof(buildall.parse_version(), out, crx,
                                    WHUB, SVC, deb_root=deb_root,
                                    attempts=3)
    assert calls["build"] == 2          # attempt 1 failed, 2 healed
    assert calls["stage"] == 2          # automatic re-stage happened
    assert os.path.exists(out)

    # ---- the .deb itself: full ar + tar validation -------------------
    data = open(out, "rb").read()
    assert data.startswith(b"!<arch>\n")
    off, members = 8, []
    while off + 60 <= len(data):
        name = data[off:off + 16].decode("ascii").strip()
        size = int(data[off + 48:off + 58].decode("ascii").strip())
        members.append((name, off + 60, size))
        off += 60 + size + (size % 2)
    assert [n for n, _o, _s in members] == \
        ["debian-binary", "control.tar.gz", "data.tar.gz"]
    for name, o, size in members:
        if name == "control.tar.gz":
            with tarfile.open(fileobj=io.BytesIO(data[o:o + size]),
                              mode="r:gz") as tf:
                assert "./control" in tf.getnames()
        if name == "data.tar.gz":
            with tarfile.open(fileobj=io.BytesIO(data[o:o + size]),
                              mode="r:gz") as tf:
                names = tf.getnames()
                for must in ("./opt/advprint/hub/console.html",
                             "./opt/advprint/hub/advprint.py",
                             "./opt/advprint/hub/extension/"
                             "AdvPrint-Pro.crx",
                             "./etc/xdg/autostart/advprint.desktop",
                             "./usr/bin/advprint",
                             "./usr/lib/systemd/user/advprint.service"):
                    assert must in names, must
                assert tf.extractfile(
                    "./opt/advprint/hub/console.html").read() == \
                    open(CONSOLE_PATHS[0], "rb").read()
                assert tf.getmember("./usr/bin/advprint").mode == 0o755
                assert tf.getmember(
                    "./opt/advprint/hub/console.html").mode == 0o644


def test_v359_scannerproof_heals_a_poststage_vanish(tmp_path, monkeypatch):
    """The OTHER failure shape: the file is eaten during the copy, so
    verify_deb_stage catches it BEFORE any tar - the cycle re-stages."""
    tmp, deb_root, out, crx = _staged_tree(tmp_path)
    calls = {"stage": 0}
    real_stage = buildall.stage_deb_tree

    def flaky_stage(t, V_, crx_, whub, svc, deb_root=None):
        calls["stage"] += 1
        real_stage(t, V_, crx_, whub, svc, deb_root=deb_root)
        if calls["stage"] == 1:
            os.remove(os.path.join(t, "opt", "advprint", "hub",
                                   "console.html"))

    monkeypatch.setattr(buildall, "stage_deb_tree", flaky_stage)
    monkeypatch.setattr(buildall.time, "sleep", lambda s: None)
    buildall.build_deb_scannerproof(buildall.parse_version(), out, crx,
                                    WHUB, SVC, deb_root=deb_root,
                                    attempts=3)
    assert calls["stage"] == 2
    assert os.path.exists(out)


def test_v359_scannerproof_dies_loudly_when_exhausted(tmp_path,
                                                      monkeypatch):
    """If files keep vanishing, the build stops with the fix-it hint
    (die -> SystemExit), never with a half-built .deb."""
    tmp, deb_root, out, crx = _staged_tree(tmp_path)
    monkeypatch.setattr(buildall, "verify_deb_stage",
                        lambda t: ["opt/advprint/hub/console.html"])
    monkeypatch.setattr(buildall.time, "sleep", lambda s: None)
    with pytest.raises(SystemExit):
        buildall.build_deb_scannerproof(buildall.parse_version(), out,
                                        crx, WHUB, SVC,
                                        deb_root=deb_root, attempts=2)
    assert not os.path.exists(out)      # no deb was written


def test_v359_tar_modes_are_explicit(tmp_path):
    """usr/bin launchers stay executable, payload files are 0644 - on
    any host filesystem (FAT/NTFS included)."""
    tmp, deb_root, out, crx = _staged_tree(tmp_path)
    buildall.build_deb(tmp, out, expect=buildall.deb_expected_files())
    data = open(out, "rb").read()
    off, members = 8, []
    while off + 60 <= len(data):
        name = data[off:off + 16].decode("ascii").strip()
        size = int(data[off + 48:off + 58].decode("ascii").strip())
        members.append((name, off + 60, size))
        off += 60 + size + (size % 2)
    for name, o, size in members:
        if name == "data.tar.gz":
            with tarfile.open(fileobj=io.BytesIO(data[o:o + size]),
                              mode="r:gz") as tf:
                assert tf.getmember("./usr/bin/advprint").mode == 0o755
                assert tf.getmember("./usr/bin/advprint-start").mode == 0o755
                assert tf.getmember("./DEBIAN/postinst" if
                                    "./DEBIAN/postinst" in tf.getnames()
                                    else "./opt/advprint/hub/advprint.py"
                                    ).mode in (0o755, 0o644)


# ---------------- D. carried guarantees + release docs ----------------

def test_v359_silent_windows_carried():
    a, t = adv(), open(TOOL_PATHS[0], encoding="utf-8").read()
    assert "HIDE = 0x08000000 if IS_WIN else 0" in a
    assert a.count("creationflags=HIDE") == 21
    assert t.count("creationflags=HIDE") == 6
    assert "CREATE_NO_WINDOW" in advprint.VERSION_NAME
    assert advprint.HIDE == 0              # POSIX: the flag is a no-op


def test_v359_extension_id_stable():
    assert EXT_ID in adv()
    assert advprint.EXT_CRX_ID == EXT_ID


def test_v359_release_docs():
    ch = open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8").read()
    assert ch.count("## v%s" % V) == 1
    assert "UNBREAKABLE DEB BUILD" in ch
    rd = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
    assert ("## What's new in v%s (%s" % (V, "ONE POWER SWITCH")) in rd
    sh = open(os.path.join(ROOT, "START-HERE.txt"), encoding="utf-8").read()
    assert ("AdvPrint Pro (Advanced Printer) v%s - START HERE" % V) in sh
    assert "QUICK NOTE ON v3.5.10" in sh
    assert "QUICK NOTE ON v3.5.8" in sh     # the v3.5.8 note stays
    rn = os.path.join(ROOT, "docs", "RELEASE-NOTES-v%s.md" % V)
    assert os.path.exists(rn)
    body = open(rn, encoding="utf-8").read()
    assert "SCANNER-PROOF" in body
    assert "_read_visible" in body
    assert os.path.exists(os.path.join(ROOT, "scripts",
                          "smoke_v%s.py" % V.replace(".", "")))


def test_v359_buildall_header_documents_the_fix():
    s = open(os.path.join(ROOT, "scripts", "build-all.py"),
             encoding="utf-8").read()
    assert "8. v3.5.9 DEB HARDENING" in s
    for fn in ("_read_visible", "_visible_mtime", "_walk_loud",
               "deb_expected_files", "verify_deb_stage", "stage_deb_tree",
               "build_deb_scannerproof"):
        assert ("def %s(" % fn) in s


def test_v359_buildall_imports_clean():
    """build-all.py must stay import-safe (no side effects at import
    time) so tests can drive its functions directly."""
    assert callable(buildall.build_deb_scannerproof)
    assert callable(buildall.stage_deb_tree)
    assert callable(buildall.parse_version)
