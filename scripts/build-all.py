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
# v3.5.5 HARDENING (the "stage/install/hub-stop.ps1 -> no files found"
# support case): an incomplete source tree used to fail deep inside
# makensis with a confusing error. Now the build:
#   1. hard-fails BEFORE makensis if ANY expected source file is
#      missing from the tree (and says exactly which ones),
#   2. pre-validates EVERY File reference in installer/setup.nsi,
#   3. refuses to run if the unix/windows twin files drifted apart,
#   4. SELF-HEALS the 9 Windows install scripts from copies embedded
#      in this file, so antivirus quarantine of a .ps1/.bat/.vbs can
#      never break the build,
#   5. if staged files vanish DURING makensis (on-access scanner),
#      diagnoses it, prints the Defender exclusion fix and retries.
#   6. WIPES dist/ + installer/stage with a lock-aware wipe(): old
#      builds used rmtree(ignore_errors=True), which on Windows
#      silently left stage/runtime behind when Defender / the search
#      indexer / an open Explorer window held a handle - the next
#      copytree then died with WinError 183 'Cannot create a file
#      when that file already exists'. Now: read-only bits cleared,
#      short backoff retries, and a loud fix-it message if the
#      folder truly cannot be deleted.
#   7. COMPILES A GENERATED setup-abs.nsi: every File/Icon/OutFile
#      path is rewritten to an ABSOLUTE path that Python verified to
#      exist right before the compile, so no makensis path-resolution
#      quirk can ever matter. Plus: 'no files found' in the compiler
#      output now ALWAYS triggers a re-stage + retry (a scanner can
#      hide a file for a moment and put it back before the old
#      post-mortem looked), and setup.nsi itself is working-directory
#      independent (!cd "${__FILEDIR__}").
# ============================================================
import argparse
import base64
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

# every repo file the NSIS stage is built from - an incomplete tree
# must fail HERE, with the full list, not inside makensis
REQUIRED_TREE_FILES = [
    "VERSION.txt", "README.md", "LICENSE",
    "extension/manifest.json",
    "extension-signing/advprint-printer.pem",
    "tool/unix/hub/advprint.py",
    "tool/unix/hub/console.html",
    "tool/unix/hub/gui_app.py",
    "tool/windows/portable/hub/advprint.py",
    "tool/windows/portable/hub/console.html",
    "tool/windows/portable/hub/tool.py",
    "tool/windows/portable/hub/tray_windows.py",
    "tool/windows/portable/hub/service_main.py",
    "tool/windows/portable/hub/advprint.ico",
    "tool/windows/portable/hub/service/AdvPrintProService.cs",
    "tool/windows/portable/install/install-windows.bat",
    "tool/windows/portable/install/UNINSTALL-WINDOWS.bat",
    "tool/windows/portable/install/START-ADVPRINT.vbs",
    "tool/windows/portable/install/START-CONSOLE.vbs",
    "tool/windows/portable/install/INSTALL-WINDOWS-SERVICE.bat",
    "tool/windows/portable/install/REMOVE-WINDOWS-SERVICE.bat",
    "tool/windows/portable/install/service-install.ps1",
    "tool/windows/portable/install/service-remove.ps1",
    "tool/windows/portable/install/hub-stop.ps1",
    "tool/windows/portable/installer/runtime/python311.dll",
    "tool/windows/portable/installer/runtime/AdvPrintPro.exe",
    "docs/AdvPrint-Pro-Full-Guide.html",
    "installer/setup.nsi", "installer/installer.ico",
    "installer/deb/DEBIAN/control",
    "installer/deb/DEBIAN/postinst",
    "installer/deb/DEBIAN/prerm",
    "installer/deb/data/advprint-launcher",
    "installer/deb/data/advprint-start",
    "installer/deb/data/advprint.desktop",
    "installer/deb/data/advprint.service",
    "scripts/build-all.py", "tool/crx3.py",
]

# unix <-> windows twins that must stay byte-identical
TWIN_FILES = [
    "hub/advprint.py",
    "hub/console.html",
    "hub/gui_app.py",
]

# the 9 Windows install scripts the NSIS stage requires - if any of
# them is missing (antivirus quarantine of .ps1/.bat/.vbs files is
# the usual cause) it is restored from the embedded copy below and
# the build continues with a printed warning
STAGE_INSTALL_FILES = (
    "install-windows.bat", "UNINSTALL-WINDOWS.bat", "START-ADVPRINT.vbs",
    "START-CONSOLE.vbs", "INSTALL-WINDOWS-SERVICE.bat",
    "REMOVE-WINDOWS-SERVICE.bat", "service-install.ps1",
    "service-remove.ps1", "hub-stop.ps1",
)

