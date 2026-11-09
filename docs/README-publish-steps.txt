# v3.1.3 - GitHub release + push steps (5 minutes)

## 1) Push the source (the commit is already made in this tree)

    cd AdvPrint-Pro
    git push origin main

## 2) Publish the release (web UI - as in docs/HOW-TO-RELEASE.md)

1. Open https://github.com/bitdreamit/AdvPrint-Pro/releases/new
2. Choose a tag: type  v3.1.3  -> Create new tag on publish (target: main)
3. Release title:
   THE ONE UI SKIN - the approved IDM design, pixel for pixel (console + options)
4. Describe: paste docs/RELEASE-NOTES-v3.1.3.md
5. Attach binaries - drag & drop from this kit:
   - AdvPrint-Pro-Setup-3.1.3.exe
   - advprint-pro_3.1.3_all.deb
   - AdvPrint-Pro.crx
   - AdvPrint-Pro-3.1.3-source.zip
   - SHA256SUMS-3.1.3.txt
6. Tick "Set as the latest release" -> Publish.

## 3) Verify

- https://github.com/bitdreamit/AdvPrint-Pro/releases/latest shows v3.1.3
- On the Windows PC: run AdvPrint-Pro-Setup-3.1.3.exe over the old
  install (or /S silent). Chrome updates the force-installed extension
  by itself on next browser start.
- Open the console (tray -> Console / START-CONSOLE.vbs /
  http://127.0.0.1:9235/ui): the window is now the approved IDM design
  (SVG toolbar, category tree, KPI cards, dark log terminal).
- Chrome -> extension Options: the same IDM design around all 10 tabs,
  Console is the landing tab and embeds the live /ui.
