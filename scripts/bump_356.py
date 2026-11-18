#!/usr/bin/env python3
# ============================================================
# AdvPrint Pro - version bump 3.5.5 -> 3.5.6 (exact counts,
# idempotent: running it twice changes nothing).
#
# v3.5.6 release theme: LAN ADMIN CONSOLE + IPP:// PRINTER URLS
#   - THE ONE UI console can be driven from any device on the
#     same network (ui_admin_mode=lan, factory default) plus an
#     extra admin_ips allow-list from any network;
#   - every printer URL shown for OS/Android manual add now
#     displays the ipp:// scheme (Android's manual-add box
#     refuses http:// - its Save button stays disabled).
# ============================================================
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

OLD, NEW = "3.5.5", "3.5.6"
OLD_DATE, NEW_DATE = "2026-11-16", "2026-11-18"

VERSION_NAME_356 = (
    "v3.5.6 (LAN ADMIN CONSOLE + IPP:// PRINTER URLS - THE ONE UI can now be "
    "driven from any PC or phone on the SAME NETWORK as the hub "
    "(ui_admin_mode=lan, the factory default), with an extra admin_ips "
    "allow-list for admin devices on any other network and a self/any mode "
    "switch, while the print surface keeps exactly the v3.2.3 Allowed-IPs "
    "rules; every printer URL the hub shows for OS/Android manual add now "
    "DISPLAYS the ipp:// scheme Android's manual-add screen actually accepts "
    "(an http:// URL disables its Save button - the hub still SPEAKS plain "
    "HTTP/IPP underneath, only the displayed URI changed). Keeps the full "
    "v3.5.5 build kit: build.cmd / scripts/build-all.py packs the CRX with "
    "the stable key, syncs + Chrome-verifies every embedded copy, builds the "
    "extension zip, a WSL-free pure-Python DEB and the NSIS Setup EXE, and "
    "hard-fails on any missing source file, any drifted unix/windows twin "
    "copy or any setup.nsi File reference that does not resolve.")

VERSION_NAME_355 = (
    "v3.5.5 (CRX SIGNATURE VERIFIED + FULL-SOURCE WINDOWS BUILD KIT - the "
    "tree is complete and buildable on Windows with one command: build.cmd / "
    "scripts/build-all.py packs the CRX with the stable key, syncs + "
    "Chrome-verifies every embedded copy, builds the extension zip, a "
    "WSL-free pure-Python DEB and the NSIS Setup EXE, and hard-fails on any "
    "missing source file, any drifted unix/windows twin copy or any "
    "setup.nsi File reference that does not resolve. Everything else is "
    "exactly the working v3.5.4 build: the always-visible status bar, real "
    "success rate, save-password fix, date+time history, per-row VIEW file "
    "button, server-side date filter, live dashboard cards, the ProTheme "
    "engine (8 themes + density / corners / frame) and the single port for "
    "every queue.")

# (relative path, old, new, expected count, label)
EDITS = []


def edit(rel, old, new, count, label):
    EDITS.append((rel, old, new, count, label))


# ---- hub advprint.py twins (7 version spots each) ------------------
NAME_OLD = 'VERSION_NAME = ("v3.5.5 (CRX SIGNATURE VERIFIED'
for twin in ("tool/unix/hub/advprint.py",
             "tool/windows/portable/hub/advprint.py"):
    edit(twin, 'VERSION = "3.5.5"', 'VERSION = "3.5.6"', 1, "VERSION")
    edit(twin, 'v3.5.5 (CRX SIGNATURE VERIFIED + FULL-SOURCE WINDOWS BUILD KIT',
         'v3.5.6 (LAN ADMIN CONSOLE + IPP:// PRINTER URLS', 1,
         "VERSION_NAME head")
    edit(twin, "ALL-IN-ONE Console v3.5.5", "ALL-IN-ONE Console v3.5.6", 1,
         "console title")
    edit(twin, '<div class="v">v3.5.5</div>', '<div class="v">v3.5.6</div>',
         1, "hub stat card")
    edit(twin, '(BOOT.version || "3.5.5")', '(BOOT.version || "3.5.6")', 3,
         "BOOT.version fallbacks")