# base64 of the 9 install scripts, captured from this repo -
# the build restores any of them that an antivirus removes
EMBEDDED_INSTALL_FILES = {
    "install-windows.bat":
        "QGVjaG8gb2ZmClJFTSA9PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09"
        "PT09PT09PT09PT09PT09PT09PT0KUkVNICBBZHZQcmludCBQcm8gLSBPTkUtQ0xJQ0sgV2lu"
        "ZG93cyBzZXR1cCAgKHYyLjUuMCkKUkVNICBKdXN0IGRvdWJsZS1jbGljayB0aGlzIGZpbGUu"
        "IFplcm8gcXVlc3Rpb25zOgpSRU0gICAgMS4gcmVtb3ZlcyBNYXJrLW9mLXRoZS1XZWIgZnJv"
        "bSBhbGwgZmlsZXMKUkVNICAgICAgIChmaXhlcyAiQWNjZXNzIGlzIGRlbmllZCIgb24gZG93"
        "bmxvYWRlZCB6aXBzKQpSRU0gICAgMi4gc3RvcHMgYW55IE9MRCBodWIgc3RpbGwgaG9sZGlu"
        "ZyBwb3J0IDkyMzUKUkVNICAgIDMuIHVzZXMgdGhlIEJVTkRMRUQgUHl0aG9uIHJ1bnRpbWUg"
        "KGluc3RhbGxlclxydW50aW1lKSAtClJFTSAgICAgICBubyBzeXN0ZW0gUHl0aG9uIG5lZWRl"
        "ZDsgc3lzdGVtIFB5dGhvbiA9IGZhbGxiYWNrClJFTSAgICA0LiBjaGVja3MgU3VtYXRyYVBE"
        "RiAoYXV0by1pbnN0YWxscyBpdCB2aWEgd2luZ2V0KQpSRU0gICAgNS4gcmVnaXN0ZXJzIEFV"
        "VE8tUlVOIGFzIGEgTk9STUFMIFNUQVJUVVAgQVBQOgpSRU0gICAgICAgIkFkdlByaW50IFBy"
        "byIgc2hvd3MgaW4gVGFzayBNYW5hZ2VyID4gU3RhcnR1cCBhcHBzClJFTSAgICAgICAoZW5h"
        "YmxlL2Rpc2FibGUgdGhlcmUsIG9yIGZyb20gdGhlIHRyYXkgaWNvbiBtZW51KQpSRU0gICAg"
        "Ni4gc3RhcnRzIHRoZSBodWIgbm93LCBoaWRkZW4sIGFuZCBoZWFsdGgtY2hlY2tzIGl0ClJF"
        "TSAgICA3LiB0aGUgaHViIHNob3dzIGEgIkFkdlByaW50IFBybyIgVFJBWSBJQ09OIHdpdGgg"
        "YSBtZW51ClJFTSAgICAgICAob3BlbiBzdGF0dXMgcGFnZSwgdGVzdCBwYWdlLCBwYXVzZSwg"
        "YXV0b3N0YXJ0LCBleGl0KQpSRU0gIE5vIGFkbWluIHJpZ2h0cyBuZWVkZWQuICBVbmRvID0g"
        "VU5JTlNUQUxMLVdJTkRPV1MuYmF0ClJFTSAgYnkgQml0IERyZWFtIElUIC0gTUlUIGxpY2Vu"
        "c2VkClJFTSA9PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09"
        "PT09PT09PT09PT09PT0KdGl0bGUgQWR2UHJpbnQgUHJvIFNldHVwCnNldGxvY2FsIEVuYWJs"
        "ZURlbGF5ZWRFeHBhbnNpb24KZWNoby4KZWNobyAgID09PT09PT09PT09PT09PT09PT09PT09"
        "PT09PT09PT09PT09PT09PT09PT09PT0KZWNobyAgICBBZHZQcmludCBQcm8gIC0gIG9uZS1j"
        "bGljayBzZXR1cAplY2hvICAgIGluc3RhbGxzICsgYXV0by1ydW4gYXQgbG9nb24sIG5vIHF1"
        "ZXN0aW9ucwplY2hvICAgPT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09"
        "PT09PT09PQplY2hvLgoKUkVNIC0tLS0gMGEpIHJlbW92ZSBNYXJrLW9mLXRoZS1XZWIgKGRv"
        "d25sb2FkZWQtemlwIGJsb2NrcykgLS0tLS0tLS0tLS0tLS0KZWNobyBbLi5dIFVuYmxvY2tp"
        "bmcgZG93bmxvYWRlZCBmaWxlcyAuLi4KcG93ZXJzaGVsbCAtTm9Qcm9maWxlIC1FeGVjdXRp"
        "b25Qb2xpY3kgQnlwYXNzIC1Db21tYW5kIF4KICAiR2V0LUNoaWxkSXRlbSAtTGl0ZXJhbFBh"
        "dGggJyV+ZHAwLi4nIC1SZWN1cnNlIC1GaWxlIHwgVW5ibG9jay1GaWxlIiA+bnVsIDI+JjEK"
        "ZWNobyBbT0tdIEZpbGVzIHVuYmxvY2tlZCAtIG5vIG1vcmUgIkFjY2VzcyBpcyBkZW5pZWQi"
        "IG9uIHRoaXMgZm9sZGVyCgpSRU0gLS0tLSAwYikgc3RvcCBhbnkgT0xEIGh1YiBob2xkaW5n"
        "IHBvcnQgOTIzNSAtLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLQplY2hvIFsuLl0gQ2hlY2tp"
        "bmcgcG9ydCA5MjM1IGZvciBhbiBvbGQgaHViIC4uLgpzZXQgT0xES0lMTD0KZm9yIC9mICJ0"
        "b2tlbnM9NSIgJSVhIGluICgnbmV0c3RhdCAtYW9uIDJePm51bCBefCBmaW5kc3RyIC9yIC9j"
        "OiI6OTIzNSAuKkxJU1RFTklORyInKSBkbyAoCiAgdGFza2tpbGwgL0YgL1BJRCAlJWEgPm51"
        "bCAyPiYxICYmIHNldCBPTERLSUxMPTEKKQppZiBkZWZpbmVkIE9MREtJTEwgKAogIGVjaG8g"
        "W09LXSBPbGQgaHViIHByb2Nlc3Mgc3RvcHBlZCAtIHBvcnQgOTIzNSBpcyBub3cgZnJlZQop"
        "IGVsc2UgKAogIGVjaG8gW09LXSBQb3J0IDkyMzUgd2FzIGFscmVhZHkgZnJlZQopCgpSRU0g"
        "LS0tLSAxKSBQeXRob246IEJVTkRMRUQgcnVudGltZSBmaXJzdCwgc3lzdGVtIFB5dGhvbiA9"
        "IGZhbGxiYWNrIC0tLS0tLQpSRU0gIHYyLjQuMDogQWR2UHJpbnRQcm8uZXhlID0gcHl0aG9u"
        "dy5leGUgcmVuYW1lZCwgc28gVGFzayBNYW5hZ2VyClJFTSAgc2hvd3MgIkFkdlByaW50UHJv"
        "IiBpbnN0ZWFkIG9mICJweXRob24iLgpzZXQgUFlXPQppZiBleGlzdCAiJX5kcDAuLlxydW50"
        "aW1lXEFkdlByaW50UHJvLmV4ZSIgKAogIGZvciAlJUkgaW4gKCIlfmRwMC4uXHJ1bnRpbWVc"
        "QWR2UHJpbnRQcm8uZXhlIikgZG8gc2V0ICJQWVc9JSV+ZkkiCiAgZWNobyBbT0tdIEJ1bmRs"
        "ZWQgcnVudGltZSBmb3VuZCAtIEFkdlByaW50UHJvLmV4ZSwgbm8gc3lzdGVtIFB5dGhvbiBu"
        "ZWVkZWQKICBnb3RvIHB5d19yZWFkeQopCmlmIGV4aXN0ICIlfmRwMC4uXHJ1bnRpbWVccHl0"
        "aG9udy5leGUiICgKICBmb3IgJSVJIGluICgiJX5kcDAuLlxydW50aW1lXHB5dGhvbncuZXhl"
        "IikgZG8gc2V0ICJQWVc9JSV+ZkkiCiAgZWNobyBbT0tdIEJ1bmRsZWQgUHl0aG9uIDMuMTEg"
        "cnVudGltZSBmb3VuZCAtIG5vIHN5c3RlbSBQeXRob24gbmVlZGVkCiAgZ290byBweXdfcmVh"
        "ZHkKKQppZiBleGlzdCAiJX5kcDAuLlxpbnN0YWxsZXJccnVudGltZVxBZHZQcmludFByby5l"
        "eGUiICgKICBmb3IgJSVJIGluICgiJX5kcDAuLlxpbnN0YWxsZXJccnVudGltZVxBZHZQcmlu"
        "dFByby5leGUiKSBkbyBzZXQgIlBZVz0lJX5mSSIKICBlY2hvIFtPS10gQnVuZGxlZCBydW50"
        "aW1lIGZvdW5kIC0gQWR2UHJpbnRQcm8uZXhlLCBubyBzeXN0ZW0gUHl0aG9uIG5lZWRlZAog"
        "IGdvdG8gcHl3X3JlYWR5CikKaWYgZXhpc3QgIiV+ZHAwLi5caW5zdGFsbGVyXHJ1bnRpbWVc"
        "cHl0aG9udy5leGUiICgKICBmb3IgJSVJIGluICgiJX5kcDAuLlxpbnN0YWxsZXJccnVudGlt"
        "ZVxweXRob253LmV4ZSIpIGRvIHNldCAiUFlXPSUlfmZJIgogIGVjaG8gW09LXSBCdW5kbGVk"
        "IFB5dGhvbiAzLjExIHJ1bnRpbWUgZm91bmQgLSBubyBzeXN0ZW0gUHl0aG9uIG5lZWRlZAog"
        "IGdvdG8gcHl3X3JlYWR5CikKc2V0IFBZPQpweSAtMyAtLXZlcnNpb24gPm51bCAyPiYxICYm"
        "IHNldCBQWT1weSAtMwppZiBub3QgZGVmaW5lZCBQWSAoCiAgcHl0aG9uIC0tdmVyc2lvbiA+"
        "bnVsIDI+JjEgJiYgc2V0IFBZPXB5dGhvbgopCmlmIG5vdCBkZWZpbmVkIFBZICgKICBlY2hv"
        "IFshXSBQeXRob24gMyB3YXMgbm90IGZvdW5kIG9uIHRoaXMgUEMuCiAgZWNobyAgICAgS2Vl"
        "cCB0aGUgRlVMTCBwYWNrYWdlIHVuemlwcGVkOiBpbnN0YWxsZXJccnVudGltZVxweXRob253"
        "LmV4ZQogIGVjaG8gICAgIGlzIHRoZSBidW5kbGVkIHJ1bnRpbWUuIE9yIGluc3RhbGwgUHl0"
        "aG9uIGZyb20gcHl0aG9uLm9yZy4KICBzdGFydCBodHRwczovL3d3dy5weXRob24ub3JnL2Rv"
        "d25sb2Fkcy8KICBwYXVzZQogIGV4aXQgL2IgMQopCmVjaG8gW09LXSBQeXRob24gZm91bmQg"
        "IC0gICFQWSEKClJFTSAtLS0tIDIpIHJlc29sdmUgcHl0aG9udy5leGUgRlVMTCBwYXRoIChz"
        "a2lwIGlmIGJ1bmRsZWQgcnVudGltZSkgLS0tLS0tClJFTSAgVGhlIHRhc2sgcnVucyBweXRo"
        "b253IGRpcmVjdGx5IC0gV2luZG93cyBzY3JpcHQgaG9zdHMgYXJlIG9mdGVuClJFTSAgYmxv"
        "Y2tlZCBieSBEZWZlbmRlciBBU1IgLyBncm91cCBwb2xpY3kgb24gY29tcGFueSBtYWNoaW5l"
        "cy4KaWYgZGVmaW5lZCBQWVcgZ290byBweXdfcmVhZHkKc2V0IFBZRVhFPQpzZXQgUFlXPQpm"
        "b3IgL2YgImRlbGltcz0iICUlcCBpbiAoJyVQWSUgLWMgImltcG9ydCBzeXM7cHJpbnQoc3lz"
        "LmV4ZWN1dGFibGUpIicpIGRvIHNldCBQWUVYRT0lJXAKaWYgZGVmaW5lZCBQWUVYRSAoCiAg"
        "c2V0ICJQWVc9IVBZRVhFOnB5dGhvbi5leGU9cHl0aG9udy5leGUhIgogIGlmIG5vdCBleGlz"
        "dCAiIVBZVyEiIHNldCAiUFlXPSIKKQppZiBub3QgZGVmaW5lZCBQWVcgKAogIGZvciAvZiAi"
        "ZGVsaW1zPSIgJSVwIGluICgnd2hlcmUgcHl0aG9udy5leGUgMl4+bnVsJykgZG8gaWYgbm90"
        "IGRlZmluZWQgUFlXIHNldCAiUFlXPSUlcCIKKQppZiBkZWZpbmVkIFBZVyAoCiAgZWNobyBb"
        "T0tdIHB5dGhvbncgcmVzb2x2ZWQ6ICAhUFlXIQopIGVsc2UgKAogIGVjaG8gWy4uXSBweXRo"
        "b253IHBhdGggbm90IHJlc29sdmVkIC0gdGFzayB3aWxsIHVzZSB0aGUgLnZicyBsYXVuY2hl"
        "cgopCjpweXdfcmVhZHkKClJFTSAtLS0tIDMpIFN1bWF0cmFQREYgY2hlY2sgKHNpbGVudCBQ"
        "REYgcHJpbnRpbmcgZW5naW5lKSAtLS0tLS0tLS0tLS0tLS0tCnNldCBTVU1BVFJBPQppZiBl"
        "eGlzdCAiJVByb2dyYW1GaWxlcyVcU3VtYXRyYVBERlxTdW1hdHJhUERGLmV4ZSIgc2V0IFNV"
        "TUFUUkE9MQppZiBleGlzdCAiJVByb2dyYW1GaWxlcyh4ODYpJVxTdW1hdHJhUERGXFN1bWF0"
        "cmFQREYuZXhlIiBzZXQgU1VNQVRSQT0xCmlmIGV4aXN0ICIlTG9jYWxBcHBEYXRhJVxTdW1h"
        "dHJhUERGXFN1bWF0cmFQREYuZXhlIiBzZXQgU1VNQVRSQT0xCmlmIGV4aXN0ICJDOlxUb29s"
        "c1xTdW1hdHJhUERGLmV4ZSIgc2V0IFNVTUFUUkE9MQppZiBkZWZpbmVkIFNVTUFUUkEgKAog"
        "IGVjaG8gW09LXSBTdW1hdHJhUERGIGZvdW5kCikgZWxzZSAoCiAgZWNobyBbLi5dIFN1bWF0"
        "cmFQREYgbm90IGZvdW5kIC0gaW5zdGFsbGluZyB3aXRoIHdpbmdldCAuLi4KICB3aW5nZXQg"
        "aW5zdGFsbCAtLWlkIFN1bWF0cmFQREYuU3VtYXRyYVBERiAtZSAtLXNpbGVudCAtLWFjY2Vw"
        "dC1zb3VyY2UtYWdyZWVtZW50cyAtLWFjY2VwdC1wYWNrYWdlLWFncmVlbWVudHMgPm51bCAy"
        "PiYxCiAgaWYgZXhpc3QgIiVQcm9ncmFtRmlsZXMlXFN1bWF0cmFQREZcU3VtYXRyYVBERi5l"
        "eGUiICgKICAgIGVjaG8gW09LXSBTdW1hdHJhUERGIGluc3RhbGxlZAogICkgZWxzZSAoCiAg"
        "ICBlY2hvIFshXSBBdXRvLWluc3RhbGwgZmFpbGVkIC0gb3BlbmluZyB0aGUgZG93bmxvYWQg"
        "cGFnZS4KICAgIGVjaG8gICAgIEluc3RhbGwgU3VtYXRyYVBERiwgdGhlbiBydW4gdGhpcyBz"
        "ZXR1cCBhZ2Fpbi4KICAgIHN0YXJ0IGh0dHBzOi8vd3d3LnN1bWF0cmFwZGZyZWFkZXIub3Jn"
        "L2Rvd25sb2FkLWZyZWUtcGRmLXZpZXdlcgogICkKKQoKUkVNIC0tLS0gNCkgQVVUTy1SVU4g"
        "YXMgYSBub3JtYWwgU1RBUlRVUCBBUFAgKHZpc2libGUgKyBjb250cm9sbGFibGUpIC0tLS0K"
        "UkVNICB2Mi40LjA6IGEgc2hvcnRjdXQgbmFtZWQgIkFkdlByaW50IFBybyIgaW4gdGhlIHVz"
        "ZXIncyBTdGFydHVwClJFTSAgZm9sZGVyIC0gVGFzayBNYW5hZ2VyID4gU3RhcnR1cCBhcHBz"
        "IGxpc3RzIGl0IHdpdGggb3VyIGljb24sIGFuZApSRU0gIGl0IGNhbiBiZSBlbmFibGVkL2Rp"
        "c2FibGVkIHRoZXJlIChvciBpbiB0aGUgdHJheSBpY29uIG1lbnUpLgpSRU0gIFRoZSBoaWRk"
        "ZW4gU0NIRURVTEVEIFRBU0sgZnJvbSB2MS4yLXYxLjQgaXMgcmVtb3ZlZCBzbyB0aGUgaHVi"
        "ClJFTSAgbmV2ZXIgc3RhcnRzIHR3aWNlLgpzZXQgTE5LPSVBUFBEQVRBJVxNaWNyb3NvZnRc"
        "V2luZG93c1xTdGFydCBNZW51XFByb2dyYW1zXFN0YXJ0dXBcQWR2UHJpbnQgUHJvLmxuawpz"
        "Y2h0YXNrcyAvRGVsZXRlIC9UTiAiQWR2UHJpbnQgUHJvIiAvRiA+bnVsIDI+JjEKZGVsICIl"
        "TE5LJSIgPm51bCAyPiYxCmlmIGRlZmluZWQgUFlXICgKICBmb3IgJSVJIGluICgiJX5kcDAu"
        "LlxodWJcYWR2cHJpbnQucHkiKSBkbyBzZXQgIkhVQlBZPSUlfmZJIgogIGZvciAlJUkgaW4g"
        "KCIlfmRwMC4uXGh1YlxhZHZwcmludC5pY28iKSBkbyBzZXQgIkhVQklDTz0lJX5mSSIKICBm"
        "b3IgJSVJIGluICgiJX5kcDAuLlxodWIiKSBkbyBzZXQgIkhVQkRJUj0lJX5mSSIKICBwb3dl"
        "cnNoZWxsIC1Ob1Byb2ZpbGUgLUV4ZWN1dGlvblBvbGljeSBCeXBhc3MgLUNvbW1hbmQgXgog"
        "ICAgIiR3PU5ldy1PYmplY3QgLUNvbU9iamVjdCBXU2NyaXB0LlNoZWxsOyAkcz0kdy5DcmVh"
        "dGVTaG9ydGN1dCgnIUxOSyEnKTsgJHMuVGFyZ2V0UGF0aD0nIVBZVyEnOyAkcy5Bcmd1bWVu"
        "dHM9W2NoYXJdMzQrJyFIVUJQWSEnK1tjaGFyXTM0Kycgc2VydmUnOyAkcy5JY29uTG9jYXRp"
        "b249JyFIVUJJQ08hLDAnOyAkcy5Xb3JraW5nRGlyZWN0b3J5PSchSFVCRElSISc7ICRzLkRl"
        "c2NyaXB0aW9uPSdBZHZQcmludCBQcm8gc2lsZW50IHByaW50IGh1Yic7ICRzLlNhdmUoKSIg"
        "Pm51bCAyPiYxCikgZWxzZSAoCiAgcG93ZXJzaGVsbCAtTm9Qcm9maWxlIC1FeGVjdXRpb25Q"
        "b2xpY3kgQnlwYXNzIC1Db21tYW5kIF4KICAgICIkdz1OZXctT2JqZWN0IC1Db21PYmplY3Qg"
        "V1NjcmlwdC5TaGVsbDsgJHM9JHcuQ3JlYXRlU2hvcnRjdXQoJyFMTkshJyk7ICRzLlRhcmdl"
        "dFBhdGg9J3dzY3JpcHQuZXhlJzsgJHMuQXJndW1lbnRzPVtjaGFyXTM0KyclfmRwMFNUQVJU"
        "LVBSSU5ULUhVQi52YnMnK1tjaGFyXTM0OyAkcy5JY29uTG9jYXRpb249JyV+ZHAwLi5caHVi"
        "XGFkdnByaW50LmljbywwJzsgJHMuRGVzY3JpcHRpb249J0FkdlByaW50IFBybyBzaWxlbnQg"
        "cHJpbnQgaHViJzsgJHMuU2F2ZSgpIiA+bnVsIDI+JjEKKQppZiBleGlzdCAiJUxOSyUiICgK"
        "ICBlY2hvIFtPS10gQXV0by1ydW4gcmVnaXN0ZXJlZCBhcyBhIFN0YXJ0dXAgYXBwIG5hbWVk"
        "ICJBZHZQcmludCBQcm8iCiAgZWNobyAgICAgIENvbnRyb2wgaXQ6IFRhc2sgTWFuYWdlciBe"
        "PiBTdGFydHVwIGFwcHMgIC1vci0gIHRyYXkgaWNvbiBtZW51CikgZWxzZSAoCiAgZWNobyBb"
        "IV0gQ291bGQgbm90IHJlZ2lzdGVyIGF1dG8tcnVuIC0gaHViIHN0aWxsIHJ1bnMgbm93LCBi"
        "dXQKICBlY2hvICAgICBhZnRlciBhIHJlYm9vdCBzdGFydCBpdCB3aXRoIGluc3RhbGxcU1RB"
        "UlQtUFJJTlQtSFVCLnZicwopCgpSRU0gLS0tLSA0YikgdjMuMC43OiBTSUxFTlQgZXh0ZW5z"
        "aW9uIGluc3RhbGwgcG9saWN5ICh0aGlzIHVzZXIpIC0tLS0tLQpSRU0gIFdyaXRlcyB0aGUg"
        "RXh0ZW5zaW9uSW5zdGFsbEZvcmNlbGlzdCBwb2xpY3kgdW5kZXIgSEtDVSAobm8gYWRtaW4K"
        "UkVNICBuZWVkZWQpOiBDaHJvbWUvRWRnZS9CcmF2ZS9DaHJvbWl1bS9WaXZhbGRpIGZldGNo"
        "IHRoZSBTSUdORUQKUkVNICBleHRlbnNpb24gZnJvbSB0aGUgaHViJ3Mgb3duIC9leHRlbnNp"
        "b24vdXBkYXRlcy54bWwgZW5kcG9pbnQgYW5kClJFTSAgaW5zdGFsbCBpdCBzaWxlbnRseSAr"
        "IGF1dG8tdXBkYXRlIGl0IG9uIGV2ZXJ5IG5ld2VyIHJlbGVhc2UuClJFTSAgU2lsZW50IGlu"
        "c3RhbGwgdGFrZXMgZWZmZWN0IG9uIGRvbWFpbi1qb2luZWQvZW5yb2xsZWQgbWFjaGluZXMK"
        "UkVNICAoc2Nob29scywgd29ya3BsYWNlcyk7IGEgbm9ybWFsIGhvbWUgUEMgaWdub3JlcyBv"
        "ZmYtc3RvcmUKUkVNICBmb3JjZS1pbnN0YWxsIC0gdGhlcmUgdXNlIGNocm9tZTovL2V4dGVu"
        "c2lvbnMgPiBMb2FkIHVucGFja2VkLgplY2hvIFsuLl0gV3JpdGluZyB0aGUgZXh0ZW5zaW9u"
        "IGZvcmNlLWluc3RhbGwgcG9saWN5IC4uLgpwb3dlcnNoZWxsIC1Ob1Byb2ZpbGUgLUV4ZWN1"
        "dGlvblBvbGljeSBCeXBhc3MgLUNvbW1hbmQgIgokaWQ9J2xpa2xkYmthbW9qb2trZmRsY2pp"
        "YmlsanBnYmJub2hjJzsgJHZhbD0kaWQrJztodHRwOi8vMTI3LjAuMC4xOjkyMzUvZXh0ZW5z"
        "aW9uL3VwZGF0ZXMueG1sJzsgIgpmb3JlYWNoKCRwIGluIEAoJ0hLQ1U6XFxTT0ZUV0FSRVxc"
        "UG9saWNpZXNcXEdvb2dsZVxcQ2hyb21lXFxFeHRlbnNpb25JbnN0YWxsRm9yY2VsaXN0Jywn"
        "SEtDVTpcXFNPRlRXQVJFXFxQb2xpY2llc1xcTWljcm9zb2Z0XFxFZGdlXFxFeHRlbnNpb25J"
        "bnN0YWxsRm9yY2VsaXN0JywnSEtDVTpcXFNPRlRXQVJFXFxQb2xpY2llc1xcQnJhdmVTb2Z0"
        "d2FyZVxcQnJhdmVcXEV4dGVuc2lvbkluc3RhbGxGb3JjZWxpc3QnLCdIS0NVOlxcU09GVFdB"
        "UkVcXFBvbGljaWVzXFxDaHJvbWl1bVxcRXh0ZW5zaW9uSW5zdGFsbEZvcmNlbGlzdCcsJ0hL"
        "Q1U6XFxTT0ZUV0FSRVxcUG9saWNpZXNcXFZpdmFsZGlcXEV4dGVuc2lvbkluc3RhbGxGb3Jj"
        "ZWxpc3QnKSl7ICIKTmV3LUl0ZW0gLVBhdGggJHAgLUZvcmNlIHwgT3V0LU51bGw7ICIKJHBy"
        "b3BzPShHZXQtSXRlbSAkcCkuUHJvcGVydHk7ICRzbG90PSRudWxsOyAiCmZvcmVhY2goJG4g"
        "aW4gJHByb3BzKXsgJHY9KEdldC1JdGVtUHJvcGVydHkgLVBhdGggJHAgLU5hbWUgJG4pLiRu"
        "OyBpZigkdiAtbGlrZSAoJGlkKyc7KicpKXsgJHNsb3Q9JG47IGJyZWFrIH0gfTsgIgppZigt"
        "bm90ICRzbG90KXsgJHNsb3Q9W3N0cmluZ10oJHByb3BzLkNvdW50KzEpIH07ICIKU2V0LUl0"
        "ZW1Qcm9wZXJ0eSAtUGF0aCAkcCAtTmFtZSAkc2xvdCAtVmFsdWUgJHZhbDsgfSIgPm51bCAy"
        "PiYxCmVjaG8gW09LXSBFeHRlbnNpb24gZm9yY2UtaW5zdGFsbCBwb2xpY3kgd3JpdHRlbiAo"
        "Q2hyb21lL0VkZ2UvQnJhdmUgLSBzaWxlbnQgaW5zdGFsbCBvbiBtYW5hZ2VkIFBDcykKClJF"
        "TSAtLS0tIDUpIHN0YXJ0IHRoZSBodWIgcmlnaHQgbm93LCBoaWRkZW4gLS0tLS0tLS0tLS0t"
        "LS0tLS0tLS0tLS0tLS0tLS0tCmVjaG8gWy4uXSBTdGFydGluZyBBZHZQcmludCBQcm8gb24g"
        "aHR0cDovLzEyNy4wLjAuMTo5MjM1IC4uLgppZiBkZWZpbmVkIFBZVyAoCiAgc3RhcnQgIiIg"
        "IiFQWVchIiAiJX5kcDAuLlxodWJcYWR2cHJpbnQucHkiIHNlcnZlCikgZWxzZSAoCiAgd3Nj"
        "cmlwdC5leGUgIiV+ZHAwU1RBUlQtUFJJTlQtSFVCLnZicyIKKQoKUkVNIC0tLS0gNikgaGVh"
        "bHRoIGNoZWNrLCB1cCB0byA4IHNlY29uZHMgLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0t"
        "LS0tLS0Kc2V0IFVQPQpmb3IgL2wgJSVpIGluICgxLDEsOCkgZG8gKAogIGlmIG5vdCBkZWZp"
        "bmVkIFVQICgKICAgIHRpbWVvdXQgL3QgMSAvbm9icmVhayA+bnVsCiAgICBjdXJsIC1zIGh0"
        "dHA6Ly8xMjcuMC4wLjE6OTIzNS9oZWFsdGggMj5udWwgfCBmaW5kc3RyIC9jOiJ2ZXJzaW9u"
        "IiA+bnVsIDI+JjEgJiYgc2V0IFVQPTEKICApCikKaWYgZGVmaW5lZCBVUCAoCiAgZWNobyBb"
        "T0tdIEh1YiBpcyBydW5uaW5nIC0gaGVhbHRoIGNoZWNrIHBhc3NlZAopIGVsc2UgKAogIGVj"
        "aG8gWyFdIEhlYWx0aCBjaGVjayBGQUlMRUQuCiAgZWNobyAgICAgTG9vayBhdDogICVVU0VS"
        "UFJPRklMRSVcLmFkdnByaW50XGh1Yi5sb2cKICBlY2hvICAgICBPciBydW4gaW4gYSBjb25z"
        "b2xlOiAgaHViXGFkdnByaW50LnB5IHNlcnZlICB0byBzZWUgdGhlIGVycm9yLgopCgplY2hv"
        "LgplY2hvICAgPT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09"
        "PT09PT09PQplY2hvICAgIFNldHVwIGZpbmlzaGVkIC0gZXZlcnl0aGluZyBpcyBhdXRvbWF0"
        "aWMgbm93OgplY2hvICAgICAtIGh1YiBydW5uaW5nIGhpZGRlbiBhdCBodHRwOi8vMTI3LjAu"
        "MC4xOjkyMzUKZWNobyAgICAgLSAiQWR2UHJpbnQgUHJvIiBUUkFZIElDT04gbmVhciB0aGUg"
        "Y2xvY2s6IHJpZ2h0LWNsaWNrCmVjaG8gICAgICAgaXQgZm9yIHN0YXR1cyBwYWdlIC8gdGVz"
        "dCBwYWdlIC8gcGF1c2UgLyBhdXRvLXJ1biAvIGV4aXQKZWNobyAgICAgLSBzdGFydHMgYWdh"
        "aW4gYXV0b21hdGljYWxseSBhdCBldmVyeSBsb2dvbiBhcyB0aGUKZWNobyAgICAgICBTdGFy"
        "dHVwIGFwcCAiQWR2UHJpbnQgUHJvIiAoVGFzayBNYW5hZ2VyIF4+IFN0YXJ0dXApCmVjaG8g"
        "ICAgIC0gQ2hyb21lL0VkZ2U6IHNpbGVudCBpbnN0YWxsIHZpYSBmb3JjZS1pbnN0YWxsIHBv"
        "bGljeQplY2hvICAgICAgIChkb21haW4gUENzKS4gSG9tZSBQQzogY2hyb21lOi8vZXh0ZW5z"
        "aW9ucyBePgplY2hvICAgICAgIERldmVsb3BlciBtb2RlIF4+IExvYWQgdW5wYWNrZWQgXj4g"
        "ZXh0ZW5zaW9uIGZvbGRlcgplY2hvICAgICAtIGNsaWNrIHRoZSBBZHZQcmludCBpY29uIF4+"
        "IENvbm5lY3QKZWNobyAgICBSZW1vdmUgYXV0by1ydW4gYW55dGltZTogIGluc3RhbGxcVU5J"
        "TlNUQUxMLVdJTkRPV1MuYmF0CmVjaG8gICA9PT09PT09PT09PT09PT09PT09PT09PT09PT09"
        "PT09PT09PT09PT09PT09PT09PT09PT09CmVjaG8uCnBhdXNlCg==",
    "UNINSTALL-WINDOWS.bat":
        "QGVjaG8gb2ZmClJFTSA9PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09"
        "PT09PT09PT09PT09PT09PT09PT0KUkVNICBBZHZQcmludCBQcm8gLSBXaW5kb3dzIHVuaW5z"
        "dGFsbCAgKHYyLjgpClJFTSAgdjIuODogQUxTTyBzdG9wcyBhbmQgcmVtb3ZlcyB0aGUgb3B0"
        "aW9uYWwgIkFkdlByaW50IiBzZXJ2aWNlClJFTSAgKHN0b3AgKyB3YWl0ICsgUElEIGtpbGwg"
        "KyBzYyBkZWxldGUpIGJlZm9yZSB0b3VjaGluZyBmaWxlcywKUkVNICBhbmQgcmVtb3ZlcyB0"
        "aGUgZmlyZXdhbGwgcnVsZS4gRml4ZXMgInNlcnZpY2Ugbm90IHVuaW5zdGFsbGVkIi4KUkVN"
        "ICBEb2VzIE5PVCBkZWxldGUgeW91ciBwcmludCBkYXRhIG9yIHRoZSBDaHJvbWUgZXh0ZW5z"
        "aW9uLgpSRU0gIFJ1biBhcyBBZG1pbmlzdHJhdG9yIGZvciB0aGUgc2VydmljZSArIGZpcmV3"
        "YWxsIHN0ZXBzLgpSRU0gPT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09"
        "PT09PT09PT09PT09PT09PT09PT09CnRpdGxlIEFkdlByaW50IFBybyBVbmluc3RhbGwKZWNo"
        "by4KZWNobyBbLi5dIFJlbW92aW5nIFN0YXJ0dXAgc2hvcnRjdXQgIkFkdlByaW50IFBybyIg"
        "Li4uCmRlbCAiJUFQUERBVEElXE1pY3Jvc29mdFxXaW5kb3dzXFN0YXJ0IE1lbnVcUHJvZ3Jh"
        "bXNcU3RhcnR1cFxBZHZQcmludCBQcm8ubG5rIiA+bnVsIDI+JjEKaWYgbm90IGV4aXN0ICIl"
        "QVBQREFUQSVcTWljcm9zb2Z0XFdpbmRvd3NcU3RhcnQgTWVudVxQcm9ncmFtc1xTdGFydHVw"
        "XEFkdlByaW50IFByby5sbmsiICgKICBlY2hvIFtPS10gU3RhcnR1cCBzaG9ydGN1dCByZW1v"
        "dmVkIC0gbm8gbW9yZSBhdXRvLXJ1biBhdCBsb2dvbgopIGVsc2UgKAogIGVjaG8gWyFdIENv"
        "dWxkIG5vdCByZW1vdmUgdGhlIFN0YXJ0dXAgc2hvcnRjdXQgLSBkZWxldGUgaXQgbWFudWFs"
        "bHk6CiAgZWNobyAgICAgJUFQUERBVEElXE1pY3Jvc29mdFxXaW5kb3dzXFN0YXJ0IE1lbnVc"
        "UHJvZ3JhbXNcU3RhcnR1cAopCmVjaG8gWy4uXSBSZW1vdmluZyBsZWdhY3kgbG9nb24gdGFz"
        "ayAiQWR2UHJpbnQgUHJvIiAodjEuMi12MS40KSAuLi4Kc2NodGFza3MgL0RlbGV0ZSAvVE4g"
        "IkFkdlByaW50IFBybyIgL0YgPm51bCAyPiYxCgplY2hvIFsuLl0gU3RvcHBpbmcgdGhlIEFk"
        "dlByaW50IHNlcnZpY2UgKyBodWIgKHYyLjggYnVsbGV0LXByb29mIHN0b3ApIC4uLgpzZXQg"
        "SEVSRT0lfmRwMApwb3dlcnNoZWxsIC1Ob1Byb2ZpbGUgLUV4ZWN1dGlvblBvbGljeSBCeXBh"
        "c3MgLUZpbGUgIiVIRVJFJWh1Yi1zdG9wLnBzMSIgPm51bCAyPiYxCmlmIGVycm9ybGV2ZWwg"
        "MSAoCiAgbmV0IHN0b3AgQWR2UHJpbnQgL3kgPm51bCAyPiYxCiAgc2MgZGVsZXRlIEFkdlBy"
        "aW50ID5udWwgMj4mMQopCnNjIHF1ZXJ5IEFkdlByaW50IDI+bnVsIHwgZmluZHN0ciAvaSAi"
        "U0VSVklDRV9OQU1FIiA+bnVsIDI+JjEKaWYgbm90IGVycm9ybGV2ZWwgMSAoCiAgZWNobyBb"
        "IV0gVGhlIHNlcnZpY2UgZW50cnkgaXMgc3RpbGwgbGlzdGVkIC0gcnVuIG9uY2UgbW9yZSBh"
        "cyBBZG1pbmlzdHJhdG9yLAogIGVjaG8gICAgIG9yIHJlYm9vdCAoV2luZG93cyBtYXJrcyBp"
        "dCBmb3IgZGVsZXRpb24sIGdvbmUgYWZ0ZXIgcmVzdGFydCkuCikgZWxzZSAoCiAgZWNobyBb"
        "T0tdIFNlcnZpY2UgcmVtb3ZlZCAvIHdhcyBub3QgaW5zdGFsbGVkCikKCmVjaG8gWy4uXSBS"
        "ZW1vdmluZyB0aGUgZmlyZXdhbGwgcnVsZSAuLi4KbmV0c2ggYWR2ZmlyZXdhbGwgZmlyZXdh"
        "bGwgZGVsZXRlLXJ1bGUgbmFtZT0iQWR2UHJpbnQgUHJvIiBkaXI9aW4gPm51bCAyPiYxCmVj"
        "aG8gW09LXSBGaXJld2FsbCBydWxlIHJlbW92ZWQgKGlmIGl0IGV4aXN0ZWQpCgplY2hvLgpl"
        "Y2hvIFtPS10gQWR2UHJpbnQgUHJvIHVuaW5zdGFsbGVkLgplY2hvICAgICAgUHJpbnQgZGF0"
        "YSBrZXB0IGluOiAgJVVTRVJQUk9GSUxFJVwuYWR2cHJpbnQKZWNobyAgICAgIERlbGV0ZSBp"
        "dCBtYW51YWxseSBpZiB5b3Ugd2FudDoKZWNobyAgICAgICAgcm1kaXIgL3MgL3EgIiVVU0VS"
        "UFJPRklMRSVcLmFkdnByaW50IgplY2hvICAgICAgUmVtb3ZlIHRoZSBDaHJvbWUgZXh0ZW5z"
        "aW9uIGluIGNocm9tZTovL2V4dGVuc2lvbnMKZWNoby4KcGF1c2UK",
    "START-ADVPRINT.vbs":
        "JyBBZHZQcmludCBQcm8gLSBoaWRkZW4gbGF1bmNoZXIsIG5vIGNvbnNvbGUgd2luZG93ICAo"
        "djIuNS4wKQonIE1BTlVBTCAvIEZBTExCQUNLIGxhdW5jaGVyIG9ubHk6IG5vcm1hbCBpbnN0"
        "YWxscyBzdGFydCB0aGUgaHViCicgYXMgdGhlIFN0YXJ0dXAgYXBwICJBZHZQcmludCBQcm8i"
        "IChUYXNrIE1hbmFnZXIgPiBTdGFydHVwIGFwcHMpCicgb3IgZnJvbSB0aGUgdHJheSBpY29u"
        "LiBEb3VibGUtY2xpY2sgdGhpcyBmaWxlIG9ubHkgd2hlbiBib3RoCicgYXJlIHVuYXZhaWxh"
        "YmxlLgonIEh1YiBsb2c6ICVVc2VyUHJvZmlsZSVcLmFkdnByaW50XGh1Yi5sb2cKCk9wdGlv"
        "biBFeHBsaWNpdApEaW0gc2gsIGZzbywgYmFzZSwgaHViLCBsb2dkaXIsIHRzCkRpbSBweSwg"
        "Y2FuZGlkYXRlcywgdiwgd291dCwgd2xpbmUKClNldCBzaCAgPSBDcmVhdGVPYmplY3QoIldT"
        "Y3JpcHQuU2hlbGwiKQpTZXQgZnNvID0gQ3JlYXRlT2JqZWN0KCJTY3JpcHRpbmcuRmlsZVN5"
        "c3RlbU9iamVjdCIpCmJhc2UgPSBmc28uR2V0UGFyZW50Rm9sZGVyTmFtZShmc28uR2V0UGFy"
        "ZW50Rm9sZGVyTmFtZShXU2NyaXB0LlNjcmlwdEZ1bGxOYW1lKSkKaHViICA9IGJhc2UgJiAi"
        "XGh1YlxhZHZwcmludC5weSIKCicgLS0tLSAxKSByZXNvbHZlIHRoZSBsYXVuY2hlciAtLS0t"
        "LS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tCnB5ID0gIiIKCicgMXBy"
        "ZSkgQlVORExFRCBydW50aW1lIChmdWxsIHBhY2thZ2UpIC0gdjIuNC4wIHByZWZlcnMKJyAg"
        "ICAgICBBZHZQcmludFByby5leGUgKD0gcHl0aG9udy5leGUgcmVuYW1lZDogVGFzayBNYW5h"
        "Z2VyIHNob3dzCicgICAgICAgIkFkdlByaW50UHJvIiBpbnN0ZWFkIG9mICJweXRob24iKQpJ"
        "ZiBmc28uRmlsZUV4aXN0cyhiYXNlICYgIlxpbnN0YWxsZXJccnVudGltZVxBZHZQcmludFBy"
        "by5leGUiKSBUaGVuCiAgcHkgPSBiYXNlICYgIlxpbnN0YWxsZXJccnVudGltZVxBZHZQcmlu"
        "dFByby5leGUiCkVsc2VJZiBmc28uRmlsZUV4aXN0cyhiYXNlICYgIlxpbnN0YWxsZXJccnVu"
        "dGltZVxweXRob253LmV4ZSIpIFRoZW4KICBweSA9IGJhc2UgJiAiXGluc3RhbGxlclxydW50"
        "aW1lXHB5dGhvbncuZXhlIgpFbHNlSWYgZnNvLkZpbGVFeGlzdHMoYmFzZSAmICJccnVudGlt"
        "ZVxBZHZQcmludFByby5leGUiKSBUaGVuCiAgJyBOU0lTLWluc3RhbGxlZCBsYXlvdXQ6IHJ1"
        "bnRpbWVcIHNpdHMgZGlyZWN0bHkgdW5kZXIgJElOU1RESVIKICBweSA9IGJhc2UgJiAiXHJ1"
        "bnRpbWVcQWR2UHJpbnRQcm8uZXhlIgpFbHNlSWYgZnNvLkZpbGVFeGlzdHMoYmFzZSAmICJc"
        "cnVudGltZVxweXRob253LmV4ZSIpIFRoZW4KICBweSA9IGJhc2UgJiAiXHJ1bnRpbWVccHl0"
        "aG9udy5leGUiCkVuZCBJZgoKJyAxYSkgd2hhdGV2ZXIgaXMgb24gUEFUSCAod2hlcmUuZXhl"
        "LCBmaXJzdCBoaXQgd2lucykKT24gRXJyb3IgUmVzdW1lIE5leHQKSWYgZnNvLkZpbGVFeGlz"
        "dHMoc2guRXhwYW5kRW52aXJvbm1lbnRTdHJpbmdzKCIlU3lzdGVtUm9vdCVcU3lzdGVtMzJc"
        "d2hlcmUuZXhlIikpIFRoZW4KICBTZXQgd291dCA9IHNoLkV4ZWMoIiVDb21TcGVjJSAvYyB3"
        "aGVyZSBweXRob253LmV4ZSAyPm51bCIpCiAgRG8gV2hpbGUgTm90IHdvdXQuU3RkT3V0LkF0"
        "RW5kT2ZTdHJlYW0KICAgIHdsaW5lID0gVHJpbSh3b3V0LlN0ZE91dC5SZWFkTGluZSgpKQog"
        "ICAgSWYgcHkgPSAiIiBBbmQgd2xpbmUgPD4gIiIgQW5kIGZzby5GaWxlRXhpc3RzKHdsaW5l"
        "KSBUaGVuIHB5ID0gd2xpbmUKICBMb29wCkVuZCBJZgpPbiBFcnJvciBHb1RvIDAKCicgMWIp"
        "IHBlci11c2VyIGluc3RhbGxzIC0gdGhlIGNhc2UgbW9zdCBpbnN0YWxsZXJzIG1pc3MKJyAg"
        "ICAgJUxvY2FsQXBwRGF0YSVcUHJvZ3JhbXNcUHl0aG9uXFB5dGhvbjMxeFxweXRob253LmV4"
        "ZQonIDFjKSBhbGwtdXNlcnMgaW5zdGFsbHMgLSBDOlxQcm9ncmFtIEZpbGVzXFB5dGhvbjMx"
        "eFxweXRob253LmV4ZQpJZiBweSA9ICIiIFRoZW4KICBjYW5kaWRhdGVzID0gQXJyYXkoIF8K"
        "ICAgIHNoLkV4cGFuZEVudmlyb25tZW50U3RyaW5ncygiJUxvY2FsQXBwRGF0YSVcUHJvZ3Jh"
        "bXNcUHl0aG9uIiksIF8KICAgICJDOlxQcm9ncmFtIEZpbGVzXCIgKQogIERpbSByb290cywg"
        "cm9vdCwgdmVycwogIHZlcnMgPSBBcnJheSgiMzE0IiwiMzEzIiwiMzEyIiwiMzExIiwiMzEw"
        "IikKICBGb3IgRWFjaCByb290IEluIGNhbmRpZGF0ZXMKICAgIEZvciBFYWNoIHYgSW4gdmVy"
        "cwogICAgICBJZiBmc28uRmlsZUV4aXN0cyhyb290ICYgIlxQeXRob24iICYgdiAmICJccHl0"
        "aG9udy5leGUiKSBUaGVuCiAgICAgICAgcHkgPSByb290ICYgIlxQeXRob24iICYgdiAmICJc"
        "cHl0aG9udy5leGUiCiAgICAgICAgRXhpdCBGb3IKICAgICAgRW5kIElmCiAgICBOZXh0CiAg"
        "ICBJZiBweSA8PiAiIiBUaGVuIEV4aXQgRm9yCiAgTmV4dApFbmQgSWYKCicgMWQpIHB5IGxh"
        "dW5jaGVyIChhbGwtdXNlcnMgZGVmYXVsdCkgdGhlbiBiYXJlIFBBVEggZmFsbGJhY2sKSWYg"
        "cHkgPSAiIiBBbmQgZnNvLkZpbGVFeGlzdHMoIkM6XFdpbmRvd3NccHl3LmV4ZSIpIFRoZW4g"
        "cHkgPSAiQzpcV2luZG93c1xweXcuZXhlIgpJZiBweSA9ICIiIFRoZW4gcHkgPSAicHl0aG9u"
        "dy5leGUiCgonIC0tLS0gMikgYm9vdCBsb2cgLSBtYWtlcyAid2h5IGlzIG5vdGhpbmcgcHJp"
        "bnRpbmciIGFuc3dlcmFibGUgLS0tLS0tLS0tCmxvZ2RpciA9IHNoLkV4cGFuZEVudmlyb25t"
        "ZW50U3RyaW5ncygiJUxvY2FsQXBwRGF0YSVcQWR2UHJpbnRQcm8iKQpPbiBFcnJvciBSZXN1"
        "bWUgTmV4dApJZiBOb3QgZnNvLkZvbGRlckV4aXN0cyhsb2dkaXIpIFRoZW4gZnNvLkNyZWF0"
        "ZUZvbGRlcihsb2dkaXIpClNldCB0cyA9IGZzby5PcGVuVGV4dEZpbGUobG9nZGlyICYgIlxi"
        "b290LmxvZyIsIDgsIFRydWUpCnRzLldyaXRlTGluZSBOb3cgJiAiICBzdGFydCAgcHl0aG9u"
        "PSIiIiAmIHB5ICYgIiIiICBodWI9IiIiICYgaHViICYgIiIiIgp0cy5DbG9zZQpPbiBFcnJv"
        "ciBHb1RvIDAKCicgLS0tLSAzKSBsYXVuY2ggaGlkZGVuIC0tLS0tLS0tLS0tLS0tLS0tLS0t"
        "LS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tCnNoLkN1cnJlbnREaXJlY3RvcnkgPSBi"
        "YXNlICYgIlxodWIiCnNoLlJ1biAiIiIiICYgcHkgJiAiIiIgIiIiICYgaHViICYgIiIiIHNl"
        "cnZlIiwgMCwgRmFsc2UK",
    "START-CONSOLE.vbs":
        "JyBBZHZQcmludCBQcm8gdjMuMS4zIC0gUFJFTUlVTSBHUkFQSElDQUwgV0lORE9XIGxhdW5j"
        "aGVyCicgU3RhcnRzIGd1aV9hcHAgdjI6IHRoZSBuYXRpdmUgd2luZG93IGhvc3RpbmcgVEhF"
        "IE9ORSBVSSBjb25zb2xlCicgKHB5d2VidmlldyAtPiBRdCBXZWJFbmdpbmUgLT4gR1RLIFdl"
        "YktpdCAtPiBDaHJvbWUgYXBwIHdpbmRvdyAtPgonIGRlZmF1bHQgYnJvd3NlcikuIFRoZSBo"
        "dWIgaXMgYXV0by1zdGFydGVkIGJ5IGd1aV9hcHAgd2hlbiBuZWVkZWQuCicgVHJheS1vbmx5"
        "IGhpZGRlbiBodWIgbGF1bmNoZXI6IFNUQVJULUFEVlBSSU5ULnZicyAodW5jaGFuZ2VkKS4K"
        "JyBNQU5VQUwgLyBGQUxMQkFDSyBsYXVuY2hlciBvbmx5OiBub3JtYWwgaW5zdGFsbHMgc3Rh"
        "cnQgdGhlIGh1YgonIGFzIHRoZSBTdGFydHVwIGFwcCAiQWR2UHJpbnQgUHJvIiAoVGFzayBN"
        "YW5hZ2VyID4gU3RhcnR1cCBhcHBzKQonIG9yIGZyb20gdGhlIHRyYXkgaWNvbi4gRG91Ymxl"
        "LWNsaWNrIHRoaXMgZmlsZSBvbmx5IHdoZW4gYm90aAonIGFyZSB1bmF2YWlsYWJsZS4KJyBI"
        "dWIgbG9nOiAlVXNlclByb2ZpbGUlXC5hZHZwcmludFxodWIubG9nCgpPcHRpb24gRXhwbGlj"
        "aXQKRGltIHNoLCBmc28sIGJhc2UsIGh1YiwgbG9nZGlyLCB0cwpEaW0gcHksIGNhbmRpZGF0"
        "ZXMsIHYsIHdvdXQsIHdsaW5lCgpTZXQgc2ggID0gQ3JlYXRlT2JqZWN0KCJXU2NyaXB0LlNo"
        "ZWxsIikKU2V0IGZzbyA9IENyZWF0ZU9iamVjdCgiU2NyaXB0aW5nLkZpbGVTeXN0ZW1PYmpl"
        "Y3QiKQpiYXNlID0gZnNvLkdldFBhcmVudEZvbGRlck5hbWUoZnNvLkdldFBhcmVudEZvbGRl"
        "ck5hbWUoV1NjcmlwdC5TY3JpcHRGdWxsTmFtZSkpCmh1YiAgPSBiYXNlICYgIlxodWJcYWR2"
        "cHJpbnQucHkiCmd1aSAgPSBiYXNlICYgIlxodWJcZ3VpX2FwcC5weSIKCicgLS0tLSAxKSBy"
        "ZXNvbHZlIHRoZSBsYXVuY2hlciAtLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0t"
        "LS0tLS0tLS0tCnB5ID0gIiIKCicgMXByZSkgQlVORExFRCBydW50aW1lIChmdWxsIHBhY2th"
        "Z2UpIC0gdjIuNC4wIHByZWZlcnMKJyAgICAgICBBZHZQcmludFByby5leGUgKD0gcHl0aG9u"
        "dy5leGUgcmVuYW1lZDogVGFzayBNYW5hZ2VyIHNob3dzCicgICAgICAgIkFkdlByaW50UHJv"
        "IiBpbnN0ZWFkIG9mICJweXRob24iKQpJZiBmc28uRmlsZUV4aXN0cyhiYXNlICYgIlxpbnN0"
        "YWxsZXJccnVudGltZVxBZHZQcmludFByby5leGUiKSBUaGVuCiAgcHkgPSBiYXNlICYgIlxp"
        "bnN0YWxsZXJccnVudGltZVxBZHZQcmludFByby5leGUiCkVsc2VJZiBmc28uRmlsZUV4aXN0"
        "cyhiYXNlICYgIlxpbnN0YWxsZXJccnVudGltZVxweXRob253LmV4ZSIpIFRoZW4KICBweSA9"
        "IGJhc2UgJiAiXGluc3RhbGxlclxydW50aW1lXHB5dGhvbncuZXhlIgpFbHNlSWYgZnNvLkZp"
        "bGVFeGlzdHMoYmFzZSAmICJccnVudGltZVxBZHZQcmludFByby5leGUiKSBUaGVuCiAgJyBO"
        "U0lTLWluc3RhbGxlZCBsYXlvdXQ6IHJ1bnRpbWVcIHNpdHMgZGlyZWN0bHkgdW5kZXIgJElO"
        "U1RESVIKICBweSA9IGJhc2UgJiAiXHJ1bnRpbWVcQWR2UHJpbnRQcm8uZXhlIgpFbHNlSWYg"
        "ZnNvLkZpbGVFeGlzdHMoYmFzZSAmICJccnVudGltZVxweXRob253LmV4ZSIpIFRoZW4KICBw"
        "eSA9IGJhc2UgJiAiXHJ1bnRpbWVccHl0aG9udy5leGUiCkVuZCBJZgoKJyAxYSkgd2hhdGV2"
        "ZXIgaXMgb24gUEFUSCAod2hlcmUuZXhlLCBmaXJzdCBoaXQgd2lucykKT24gRXJyb3IgUmVz"
        "dW1lIE5leHQKSWYgZnNvLkZpbGVFeGlzdHMoc2guRXhwYW5kRW52aXJvbm1lbnRTdHJpbmdz"
        "KCIlU3lzdGVtUm9vdCVcU3lzdGVtMzJcd2hlcmUuZXhlIikpIFRoZW4KICBTZXQgd291dCA9"
        "IHNoLkV4ZWMoIiVDb21TcGVjJSAvYyB3aGVyZSBweXRob253LmV4ZSAyPm51bCIpCiAgRG8g"
        "V2hpbGUgTm90IHdvdXQuU3RkT3V0LkF0RW5kT2ZTdHJlYW0KICAgIHdsaW5lID0gVHJpbSh3"
        "b3V0LlN0ZE91dC5SZWFkTGluZSgpKQogICAgSWYgcHkgPSAiIiBBbmQgd2xpbmUgPD4gIiIg"
        "QW5kIGZzby5GaWxlRXhpc3RzKHdsaW5lKSBUaGVuIHB5ID0gd2xpbmUKICBMb29wCkVuZCBJ"
        "ZgpPbiBFcnJvciBHb1RvIDAKCicgMWIpIHBlci11c2VyIGluc3RhbGxzIC0gdGhlIGNhc2Ug"
        "bW9zdCBpbnN0YWxsZXJzIG1pc3MKJyAgICAgJUxvY2FsQXBwRGF0YSVcUHJvZ3JhbXNcUHl0"
        "aG9uXFB5dGhvbjMxeFxweXRob253LmV4ZQonIDFjKSBhbGwtdXNlcnMgaW5zdGFsbHMgLSBD"
        "OlxQcm9ncmFtIEZpbGVzXFB5dGhvbjMxeFxweXRob253LmV4ZQpJZiBweSA9ICIiIFRoZW4K"
        "ICBjYW5kaWRhdGVzID0gQXJyYXkoIF8KICAgIHNoLkV4cGFuZEVudmlyb25tZW50U3RyaW5n"
        "cygiJUxvY2FsQXBwRGF0YSVcUHJvZ3JhbXNcUHl0aG9uIiksIF8KICAgICJDOlxQcm9ncmFt"
        "IEZpbGVzXCIgKQogIERpbSByb290cywgcm9vdCwgdmVycwogIHZlcnMgPSBBcnJheSgiMzE0"
        "IiwiMzEzIiwiMzEyIiwiMzExIiwiMzEwIikKICBGb3IgRWFjaCByb290IEluIGNhbmRpZGF0"
        "ZXMKICAgIEZvciBFYWNoIHYgSW4gdmVycwogICAgICBJZiBmc28uRmlsZUV4aXN0cyhyb290"
        "ICYgIlxQeXRob24iICYgdiAmICJccHl0aG9udy5leGUiKSBUaGVuCiAgICAgICAgcHkgPSBy"
        "b290ICYgIlxQeXRob24iICYgdiAmICJccHl0aG9udy5leGUiCiAgICAgICAgRXhpdCBGb3IK"
        "ICAgICAgRW5kIElmCiAgICBOZXh0CiAgICBJZiBweSA8PiAiIiBUaGVuIEV4aXQgRm9yCiAg"
        "TmV4dApFbmQgSWYKCicgMWQpIHB5IGxhdW5jaGVyIChhbGwtdXNlcnMgZGVmYXVsdCkgdGhl"
        "biBiYXJlIFBBVEggZmFsbGJhY2sKSWYgcHkgPSAiIiBBbmQgZnNvLkZpbGVFeGlzdHMoIkM6"
        "XFdpbmRvd3NccHl3LmV4ZSIpIFRoZW4gcHkgPSAiQzpcV2luZG93c1xweXcuZXhlIgpJZiBw"
        "eSA9ICIiIFRoZW4gcHkgPSAicHl0aG9udy5leGUiCgonIC0tLS0gMikgYm9vdCBsb2cgLSBt"
        "YWtlcyAid2h5IGlzIG5vdGhpbmcgcHJpbnRpbmciIGFuc3dlcmFibGUgLS0tLS0tLS0tCmxv"
        "Z2RpciA9IHNoLkV4cGFuZEVudmlyb25tZW50U3RyaW5ncygiJUxvY2FsQXBwRGF0YSVcQWR2"
        "UHJpbnRQcm8iKQpPbiBFcnJvciBSZXN1bWUgTmV4dApJZiBOb3QgZnNvLkZvbGRlckV4aXN0"
        "cyhsb2dkaXIpIFRoZW4gZnNvLkNyZWF0ZUZvbGRlcihsb2dkaXIpClNldCB0cyA9IGZzby5P"
        "cGVuVGV4dEZpbGUobG9nZGlyICYgIlxib290LmxvZyIsIDgsIFRydWUpCnRzLldyaXRlTGlu"
        "ZSBOb3cgJiAiICBzdGFydCAgcHl0aG9uPSIiIiAmIHB5ICYgIiIiICBodWI9IiIiICYgaHVi"
        "ICYgIiIiIgp0cy5DbG9zZQpPbiBFcnJvciBHb1RvIDAKCicgLS0tLSAzKSBsYXVuY2ggaGlk"
        "ZGVuIC0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0t"
        "CnNoLkN1cnJlbnREaXJlY3RvcnkgPSBiYXNlICYgIlxodWIiCicgdjMuMS4yOiBsYXVuY2gg"
        "dGhlIGdyYXBoaWNhbCBjb25zb2xlIHdpbmRvdyAoZ3VpX2FwcCB2Mik7IGl0Cicgc3RhcnRz"
        "IHRoZSBodWIgaXRzZWxmIHdoZW4gbmVlZGVkLiBGYWxscyBiYWNrIHRvIHRoZSB0cmF5Cicg"
        "bGF1bmNoZXIgd2hlbiB0aGUgZ3VpIG1vZHVsZSBpcyBtaXNzaW5nIChvbGRlciBwYXlsb2Fk"
        "KS4KSWYgZnNvLkZpbGVFeGlzdHMoZ3VpKSBUaGVuCiAgc2guUnVuICIiIiIgJiBweSAmICIi"
        "IiAiIiIgJiBndWkgJiAiIiIiLCAwLCBGYWxzZQpFbHNlCiAgc2guUnVuICIiIiIgJiBweSAm"
        "ICIiIiAiIiIgJiBodWIgJiAiIiIgc2VydmUiLCAwLCBGYWxzZQpFbmQgSWYK",
    "INSTALL-WINDOWS-SERVICE.bat":
        "QGVjaG8gb2ZmClJFTSAgQWR2UHJpbnQgUHJvIHYxLjcuMiAtIGluc3RhbGwgYXMgYSBXaW5k"
        "b3dzIHNlcnZpY2UgKCJBZHZQcmludCBQcm8gU2VydmljZSIKUkVNICBpbiBzZXJ2aWNlcy5t"
        "c2MsIHN0YXJ0cyBhdCBib290LCBhdXRvLXJlc3RhcnRzKS4gT25lIFVBQyBwcm9tcHQuClJF"
        "TSAgSW5zdGFsbGVkIGxheW91dDogPHJvb3Q+XGluc3RhbGxcKi5iYXQsIDxyb290PlxydW50"
        "aW1lXEFkdlByaW50UHJvLmV4ZSwKUkVNICA8cm9vdD5caHViXGFkdnByaW50LnB5CnBvd2Vy"
        "c2hlbGwgLU5vUHJvZmlsZSAtRXhlY3V0aW9uUG9saWN5IEJ5cGFzcyAtRmlsZSAiJX5kcDBz"
        "ZXJ2aWNlLWluc3RhbGwucHMxIgo=",
    "REMOVE-WINDOWS-SERVICE.bat":
        "QGVjaG8gb2ZmClJFTSAgQWR2UHJpbnQgUHJvIHYxLjcuMiAtIHJlbW92ZSB0aGUgV2luZG93"
        "cyBzZXJ2aWNlLiBPbmUgVUFDIHByb21wdC4KcG93ZXJzaGVsbCAtTm9Qcm9maWxlIC1FeGVj"
        "dXRpb25Qb2xpY3kgQnlwYXNzIC1GaWxlICIlfmRwMHNlcnZpY2UtcmVtb3ZlLnBzMSIK",
    "service-install.ps1":
        "IyBBZHZQcmludCBQcm8gdjEuNy4yIC0gaW5zdGFsbCB0aGUgV2luZG93cyBzZXJ2aWNlIChv"
        "bmUgVUFDIHByb21wdCkKIyBSdW5zIGZyb20gaW5zdGFsbFxJTlNUQUxMLVdJTkRPV1MtU0VS"
        "VklDRS5iYXQgb3IgZGlyZWN0bHk6CiMgICBwb3dlcnNoZWxsIC1Ob1Byb2ZpbGUgLUV4ZWN1"
        "dGlvblBvbGljeSBCeXBhc3MgLUZpbGUgc2VydmljZS1pbnN0YWxsLnBzMQokRXJyb3JBY3Rp"
        "b25QcmVmZXJlbmNlID0gIlN0b3AiCiRyb290ID0gU3BsaXQtUGF0aCAtUGFyZW50ICRQU1Nj"
        "cmlwdFJvb3QgICAgICAgICAgIyBpbnN0YWxsXCAtPiBwYWNrYWdlIHJvb3QKJHB5ICAgPSBK"
        "b2luLVBhdGggJHJvb3QgInJ1bnRpbWVcQWR2UHJpbnRQcm8uZXhlIgppZiAoLW5vdCAoVGVz"
        "dC1QYXRoICRweSkpIHsgJHB5ID0gSm9pbi1QYXRoICRyb290ICJpbnN0YWxsZXJccnVudGlt"
        "ZVxBZHZQcmludFByby5leGUiIH0KaWYgKC1ub3QgKFRlc3QtUGF0aCAkcHkpKSB7ICRweSA9"
        "IEpvaW4tUGF0aCAkcm9vdCAicnVudGltZVxweXRob253LmV4ZSIgfQppZiAoLW5vdCAoVGVz"
        "dC1QYXRoICRweSkpIHsgJHB5ID0gSm9pbi1QYXRoICRyb290ICJpbnN0YWxsZXJccnVudGlt"
        "ZVxweXRob253LmV4ZSIgfQppZiAoLW5vdCAoVGVzdC1QYXRoICRweSkpIHsgJHB5ID0gSm9p"
        "bi1QYXRoICRyb290ICJBZHZQcmludFByby5leGUiIH0KJGh1YiA9IEpvaW4tUGF0aCAkcm9v"
        "dCAiaHViXGFkdnByaW50LnB5IgppZiAoLW5vdCAoVGVzdC1QYXRoICRodWIpKSB7IFdyaXRl"
        "LUhvc3QgImh1YlxhZHZwcmludC5weSBub3QgZm91bmQgbmV4dCB0byB0aGlzIHNjcmlwdCI7"
        "IFBhdXNlOyBleGl0IDEgfQpXcml0ZS1Ib3N0ICJBZHZQcmludCBQcm8gLSBpbnN0YWxsaW5n"
        "IHRoZSBXaW5kb3dzIHNlcnZpY2UgKGNvbmZpcm0gdGhlIFVBQyBwcm9tcHQpLi4uIgpTdGFy"
        "dC1Qcm9jZXNzIC1GaWxlUGF0aCAkcHkgLUFyZ3VtZW50TGlzdCAoJyInICsgJGh1YiArICci"
        "JywgInNlcnZpY2UtaW5zdGFsbCIpIC1WZXJiIFJ1bkFzIC1XYWl0CiRyZXMgPSBKb2luLVBh"
        "dGggJGVudjpVU0VSUFJPRklMRSAiLmFkdnByaW50XHNlcnZpY2VfcmVzdWx0LnR4dCIKaWYg"
        "KFRlc3QtUGF0aCAkcmVzKSB7IEdldC1Db250ZW50ICRyZXMgfQpXcml0ZS1Ib3N0ICIiCldy"
        "aXRlLUhvc3QgIkNoZWNrOiBzZXJ2aWNlcy5tc2MgLT4gJ0FkdlByaW50IFBybyBTZXJ2aWNl"
        "JyAob3I6IHB5dGhvbiBhZHZwcmludC5weSBzZXJ2aWNlIHN0YXR1cykiClBhdXNlCg==",
    "service-remove.ps1":
        "IyBBZHZQcmludCBQcm8gdjIuOCAtIHJlbW92ZSB0aGUgV2luZG93cyBzZXJ2aWNlIChvbmUg"
        "VUFDIHByb21wdCkKIyB2Mi44OiBzdG9wcyB0aGUgc2VydmljZSBGSVJTVCAoYnVsbGV0LXBy"
        "b29mOiBzdGF0dXMgd2FpdCArIFBJRCBraWxsKSwKIyBkZWxldGVzIHRoZSByZWdpc3RyYXRp"
        "b24sIHRoZW4gdmVyaWZpZXMgaXQgaXMgcmVhbGx5IGdvbmUuCiRFcnJvckFjdGlvblByZWZl"
        "cmVuY2UgPSAiQ29udGludWUiCiRyb290ID0gU3BsaXQtUGF0aCAtUGFyZW50ICRQU1Njcmlw"
        "dFJvb3QgICAgICAgICAgIyBpbnN0YWxsXCAtPiBwYWNrYWdlIHJvb3QKJHB5ICAgPSBKb2lu"
        "LVBhdGggJHJvb3QgInJ1bnRpbWVcQWR2UHJpbnRQcm8uZXhlIgppZiAoLW5vdCAoVGVzdC1Q"
        "YXRoICRweSkpIHsgJHB5ID0gSm9pbi1QYXRoICRyb290ICJpbnN0YWxsZXJccnVudGltZVxB"
        "ZHZQcmludFByby5leGUiIH0KaWYgKC1ub3QgKFRlc3QtUGF0aCAkcHkpKSB7ICRweSA9IEpv"
        "aW4tUGF0aCAkcm9vdCAicnVudGltZVxweXRob253LmV4ZSIgfQppZiAoLW5vdCAoVGVzdC1Q"
        "YXRoICRweSkpIHsgJHB5ID0gSm9pbi1QYXRoICRyb290ICJpbnN0YWxsZXJccnVudGltZVxw"
        "eXRob253LmV4ZSIgfQppZiAoLW5vdCAoVGVzdC1QYXRoICRweSkpIHsgJHB5ID0gSm9pbi1Q"
        "YXRoICRyb290ICJBZHZQcmludFByby5leGUiIH0KJGh1YiA9IEpvaW4tUGF0aCAkcm9vdCAi"
        "aHViXGFkdnByaW50LnB5IgoKV3JpdGUtSG9zdCAiQWR2UHJpbnQgUHJvIC0gcmVtb3Zpbmcg"
        "dGhlIFdpbmRvd3Mgc2VydmljZS4uLiIKIyAxKSBzdG9wICsgZGVyZWdpc3RlciB3aXRob3V0"
        "IGFueSBwcm9tcHQgKHRoaXMgc2NyaXB0IGlzIGFscmVhZHkgYWRtaW4KIyAgICB3aGVuIHRo"
        "ZSBVQUMgcHJvbXB0IG9mIHRoZSBjYWxsZXIgd2FzIGNvbmZpcm1lZDsgb3RoZXJ3aXNlIHN0"
        "YXJ0CiMgICAgdGhlIGhlbHBlciBlbGV2YXRlZCBiZWxvdykKJHN2YyA9IEdldC1TZXJ2aWNl"
        "IC1OYW1lIEFkdlByaW50IC1FcnJvckFjdGlvbiBTaWxlbnRseUNvbnRpbnVlCmlmICgkc3Zj"
        "IC1hbmQgLW5vdCAoVGVzdC1QYXRoICRodWIpKSB7CiAgIyBodWIgZmlsZXMgbWlzc2luZyAt"
        "IGRvIGl0IGlubGluZSAobm8gcHl0aG9uIG5lZWRlZCkKICBTdG9wLVNlcnZpY2UgLU5hbWUg"
        "QWR2UHJpbnQgLUZvcmNlIC1FcnJvckFjdGlvbiBTaWxlbnRseUNvbnRpbnVlCiAgU3RhcnQt"
        "U2xlZXAgMQogIHNjLmV4ZSBkZWxldGUgQWR2UHJpbnQgfCBPdXQtTnVsbAp9CiMgMikgbm9y"
        "bWFsIHBhdGg6IHRoZSBodWIncyBvd24gc2VydmljZS1yZW1vdmUgKHdyaXRlcyBzZXJ2aWNl"
        "X3Jlc3VsdC50eHQpCmlmIChUZXN0LVBhdGggJGh1YikgewogIFdyaXRlLUhvc3QgIiAgcnVu"
        "bmluZyB0aGUgaHViJ3Mgc2VydmljZS1yZW1vdmUgKGNvbmZpcm0gdGhlIFVBQyBwcm9tcHQp"
        "Li4uIgogIFN0YXJ0LVByb2Nlc3MgLUZpbGVQYXRoICRweSAtQXJndW1lbnRMaXN0ICgnIicg"
        "KyAkaHViICsgJyInLCAic2VydmljZS1yZW1vdmUiKSAtVmVyYiBSdW5BcyAtV2FpdAogICRy"
        "ZXMgPSBKb2luLVBhdGggJGVudjpVU0VSUFJPRklMRSAiLmFkdnByaW50XHNlcnZpY2VfcmVz"
        "dWx0LnR4dCIKICBpZiAoVGVzdC1QYXRoICRyZXMpIHsgR2V0LUNvbnRlbnQgJHJlcyB9Cn0K"
        "IyAzKSB2ZXJpZnkgLSBhIGhhbGYtcmVtb3ZlZCBzZXJ2aWNlIG11c3QgbmV2ZXIgc3Vydml2"
        "ZQpTdGFydC1TbGVlcCAxCiRzdmMgPSBHZXQtU2VydmljZSAtTmFtZSBBZHZQcmludCAtRXJy"
        "b3JBY3Rpb24gU2lsZW50bHlDb250aW51ZQppZiAoJHN2YykgewogIFdyaXRlLUhvc3QgIiAg"
        "c2VydmljZSBzdGlsbCByZWdpc3RlcmVkIC0gZm9yY2luZyByZW1vdmFsLi4uIgogIFN0b3At"
        "U2VydmljZSAtTmFtZSBBZHZQcmludCAtRm9yY2UgLUVycm9yQWN0aW9uIFNpbGVudGx5Q29u"
        "dGludWUKICBTdGFydC1TbGVlcCAxCiAgJHAgPSAoR2V0LUNpbUluc3RhbmNlIFdpbjMyX1Nl"
        "cnZpY2UgLUZpbHRlciAiTmFtZT0nQWR2UHJpbnQnIikuUHJvY2Vzc0lkCiAgaWYgKCRwKSB7"
        "IFN0b3AtUHJvY2VzcyAtSWQgJHAgLUZvcmNlIC1FcnJvckFjdGlvbiBTaWxlbnRseUNvbnRp"
        "bnVlIH0KICBzYy5leGUgZGVsZXRlIEFkdlByaW50IHwgT3V0LU51bGwKICBTdGFydC1TbGVl"
        "cCAxCiAgaWYgKEdldC1TZXJ2aWNlIC1OYW1lIEFkdlByaW50IC1FcnJvckFjdGlvbiBTaWxl"
        "bnRseUNvbnRpbnVlKSB7CiAgICBXcml0ZS1Ib3N0ICIgIFdBUk5JTkc6IFdpbmRvd3Mgc3Rp"
        "bGwgbGlzdHMgdGhlIHNlcnZpY2UgKG1hcmtlZCBmb3IgZGVsZXRpb24pLiIKICAgIFdyaXRl"
        "LUhvc3QgIiAgSXQgZGlzYXBwZWFycyBhdCB0aGUgbmV4dCByZWJvb3QgLSB0aGlzIGlzIGEg"
        "V2luZG93cyBTQ00gYmVoYXZpb3IsIgogICAgV3JpdGUtSG9zdCAiICBub3QgYW4gQWR2UHJp"
        "bnQgcHJvYmxlbS4iCiAgfSBlbHNlIHsKICAgIFdyaXRlLUhvc3QgIiAgW09LXSBzZXJ2aWNl"
        "IHJlbW92ZWQuIgogIH0KfSBlbHNlIHsKICBXcml0ZS1Ib3N0ICIgIFtPS10gc2VydmljZSBy"
        "ZW1vdmVkIChvciB3YXMgbmV2ZXIgaW5zdGFsbGVkKS4iCn0KV3JpdGUtSG9zdCAiVGlwOiB0"
        "dXJuIHRoZSBTdGFydHVwIGFwcCBiYWNrIG9uIGZyb20gdGhlIHRyYXkgbWVudSBvciBPcHRp"
        "b25zID4gV2luZG93cyBzZXJ2aWNlLiIKUGF1c2UK",
    "hub-stop.ps1":
        "IyA9PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09"
        "PT09PT09PT0KIyAgQWR2UHJpbnQgUHJvIHYyLjggLSBidWxsZXQtcHJvb2YgaHViIHN0b3AK"
        "IyAgVXNlZCBieSB0aGUgU2V0dXAgKHVwZ3JhZGUpLCB0aGUgVW5pbnN0YWxsZXIgYW5kIHRo"
        "ZQojICBpbnN0YWxsL3VuaW5zdGFsbCBoZWxwZXIgc2NyaXB0cy4gRml4ZXMgdGhlIHYyLjcu"
        "eCBwYWluOgojICAic2VydmljZSBub3QgdW5pbnN0YWxsZWQgLyBzb21lIGZpbGVzIGFib3J0"
        "IGluc3RhbGwiIC0gdGhlCiMgIHNlcnZpY2UgYW5kIGV2ZXJ5IGh1YiBwcm9jZXNzIGFyZSBz"
        "dG9wcGVkIEFORCByZW1vdmVkIEJFRk9SRQojICBhbnkgZmlsZSBpcyBvdmVyd3JpdHRlbiBv"
        "ciBkZWxldGVkLgojICBSdW46ICBwb3dlcnNoZWxsIC1Ob1Byb2ZpbGUgLUV4ZWN1dGlvblBv"
        "bGljeSBCeXBhc3MgLUZpbGUgaHViLXN0b3AucHMxICJDOlxQcm9ncmFtIEZpbGVzXEFkdlBy"
        "aW50UHJvIgojID09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09"
        "PT09PT09PT09PT09PT09PQokRXJyb3JBY3Rpb25QcmVmZXJlbmNlID0gJ1NpbGVudGx5Q29u"
        "dGludWUnCgpXcml0ZS1Ib3N0ICIgIFsxLzRdIHN0b3BwaW5nIHRoZSBBZHZQcmludCBzZXJ2"
        "aWNlIChpZiBpbnN0YWxsZWQpLi4uIgokc3ZjID0gR2V0LVNlcnZpY2UgLU5hbWUgQWR2UHJp"
        "bnQgLUVycm9yQWN0aW9uIFNpbGVudGx5Q29udGludWUKaWYgKCRzdmMpIHsKICBTdG9wLVNl"
        "cnZpY2UgLU5hbWUgQWR2UHJpbnQgLUZvcmNlCiAgJGkgPSAwCiAgd2hpbGUgKCRzdmMuU3Rh"
        "dHVzIC1uZSAnU3RvcHBlZCcgLWFuZCAkaSAtbHQgMjApIHsKICAgIFN0YXJ0LVNsZWVwIC1N"
        "aWxsaXNlY29uZHMgNTAwCiAgICAkc3ZjLlJlZnJlc2goKQogICAgJGkrKwogIH0KICBpZiAo"
        "JHN2Yy5TdGF0dXMgLW5lICdTdG9wcGVkJykgewogICAgIyBzdHVjayBpbiBTVE9QX1BFTkRJ"
        "Tkc6IGtpbGwgdGhlIHNlcnZpY2UgcHJvY2VzcyBieSBQSUQKICAgICRwID0gKEdldC1DaW1J"
        "bnN0YW5jZSBXaW4zMl9TZXJ2aWNlIC1GaWx0ZXIgIk5hbWU9J0FkdlByaW50JyIpLlByb2Nl"
        "c3NJZAogICAgaWYgKCRwIC1hbmQgJHAgLW5lIDApIHsgU3RvcC1Qcm9jZXNzIC1JZCAkcCAt"
        "Rm9yY2UgfQogICAgU3RhcnQtU2xlZXAgLU1pbGxpc2Vjb25kcyA4MDAKICB9CiAgIyByZW1v"
        "dmUgdGhlIHJlZ2lzdHJhdGlvbiBzbyBubyBoYWxmLWRlYWQgc2VydmljZSBzdXJ2aXZlcyBh"
        "bgogICMgdXBncmFkZSAtIFNldHVwIHJlLWluc3RhbGxzIGl0IGZyZXNoIHdoZW4gdGhlIGJv"
        "eCBpcyB0aWNrZWQKICBzYy5leGUgZGVsZXRlIEFkdlByaW50IHwgT3V0LU51bGwKICBXcml0"
        "ZS1Ib3N0ICIgICAgICAgIHNlcnZpY2Ugc3RvcHBlZCBhbmQgZGVyZWdpc3RlcmVkIgp9IGVs"
        "c2UgewogIFdyaXRlLUhvc3QgIiAgICAgICAgbm8gc2VydmljZSBpbnN0YWxsZWQiCn0KCldy"
        "aXRlLUhvc3QgIiAgWzIvNF0gc3RvcHBpbmcgaHViIHByb2Nlc3NlcyBmcm9tIHRoZSBpbnN0"
        "YWxsIGZvbGRlci4uLiIKJGRpciA9ICIkYXJncyIKaWYgKCRkaXIpIHsKICAkZGlyID0gJGRp"
        "ci5UcmltRW5kKCdcJykKICBHZXQtUHJvY2VzcyB8IFdoZXJlLU9iamVjdCB7ICRfLlBhdGgg"
        "LWxpa2UgKCRkaXIgKyAnXConKSB9IHwKICAgIFN0b3AtUHJvY2VzcyAtRm9yY2UKfQoKV3Jp"
        "dGUtSG9zdCAiICBbMy80XSBzdG9wcGluZyBhbnl0aGluZyBsaXN0ZW5pbmcgb24gVENQIDky"
        "MzUuLi4iCkdldC1OZXRUQ1BDb25uZWN0aW9uIC1Mb2NhbFBvcnQgOTIzNSAtU3RhdGUgTGlz"
        "dGVuIC1FcnJvckFjdGlvbiBTaWxlbnRseUNvbnRpbnVlIHwKICBTZWxlY3QtT2JqZWN0IC1F"
        "eHBhbmRQcm9wZXJ0eSBPd25pbmdQcm9jZXNzIC1VbmlxdWUgfAogIEZvckVhY2gtT2JqZWN0"
        "IHsgU3RvcC1Qcm9jZXNzIC1JZCAkXyAtRm9yY2UgfQoKV3JpdGUtSG9zdCAiICBbNC80XSBz"
        "dG9wcGluZyByZW5hbWVkIGh1YiBpbWFnZXMuLi4iClN0b3AtUHJvY2VzcyAtTmFtZSBBZHZQ"
        "cmludFBybyAtRm9yY2UKU3RvcC1Qcm9jZXNzIC1OYW1lIFByaW50SHViUHJvIC1Gb3JjZQpT"
        "dGFydC1TbGVlcCAtTWlsbGlzZWNvbmRzIDcwMAoKV3JpdGUtSG9zdCAiICBodWIgc3RvcHBl"
        "ZCAtIGZpbGVzIGFyZSBmcmVlIG5vdy4iCmV4aXQgMAo=",
}


