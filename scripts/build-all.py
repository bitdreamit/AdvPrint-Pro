#!/usr/bin/env python3
# ============================================================
# AdvPrint Pro - build EVERYTHING from this repo, on ANY OS.
# Windows / Linux / macOS - needs only Python 3.9+ and, for
# the Setup EXE, NSIS 3.x.  by Bit Dream IT - Innovative
# Healthcare Solutions
#
#   python scripts/build-all.py            (or:  build.cmd  on Windows)
#
# Produces in dist/:
#   AdvPrint-Pro.crx                      signed extension (CRX3, repo key)
#   AdvPrint-Pro-Extension-<V>.zip        unpacked extension zip (store/dev)
#   AdvPrint-Pro-Setup-<V>.exe            Windows installer (NSIS, staged)
#   advprint-pro_<V>_all.deb              Linux DEB (built in PURE PYTHON,
#                                         no dpkg-deb / WSL needed)
#   SHA256SUMS-<V>.txt                    checksums of everything
#
# Requirements: python3 + `pip install cryptography` (CRX signing).
#               NSIS 3.x (makensis) for the EXE - auto-detected.
# ============================================================
import argparse
import filecmp
import io
import os
import re
import shutil
import struct
import subprocess
import sys
import tarfile
import time
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPECTED_EXT_ID = "likldbkamojokkfdlcjibiljpgbbnohc"


def die(msg):
    print("!! " + msg)
    sys.exit(1)


def py(*args, cwd=None, env=None, show=False):
    """Run a python subprocess with THIS interpreter and fail hard."""
    r = subprocess.run([sys.executable, *args], cwd=cwd or ROOT,
                       env=env, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout)
        print(r.stderr)
        die("command failed: %s" % " ".join(args))
    if show and r.stdout.strip():
        print(r.stdout.rstrip())
    return r.stdout


def parse_version():
    txt = open(os.path.join(ROOT, "VERSION.txt"), encoding="utf-8").read()
    m = re.search(r"AdvPrint Pro \(Advanced Printer\) ([0-9][0-9.]*)", txt)
    if not m:
        die("cannot parse version from VERSION.txt")
    return m.group(1)


# ------------------------------------------------------------ DEB (pure python)
def _ar_member(name, data, mtime):
    hdr = (name.ljust(16).encode() +
           str(mtime).ljust(12).encode() +
           "0".ljust(6).encode() + "0".ljust(6).encode() +
           "100644".ljust(8).encode() +
           str(len(data)).ljust(10).encode() + b"`\n")
    pad = b"\n" if len(data) % 2 else b""
    return hdr + data + pad


def _tar_from_dir(src_dir, exclude_prefix=None):
    """tar.gz of a staged tree - ./ prefixed names, root ownership,
    explicit modes (works on FAT/NTFS where +x does not exist)."""
    buf = io.BytesIO()
    entries = []
    for root, dirs, files in os.walk(src_dir):
        dirs.sort()
        for name in sorted(files):
            full = os.path.join(root, name)
            rel = "./" + os.path.relpath(full, src_dir).replace(os.sep, "/")
            if exclude_prefix and rel.startswith(exclude_prefix):
                continue
            entries.append((full, rel))
    mtime = int(time.time())

    def dirinfo(name):
        di = tarfile.TarInfo(name)
        di.type = tarfile.DIRTYPE
        di.mode = 0o755
        di.uid = di.gid = 0
        di.uname = di.gname = "root"
        di.mtime = mtime
        return di

    with tarfile.open(fileobj=buf, mode="w:gz", format=tarfile.GNU_FORMAT) as tf:
        tf.addfile(dirinfo("./"))
        made = set()
        for full, rel in entries:
            parts = rel.lstrip("./").split("/")
            for i in range(1, len(parts)):
                d = "./" + "/".join(parts[:i])
                if d not in made:
                    tf.addfile(dirinfo(d))
                    made.add(d)
        for full, rel in entries:
            mode = 0o755 if (rel.startswith("./DEBIAN/postinst")
                             or rel.startswith("./DEBIAN/prerm")
                             or rel.startswith("./usr/bin/")) else 0o644
            data = open(full, "rb").read()
            ti = tarfile.TarInfo(rel)
            ti.size = len(data)
            ti.mode = mode
            ti.uid = ti.gid = 0
            ti.uname = ti.gname = "root"
            ti.mtime = int(os.path.getmtime(full))
            tf.addfile(ti, io.BytesIO(data))
    return buf.getvalue()