# ---- console.html twins (5 version spots each) ---------------------
for twin in ("tool/unix/hub/console.html",
             "tool/windows/portable/hub/console.html"):
    edit(twin, "ALL-IN-ONE Console v3.5.5", "ALL-IN-ONE Console v3.5.6", 1,
         "title")
    edit(twin, '<div class="v">v3.5.5</div>', '<div class="v">v3.5.6</div>',
         1, "hub stat card")
    edit(twin, '(BOOT.version || "3.5.5")', '(BOOT.version || "3.5.6")', 3,
         "BOOT.version fallbacks")

# ---- extension ------------------------------------------------------
edit("extension/manifest.json", '"version": "3.5.5"', '"version": "3.5.6"',
     1, "manifest version")
edit("extension/popup.html", "AdvPrint Pro v3.5.5", "AdvPrint Pro v3.5.6", 1,
     "popup comment")
edit("extension/popup.html", 'id="ver">v3.5.5<', 'id="ver">v3.5.6<', 1,
     "popup ver chip")
edit("extension/i18n.js", "AdvPrint Pro v3.5.5", "AdvPrint Pro v3.5.6", 1,
     "i18n header")
edit("extension/i18n.js", "Version 3.5.5 - AdvPrint Pro",
     "Version 3.5.6 - AdvPrint Pro", 1, "i18n EN brandLine")
edit("extension/i18n.js, ", "", "", 0, "noop") if False else None
edit("extension/i18n.js", "সংস্করণ 3.5.5 - AdvPrint Pro",
     "সংস্করণ 3.5.6 - AdvPrint Pro", 1, "i18n BN brandLine")
edit("extension/content/api.js", '_apVerFallback = "3.5.5"',
     '_apVerFallback = "3.5.6"', 1, "api.js fallback")
edit("extension/options.html", "Solutions · v3.5.5", "Solutions · v3.5.6", 1,
     "options ver")

# ---- installer ------------------------------------------------------
edit("installer/setup.nsi", "AdvPrint-Pro-Setup-3.5.5.exe /S",
     "AdvPrint-Pro-Setup-3.5.6.exe /S", 1, "silent comment")
edit("installer/setup.nsi", 'OutFile "../dist/AdvPrint-Pro-Setup-3.5.5.exe"',
     'OutFile "../dist/AdvPrint-Pro-Setup-3.5.6.exe"', 1, "OutFile")
edit("installer/setup.nsi", 'VIProductVersion "3.5.5.0"',
     'VIProductVersion "3.5.6.0"', 1, "VIProductVersion")
edit("installer/setup.nsi", 'VIAddVersionKey FileVersion "3.5.5.0"',
     'VIAddVersionKey FileVersion "3.5.6.0"', 1, "FileVersion")
edit("installer/setup.nsi", 'VIAddVersionKey ProductVersion "3.5.5.0"',
     'VIAddVersionKey ProductVersion "3.5.6.0"', 1, "ProductVersion")
edit("installer/setup.nsi", "AdvPrint-Pro-Setup-3.5.5.exe (the file may be",
     "AdvPrint-Pro-Setup-3.5.6.exe (the file may be", 1, "re-download msg")
edit("installer/setup.nsi", '"DisplayVersion" "3.5.5"',
     '"DisplayVersion" "3.5.6"', 1, "DisplayVersion")
edit("installer/deb/DEBIAN/control", "Version: 3.5.5", "Version: 3.5.6", 1,
     "deb control")