def die(msg):
    print("!! " + msg)
    sys.exit(1)


def rel(*p):
    return os.path.join(ROOT, *p)


def _on_rm_error(func, path, _exc):
    """rmtree error hook: clear read-only bits and retry once (files
    written moments ago are often still held briefly by Defender or
    the Windows search indexer)."""
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass
    try:
        func(path)
    except OSError:
        pass


def wipe(path):
    """rmtree that never fails silently (v3.5.5 WinError 183 fix).

    shutil.rmtree(..., ignore_errors=True) used to leave directories
    behind whenever an on-access scanner / indexer / an open Explorer
    or cmd window held a handle. The next copytree into the same spot
    then died with WinError 183. This version clears read-only bits,
    retries with a short backoff, and if the path STILL survives it
    stops the build with a fix-it message instead of letting the
    stage get corrupted."""
    if not os.path.exists(path):
        return
    delay = 0.4
    for _attempt in range(5):
        if sys.version_info >= (3, 12):
            shutil.rmtree(path, onexc=_on_rm_error)
        else:
            shutil.rmtree(path, onerror=_on_rm_error)
        if not os.path.exists(path):
            return
        time.sleep(delay)
        delay *= 2
    die("%s is LOCKED and cannot be deleted.\n"
        "  1) close any Explorer / cmd / editor window open inside it\n"
        "  2) one-time, in an ADMIN PowerShell, allow the repo folder:\n"
        '       Add-MpPreference -ExclusionPath "%s"\n'
        "  3) delete the folder by hand, then run the build again."
        % (path, ROOT))


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
    txt = open(rel("VERSION.txt"), encoding="utf-8").read()
    m = re.search(r"AdvPrint Pro \(Advanced Printer\) ([0-9][0-9.]*)", txt)
    if not m:
        die("cannot parse version from VERSION.txt")
    return m.group(1)


