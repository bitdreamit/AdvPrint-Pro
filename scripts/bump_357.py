#!/usr/bin/env python3
# ============================================================
# AdvPrint Pro - version bump 3.5.6 -> 3.5.7 (exact counts,
# idempotent: running it twice changes nothing).
#
# v3.5.7 release theme: SILENT WINDOWS (no CMD window flashes)
#   - the hub runs windowless on Windows (pythonw / AdvPrintPro.exe),
#     but several helper launches lacked creationflags=CREATE_NO_WINDOW,
#     so each reg.exe policy query/write/delete, the elevated service
#     PowerShell and the CUPS lp fallback popped their own flashing
#     CMD window - most visibly on the first run and on every console
#     poll of the policy status (5 browsers x 2 hives = 10 flashes).
#   - every hub/tool child process now launches with HIDE
#     (CREATE_NO_WINDOW on Windows, 0 elsewhere); UAC prompts still
#     appear because elevation must be approved.
# ============================================================
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

OLD, NEW = "3.5.6", "3.5.7"

SILENT_NOTE_357 = (
    "NEW IN v3.5.7 - SILENT WINDOWS: every helper process the hub starts "
    "on Windows (reg.exe policy queries/writes/removes, the elevated "
    "PowerShell passes, CUPS lp) now launches with CREATE_NO_WINDOW - no "
    "more CMD windows flashing on screen on first run or whenever the "
    "console polls the policy status; UAC prompts still appear because "
    "elevation must be approved, nothing else does. ")

# (relative path, old, new, expected count, label)
EDITS = []


def edit(rel, old, new, count, label):
    EDITS.append((rel, old, new, count, label))


# ---- hub advprint.py twins (8 version spots each) ------------------
for twin in ("tool/unix/hub/advprint.py",
             "tool/windows/portable/hub/advprint.py"):
    edit(twin, 'VERSION = "3.5.6"', 'VERSION = "3.5.7"', 1, "VERSION")
    edit(twin,
         'VERSION_NAME = ("v3.5.6 (CRX SIGNATURE VERIFIED + LAN ADMIN CONSOLE',
         'VERSION_NAME = ("v3.5.7 (CRX SIGNATURE VERIFIED + LAN ADMIN CONSOLE',
         1, "VERSION_NAME head")
    edit(twin,
         "only the displayed URI changed. Keeps the full v3.5.5 build kit:",
         "only the displayed URI changed. %sKeeps the full v3.5.5 build kit:"
         % SILENT_NOTE_357, 1, "VERSION_NAME silent note")
    edit(twin, "ALL-IN-ONE Console v3.5.6", "ALL-IN-ONE Console v3.5.7", 1,
         "console title")
    edit(twin, '<div class="v">v3.5.6</div>', '<div class="v">v3.5.7</div>',
         1, "hub stat card")
    edit(twin, '(BOOT.version || "3.5.6")', '(BOOT.version || "3.5.7")', 3,
         "BOOT.version fallbacks")

# ---- console.html twins (5 version spots each) ---------------------
for twin in ("tool/unix/hub/console.html",
             "tool/windows/portable/hub/console.html"):
    edit(twin, "ALL-IN-ONE Console v3.5.6", "ALL-IN-ONE Console v3.5.7", 1,
         "title")
    edit(twin, '<div class="v">v3.5.6</div>', '<div class="v">v3.5.7</div>',
         1, "hub stat card")
    edit(twin, '(BOOT.version || "3.5.6")', '(BOOT.version || "3.5.7")', 3,
         "BOOT.version fallbacks")

# ---- extension ------------------------------------------------------
edit("extension/manifest.json", '"version": "3.5.6"', '"version": "3.5.7"',
     1, "manifest version")
edit("extension/popup.html", "AdvPrint Pro v3.5.6", "AdvPrint Pro v3.5.7", 1,
     "popup comment")
edit("extension/popup.html", 'id="ver">v3.5.6<', 'id="ver">v3.5.7<', 1,
     "popup ver chip")
