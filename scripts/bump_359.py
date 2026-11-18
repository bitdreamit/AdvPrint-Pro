#!/usr/bin/env python3
# ============================================================
# AdvPrint Pro - version bump 3.5.8 -> 3.5.9 (exact counts,
# idempotent: running it twice changes nothing).
#
# v3.5.9 release theme: UNBREAKABLE DEB BUILD (SCANNER-PROOF
#   STAGING) - the first v3.5.8 build on the owner's PC died inside
#   the pure-Python DEB packer with FileNotFoundError on a freshly
#   staged opt/advprint/hub/console.html (the Windows on-access
#   scanner hid the just-copied file between the tar walk and the
#   open(); the second run always passed). The DEB cycle is now
#   defended in depth like the v3.5.5 makensis fix: visibility-retry
#   reads, a loud walk that never silently skips a hidden directory,
#   file-by-file verification of the staged tree BEFORE tarring,
#   an automatic re-stage + retry of the whole cycle, and the
#   Defender exclusion hint on final failure.
# ============================================================
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

OLD, NEW = "3.5.8", "3.5.9"

# the note currently inside VERSION_NAME (embedded by bump_358)
BRAND_NOTE_358 = (
    "NEW IN v3.5.8 - REAL WINDOW BUTTONS + BRAND + TAB MEMORY: the console "
    "title bar now reads AdvPrint Pro by Bit Dream IT - Innovative "
    "Healthcare Solutions (no version, no machine id, no theme labels "
    "anywhere in the title or the Dashboard subtitle), the title-bar "
    "minimize/maximize/close buttons REALLY work (minimize collapses the "
    "console to its title bar and restores on the second click, maximize "
    "toggles real fullscreen with an edge-to-edge in-page fallback plus "
    "double-click-on-titlebar support, close really closes the tab and "
    "says so honestly when the browser blocks it), every tab switch "
    "writes ?path=<tab> into the URL and remembers the last tab "
    "(localStorage) so a refresh or re-open lands on the SAME tab, and "
    "the uuid-looking machine id is gone from the Dashboard. Windows "
    "CMD/PowerShell keeps the v3.5.7 SILENT WINDOWS guarantee: "
    "CREATE_NO_WINDOW on every helper the hub launches, zero flicker. ")

BRAND_NOTE_359 = (
    "NEW IN v3.5.9 - UNBREAKABLE DEB BUILD (SCANNER-PROOF STAGING): the "
    "first v3.5.8 build on the owner's PC died inside the pure-Python DEB "
    "packer with FileNotFoundError on the freshly staged "
    "opt/advprint/hub/console.html - the Windows on-access scanner "
    "(Defender real-time protection) hid the just-copied file between the "
    "tar walk and the open(), the same failure class as the v3.5.5 "
    "makensis 'no files found' case, and the second run always passed. "
    "The DEB cycle is now defended in depth like makensis: every staged "
    "file is read through a short visibility retry (0.3s doubling "
    "backoff, six attempts), os.walk fails LOUDLY instead of silently "
    "skipping a hidden directory (a silent skip would quietly ship an "
    "INCOMPLETE .deb), the staged tree is verified file-by-file against "
    "the complete expected DEB layout before tarring, and anything still "
    "getting through forces an automatic re-stage + retry of the whole "
    "stage/tar cycle (up to three attempts) with the Defender exclusion "
    "hint printed if it ever still fails. Keeps the v3.5.8 REAL WINDOW "
    "BUTTONS + BRAND + TAB MEMORY console (brand-only title bar that "
    "really minimizes/maximizes/closes, ?path=<tab> URL memory, no "
    "machine id on the Dashboard) and the v3.5.7 SILENT WINDOWS "
    "guarantee: CREATE_NO_WINDOW on every helper the hub launches, zero "
    "flicker. ")

# (relative path, old, new, expected count, label)
EDITS = []


def edit(rel, old, new, count, label):
    EDITS.append((rel, old, new, count, label))


# ---- hub advprint.py twins (5 version spots each) ------------------
for twin in ("tool/unix/hub/advprint.py",
             "tool/windows/portable/hub/advprint.py"):
    edit(twin, 'VERSION = "3.5.8"', 'VERSION = "3.5.9"', 1, "VERSION")
    edit(twin,
         'VERSION_NAME = ("v3.5.8 (CRX SIGNATURE VERIFIED + LAN ADMIN CONSOLE',
         'VERSION_NAME = ("v3.5.9 (CRX SIGNATURE VERIFIED + LAN ADMIN CONSOLE',
         1, "VERSION_NAME head")
    edit(twin, BRAND_NOTE_358, BRAND_NOTE_359, 1, "VERSION_NAME brand note")
    edit(twin,
         '<div class="stat"><div class="d">hub</div><div class="v">v3.5.8</div>',
         '<div class="stat"><div class="d">hub</div><div class="v">v3.5.9</div>',
         1, "hub stat card")
    edit(twin, '(BOOT.version || "3.5.8")', '(BOOT.version || "3.5.9")', 3,
         "BOOT.version fallbacks")