def restore_embedded(name):
    """Write an install script back from the copy embedded in this
    file. Returns True on success (v3.5.5 self-heal)."""
    b64 = EMBEDDED_INSTALL_FILES.get(name)
    if not b64:
        return False
    p = rel("tool", "windows", "portable", "install", name)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as f:
        f.write(base64.b64decode(b64))
    print("   [!] tool/windows/portable/install/%s was MISSING from the" % name)
    print("       tree - it was restored from the copy embedded inside")
    print("       build-all.py (antivirus quarantine is the usual cause)")
    return True


def check_tree():
    """Fail LOUDLY on an incomplete source tree (v3.5.5 guard),
    self-healing the install scripts from the embedded copies first."""
    missing = [f for f in REQUIRED_TREE_FILES if not os.path.exists(rel(*f.split("/")))]
    if missing:
        rest = []
        for m in missing:
            name = m.split("/")[-1]
            if m.startswith("tool/windows/portable/install/") \
                    and restore_embedded(name):
                continue
            rest.append(m)
        if rest:
            die("your source tree is MISSING %d file(s):\n  - %s\n"
                "Restore the full source (re-extract the release source zip)\n"
                "and build again. Do not mix old trees with new kit files."
                % (len(rest), "\n  - ".join(rest)))
    for name in TWIN_FILES:
        a = rel("tool", "unix", *name.split("/")[1:])
        b = rel("tool", "windows", "portable", *name.split("/")[1:])
        if os.path.exists(a) and os.path.exists(b) \
                and not filecmp.cmp(a, b, shallow=False):
            die("twin files drifted apart:\n  %s\n  %s\n"
                "Copy the unix file over the windows one (or vice versa) "
                "and rebuild." % (a, b))


