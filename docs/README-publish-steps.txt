# v3.0.9 - GitHub release + push steps (5 minutes)

1. Commit the tree and push the tag:
     git add -A && git commit -m "v3.0.9 - dropdown doubling fix + per-printer IPP queues (central IPP middleware)"
     git tag v3.0.9 && git push origin main && git push origin v3.0.9

2. Open https://github.com/bitdreamit/AdvPrint-Pro/releases/new

3. Choose a tag: type  v3.0.9  -> Create new tag on publish (target: main)

4. Title:  v3.0.9 - dropdown doubling fix + per-printer IPP queues

5. Describe: paste docs/RELEASE-NOTES-v3.0.9.md (in this kit)

6. Attach binaries (this kit / download folder):
   - AdvPrint-Pro-Setup-3.0.9.exe
   - advprint-pro_3.0.9_all.deb
   - AdvPrint-Pro.crx            (extension - hub auto-distributes it too)
   - AdvPrint-Pro-3.0.9-source.zip
   - SHA256SUMS-3.0.9.txt

7. Tick "Set as the latest release" -> Publish release.

8. Verify:
   - https://github.com/bitdreamit/AdvPrint-Pro/releases/latest shows v3.0.9
   - On the Windows PC: run AdvPrint-Pro-Setup-3.0.9.exe over the old
     install (no uninstall needed) - tray icon shows v3.0.9
   - Open the extension Options -> Default printer dropdown shows every
     printer ONCE (no more "NameName")
   - Settings -> share LAN -> on a phone's print dialog you now see the
     hub AND every printer of that PC (each prints into its own queue)
     - /ipp/print/<printer> works: Add printer -> IPP Device -> the URL
       from Options > LAN tab (each printer row shows its ipp_url)

9. After publishing: the hub silently updates every installed Chrome
   extension (ExtensionInstallForcelist + updates.xml keep working).