# ---- console.html twins (2 version spots each; the title itself is
#      the version-agnostic brand since v3.5.8) -----------------------
for twin in ("tool/unix/hub/console.html",
             "tool/windows/portable/hub/console.html"):
    edit(twin,
         '<div class="stat"><div class="d">hub</div><div class="v">v3.5.8</div>',
         '<div class="stat"><div class="d">hub</div><div class="v">v3.5.9</div>',
         1, "hub stat card")
    edit(twin, '(BOOT.version || "3.5.8")', '(BOOT.version || "3.5.9")', 3,
         "BOOT.version fallbacks")

# ---- extension ------------------------------------------------------
edit("extension/manifest.json", '"version": "3.5.8"', '"version": "3.5.9"',
     1, "manifest version")
edit("extension/popup.html", "AdvPrint Pro v3.5.8", "AdvPrint Pro v3.5.9", 1,
     "popup comment")
edit("extension/popup.html", 'id="ver">v3.5.8<', 'id="ver">v3.5.9<', 1,
     "popup ver chip")
edit("extension/i18n.js", "AdvPrint Pro v3.5.8", "AdvPrint Pro v3.5.9", 1,
     "i18n header")
edit("extension/i18n.js", "Version 3.5.8 - AdvPrint Pro",
     "Version 3.5.9 - AdvPrint Pro", 1, "i18n EN brandLine")
edit("extension/i18n.js", "সংস্করণ 3.5.8 - AdvPrint Pro",
     "সংস্করণ 3.5.9 - AdvPrint Pro", 1, "i18n BN brandLine")
edit("extension/content/api.js", '_apVerFallback = "3.5.8"',
     '_apVerFallback = "3.5.9"', 1, "api.js fallback")
edit("extension/options.html", "Solutions · v3.5.8", "Solutions · v3.5.9", 1,
     "options ver")

# ---- installer ------------------------------------------------------
edit("installer/setup.nsi", "AdvPrint-Pro-Setup-3.5.8.exe /S",
     "AdvPrint-Pro-Setup-3.5.9.exe /S", 1, "silent comment")
edit("installer/setup.nsi", 'OutFile "../dist/AdvPrint-Pro-Setup-3.5.8.exe"',
     'OutFile "../dist/AdvPrint-Pro-Setup-3.5.9.exe"', 1, "OutFile")
edit("installer/setup.nsi", 'VIProductVersion "3.5.8.0"',
     'VIProductVersion "3.5.9.0"', 1, "VIProductVersion")
edit("installer/setup.nsi", 'VIAddVersionKey FileVersion "3.5.8.0"',
     'VIAddVersionKey FileVersion "3.5.9.0"', 1, "FileVersion")
edit("installer/setup.nsi", 'VIAddVersionKey ProductVersion "3.5.8.0"',
     'VIAddVersionKey ProductVersion "3.5.9.0"', 1, "ProductVersion")
edit("installer/setup.nsi", "AdvPrint-Pro-Setup-3.5.8.exe (the file may be",
     "AdvPrint-Pro-Setup-3.5.9.exe (the file may be", 1, "re-download msg")
edit("installer/setup.nsi", '"DisplayVersion" "3.5.8"',
     '"DisplayVersion" "3.5.9"', 1, "DisplayVersion")
edit("installer/deb/DEBIAN/control", "Version: 3.5.8", "Version: 3.5.9", 1,
     "deb control")

# ---- VERSION.txt ----------------------------------------------------
edit("VERSION.txt",
     "AdvPrint Pro (Advanced Printer) 3.5.8 - built 2026-11-18",
     "AdvPrint Pro (Advanced Printer) 3.5.9 - built 2026-11-18", 1,
     "VERSION.txt")

# ---- START-HERE.txt header + note heading (body edited by hand) -----
edit("START-HERE.txt",
     "AdvPrint Pro (Advanced Printer) v3.5.8 - START HERE",
     "AdvPrint Pro (Advanced Printer) v3.5.9 - START HERE", 1,
     "START-HERE header")
edit("START-HERE.txt",
     "QUICK NOTE ON v3.5.8 - REAL WINDOW BUTTONS + BRAND + TAB MEMORY",
     "QUICK NOTE ON v3.5.9 - UNBREAKABLE DEB BUILD (SCANNER-PROOF STAGING)",
     1, "START-HERE note heading")

# ---- tests (V follows the current release - established pattern) ----
edit("tests/test_hub_v2.py", 'advprint.VERSION == "3.5.8"',
     'advprint.VERSION == "3.5.9"', 1, "test_hub_v2 VERSION")
edit("tests/test_v352.py", 'V = "3.5.8"', 'V = "3.5.9"', 1, "test_v352 V")
edit("tests/test_v352.py", 'assert "v3.5.8" in emb', 'assert "v3.5.9" in emb',
     1, "test_v352 embedded version")