def ensure_source(name):
    """Stage source for one install script - heal if a scanner ate it."""
    p = rel("tool", "windows", "portable", "install", name)
    if not os.path.exists(p) and not restore_embedded(name):
        die("missing stage source: tool/windows/portable/install/%s\n"
            "no embedded fallback exists - restore the full source zip"
            % name)
    return p


def stage_install_scripts(stage_dir):
    """Copy all 9 install scripts into stage/install - guaranteed."""
    for name in STAGE_INSTALL_FILES:
        shutil.copy2(ensure_source(name),
                     os.path.join(stage_dir, "install", name))


def nsi_missing_refs():
    """Every File reference in setup.nsi that does not resolve right now."""
    text = open(rel("installer", "setup.nsi"), encoding="utf-8",
                errors="replace").read()
    missing = []
    for line in text.splitlines():
        if not re.match(r'\s*File\b', line):
            continue
        line = line.split(";")[0]          # strip NSIS comment tails
        if "/nonfatal" in line:
            continue
        paths = re.findall(r'"([^"]+)"', line)
        if not paths:
            continue
        src = paths[-1]                    # last quoted token = source
        if src.startswith("$"):            # runtime symbols - skip
            continue
        src_path = os.path.join(rel("installer"), *src.split("/"))
        if "*" in src:                     # /r "dir/*.*" - check the dir
            src_path = os.path.dirname(src_path)
        if not os.path.exists(src_path):
            missing.append(src.replace("\\", "/"))
    return sorted(set(missing))