# ---- VERSION.txt ----------------------------------------------------
edit("VERSION.txt",
     "AdvPrint Pro (Advanced Printer) 3.5.5 - built 2026-11-16",
     "AdvPrint Pro (Advanced Printer) 3.5.6 - built 2026-11-18", 1,
     "VERSION.txt")

# ---- tests (V follows the current release - established pattern) ----
edit("tests/test_hub_v2.py", 'advprint.VERSION == "3.5.5"',
     'advprint.VERSION == "3.5.6"', 1, "test_hub_v2 VERSION")
edit("tests/test_v352.py", 'V = "3.5.5"', 'V = "3.5.6"', 1, "test_v352 V")
edit("tests/test_v352.py", 'assert "v3.5.5" in emb', 'assert "v3.5.6" in emb',
     1, "test_v352 embedded title")
edit("tests/test_v353.py", 'V = "3.5.5"', 'V = "3.5.6"', 1, "test_v353 V")
edit("tests/test_v354.py", 'V = "3.5.5"', 'V = "3.5.6"', 1, "test_v354 V")
edit("tests/test_v355.py", 'V = "3.5.5"', 'V = "3.5.6"', 1, "test_v355 V")
edit("tests/test_v355.py", "payload version 3.5.5", "payload version 3.5.6",
     1, "test_v355 docstring payload")
edit("tests/test_v355.py", "version coherence 3.5.5", "version coherence 3.5.6",
     2, "test_v355 coherence mentions")

# ---- build kit docs (version references only; historical notes stay) --
edit("README-BUILDKIT.txt", "Windows Build Kit (v3.5.5 - now part of the tree)",
     "Windows Build Kit (v3.5.6 - now part of the tree)", 1, "kit title")
edit("README-BUILDKIT.txt", "dist\\AdvPrint-Pro.crx 3.5.5",
     "dist\\AdvPrint-Pro.crx 3.5.6", 1, "kit verify cmd")
edit("README-BUILDKIT.txt", "the full v3.5.5 source",
     "the full v3.5.6 source", 1, "kit restore hint")
edit("docs/BUILD-WINDOWS.md", "step by step (v3.5.5)",
     "step by step (v3.5.6)", 1, "guide title")
edit("docs/BUILD-WINDOWS.md", "(currently 3.5.5)", "(currently 3.5.6)", 1,
     "guide version line")
edit("docs/BUILD-WINDOWS.md", "git checkout v3.5.5", "git checkout v3.5.6", 1,
     "guide checkout")
edit("docs/BUILD-WINDOWS.md", "(`AdvPrint-Pro-3.5.5-src.zip` or",
     "(`AdvPrint-Pro-3.5.6-src.zip` or", 1, "guide zip name")
edit("docs/BUILD-WINDOWS.md", "AdvPrint-Pro-Extension-3.5.5.zip",
     "AdvPrint-Pro-Extension-3.5.6.zip", 1, "guide ext name")
edit("docs/BUILD-WINDOWS.md", "AdvPrint-Pro-Setup-3.5.5.exe",
     "AdvPrint-Pro-Setup-3.5.6.exe", 1, "guide exe name")
edit("docs/BUILD-WINDOWS.md", "advprint-pro_3.5.5_all.deb",
     "advprint-pro_3.5.6_all.deb", 1, "guide deb name")
edit("docs/BUILD-WINDOWS.md", "SHA256SUMS-3.5.5.txt",
     "SHA256SUMS-3.5.6.txt", 2, "guide sums name")
edit("docs/BUILD-WINDOWS.md", "dist\\AdvPrint-Pro.crx 3.5.5",
     "dist\\AdvPrint-Pro.crx 3.5.6", 1, "guide verify cmd")
edit("docs/BUILD-FROM-SOURCE.md", "no prebuilt binaries (v3.5.5)",
     "no prebuilt binaries (v3.5.6)", 1, "from-source title")


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
          ("BUMP 3.5.5 -> 3.5.6", total, changed, skipped))
    return 0 if skipped == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
