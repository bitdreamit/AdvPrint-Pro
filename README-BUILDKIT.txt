AdvPrint Pro - Windows Build Kit (v3.5.9 - now part of the tree)
by Bit Dream IT - Innovative Healthcare Solutions
====================================================

Since v3.5.5 these files SHIP INSIDE the repository - this kit is only
needed to update an OLDER clone (v3.5.4 or earlier).

WHAT IT BUILDS
  Every release artifact from source on Windows: Setup EXE, signed
  CRX, extension zip, Linux DEB, SHA256SUMS - one command, no WSL,
  no Linux box.

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
  6. Verify:  python tool\crx3.py verify dist\AdvPrint-Pro.crx 3.5.9

NOTE 1: the build now verifies the COMPLETE file list first. If it says
"your source tree is MISSING ...", re-extract the full v3.5.9 source
zip - do not mix an old tree with new kit files.

NOTE 2: the build carries embedded copies of the 9 install helpers
(.bat/.vbs/.ps1) and restores them automatically if your antivirus
(Windows Defender) quarantines one. If a staged file vanishes during
the makensis compile, it prints the one-time fix
(Add-MpPreference -ExclusionPath "<repo folder>") and retries.

IMPORTANT: copy BOTH kit files (build.cmd AND scripts\build-all.py)
over your tree. An OLD build-all.py next to the new setup.nsi is
exactly what produced the "line 198 / no files found" failure.

FULL INSTRUCTIONS:  docs\BUILD-WINDOWS.md