def build_deb(staged_dir, out_path):
    """dpkg-deb equivalent in pure Python (ar + tar.gz, root owner-group).
    member order: debian-binary, control.tar.gz, data.tar.gz."""
    mtime = int(time.time())
    control = _tar_from_dir(os.path.join(staged_dir, "DEBIAN"))
    data = _tar_from_dir(staged_dir, exclude_prefix="./DEBIAN")
    with open(out_path, "wb") as f:
        f.write(b"!<arch>\n")
        f.write(_ar_member("debian-binary", b"2.0\n", mtime))
        f.write(_ar_member("control.tar.gz", control, mtime))
        f.write(_ar_member("data.tar.gz", data, mtime))


# ------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser(description="AdvPrint Pro build-everything "
                                 "(Windows / Linux / macOS)")
    ap.add_argument("--skip-exe", action="store_true",
                    help="do not build the NSIS Setup EXE")
    ap.add_argument("--skip-deb", action="store_true",
                    help="do not build the Linux DEB")
    args = ap.parse_args()

    V = parse_version()
    print("== AdvPrint Pro build-all: version %s ==" % V)

    DIST = os.path.join(ROOT, "dist")
    STAGE = os.path.join(ROOT, "installer", "stage")
    for d in (DIST, STAGE):
        shutil.rmtree(d, ignore_errors=True)
    for d in (DIST,
              os.path.join(STAGE, "hub", "extension"),
              os.path.join(STAGE, "install"),
              os.path.join(STAGE, "docs")):
        os.makedirs(d, exist_ok=True)

    # ---------- 1) signed CRX3 (repo extension + repo signing key) ----------
    print("-- CRX3")
    crx = os.path.join(DIST, "AdvPrint-Pro.crx")
    eid = py("tool/crx3.py", "pack", "extension",
             "extension-signing/advprint-printer.pem", crx).splitlines()
    print("   " + " | ".join(x.strip() for x in eid if x.strip()))
    if EXPECTED_EXT_ID not in " ".join(eid):
        die("extension ID changed! extension-signing/advprint-printer.pem "
            "was replaced - restore the original key, never --gen-key")

    # STALE-CRX GUARD: sync EVERY embedded copy, then byte-compare all
    shutil.copyfile(crx, os.path.join(STAGE, "hub", "extension", "AdvPrint-Pro.crx"))
    os.makedirs(os.path.join(ROOT, "prebuilt"), exist_ok=True)
    sync_targets = [
        os.path.join(STAGE, "hub", "extension", "AdvPrint-Pro.crx"),
        os.path.join(ROOT, "tool", "unix", "hub", "extension", "AdvPrint-Pro.crx"),
        os.path.join(ROOT, "tool", "windows", "portable", "hub", "extension", "AdvPrint-Pro.crx"),
        os.path.join(ROOT, "prebuilt", "AdvPrint-Pro.crx"),
    ]
    for p in sync_targets:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        shutil.copyfile(crx, p)
        if not filecmp.cmp(crx, p, shallow=False):
            die("CRX sync FAILED: %s != dist/AdvPrint-Pro.crx" % p)

    # payload version guard
    with zipfile.ZipFile(crx) as z:
        crx_v = __import__("json").loads(z.read("manifest.json").decode())["version"]
    if crx_v != V:
        die("CRX version %s != hub version %s (bump extension/manifest.json)" % (crx_v, V))
    print("   embedded CRX copies synced + verified v%s" % crx_v)

    # v3.5.3 CRX-SIGNATURE GUARD: Chrome-identical verification as a hard gate
    py("tool/crx3.py", "verify", crx, V, show=True)

    # ---------- 2) unpacked extension zip (Web-store upload / dev load) -----
    print("-- extension zip")
    extzip = os.path.join(DIST, "AdvPrint-Pro-Extension-%s.zip" % V)
    ext_dir = os.path.join(ROOT, "extension")
    with zipfile.ZipFile(extzip, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, names in os.walk(ext_dir):
            for name in sorted(names):
                full = os.path.join(root, name)
                zf.write(full, os.path.relpath(full, ext_dir).replace(os.sep, "/"))

    # ---------- 3) NSIS stage (hub + installers + runtime + docs) ----------
    print("-- NSIS stage")
    whub = os.path.join(ROOT, "tool", "windows", "portable", "hub")
    for name in sorted(os.listdir(whub)):
        if name.endswith((".py", ".ico", ".html")):
            shutil.copy2(os.path.join(whub, name), os.path.join(STAGE, "hub", name))
    os.makedirs(os.path.join(STAGE, "hub", "service"), exist_ok=True)
    svc = os.path.join(whub, "service", "AdvPrintProService.cs")
    if os.path.exists(svc):
        shutil.copy2(svc, os.path.join(STAGE, "hub", "service"))
    winst = os.path.join(ROOT, "tool", "windows", "portable", "install")
    for name in ("install-windows.bat", "UNINSTALL-WINDOWS.bat", "START-ADVPRINT.vbs",
                 "START-CONSOLE.vbs", "INSTALL-WINDOWS-SERVICE.bat",
                 "REMOVE-WINDOWS-SERVICE.bat", "service-install.ps1",
                 "service-remove.ps1", "hub-stop.ps1"):
        p = os.path.join(winst, name)
        if os.path.exists(p):
            shutil.copy2(p, os.path.join(STAGE, "install", name))
    shutil.copy2(os.path.join(ROOT, "docs", "AdvPrint-Pro-Full-Guide.html"),
                 os.path.join(STAGE, "docs", "AdvPrint-Pro-Full-Guide.html"))
    shutil.copy2(os.path.join(ROOT, "README.md"), os.path.join(STAGE, "README.md"))
    runtime = os.path.join(ROOT, "tool", "windows", "portable", "installer", "runtime")
    if os.path.isdir(runtime):
        print("   embedding Python runtime (%.0f MB)..." % (sum(
            os.path.getsize(os.path.join(r, f))
            for r, _d, fs in os.walk(runtime) for f in fs) / 2**20))
        shutil.copytree(runtime, os.path.join(STAGE, "runtime"))
    else:
        print("   WARNING: runtime missing - Setup EXE would need system Python")

    # ---------- 4) DEB ----------
    if args.skip_deb:
        print("-- DEB (skipped by request)")
    else:
        print("-- DEB (pure-python builder, no dpkg-deb needed)")
        tmp = os.path.join(DIST, "deb-build", "advprint-pro_%s" % V)
        shutil.rmtree(os.path.join(DIST, "deb-build"), ignore_errors=True)
        shutil.copytree(os.path.join(ROOT, "installer", "deb", "DEBIAN"),
                        os.path.join(tmp, "DEBIAN"))
        ctrl = os.path.join(tmp, "DEBIAN", "control")
        ctl = open(ctrl, encoding="utf-8").read()
        open(ctrl, "w", encoding="utf-8", newline="\n").write(
            re.sub(r"(?m)^Version: .*", "Version: %s" % V, ctl))
        for d in ("opt/advprint/hub/extension", "opt/advprint/hub/service",
                  "etc/xdg/autostart", "usr/bin", "usr/lib/systemd/user"):
            os.makedirs(os.path.join(tmp, d.replace("/", os.sep)), exist_ok=True)
        dst = lambda *p: os.path.join(tmp, *p)
        shutil.copy2(os.path.join(ROOT, "tool/unix/hub/advprint.py".replace("/", os.sep)),
                     dst("opt", "advprint", "hub", "advprint.py"))
        for name in ("tool.py", "tray_windows.py", "service_main.py", "advprint.ico"):
            shutil.copy2(os.path.join(whub, name), dst("opt", "advprint", "hub", name))
        if os.path.exists(os.path.join(ROOT, "tool/unix/hub/console.html".replace("/", os.sep))):
            shutil.copy2(os.path.join(ROOT, "tool/unix/hub/console.html".replace("/", os.sep)),
                         dst("opt", "advprint", "hub", "console.html"))
        if os.path.exists(os.path.join(ROOT, "tool/unix/hub/gui_app.py".replace("/", os.sep))):
            shutil.copy2(os.path.join(ROOT, "tool/unix/hub/gui_app.py".replace("/", os.sep)),
                         dst("opt", "advprint", "hub", "gui_app.py"))
        htmldir = os.path.join(ROOT, "tool", "unix", "hub")
        for name in sorted(os.listdir(htmldir)):
            if name.endswith(".html"):
                shutil.copy2(os.path.join(htmldir, name), dst("opt", "advprint", "hub", name))
        shutil.copy2(crx, dst("opt", "advprint", "hub", "extension", "AdvPrint-Pro.crx"))
        if os.path.exists(svc):
            shutil.copy2(svc, dst("opt", "advprint", "hub", "service", "AdvPrintProService.cs"))
        shutil.copy2(os.path.join(ROOT, "installer", "deb", "data", "advprint.desktop"),
                     dst("etc", "xdg", "autostart", "advprint.desktop"))
        shutil.copy2(os.path.join(ROOT, "installer", "deb", "data", "advprint-launcher"),
                     dst("usr", "bin", "advprint"))
        shutil.copy2(os.path.join(ROOT, "installer", "deb", "data", "advprint-start"),
                     dst("usr", "bin", "advprint-start"))
        shutil.copy2(os.path.join(ROOT, "installer", "deb", "data", "advprint.service"),
                     dst("usr", "lib", "systemd", "user", "advprint.service"))
        deb = os.path.join(DIST, "advprint-pro_%s_all.deb" % V)
        build_deb(tmp, deb)
        shutil.rmtree(os.path.join(DIST, "deb-build"), ignore_errors=True)
        if shutil.which("dpkg-deb"):  # sanity check where available
            r = subprocess.run(["dpkg-deb", "--info", deb], capture_output=True, text=True)
            if r.returncode != 0:
                print(r.stdout)
                print(r.stderr)
                die("built DEB rejected by dpkg-deb --info")
            print("   dpkg-deb --info: OK (%s)" %
                  re.search(r"Version: (.*)", r.stdout).group(1).strip())
        else:
            print("   (dpkg-deb not present - skipped the optional lint check)")

    # ---------- 5) NSIS Setup EXE ----------
    nsi = os.path.join(ROOT, "installer", "setup.nsi")
    m = re.search(r'(?m)^OutFile\s+"\.\.[\\/]dist[\\/]AdvPrint-Pro-Setup-(.+)\.exe"',
                  open(nsi, encoding="utf-8", errors="replace").read())
    if not m or m.group(1) != V:
        want = 'OutFile "../dist/AdvPrint-Pro-Setup-%s.exe"' % V
        die("installer/setup.nsi OutFile is %s - update it to:\n   %s"
            % (('"%s"' % m.group(1)) if m else "missing/unparsable", want))
    mk, env = find_makensis()
    exe = os.path.join(DIST, "AdvPrint-Pro-Setup-%s.exe" % V)
    if args.skip_exe:
        print("-- Setup EXE (skipped by request)")
    elif mk:
        print("-- NSIS Setup EXE (%s)" % mk)
        e = dict(os.environ)
        if env:
            e.update(env)
        r = subprocess.run([mk, "-V2", "setup.nsi"], cwd=os.path.join(ROOT, "installer"),
                           env=e)
        if r.returncode != 0 or not os.path.exists(exe):
            die("makensis failed")
    else:
        print("!! makensis NOT found - stage/ is ready; install NSIS 3.x and")
        print("   re-run, or run:  cd installer && makensis setup.nsi")
        print("   Windows: https://nsis.sourceforge.io (default dir is auto-found)")

    # ---------- 6) SHA256SUMS ----------
    print("-- SHA256SUMS")
    sums = ["AdvPrint-Pro.crx", "AdvPrint-Pro-Extension-%s.zip" % V]
    if not args.skip_deb:
        sums.append("advprint-pro_%s_all.deb" % V)
    if os.path.exists(exe):
        sums.append("AdvPrint-Pro-Setup-%s.exe" % V)
    else:
        print("!! Setup EXE missing - SHA256SUMS will cover only %s" % " ".join(sums))
    lines = []
    for name in sums:
        h = hashlib_file(os.path.join(DIST, name))
        lines.append("%s  %s" % (h, name))
    with open(os.path.join(DIST, "SHA256SUMS-%s.txt" % V), "w", newline="\n") as f:
        f.write("\n".join(lines) + "\n")

    print("== DONE - artifacts in dist/ ==")
    for name in sorted(os.listdir(DIST)):
        p = os.path.join(DIST, name)
        if os.path.isfile(p):
            print("   %10d  %s" % (os.path.getsize(p), name))


def hashlib_file(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def find_makensis():
    """Locate makensis on Windows / Linux. Returns (path, extra_env)."""
    cand = shutil.which("makensis")
    if cand:
        return cand, None
    if sys.platform == "win32":
        for base in (os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                     os.environ.get("ProgramFiles", r"C:\Program Files")):
            p = os.path.join(base, "NSIS", "makensis.exe")
            if os.path.exists(p):
                return p, None
    else:
        p = os.path.expanduser("~/nsis-root/usr/bin/makensis")
        if os.path.exists(p):
            return p, {"NSISDIR": os.path.expanduser("~/nsis-root/usr/share/nsis"),
                       "LD_LIBRARY_PATH": os.path.expanduser(
                           "~/nsis-root/usr/lib/x86_64-linux-gnu")}
    return None, None


if __name__ == "__main__":
    main()