def validate_nsi_refs(V):
    """Pre-validate every File reference in setup.nsi (v3.5.5 guard)."""
    missing = nsi_missing_refs()
    if missing:
        hints = []
        for m in missing:
            if m.startswith("stage/runtime"):
                hints.append("- %s : the bundled Python runtime is missing\n"
                             "  from the tree (tool/windows/portable/installer/"
                             "runtime)\n  - re-extract the full source zip" % m)
            elif m.startswith("stage/install/"):
                hints.append("- %s : an install script vanished after\n"
                             "  staging - an on-access antivirus is the usual\n"
                             "  cause; build-all.py re-stages these "
                             "automatically" % m)
            else:
                hints.append("- %s : restore it from the full source zip" % m)
        die("setup.nsi needs %d file(s) that do not exist:\n  - %s\n%s"
            % (len(missing), "\n  - ".join(missing), "\n".join(hints)))
    m = re.search(r'(?m)^OutFile\s+"\.\.[\\/]dist[\\/]AdvPrint-Pro-Setup-(.+)\.exe"',
                  open(rel("installer", "setup.nsi"), encoding="utf-8",
                       errors="replace").read())
    if not m or m.group(1) != V:
        die("installer/setup.nsi OutFile is %s - update it to:\n   %s"
            % (('"%s"' % m.group(1)) if m else "missing/unparsable",
               'OutFile "../dist/AdvPrint-Pro-Setup-%s.exe"' % V))


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
            r = "./" + os.path.relpath(full, src_dir).replace(os.sep, "/")
            if exclude_prefix and r.startswith(exclude_prefix):
                continue
            entries.append((full, r))
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
        for _full, r in entries:
            parts = r[2:].split("/")
            for i in range(1, len(parts)):
                d = "./" + "/".join(parts[:i])
                if d not in made:
                    tf.addfile(dirinfo(d))
                    made.add(d)
        for full, r in entries:
            mode = 0o755 if (r.startswith("./DEBIAN/postinst")
                             or r.startswith("./DEBIAN/prerm")
                             or r.startswith("./usr/bin/")) else 0o644
            data = open(full, "rb").read()
            ti = tarfile.TarInfo(r)
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

    # v3.5.5 GUARD 0: complete tree + twins, BEFORE anything else
    check_tree()

    DIST = rel("dist")
    STAGE = rel("installer", "stage")
    for d in (DIST, STAGE):
        wipe(d)                                   # lock-aware, v3.5.5
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
    os.makedirs(rel("prebuilt"), exist_ok=True)
    sync_targets = [
        os.path.join(STAGE, "hub", "extension", "AdvPrint-Pro.crx"),
        rel("tool", "unix", "hub", "extension", "AdvPrint-Pro.crx"),
        rel("tool", "windows", "portable", "hub", "extension", "AdvPrint-Pro.crx"),
        rel("prebuilt", "AdvPrint-Pro.crx"),
    ]
    for p in sync_targets:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        shutil.copyfile(crx, p)
        if not filecmp.cmp(crx, p, shallow=False):
            die("CRX sync FAILED: %s != dist/AdvPrint-Pro.crx" % p)

    # payload version guard
    import json
    with zipfile.ZipFile(crx) as z:
        crx_v = json.loads(z.read("manifest.json").decode())["version"]
    if crx_v != V:
        die("CRX version %s != hub version %s (bump extension/manifest.json)"
            % (crx_v, V))
    print("   embedded CRX copies synced + verified v%s" % crx_v)

    # v3.5.3 CRX-SIGNATURE GUARD: Chrome-identical verification as a hard gate
    py("tool/crx3.py", "verify", crx, V, show=True)

    # ---------- 2) unpacked extension zip (Web-store upload / dev load) -----
    print("-- extension zip")
    extzip = os.path.join(DIST, "AdvPrint-Pro-Extension-%s.zip" % V)
    ext_dir = rel("extension")
    with zipfile.ZipFile(extzip, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, names in os.walk(ext_dir):
            for name in sorted(names):
                full = os.path.join(root, name)
                zf.write(full, os.path.relpath(full, ext_dir).replace(os.sep, "/"))

    # ---------- 3) NSIS stage (hub + installers + runtime + docs) ----------
    print("-- NSIS stage")
    whub = rel("tool", "windows", "portable", "hub")
    for name in sorted(os.listdir(whub)):
        if name.endswith((".py", ".ico", ".html")):
            shutil.copy2(os.path.join(whub, name), os.path.join(STAGE, "hub", name))
    os.makedirs(os.path.join(STAGE, "hub", "service"), exist_ok=True)
    svc = os.path.join(whub, "service", "AdvPrintProService.cs")
    shutil.copy2(svc, os.path.join(STAGE, "hub", "service"))
    stage_install_scripts(STAGE)
    shutil.copy2(rel("docs", "AdvPrint-Pro-Full-Guide.html"),
                 os.path.join(STAGE, "docs", "AdvPrint-Pro-Full-Guide.html"))
    shutil.copy2(rel("README.md"), os.path.join(STAGE, "README.md"))
    runtime = rel("tool", "windows", "portable", "installer", "runtime")
    if os.path.isdir(runtime):
        print("   embedding Python runtime (%.0f MB)..." % (sum(
            os.path.getsize(os.path.join(r, f))
            for r, _d, fs in os.walk(runtime) for f in fs) / 2**20))
        shutil.copytree(runtime, os.path.join(STAGE, "runtime"),
                        dirs_exist_ok=True)       # stage was just wiped
    else:
        print("   WARNING: runtime missing - Setup EXE would need system Python")

    # v3.5.5 GUARD: every setup.nsi File reference must resolve, version in sync
    validate_nsi_refs(V)

    # ---------- 4) DEB ----------
    if args.skip_deb:
        print("-- DEB (skipped by request)")
    else:
        print("-- DEB (pure-python builder, no dpkg-deb needed)")
        tmp = os.path.join(DIST, "deb-build", "advprint-pro_%s" % V)
        wipe(os.path.join(DIST, "deb-build"))
        shutil.copytree(rel("installer", "deb", "DEBIAN"),
                        os.path.join(tmp, "DEBIAN"), dirs_exist_ok=True)
        ctrl = os.path.join(tmp, "DEBIAN", "control")
        ctl = open(ctrl, encoding="utf-8").read()
        open(ctrl, "w", encoding="utf-8", newline="\n").write(
            re.sub(r"(?m)^Version: .*", "Version: %s" % V, ctl))
        for d in ("opt/advprint/hub/extension", "opt/advprint/hub/service",
                  "etc/xdg/autostart", "usr/bin", "usr/lib/systemd/user"):
            os.makedirs(os.path.join(tmp, *d.split("/")), exist_ok=True)
        cp = lambda src, *dst: shutil.copy2(rel(*src.split("/")),
                                            os.path.join(tmp, *dst))
        cp("tool/unix/hub/advprint.py", "opt", "advprint", "hub", "advprint.py")
        for name in ("tool.py", "tray_windows.py", "service_main.py", "advprint.ico"):
            shutil.copy2(os.path.join(whub, name),
                         os.path.join(tmp, "opt", "advprint", "hub", name))
        cp("tool/unix/hub/console.html", "opt", "advprint", "hub", "console.html")
        cp("tool/unix/hub/gui_app.py", "opt", "advprint", "hub", "gui_app.py")
        htmldir = rel("tool", "unix", "hub")
        for name in sorted(os.listdir(htmldir)):
            if name.endswith(".html"):
                shutil.copy2(os.path.join(htmldir, name),
                             os.path.join(tmp, "opt", "advprint", "hub", name))
        shutil.copy2(crx, os.path.join(tmp, "opt", "advprint", "hub",
                                       "extension", "AdvPrint-Pro.crx"))
        if os.path.exists(svc):
            shutil.copy2(svc, os.path.join(tmp, "opt", "advprint", "hub",
                                           "service", "AdvPrintProService.cs"))
        cp("installer/deb/data/advprint.desktop", "etc", "xdg", "autostart",
           "advprint.desktop")
        cp("installer/deb/data/advprint-launcher", "usr", "bin", "advprint")
        cp("installer/deb/data/advprint-start", "usr", "bin", "advprint-start")
        cp("installer/deb/data/advprint.service", "usr", "lib", "systemd",
           "user", "advprint.service")
        deb = os.path.join(DIST, "advprint-pro_%s_all.deb" % V)
        build_deb(tmp, deb)
        shutil.rmtree(os.path.join(DIST, "deb-build"), ignore_errors=True)
        if shutil.which("dpkg-deb"):  # sanity check where available
            r = subprocess.run(["dpkg-deb", "--info", deb],
                               capture_output=True, text=True)
            if r.returncode != 0:
                print(r.stdout)
                print(r.stderr)
                die("built DEB rejected by dpkg-deb --info")
            print("   dpkg-deb --info: OK (%s)" %
                  re.search(r"Version: (.*)", r.stdout).group(1).strip())
        else:
            print("   (dpkg-deb not present - skipped the optional lint check)")

    # ---------- 5) NSIS Setup EXE ----------
    mk, env = find_makensis()
    exe = os.path.join(DIST, "AdvPrint-Pro-Setup-%s.exe" % V)
    if args.skip_exe:
        print("-- Setup EXE (skipped by request)")
    elif mk:
        print("-- NSIS Setup EXE (%s)" % mk)
        run_makensis(mk, exe, env)
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
        print("!! Setup EXE missing - SHA256SUMS will cover only %s"
              % " ".join(sums))
    lines = []
    for name in sums:
        lines.append("%s  %s" % (hashlib_file(os.path.join(DIST, name)), name))
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


def _makensis_abs_script(base_dir):
    """Generate <base_dir>/setup-abs.nsi - setup.nsi with every quoted
    source path on File / Icon / OutFile / MUI_ICON lines rewritten to
    an ABSOLUTE path that Python has JUST verified to exist.

    Why (v3.5.5, the Windows 'no files found' case): makensis resolves
    relative File paths against its own base dir, and an on-access
    scanner can make a freshly staged file invisible for a moment - so
    the compile died at the FIRST File directive (setup.nsi line 198,
    hub-stop.ps1) while Python saw every file present before AND after.
    Absolute, pre-validated paths remove the resolution variable
    completely; a missing file now fails HERE with its full absolute
    path instead of inside makensis. Line count is preserved, so any
    makensis error line number still maps to setup.nsi.
    Returns (script_path, refs_checked, missing_absolute_paths)."""
    src = os.path.join(base_dir, "setup.nsi")
    dst = os.path.join(base_dir, "setup-abs.nsi")
    out, missing, refs = [], [], 0
    for line in open(src, encoding="utf-8",
                     errors="replace").read().splitlines():
        head = line.split(";")[0]
        if re.match(r"\s*File\b", head) or re.match(r"\s*Icon\b", head) \
                or re.match(r"\s*OutFile\b", head) \
                or re.match(r"\s*!define\s+MUI_(?:UN)?ICON\b", head):
            tgt = None
            for m_ in reversed(list(re.finditer(r'"([^"]+)"', line))):
                if m_.group(1).startswith("$") or m_.group(1).startswith("/"):
                    continue                      # $symbols and /oname flags
                tgt = m_
                break
            if tgt is not None:
                refs += 1
                sp = tgt.group(1)
                ap = os.path.normpath(os.path.join(base_dir, *sp.split("/")))
                # OutFile is an OUTPUT - rewrite it, do not require it
                ok = True if re.match(r"\s*OutFile\b", head) else \
                    (os.path.isdir(os.path.dirname(ap)) if "*" in sp
                     else os.path.exists(ap))
                if ok:
                    line = line[:tgt.start(1)] + ap + line[tgt.end(1):]
                else:
                    missing.append(ap)
        out.append(line)
    with open(dst, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(out) + "\n")
    return dst, refs, missing


def run_makensis(mk, exe, extra_env):
    """makensis with absolute-path staging, an antivirus post-mortem
    and self-heal retries (v3.5.5).

    Windows on-access scanners (Defender real-time protection) can
    make a freshly staged .ps1/.bat invisible for a moment - even
    while makensis is enumerating it. That surfaces as
        File: "stage/install/hub-stop.ps1" -> no files found
    at the first File directive of setup.nsi while Python sees every
    file present before AND after the compile. Defense in depth:
      1. compile the generated setup-abs.nsi (absolute, pre-verified
         paths - see _makensis_abs_script),
      2. 'no files found' in the compiler output ALWAYS forces a
         re-stage + one retry, even when the post-mortem finds nothing
         (the scanner may have put the file back by then),
      3. the log prints the makensis version and the compile dir so a
         remote diagnosis never has to guess them."""

    def mkenv():
        e = dict(os.environ)
        if extra_env:
            e.update(extra_env)
        return e

    ver = subprocess.run([mk, "-VERSION"], capture_output=True,
                         text=True, env=mkenv())
    ver = (ver.stdout or ver.stderr or "?").strip().splitlines()
    print("   makensis %s | compile dir %s"
          % (ver[-1] if ver else "?", rel("installer")))

    def attempt(script):
        r = subprocess.run([mk, "-V2", script],
                           cwd=rel("installer"), env=mkenv(),
                           capture_output=True, text=True)
        if r.stdout:
            print(r.stdout.rstrip())
        if r.stderr:
            print(r.stderr.rstrip())
        return r

    def vanish_report():
        gone = nsi_missing_refs()
        if gone:
            print("!! staged file(s) DISAPPEARED (on-access antivirus "
                  "quarantine is the usual cause):")
            for g in gone:
                ap = os.path.join(rel("installer"), *g.split("/"))
                print("   - installer/%s (python sees it now: %s)"
                      % (g, os.path.exists(ap)))
            print("   One-time fix in an ADMIN PowerShell - allow the repo")
            print("   folder so the scanner stops eating staged files:")
            print('     Add-MpPreference -ExclusionPath "%s"' % ROOT)
        return gone

    def restage():
        print("   re-staging from the source tree / embedded copies...")
        stage_install_scripts(rel("installer", "stage"))
        still = nsi_missing_refs()
        if still:
            die("setup.nsi still needs missing file(s) after re-staging:\n"
                "  %s\nAdd the antivirus exclusion shown above, restore the\n"
                "full source zip, and run build.cmd again." % "\n  ".join(still))

    abs_nsi, refs, missing = _makensis_abs_script(rel("installer"))
    if missing:
        die("setup.nsi needs %d file(s) that do not exist:\n  %s\n"
            "Restore the full source zip and run build.cmd again."
            % (len(missing), "\n  ".join(missing)))
    print("   stage OK: %d/%d File paths verified (absolute)"
          % (refs - len(missing), refs))

    try:
        gone = vanish_report()
        if gone:                    # vanished since staging - heal first
            restage()
        r = attempt("setup-abs.nsi")
        if r.returncode == 0 and os.path.exists(exe):
            return
        nofiles = "no files found" in (r.stdout or "") + (r.stderr or "")
        gone = vanish_report()
        if not gone and not nofiles:
            die("makensis failed - read the compiler message above")
        if not gone:
            print("   'no files found' but every file is back NOW - an")
            print("   on-access scanner hid it only for a moment.")
        restage()
        r = attempt("setup-abs.nsi")
        if r.returncode == 0 and os.path.exists(exe):
            print("   retry SUCCEEDED (still add the exclusion above - the")
            print("   scanner may strike earlier on a future run)")
            return
        still = nsi_missing_refs()
        if still:
            die("makensis failed again - staged file(s) keep disappearing:\n"
                "  %s\nAdd the antivirus exclusion shown above, restore the\n"
                "full source zip, and run build.cmd again." % "\n  ".join(still))
        die("makensis failed - read the compiler message above")
    finally:
        if os.path.exists(abs_nsi):
            os.remove(abs_nsi)


if __name__ == "__main__":
    main()
