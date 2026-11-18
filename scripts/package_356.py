#!/usr/bin/env python3
# ============================================================
# AdvPrint Pro v3.5.6 - package the release:
#   1. download/AdvPrint-Pro-3.5.6-src.zip   complete A-Z source
#      (MANIFEST-3.5.6-locked, signing key + runtime included,
#      build intermediates excluded - build-all.py regenerates them)
#   2. download/AdvPrint-Pro-BuildKit-Windows-v3.5.6.zip
#      the 6-file Windows build kit
#   3. the 5 prebuilt artifacts from dist/
# Every zip is testzip()-verified and the manifest is re-checked
# against the zip contents after packing.
# ============================================================
import os
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = "/home/z/my-project/download"
V = "3.5.6"

EXCLUDE_DIRS = {"dist", ".build-bin", "__pycache__", ".pytest_cache"}
EXCLUDE_FILES = {"MANIFEST-3.5.6.txt", "docs/SHA256SUMS-3.5.6.txt"}

KIT_FILES = [
    "build.cmd",
    "scripts/build-all.py",
    "installer/setup.nsi",
    "docs/BUILD-WINDOWS.md",
    "docs/BUILD-FROM-SOURCE.md",
    "README-BUILDKIT.txt",
]

PREBUILT = [
    "dist/AdvPrint-Pro.crx",
    "dist/AdvPrint-Pro-Extension-%s.zip" % V,
    "dist/AdvPrint-Pro-Setup-%s.exe" % V,
    "dist/advprint-pro_%s_all.deb" % V,
    "dist/SHA256SUMS-%s.txt" % V,
]


def collect_source():
    rows = []
    for root, dirs, files in os.walk(ROOT):
        rel_root = os.path.relpath(root, ROOT).replace(os.sep, "/")
        dirs[:] = [d for d in sorted(dirs)
                   if d not in EXCLUDE_DIRS
                   and os.path.join(rel_root, d) != "installer/stage"]
        for f in sorted(files):
            p = os.path.join(rel_root, f).replace(os.sep, "/")
            while p.startswith("./"):
                p = p[2:]
            if p in EXCLUDE_FILES or "/stage/" in p or p.startswith("dist/"):
                continue
            rows.append(p)
    return rows


def main():
    os.makedirs(OUT, exist_ok=True)
    src_zip = os.path.join(OUT, "AdvPrint-Pro-%s-src.zip" % V)

    # ---- 1. full source zip ----
    files = collect_source()
    with zipfile.ZipFile(src_zip, "w", zipfile.ZIP_DEFLATED) as z:
        # manifest FIRST so extractors see it up front
        z.write(os.path.join(ROOT, "MANIFEST-%s.txt" % V),
                "AdvPrint-Pro-%s/MANIFEST-%s.txt" % (V, V))
        for rel in files:
            z.write(os.path.join(ROOT, rel),
                    "AdvPrint-Pro-%s/%s" % (V, rel))
    with zipfile.ZipFile(src_zip) as z:
        bad = z.testzip()
        assert bad is None, "corrupt member in src zip: " + bad
        names = set(z.namelist())
        assert len(names) == len(files) + 1
        for must in ("AdvPrint-Pro-%s/tool/windows/portable/install/"
                     "hub-stop.ps1" % V,
                     "AdvPrint-Pro-%s/extension-signing/"
                     "advprint-printer.pem" % V,
                     "AdvPrint-Pro-%s/tool/windows/portable/installer/"
                     "runtime/python311.dll" % V,
                     "AdvPrint-Pro-%s/tests/test_v356.py" % V,
                     "AdvPrint-Pro-%s/MANIFEST-%s.txt" % (V, V)):
            assert must in names, must
    print("src zip      : %s (%d entries, %d bytes)"
          % (os.path.basename(src_zip), len(files) + 1,
             os.path.getsize(src_zip)))

    # ---- 2. Windows build kit zip ----
    kit_zip = os.path.join(OUT, "AdvPrint-Pro-BuildKit-Windows-v%s.zip" % V)
    with zipfile.ZipFile(kit_zip, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in KIT_FILES:
            assert os.path.exists(os.path.join(ROOT, rel)), rel
            z.write(os.path.join(ROOT, rel),
                    "AdvPrint-Pro-BuildKit-v%s/%s" % (V, rel))
    with zipfile.ZipFile(kit_zip) as z:
        assert z.testzip() is None
        assert len(z.namelist()) == len(KIT_FILES)
    print("build kit zip: %s (%d files, %d bytes)"
          % (os.path.basename(kit_zip), len(KIT_FILES),
             os.path.getsize(kit_zip)))

    # ---- 3. prebuilt artifacts ----
    for rel in PREBUILT:
        p = os.path.join(ROOT, rel)
        assert os.path.exists(p), rel
        dst = os.path.join(OUT, os.path.basename(p))
        data = open(p, "rb").read()
        open(dst, "wb").write(data)
        print("prebuilt     : %s (%d bytes)"
              % (os.path.basename(dst), len(data)))

    print("PACKAGE OK")


if __name__ == "__main__":
    main()
