#!/usr/bin/env python3
# ============================================================
# AdvPrint Pro v3.5.9 - package the release:
#   0. MANIFEST-3.5.9.txt  generated from the actual tree
#   1. download/AdvPrint-Pro-3.5.9-src.zip   complete A-Z source
#      (MANIFEST-3.5.9-locked, signing key + runtime included,
#      build intermediates excluded - build-all.py regenerates them)
#   2. download/AdvPrint-Pro-BuildKit-Windows-v3.5.9.zip
#      the 6-file Windows build kit (with the v3.5.9 hardened
#      build-all.py - the DEB stage is now scanner-proof)
#   3. the 5 prebuilt artifacts from dist/
# Every zip is testzip()-verified and the manifest is re-checked
# against the zip contents after packing.
# ============================================================
import fnmatch
import os
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = "/home/z/my-project/download"
V = "3.5.9"

EXCLUDE_DIRS = {"dist", ".build-bin", "__pycache__", ".pytest_cache"}
# any stale manifest / checksum files from older releases are
# excluded; the fresh MANIFEST-<V>.txt is added to the zip explicitly
EXCLUDE_PATTERNS = ["MANIFEST-*.txt", "docs/SHA256SUMS-*.txt"]

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


def _excluded(p):
    return any(fnmatch.fnmatch(p, pat) for pat in EXCLUDE_PATTERNS)


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
            if p.startswith("dist/") or "/stage/" in p or _excluded(p):
                continue
            rows.append(p)
    return rows


def write_manifest(files):
    total = sum(os.path.getsize(os.path.join(ROOT, p)) for p in files)
    lines = [
        "AdvPrint Pro (Advanced Printer) v%s - COMPLETE SOURCE MANIFEST" % V,
        "by Bit Dream IT - Innovative Healthcare Solutions",
        "",
        "This file lists EVERY file in the v%s source tree (the manifest" % V,
        "file itself ships in the zip on top of this count). After extracting",
        "the source zip you can compare: the number of files and the total",
        "size must match. If anything on this list is missing from your local",
        "tree, the build will tell you its exact name - re-extract the full",
        "source zip. (Build intermediates - dist/, installer/stage/, caches -",
        "are excluded: build-all.py regenerates them.)",
        "",
        "Files: %d   Total bytes: %d" % (len(files), total),
        "",
    ]
    for p in files:
        lines.append("%10d %s" % (os.path.getsize(os.path.join(ROOT, p)), p))
    open(os.path.join(ROOT, "MANIFEST-%s.txt" % V), "w",
         encoding="utf-8", newline="\n").write("\n".join(lines) + "\n")
    return len(files), total


def main():
    os.makedirs(OUT, exist_ok=True)

    # ---- 0. manifest ----
    files = collect_source()
    n, total = write_manifest(files)
    print("manifest     : MANIFEST-%s.txt (%d files, %d bytes)" % (V, n, total))

    # ---- 1. full source zip ----
    src_zip = os.path.join(OUT, "AdvPrint-Pro-%s-src.zip" % V)
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
                     "AdvPrint-Pro-%s/tests/test_v359.py" % V,
                     "AdvPrint-Pro-%s/scripts/smoke_v359.py" % V,
                     "AdvPrint-Pro-%s/scripts/bump_359.py" % V,
                     "AdvPrint-Pro-%s/docs/RELEASE-NOTES-v3.5.9.md" % V,
                     "AdvPrint-Pro-%s/MANIFEST-%s.txt" % (V, V)):
            assert must in names, must
        # the hardened build-all must be the v3.5.9 one
        ba = z.read("AdvPrint-Pro-%s/scripts/build-all.py" % V).decode()
        assert "build_deb_scannerproof" in ba
        assert "_read_visible" in ba
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
        ba = z.read("AdvPrint-Pro-BuildKit-v%s/scripts/build-all.py"
                    % V).decode()
        assert "build_deb_scannerproof" in ba
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
