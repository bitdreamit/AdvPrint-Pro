AdvPrint Pro - Windows Build Kit (v3.5.4)
by Bit Dream IT - Innovative Healthcare Solutions
====================================================

WHAT IS THIS
  Everything you need to build ALL release artifacts from source
  on a Windows PC: Setup EXE, signed CRX, extension zip, Linux
  DEB, SHA256SUMS - one command, no WSL, no Linux box.

FILES (copy them into your source tree at the SAME paths)
  build.cmd                 -> repo root          (one-click Windows launcher)
  scripts\build-all.py      -> scripts\           (cross-platform builder)
  docs\BUILD-WINDOWS.md     -> docs\              (step-by-step guide - READ THIS)
  docs\BUILD-FROM-SOURCE.md -> docs\              (updated Linux guide + Windows pointer)

QUICK START
  1. Install Python 3.9+  https://www.python.org/downloads/
     (tick "Add python.exe to PATH")
  2. Install NSIS 3.x     https://nsis.sourceforge.io/Download
     (only for the Setup EXE; default folder is auto-found)
  3. Get the source:  git clone https://github.com/bitdreamit/AdvPrint-Pro.git
     (or Download ZIP on github)  - then copy this kit's files in
  4. Double-click  build.cmd
  5. Collect your artifacts from the new  dist\  folder
  6. Verify:  python tool\crx3.py verify dist\AdvPrint-Pro.crx 3.5.4

FULL INSTRUCTIONS:  docs\BUILD-WINDOWS.md