edit("extension/i18n.js", "AdvPrint Pro v3.5.6", "AdvPrint Pro v3.5.7", 1,
     "i18n header")
edit("extension/i18n.js", "Version 3.5.6 - AdvPrint Pro",
     "Version 3.5.7 - AdvPrint Pro", 1, "i18n EN brandLine")
edit("extension/i18n.js", "সংস্করণ 3.5.6 - AdvPrint Pro",
     "সংস্করণ 3.5.7 - AdvPrint Pro", 1, "i18n BN brandLine")
edit("extension/content/api.js", '_apVerFallback = "3.5.6"',
     '_apVerFallback = "3.5.7"', 1, "api.js fallback")
edit("extension/options.html", "Solutions · v3.5.6", "Solutions · v3.5.7", 1,
     "options ver")

# ---- installer ------------------------------------------------------
edit("installer/setup.nsi", "AdvPrint-Pro-Setup-3.5.6.exe /S",
     "AdvPrint-Pro-Setup-3.5.7.exe /S", 1, "silent comment")
edit("installer/setup.nsi", 'OutFile "../dist/AdvPrint-Pro-Setup-3.5.6.exe"',
     'OutFile "../dist/AdvPrint-Pro-Setup-3.5.7.exe"', 1, "OutFile")
edit("installer/setup.nsi", 'VIProductVersion "3.5.6.0"',
     'VIProductVersion "3.5.7.0"', 1, "VIProductVersion")
edit("installer/setup.nsi", 'VIAddVersionKey FileVersion "3.5.6.0"',
     'VIAddVersionKey FileVersion "3.5.7.0"', 1, "FileVersion")
edit("installer/setup.nsi", 'VIAddVersionKey ProductVersion "3.5.6.0"',
     'VIAddVersionKey ProductVersion "3.5.7.0"', 1, "ProductVersion")
edit("installer/setup.nsi", "AdvPrint-Pro-Setup-3.5.6.exe (the file may be",
     "AdvPrint-Pro-Setup-3.5.7.exe (the file may be", 1, "re-download msg")
edit("installer/setup.nsi", '"DisplayVersion" "3.5.6"',
     '"DisplayVersion" "3.5.7"', 1, "DisplayVersion")
edit("installer/deb/DEBIAN/control", "Version: 3.5.6", "Version: 3.5.7", 1,
     "deb control")

# ---- VERSION.txt ----------------------------------------------------
edit("VERSION.txt",
     "AdvPrint Pro (Advanced Printer) 3.5.6 - built 2026-11-18",
     "AdvPrint Pro (Advanced Printer) 3.5.7 - built 2026-11-18", 1,
     "VERSION.txt")

# ---- tests (V follows the current release - established pattern) ----
edit("tests/test_hub_v2.py", 'advprint.VERSION == "3.5.6"',
     'advprint.VERSION == "3.5.7"', 1, "test_hub_v2 VERSION")
edit("tests/test_v352.py", 'V = "3.5.6"', 'V = "3.5.7"', 1, "test_v352 V")
edit("tests/test_v352.py", 'assert "v3.5.6" in emb', 'assert "v3.5.7" in emb',
     1, "test_v352 embedded title")
edit("tests/test_v353.py", 'V = "3.5.6"', 'V = "3.5.7"', 1, "test_v353 V")
edit("tests/test_v354.py", 'V = "3.5.6"', 'V = "3.5.7"', 1, "test_v354 V")
edit("tests/test_v355.py", 'V = "3.5.6"', 'V = "3.5.7"', 1, "test_v355 V")
edit("tests/test_v355.py", "payload version 3.5.6", "payload version 3.5.7",
     1, "test_v355 docstring payload")
edit("tests/test_v355.py", "version coherence 3.5.6", "version coherence 3.5.7",
     2, "test_v355 coherence mentions")
