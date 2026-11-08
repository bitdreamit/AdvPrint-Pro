# v3.0.8 - GitHub release + push steps (5 minutes)

## 1) Push the source (the commit is already made in this tree)

    cd AdvPrint-Pro
    git push origin main        # commit 972810e "PROFESSIONAL IPP PRINTER..."

## 2) Publish the release (web UI - as in docs/HOW-TO-RELEASE.md)

1. Open https://github.com/bitdreamit/AdvPrint-Pro/releases/new
2. Choose a tag: type  v3.0.8  -> Create new tag on publish (target: main)
3. Release title:
   PROFESSIONAL IPP PRINTER - WINDOWS 10/11 CONNECTS + AIRPRINT-GRADE DISCOVERY
4. Describe: paste docs/RELEASE-NOTES-v3.0.8.md (in this kit)
5. Attach binaries - drag & drop from this kit:
   - AdvPrint-Pro-Setup-3.0.8.exe
   - advprint-pro_3.0.8_all.deb
   - AdvPrint-Pro.crx
   - AdvPrint-Pro-3.0.8-source.zip
   - SHA256SUMS-3.0.8.txt
6. Tick "Set as the latest release" -> Publish.

## 3) Verify

- https://github.com/bitdreamit/AdvPrint-Pro/releases/latest shows v3.0.8
- On the Windows PC: run AdvPrint-Pro-Setup-3.0.8.exe over the old
  install (or /S silent). Chrome updates the force-installed extension
  by itself on next browser start.
- Add the printer again: Settings -> Printers -> Add device -> it now
  APPEARS in the list; or Add manually -> IPP Device ->
  http://192.168.1.7:9235/ipp/print -> Next -> CONNECTS (fixed).
- iPhone: Share -> Print -> Select Printer -> "AdvPrint Pro @ <pc>".