edit("tests/test_v353.py", 'V = "3.5.8"', 'V = "3.5.9"', 1, "test_v353 V")
edit("tests/test_v354.py", 'V = "3.5.8"', 'V = "3.5.9"', 1, "test_v354 V")
edit("tests/test_v355.py", 'V = "3.5.8"', 'V = "3.5.9"', 1, "test_v355 V")
edit("tests/test_v355.py", "payload version 3.5.8", "payload version 3.5.9",
     1, "test_v355 docstring payload")
edit("tests/test_v355.py", "version coherence 3.5.8", "version coherence 3.5.9",
     2, "test_v355 coherence mentions")
edit("tests/test_v356.py", 'V = "3.5.8"', 'V = "3.5.9"', 1, "test_v356 V")
edit("tests/test_v356.py",
     '"v3.5.8 (CRX SIGNATURE VERIFIED + LAN ADMIN CONSOLE"',
     '"v3.5.9 (CRX SIGNATURE VERIFIED + LAN ADMIN CONSOLE"',
     1, "test_v356 VERSION_NAME head")
edit("tests/test_v356.py", "version coherence 3.5.8",
     "version coherence 3.5.9", 2, "test_v356 coherence mentions")
edit("tests/test_v357.py", 'V = "3.5.8"', 'V = "3.5.9"', 1, "test_v357 V")
edit("tests/test_v357.py",
     '"v3.5.8 (CRX SIGNATURE VERIFIED + LAN ADMIN CONSOLE"',
     '"v3.5.9 (CRX SIGNATURE VERIFIED + LAN ADMIN CONSOLE"',
     1, "test_v357 VERSION_NAME head")
edit("tests/test_v357.py", "version coherence 3.5.8",
     "version coherence 3.5.9", 2, "test_v357 coherence mentions")
edit("tests/test_v357.py", "QUICK NOTE ON v3.5.8",
     "QUICK NOTE ON v3.5.9", 1, "test_v357 START-HERE note pin")
edit("tests/test_v358.py", 'V = "3.5.8"', 'V = "3.5.9"', 1, "test_v358 V")
edit("tests/test_v358.py",
     '"v3.5.8 (CRX SIGNATURE VERIFIED + LAN ADMIN CONSOLE"',
     '"v3.5.9 (CRX SIGNATURE VERIFIED + LAN ADMIN CONSOLE"',
     1, "test_v358 VERSION_NAME head")
edit("tests/test_v358.py", "version coherence 3.5.8",
     "version coherence 3.5.9", 2, "test_v358 coherence mentions")
edit("tests/test_v358.py", "QUICK NOTE ON v3.5.8",
     "QUICK NOTE ON v3.5.9", 1, "test_v358 START-HERE note pin")

# ---- build kit docs (version references only; historical notes stay) --
edit("README-BUILDKIT.txt", "Windows Build Kit (v3.5.8 - now part of the tree)",
     "Windows Build Kit (v3.5.9 - now part of the tree)", 1, "kit title")
edit("README-BUILDKIT.txt", "dist\\AdvPrint-Pro.crx 3.5.8",
     "dist\\AdvPrint-Pro.crx 3.5.9", 1, "kit verify cmd")
edit("README-BUILDKIT.txt", "the full v3.5.8 source",
     "the full v3.5.9 source", 1, "kit restore hint")
edit("docs/BUILD-WINDOWS.md", "step by step (v3.5.8)",
     "step by step (v3.5.9)", 1, "guide title")
edit("docs/BUILD-WINDOWS.md", "(currently 3.5.8)", "(currently 3.5.9)", 1,
     "guide version line")
edit("docs/BUILD-WINDOWS.md", "git checkout v3.5.8", "git checkout v3.5.9", 1,
     "guide checkout")
edit("docs/BUILD-WINDOWS.md", "(`AdvPrint-Pro-3.5.8-src.zip` or",
     "(`AdvPrint-Pro-3.5.9-src.zip` or", 1, "guide zip name")
edit("docs/BUILD-WINDOWS.md", "AdvPrint-Pro-Extension-3.5.8.zip",
     "AdvPrint-Pro-Extension-3.5.9.zip", 1, "guide ext name")
edit("docs/BUILD-WINDOWS.md", "AdvPrint-Pro-Setup-3.5.8.exe",
     "AdvPrint-Pro-Setup-3.5.9.exe", 1, "guide exe name")
edit("docs/BUILD-WINDOWS.md", "advprint-pro_3.5.8_all.deb",
     "advprint-pro_3.5.9_all.deb", 1, "guide deb name")
edit("docs/BUILD-WINDOWS.md", "SHA256SUMS-3.5.8.txt",
     "SHA256SUMS-3.5.9.txt", 2, "guide sums name")
edit("docs/BUILD-WINDOWS.md", "dist\\AdvPrint-Pro.crx 3.5.8",
     "dist\\AdvPrint-Pro.crx 3.5.9", 1, "guide verify cmd")
edit("docs/BUILD-FROM-SOURCE.md", "no prebuilt binaries (v3.5.8)",
     "no prebuilt binaries (v3.5.9)", 1, "from-source title")


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
          ("BUMP 3.5.8 -> 3.5.9", total, changed, skipped))
    return 0 if skipped == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