edit("tests/test_v356.py", 'V = "3.5.6"', 'V = "3.5.7"', 1, "test_v356 V")
edit("tests/test_v356.py",
     '"v3.5.6 (CRX SIGNATURE VERIFIED + LAN ADMIN CONSOLE"',
     '"v3.5.7 (CRX SIGNATURE VERIFIED + LAN ADMIN CONSOLE"',
     1, "test_v356 VERSION_NAME head")
edit("tests/test_v356.py", "version coherence 3.5.6",
     "version coherence 3.5.7", 2, "test_v356 coherence mentions")

# ---- build kit docs (version references only; historical notes stay) --
edit("README-BUILDKIT.txt", "Windows Build Kit (v3.5.6 - now part of the tree)",
     "Windows Build Kit (v3.5.7 - now part of the tree)", 1, "kit title")
edit("README-BUILDKIT.txt", "dist\\AdvPrint-Pro.crx 3.5.6",
     "dist\\AdvPrint-Pro.crx 3.5.7", 1, "kit verify cmd")
edit("README-BUILDKIT.txt", "the full v3.5.6 source",
     "the full v3.5.7 source", 1, "kit restore hint")
edit("docs/BUILD-WINDOWS.md", "step by step (v3.5.6)",
     "step by step (v3.5.7)", 1, "guide title")
edit("docs/BUILD-WINDOWS.md", "(currently 3.5.6)", "(currently 3.5.7)", 1,
     "guide version line")
edit("docs/BUILD-WINDOWS.md", "git checkout v3.5.6", "git checkout v3.5.7", 1,
     "guide checkout")
edit("docs/BUILD-WINDOWS.md", "(`AdvPrint-Pro-3.5.6-src.zip` or",
     "(`AdvPrint-Pro-3.5.7-src.zip` or", 1, "guide zip name")
edit("docs/BUILD-WINDOWS.md", "AdvPrint-Pro-Extension-3.5.6.zip",
     "AdvPrint-Pro-Extension-3.5.7.zip", 1, "guide ext name")
edit("docs/BUILD-WINDOWS.md", "AdvPrint-Pro-Setup-3.5.6.exe",
     "AdvPrint-Pro-Setup-3.5.7.exe", 1, "guide exe name")
edit("docs/BUILD-WINDOWS.md", "advprint-pro_3.5.6_all.deb",
     "advprint-pro_3.5.7_all.deb", 1, "guide deb name")
edit("docs/BUILD-WINDOWS.md", "SHA256SUMS-3.5.6.txt",
     "SHA256SUMS-3.5.7.txt", 2, "guide sums name")
edit("docs/BUILD-WINDOWS.md", "dist\\AdvPrint-Pro.crx 3.5.6",
     "dist\\AdvPrint-Pro.crx 3.5.7", 1, "guide verify cmd")
edit("docs/BUILD-FROM-SOURCE.md", "no prebuilt binaries (v3.5.6)",
     "no prebuilt binaries (v3.5.7)", 1, "from-source title")


def main():
    total = changed = skipped = 0
    for rel, old, new, count, label in EDITS:
        if not old:
            continue
        total += 1
        p = os.path.join(ROOT, rel)
        if not os.path.exists(p):
            print("!! MISSING  %-46s (%s)" % (rel, label))
            skipped += 1
            continue
        s = open(p, encoding="utf-8").read()
        n = s.count(old)
        if n == 0 and s.count(new) >= count:
            print("   ok(idem) %-42s (%s)" % (rel, label))
            continue
        if n != count:
            print("!! COUNT    %-46s (%s): expected %d, found %d"
                  % (rel, label, count, n))
            skipped += 1
            continue
        open(p, "w", encoding="utf-8", newline="").write(s.replace(old, new))
        print("   bumped   %-42s (%s) x%d" % (rel, label, count))
        changed += 1
    print("\n%s: %d edits, %d applied, %d skipped" %
          ("BUMP 3.5.6 -> 3.5.7", total, changed, skipped))
    return 0 if skipped == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
