#!/usr/bin/env python3
"""AdvPrint Pro - re-embed the ONE UI console into the hub.

v3.2.8: one version-agnostic replacement for the per-release
embed_console_v3XX.py helpers. The A-to-Z guide's build step 2:

    python3 scripts/embed_console.py

reads tool/unix/hub/console.html (the ONE UI source) and writes it into
the CONSOLE_HTML r-string of BOTH advprint.py copies (unix hub + windows
portable), then mirrors console.html itself to the windows portable hub
so all three files stay byte-consistent. A stale embed means a stale
UI - always run this after editing console.html, before build-all.sh.
"""

import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "tool", "unix", "hub", "console.html")
HUBS = [
    os.path.join(ROOT, "tool", "unix", "hub", "advprint.py"),
    os.path.join(ROOT, "tool", "windows", "portable", "hub", "advprint.py"),
]
WINSRC = SRC
WINDST = os.path.join(ROOT, "tool", "windows", "portable", "hub", "console.html")
OPEN = 'CONSOLE_HTML = r"""'
CLOSE = '\n"""'


def main():
    html = open(SRC, encoding="utf-8").read()
    if "<!DOCTYPE html>" not in html[:200]:
        sys.exit("console.html does not look like the ONE UI (no doctype)")
    if "</html>" not in html[-200:]:
        sys.exit("console.html does not end with </html>")
    if CLOSE.replace("\n", "") in html[:-1]:
        sys.exit('console.html contains a """ sequence - the r-string '
                 "embed would break; reword that part of the UI source")
    block = OPEN + html + '"""'
    for path in HUBS:
        text = open(path, encoding="utf-8").read()
        i = text.find(OPEN)
        if i < 0:
            sys.exit("CONSOLE_HTML not found in " + path)
        j = text.find(CLOSE, i + len(OPEN))
        if j < 0:
            sys.exit("closing delimiter not found in " + path)
        if "</html>" not in text[max(i, j - 200):j]:
            sys.exit("closing delimiter looks wrong in " + path)
        text = text[:i] + block + text[j + len(CLOSE):]
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        print("embedded console.html -> %s (%d bytes)" % (path, len(block)))
    shutil.copyfile(WINSRC, WINDST)
    print("console.html -> " + WINDST)
    a = open(HUBS[0], "rb").read()
    b = open(HUBS[1], "rb").read()
    print("advprint.py copies identical: %s" % (a == b))


if __name__ == "__main__":
    main()
